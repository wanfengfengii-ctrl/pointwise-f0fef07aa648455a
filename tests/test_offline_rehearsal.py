from archive.catalog import UnknownDay
from archive.exchange import accept_fixed_day, export_fixed_day
from archive.lookup import read_day
from archive.transfer_codec import decode_fixed_day
from quality.dispositions import add_disposition
from rehearsal.batch_scope import InvalidQuarantine, UnknownBatch
from rehearsal.report import simulate
from seal.cut import close_day, load_cut
from tests import DAY, MANUAL_ACCOUNT, SAMPLES, LakeCase


class OfflineRehearsalTests(LakeCase):
    def test_empty_quarantine_matches_published_day(self):
        account = self.handoff(self.incident())
        published = read_day(self.published, account)
        self.detach_source()
        actual = simulate(self.station, account, set())
        self.assert_ledger(actual, (('S01', 'b', 'B', 20),), 20)
        self.assertEqual(actual, published)
        self.assertEqual(read_day(self.station, account), published)

    def test_shared_batch_removal_and_fallback(self):
        account = self.handoff(self.incident())
        self.detach_source()
        self.assert_ledger(read_day(self.station, account), (('S01', 'b', 'B', 20),), 20)
        self.assert_ledger(simulate(self.station, account, {'B'}), (), 0)
        self.assert_ledger(simulate(self.station, account, {'B', 'H'}),
                           (('S01', 'a', 'A', 10),), 10, 'QUARANTINE_FALLBACK_MISMATCH')
        self.assert_ledger(read_day(self.station, account), (('S01', 'b', 'B', 20),), 20)

    def test_evidence_handoff_preserves_the_selected_cut(self):
        revision = self.incident()
        cut = load_cut(self.source, DAY, revision)
        account = close_day(self.source, self.published, DAY, revision)
        fixed = decode_fixed_day(export_fixed_day(self.published, account))
        self.assertEqual(fixed.evidence.batches, cut.batches)
        self.assertEqual(
            {(record.slot, record.observation_id, record.batch, record.version, record.reading)
             for record in fixed.evidence.observations},
            {(record.slot, record.observation_id, record.batch, record.version, record.reading)
             for record in cut.observations},
        )
        self.assertEqual(
            {(record.observation_id, record.batch, record.sequence, record.action)
             for record in fixed.evidence.dispositions},
            {(record.observation_id, record.batch, record.sequence, record.action)
             for record in cut.dispositions},
        )
        self.assertEqual([(row.observation_id, row.batch) for row in fixed.evidence.observations],
                         [('a', 'A'), ('b', 'B')])
        self.assertEqual([(row.batch, row.action) for row in fixed.evidence.dispositions],
                         [('H', 'disable'), ('B', 'enable')])

    def test_manual_evidence_can_be_consumed_without_source(self):
        data = (SAMPLES / 'manual_fixed_day.json').read_bytes()
        self.assertEqual(accept_fixed_day(self.station, data), MANUAL_ACCOUNT)
        self.detach_source()
        self.assert_ledger(simulate(self.station, MANUAL_ACCOUNT, {'B'}), (), 0)
        self.assert_ledger(simulate(self.station, MANUAL_ACCOUNT, {'H', 'B'}),
                           (('S01', 'a', 'A', 10),), 10)
        self.assert_ledger(read_day(self.station, MANUAL_ACCOUNT), (('S01', 'b', 'B', 20),), 20)

    def test_fallback_before_newer_disabled(self):
        self.observation('A', 'a', 1, 10)
        self.observation('B', 'b', 2, 20)
        self.observation('C', 'c', 3, 30)
        add_disposition(self.source, DAY, 'H', 'b', 1, 'disable')
        revision = add_disposition(self.source, DAY, 'C', 'b', 2, 'enable')
        account = self.handoff(revision)
        self.detach_source()
        self.assert_ledger(read_day(self.station, account), (('S01', 'c', 'C', 30),), 30)
        self.assert_ledger(simulate(self.station, account, {'C'}), (('S01', 'a', 'A', 10),), 10)
        self.assert_ledger(simulate(self.station, account, {'C', 'H'}), (('S01', 'b', 'B', 20),), 20)

    def test_zero_reading_and_shared_scope(self):
        self.observation('A', 'right', 1, 7, slot='S02')
        self.observation('A', 'left', 1, 0, slot='S01')
        add_disposition(self.source, DAY, 'H', 'left', 1, 'disable')
        revision = add_disposition(self.source, DAY, 'H', 'right', 1, 'disable')
        account = self.handoff(revision)
        self.detach_source()
        self.assert_ledger(read_day(self.station, account), (), 0)
        self.assert_ledger(simulate(self.station, account, ['H', 'H']),
                           (('S01', 'left', 'A', 0), ('S02', 'right', 'A', 7)), 7)

    def test_exact_integer_totals(self):
        self.observation('A', 'wide1', 1, 2**63, slot='S01')
        self.observation('A', 'wide2', 1, 2**63 + 5, slot='S02')
        revision = self.observation('C', 'negative', 1, -2**70, slot='S03').revision
        account = self.handoff(revision)
        self.detach_source()
        rows = (('S01', 'wide1', 'A', 2**63), ('S02', 'wide2', 'A', 2**63 + 5))
        self.assert_ledger(read_day(self.station, account), rows + (('S03', 'negative', 'C', -2**70),),
                           2**64 + 5 - 2**70)
        self.assert_ledger(simulate(self.station, account, {'C'}), rows, 2**64 + 5)

    def test_quarantine_rejects_batch_from_another_revision(self):
        old = self.handoff(self.incident())
        new = self.handoff(self.observation('C', 'c', 3, 30).revision)
        self.detach_source()
        with self.assertRaises(UnknownBatch) as rejected:
            simulate(self.station, old, {'C', 'B'})
        self.assertEqual(rejected.exception.batches, ('C',))
        self.assert_ledger(simulate(self.station, new, {'C'}), (('S01', 'b', 'B', 20),), 20)
        self.assert_ledger(read_day(self.station, old), (('S01', 'b', 'B', 20),), 20)

    def test_unknown_account_and_invalid_scope(self):
        for operation in (read_day, simulate):
            with self.assertRaises(UnknownDay):
                operation(self.station, MANUAL_ACCOUNT)
        account = self.handoff(self.incident())
        for value in ('B', [False], None):
            with self.subTest(value=value):
                with self.assertRaises(InvalidQuarantine):
                    simulate(self.station, account, value)
        self.assert_ledger(read_day(self.station, account), (('S01', 'b', 'B', 20),), 20)
