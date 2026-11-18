import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import UnknownDay
from archive.exchange import ExchangeConflict, accept_fixed_day, export_fixed_day
from archive.lookup import read_day
from archive.payloads import InvalidPayload, LedgerRow
from archive.storage import ArchiveStore
from intake.batches import admit
from intake.observations import ObservationInput
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from rehearsal.report import simulate
from seal.commit import PublicationError
from seal.cut import close_day


DAY = '2026-01-14'
SLOT = 'S01'
A = LedgerRow(SLOT, 'a', 'A', 10)
B = LedgerRow(SLOT, 'b', 'B', 20)
CASES = (
    ('ABH', (A, B, B), ((1, 2, A), (2, 4, B))),
    ('AHB', (A, None, B), ((1, 2, A), (2, 3, None), (3, 4, B))),
)
MANUAL = Path(__file__).resolve().parent / 'samples' / 'manual_fixed_day.json'


def equal(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def rejects(exception, operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except exception:
        return
    raise AssertionError(f'{operation.__name__} should raise {exception.__name__}')


def stores(root, tag):
    source = SourceStore(root / f'{tag}-source.sqlite')
    published = ArchiveStore(root / f'{tag}-published.sqlite')
    station = ArchiveStore(root / f'{tag}-station.sqlite')
    for store in (source, published, station):
        store.initialize()
    return source, published, station


def account_as(raw, account):
    doc = json.loads(raw)
    doc['account'] = account
    return json.dumps(doc, sort_keys=True).encode('utf-8')


def reference_case(root, order, expected):
    source, published, station = stores(root, order)
    for operation in order:
        if operation == 'H':
            add_disposition(source, DAY, 'H', 'a', 1, 'disable')
        else:
            row = A if operation == 'A' else B
            version = 1 if operation == 'A' else 2
            admit(source, DAY, row.batch, [ObservationInput(SLOT, row.observation_id, version, row.reading)])
    for revision, row in enumerate(expected, 1):
        account = close_day(source, published, DAY, revision)
        equal(read_day(published, account).rows, () if row is None else (row,))
    raw = export_fixed_day(published, account)
    equal(accept_fixed_day(station, raw), account)
    return source, published, station, raw


def fixture(root):
    final_packages = [reference_case(root, order, states)[-1] for order, states, _ in CASES]
    key = 'D-' + '0' * 32
    equal(account_as(final_packages[0], key), account_as(final_packages[1], key))
    print('V1 修订原账 ABH=[10,20,20]，AHB=[10,空,20]，统一账号后终件相同')


def detach(source, published, station):
    for store in (source, published):
        store.path.rename(store.path.with_suffix('.detached'))
        equal(store.path.exists(), False)
    return ArchiveStore(station.path)


def incident(root, order, states, intervals, close_history, read_history, *, show):
    source, published, station, old_raw = reference_case(root, order, states)
    old_account = json.loads(old_raw)['account']
    # 来源已经推进至修订 4，这次仍封原先的修订 3。
    admit(source, DAY, 'C', [ObservationInput(SLOT, 'later', 3, 30)])
    account = close_history(source, published, DAY, 3)
    raw = export_fixed_day(published, account)
    equal(accept_fixed_day(station, raw), account)
    equal(accept_fixed_day(station, raw), account)
    station = detach(source, published, station)
    actual = read_history(station, account, SLOT)
    equal(actual, intervals)
    equal(read_day(station, account).rows, (B,))
    equal(read_history(station, account, 'S99'), ((1, 4, None),))
    equal(simulate(station, account, {'B'}).rows, ())
    equal(simulate(station, account, {'B', 'H'}).rows, (A,))
    equal(export_fixed_day(station, old_account), old_raw)
    if show:
        print(order, '断源后终账', read_day(station, account), '修订区间', actual)
    return station, account, raw


def check_exchange(root, first, second, read_history):
    station, account, raw = first
    alternate = account_as(second[2], account)
    control = ArchiveStore(root / 'exchange-control.sqlite')
    control.initialize()
    equal(accept_fixed_day(control, alternate), account)
    equal(read_history(control, account, SLOT), CASES[1][2])
    rejects(ExchangeConflict, accept_fixed_day, station, alternate)
    equal(export_fixed_day(station, account), raw)
    equal(read_history(station, account, SLOT), CASES[0][2])

    broken = json.loads(account_as(second[2], 'D-' + 'f' * 32))
    broken['original']['rows'] = [
        {'slot': SLOT, 'observation_id': 'a', 'batch': 'A', 'reading': '10'},
    ]
    broken['original']['total'] = '10'
    rejects(InvalidPayload, accept_fixed_day, station, json.dumps(broken).encode('utf-8'))
    rejects(UnknownDay, read_day, station, broken['account'])


def check_boundaries(root, close_history, read_history, history_unavailable):
    source, published, station = stores(root, 'boundaries')
    admit(source, DAY, 'A', [ObservationInput(SLOT, 'unused', 0, 8), ObservationInput(SLOT, 'a', 1, 10)])
    admit(source, DAY, 'A', [ObservationInput(SLOT, 'c', 2, 10)])
    revision = add_disposition(source, DAY, 'H', 'c', 9, 'disable')
    add_disposition(source, DAY, 'H', 'c', 2, 'enable')
    attempted = []

    def stop(account):
        attempted.append(account)
        raise OSError('interrupt seal before commit')

    rejects(PublicationError, close_history, source, published, DAY, revision, before_commit=stop)
    equal(len(attempted), 1)
    rejects(UnknownDay, read_history, ArchiveStore(published.path), attempted[0], SLOT)
    account = close_history(source, published, DAY, 4)
    accept_fixed_day(station, export_fixed_day(published, account))
    old = accept_fixed_day(station, MANUAL.read_bytes())
    station = detach(source, published, station)
    equal(read_history(station, account, SLOT), ((1, 2, A), (2, 3, LedgerRow(SLOT, 'c', 'A', 10)), (3, 5, A)))
    rejects(ValueError, read_history, station, account, '')
    rejects(history_unavailable, read_history, station, old, SLOT)
    equal(read_day(station, old).rows, (B,))
    equal(simulate(station, old, {'B', 'H'}).rows, (A,))


def main():
    parser = argparse.ArgumentParser(description='清溪固定日账的历史区间夹具')
    parser.add_argument('command', choices=('fixture', 'verify', 'demo'))
    command = parser.parse_args().command
    with TemporaryDirectory(prefix='qingxi-history-') as directory:
        root = Path(directory)
        if command == 'fixture':
            fixture(root)
            return
        from rehearsal.report import HistoryUnavailable, read_slot_history
        from seal.cut import close_day_with_history

        cases = [incident(root, order, states, intervals, close_day_with_history, read_slot_history,
                          show=command == 'demo') for order, states, intervals in CASES]
        if command == 'verify':
            check_exchange(root, *cases, read_slot_history)
            check_boundaries(root, close_day_with_history, read_slot_history, HistoryUnavailable)
            print('固定日账离线修订区间核账通过')


if __name__ == '__main__':
    main()
