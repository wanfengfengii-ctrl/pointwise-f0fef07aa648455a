import argparse
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.exchange import exchange_day
from archive.lookup import read_day
from archive.storage import ArchiveStore
from intake.batches import admit
from intake.observations import ObservationInput
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from rehearsal.batch_scope import UnknownBatch
from rehearsal.report import simulate
from seal.commit import PublicationError
from seal.cut import close_day


_ROOT = Path(__file__).resolve().parent


def _apply(source, day, event):
    operation, batch, *arguments = event
    if operation == 'admit':
        records, = arguments
        return admit(source, day, batch, [ObservationInput(*record) for record in records]).revision
    if operation == 'disposition':
        return add_disposition(source, day, batch, *arguments)
    raise ValueError(f'unknown sample operation {operation!r}')


def _summary(result):
    return {
        'rows': [[row.slot, row.observation_id, row.batch, row.reading] for row in result.rows],
        'count': result.count,
        'total': result.total,
    }


def _scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    if expected != actual or downstream_expected != downstream_actual:
        raise RuntimeError(f'{case_id}: ledger evidence differs from hand calculation')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, sort_keys=True), flush=True)


def _interrupt_publication(_account):
    raise OSError('demonstrated interruption before publication commit')


def _publication_count(store):
    with store.snapshot() as connection:
        count, = connection.execute('SELECT COUNT(*) FROM fixed_catalog').fetchone()
    return count


def demo():
    sample = json.loads((_ROOT / 'samples' / 'day_shift.json').read_text(encoding='utf-8'))
    day = sample['day']
    old_expected = {'rows': [['S01', 'b', 'B', 20]], 'count': 1, 'total': 20}
    fallback_expected = {'rows': [['S01', 'a', 'A', 10]], 'count': 1, 'total': 10}
    empty_expected = {'rows': [], 'count': 0, 'total': 0}
    with TemporaryDirectory(prefix='qingxi-demo-') as directory:
        root = Path(directory)
        source = SourceStore(root / 'source.sqlite')
        published = ArchiveStore(root / 'published.sqlite')
        station = ArchiveStore(root / 'station.sqlite')
        for store in (source, published, station):
            store.initialize()
        for event in sample['operations']:
            revision = _apply(source, day, event)
        old = close_day(source, published, day, revision)
        exchange_day(published, station, old)

        parked_source = root / 'source.detached'
        source.path.rename(parked_source)
        station = ArchiveStore(station.path)
        saved = _summary(read_day(station, old))
        control = _summary(simulate(station, old))
        _scenario('v4', {'day': day, 'operations': sample['operations'], 'bad_batches': []},
                  old_expected, saved, old_expected, control,
                  ['seal/original_ledger.py', 'archive/exchange.py', 'archive/lookup.py', 'rehearsal/report.py'],
                  'b has the highest qualified version and its sole reading is 20')
        scoped = [_summary(simulate(station, old, batches)) for batches in (('B',), ('B', 'H'))]
        _scenario('v5', {'day': day, 'operations': sample['operations'], 'bad_batches': [['B'], ['B', 'H']]},
                  [empty_expected, fallback_expected], scoped, old_expected, _summary(read_day(station, old)),
                  ['seal/evidence.py', 'archive/transfer_codec.py', 'rehearsal/batch_scope.py',
                   'rehearsal/eligibility.py', 'rehearsal/select_rows.py', 'rehearsal/report.py'],
                  'removing B leaves H disabling a; removing H as well leaves a with no restriction')

        parked_source.rename(source.path)
        revision = _apply(source, day, sample['correction'])
        try:
            close_day(source, published, day, revision, before_commit=_interrupt_publication)
        except PublicationError:
            published = ArchiveStore(published.path)
        else:
            raise RuntimeError('interrupted publication unexpectedly returned an account')
        _scenario('v8', {'day': day, 'correction': sample['correction'], 'interrupted': True},
                  {'accounts': 1, 'original': old_expected},
                  {'accounts': _publication_count(published), 'original': _summary(read_day(published, old))},
                  fallback_expected, _summary(simulate(published, old, {'B', 'H'})),
                  ['seal/commit.py', 'archive/storage.py', 'archive/lookup.py', 'rehearsal/report.py'],
                  'the interrupted publication rolls back and leaves the one earlier account')

        new = close_day(source, published, day, revision)
        exchange_day(published, station, new)
        source.path.rename(parked_source)
        station = ArchiveStore(station.path)
        try:
            simulate(station, old, {'C'})
        except UnknownBatch:
            old_rejects_c = True
        else:
            old_rejects_c = False
        _scenario('v9', {'day': day, 'correction': sample['correction'], 'old_bad_batches': ['C']},
                  [old_expected, {'rows': [['S01', 'c', 'C', 30]], 'count': 1, 'total': 30}],
                  [_summary(read_day(station, account)) for account in (old, new)],
                  {'rejects_c': True, 'fallback': fallback_expected},
                  {'rejects_c': old_rejects_c, 'fallback': _summary(simulate(station, old, {'B', 'H'}))},
                  ['seal/cut.py', 'archive/exchange.py', 'archive/lookup.py', 'rehearsal/report.py'],
                  'c belongs only to the new cut, while the original cut still contains a, b, H and B')


def main():
    parser = argparse.ArgumentParser(description='Qingxi water observation lake')
    parser.add_argument('command', choices=('verify', 'demo'))
    command = parser.parse_args().command
    if command == 'verify':
        suite = unittest.defaultTestLoader.discover(str(_ROOT / 'tests'), top_level_dir=str(_ROOT))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    demo()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
