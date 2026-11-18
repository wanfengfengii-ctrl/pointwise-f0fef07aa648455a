from archive.catalog import UnknownDay
from archive.exchange import exchange_day, export_fixed_day
from archive.lookup import read_day
from archive.storage import ArchiveStore
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from rehearsal.batch_scope import UnknownBatch
from rehearsal.report import simulate
from seal.commit import PublicationError
from seal.cut import close_day, load_cut
from tests import DAY, LakeCase


class HistoryTests(LakeCase):
    def interrupted_close(self, revision):
        attempted = []

        def interrupt(account):
            attempted.append(account)
            raise OSError('handoff staging interrupted')

        with self.assertRaises(PublicationError):
            close_day(self.source, self.published, DAY, revision, before_commit=interrupt)
        self.assertEqual(len(attempted), 1)
        return attempted[0]

    def test_failed_close_preserves_old_day(self):
        old = self.handoff(self.incident())
        before = self.archive_state(self.published)
        revision = self.observation('C', 'c', 3, 30).revision
        failed = self.interrupted_close(revision)
        self.published = ArchiveStore(self.published.path)
        self.station = ArchiveStore(self.station.path)
        self.assertEqual(self.archive_state(self.published), before)
        with self.assertRaises(UnknownDay):
            read_day(self.published, failed)
        with self.assertRaises(UnknownDay):
            export_fixed_day(self.published, failed)
        for store in (self.published, self.station):
            self.assert_ledger(read_day(store, old), (('S01', 'b', 'B', 20),), 20)
            self.assert_ledger(simulate(store, old, {'B', 'H'}), (('S01', 'a', 'A', 10),), 10)

    def test_retry_after_rollback(self):
        old = self.handoff(self.incident())
        revision = self.observation('C', 'c', 3, 30).revision
        failed = self.interrupted_close(revision)
        self.published = ArchiveStore(self.published.path)
        self.assertEqual(self.archive_state(self.published), ((old,), 1))
        new = self.handoff(revision)
        self.assertNotIn(new, {old, failed})
        self.assertEqual(self.archive_state(self.published), (tuple(sorted((old, new))), 2))
        self.assert_ledger(read_day(self.station, new), (('S01', 'c', 'C', 30),), 30)

    def test_correction_does_not_change_original_exchange(self):
        old_revision = self.incident()
        old = self.handoff(old_revision)
        old_contents = export_fixed_day(self.station, old)
        new = self.handoff(self.observation('C', 'c', 3, 30).revision)
        self.detach_source()
        self.assertNotEqual(old, new)
        self.assertEqual(export_fixed_day(self.station, old), old_contents)
        self.assert_ledger(read_day(self.station, new), (('S01', 'c', 'C', 30),), 30)
        self.assert_ledger(read_day(self.station, old), (('S01', 'b', 'B', 20),), 20)
        self.assert_ledger(simulate(self.station, old, {'B'}), (), 0)
        self.assert_ledger(simulate(self.station, old, {'B', 'H'}), (('S01', 'a', 'A', 10),), 10)
        with self.assertRaises(UnknownBatch):
            simulate(self.station, old, {'C'})

    def test_historical_cut_after_correction(self):
        early_revision = self.incident()
        prior = self.handoff(early_revision)
        self.observation('C', 'c', 3, 30)
        current = self.handoff(add_disposition(self.source, DAY, 'Q', 'a', 3, 'disable'))
        historical = self.handoff(early_revision)
        self.assertNotEqual(historical, prior)
        self.detach_source()
        self.assert_ledger(read_day(self.station, current), (('S01', 'c', 'C', 30),), 30)
        self.assert_ledger(simulate(self.station, current, {'C', 'B', 'H'}), (), 0)
        self.assert_ledger(read_day(self.station, historical), (('S01', 'b', 'B', 20),), 20)
        self.assert_ledger(simulate(self.station, historical, {'B', 'H'}),
                           (('S01', 'a', 'A', 10),), 10)
        for batch in ('C', 'Q'):
            with self.subTest(batch=batch):
                with self.assertRaises(UnknownBatch):
                    simulate(self.station, historical, {batch})

    def test_reopen_initialization_preserves_business_writes(self):
        original_revision = self.incident()
        old = self.handoff(original_revision)
        self.observation('C', 'c', 3, 30)
        correction_revision = add_disposition(self.source, DAY, 'K', 'b', 7, 'disable')
        new = self.handoff(correction_revision)
        for _ in range(2):
            self.source = SourceStore(self.source.path)
            self.published = ArchiveStore(self.published.path)
            self.station = ArchiveStore(self.station.path)
            for store in (self.source, self.published, self.station):
                store.initialize()
        cut = load_cut(self.source, DAY, correction_revision)
        self.assertEqual(cut.revision, 6)
        self.assertEqual(cut.batches, ('A', 'B', 'C', 'H', 'K'))
        self.assertEqual([(row.observation_id, row.reading) for row in cut.observations],
                         [('a', 10), ('b', 20), ('c', 30)])
        self.assertEqual((cut.dispositions[-1].batch, cut.dispositions[-1].action), ('K', 'disable'))
        self.assertEqual(exchange_day(self.published, self.station, new), new)
        for store in (self.published, self.station):
            self.assertEqual(self.archive_state(store), (tuple(sorted((old, new))), 2))
            self.assert_ledger(read_day(store, old), (('S01', 'b', 'B', 20),), 20)
            self.assert_ledger(read_day(store, new), (('S01', 'c', 'C', 30),), 30)
            self.assert_ledger(simulate(store, old, {'B', 'H'}), (('S01', 'a', 'A', 10),), 10)
            self.assert_ledger(simulate(store, new, {'C'}), (('S01', 'a', 'A', 10),), 10)
