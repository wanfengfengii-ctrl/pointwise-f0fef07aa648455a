from archive.lookup import read_day
from intake.batches import admit
from intake.observations import AdmissionError, ObservationInput
from intake.revisions import find_observation
from quality.dispositions import add_disposition
from quality.history import DispositionError
from quality.store import read_target_history
from seal.cut import close_day, load_cut
from tests import DAY, LakeCase


class SourceRevisionTests(LakeCase):
    def source_state(self, day=DAY):
        with self.source.snapshot() as connection:
            revision, = connection.execute(
                'SELECT MAX(revision) FROM source_revisions WHERE day = ?', (day,)
            ).fetchone()
            count, = connection.execute(
                'SELECT COUNT(*) FROM source_observations WHERE day = ?', (day,)
            ).fetchone()
        return revision, count

    def test_conflicting_observation_rejects_batch(self):
        self.observation('A', 'a', 1, 10)
        before = self.source_state()
        batch = [ObservationInput('S02', 'b', 1, 3), ObservationInput('S02', 'b', 2, 4)]
        with self.assertRaises(AdmissionError):
            admit(self.source, DAY, 'faulty', batch)
        self.assertEqual(self.source_state(), before)
        self.assertEqual(load_cut(self.source, DAY, 1).batches, ('A',))

    def test_conflict_does_not_admit_valid_sibling(self):
        self.observation('A', 'a', 1, 10)
        batch = [ObservationInput('S03', 'sibling', 1, 8), ObservationInput('S02', 'b', 1, 3),
                 ObservationInput('S02', 'b', 2, 4)]
        with self.assertRaises(AdmissionError):
            admit(self.source, DAY, 'faulty', batch)
        self.assertEqual(self.source_state(), (1, 1))
        with self.source.snapshot() as connection:
            self.assertIsNone(find_observation(connection, DAY, 'sibling'))
        self.assertEqual(self.observation('C', 'sibling', 1, 8, slot='S03').revision, 2)

    def test_identity_version_and_field_conflicts(self):
        self.observation('A', 'a', 1, 10)
        conflicting_batches = (
            [ObservationInput('S02', 'a', 1, 7)],
            [ObservationInput('S01', 'new', 1, 7)],
            [ObservationInput('S02', 'x', 1, 1), ObservationInput('S02', 'y', 1, 2)],
            [ObservationInput('S02', 'x', 1, True)],
            [],
        )
        for records in conflicting_batches:
            with self.subTest(records=records):
                with self.assertRaises(AdmissionError):
                    admit(self.source, DAY, 'bad', records)
                self.assertEqual(self.source_state(), (1, 1))
        with self.assertRaises(AdmissionError):
            self.observation('B', 'a', 1, 8, day='2026-01-15')
        self.assertEqual(self.source_state('2026-01-15'), (None, 0))

    def test_disposition_rejects_unknown_target(self):
        self.observation('A', 'a', 1, 10)
        add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        before = load_cut(self.source, DAY, 2)
        with self.assertRaises(DispositionError):
            add_disposition(self.source, DAY, 'Q', 'missing', 1, 'disable')
        self.assertEqual(self.source_state(), (2, 1))
        self.assertEqual(load_cut(self.source, DAY, 2), before)

    def test_disposition_rejects_cross_day_target(self):
        self.observation('A', 'a', 1, 10)
        other_day = '2026-01-15'
        self.observation('B', 'b', 1, 20, day=other_day)
        with self.assertRaises(DispositionError):
            add_disposition(self.source, other_day, 'H', 'a', 1, 'disable')
        self.assertEqual(self.source_state(other_day), (1, 1))
        self.assertEqual(load_cut(self.source, other_day, 1).dispositions, ())

    def test_disposition_accepts_historical_target(self):
        self.observation('A', 'a', 1, 10)
        self.observation('B', 'b', 2, 20)
        held = add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        released = add_disposition(self.source, DAY, 'B', 'a', 2, 'enable')
        self.assertEqual((held, released), (3, 4))
        with self.source.snapshot() as connection:
            history = read_target_history(connection, DAY, 'a')
        self.assertEqual([(row.observation_id, row.batch, row.action) for row in history],
                         [('a', 'H', 'disable'), ('a', 'B', 'enable')])

    def test_disposition_rejects_sequence_conflict(self):
        self.observation('A', 'a', 1, 10)
        add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        with self.assertRaises(DispositionError):
            add_disposition(self.source, DAY, 'B', 'a', 1, 'enable')
        self.assertEqual(self.source_state(), (2, 1))
        cut = load_cut(self.source, DAY, 2)
        self.assertEqual(cut.batches, ('A', 'H'))
        self.assertEqual([(row.batch, row.sequence, row.action) for row in cut.dispositions],
                         [('H', 1, 'disable')])

    def test_late_disposition_keeps_newer_sequence_effective(self):
        self.observation('A', 'a', 1, 10)
        add_disposition(self.source, DAY, 'H', 'a', 10, 'disable')
        revision = add_disposition(self.source, DAY, 'G', 'a', -2, 'enable')
        account = close_day(self.source, self.published, DAY, revision)
        self.assert_ledger(read_day(self.published, account), (), 0)
