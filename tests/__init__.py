import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.exchange import exchange_day
from archive.storage import ArchiveStore
from intake.batches import admit
from intake.observations import ObservationInput
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from seal.cut import close_day


DAY = '2026-01-14'
MANUAL_ACCOUNT = 'D-' + '1' * 32
SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


class LakeCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = SourceStore(self.root / 'source.sqlite')
        self.published = ArchiveStore(self.root / 'published.sqlite')
        self.station = ArchiveStore(self.root / 'station.sqlite')
        for store in (self.source, self.published, self.station):
            store.initialize()

    def observation(self, batch, observation_id, version, reading, slot='S01', day=DAY):
        return admit(self.source, day, batch, [ObservationInput(slot, observation_id, version, reading)])

    def incident(self):
        self.observation('A', 'a', 1, 10)
        add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        self.observation('B', 'b', 2, 20)
        return add_disposition(self.source, DAY, 'B', 'a', 2, 'enable')

    def handoff(self, revision):
        account = close_day(self.source, self.published, DAY, revision)
        self.assertEqual(exchange_day(self.published, self.station, account), account)
        return account

    def detach_source(self):
        self.source.path.rename(self.root / 'source.detached')
        self.assertFalse(self.source.path.exists())
        self.station = ArchiveStore(self.station.path)

    def archive_state(self, store):
        with store.snapshot() as connection:
            accounts = tuple(account for (account,) in connection.execute(
                'SELECT account FROM fixed_catalog ORDER BY account'
            ))
            payloads, = connection.execute('SELECT COUNT(*) FROM fixed_payloads').fetchone()
        return accounts, payloads

    def assert_ledger(self, result, expected_rows, expected_total, message=None):
        actual = tuple((row.slot, row.observation_id, row.batch, row.reading) for row in result.rows)
        self.assertEqual(actual, expected_rows, message)
        self.assertEqual(result.count, len(expected_rows), message)
        self.assertEqual(result.total, expected_total, message)
