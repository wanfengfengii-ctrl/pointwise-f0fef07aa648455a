from archive.lookup import load_fixed_day, read_day
from intake.revisions import UnknownRevision
from quality.dispositions import add_disposition
from seal.cut import close_day
from tests import DAY, LakeCase


class DayCloseTests(LakeCase):
    def test_close_with_quality(self):
        self.observation('A', 'a', 1, 10)
        self.observation('B', 'b', 2, 20)
        revision = add_disposition(self.source, DAY, 'Q', 'b', 1, 'disable')
        account = close_day(self.source, self.published, DAY, revision)
        self.assert_ledger(read_day(self.published, account), (('S01', 'a', 'A', 10),), 10)

    def test_late_lower_version(self):
        self.observation('B', 'b', 2, 20)
        self.observation('C', 'c', 3, 30)
        add_disposition(self.source, DAY, 'Q', 'c', 1, 'disable')
        receipt = self.observation('A', 'a', 1, 10)
        account = close_day(self.source, self.published, DAY, receipt.revision)
        self.assert_ledger(read_day(self.published, account), (('S01', 'b', 'B', 20),), 20)

    def test_fixed_evidence_history(self):
        revision = self.incident()
        add_disposition(self.source, DAY, 'L', 'a', 0, 'enable')
        account = close_day(self.source, self.published, DAY, revision)
        fixed = load_fixed_day(self.published, account)
        self.assertEqual((fixed.day, fixed.revision), (DAY, 4))
        self.assertEqual(fixed.evidence.batches, ('A', 'B', 'H'))
        self.assertEqual(
            [(row.observation_id, row.batch, row.version, row.reading) for row in fixed.evidence.observations],
            [('a', 'A', 1, 10), ('b', 'B', 2, 20)],
        )
        self.assertEqual(
            [(row.observation_id, row.batch, row.sequence, row.action) for row in fixed.evidence.dispositions],
            [('a', 'H', 1, 'disable'), ('a', 'B', 2, 'enable')],
        )

    def test_invalid_revision(self):
        self.observation('A', 'a', 1, 10)
        self.observation('B', 'other1', 1, 5, day='2026-01-15')
        self.observation('C', 'other2', 2, 6, day='2026-01-15')
        for day, revision in ((DAY, 2), (DAY, 0), (DAY, True), ('unknown', 1)):
            with self.subTest(day=day, revision=revision):
                with self.assertRaises(UnknownRevision):
                    close_day(self.source, self.published, day, revision)
        self.assertEqual(self.archive_state(self.published), ((), 0))
