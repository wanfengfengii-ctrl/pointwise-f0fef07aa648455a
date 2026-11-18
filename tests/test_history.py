from archive.catalog import UnknownDay
from archive.exchange import ExchangeConflict, accept_fixed_day, exchange_day, export_fixed_day
from archive.lookup import read_day
from archive.payloads import InvalidPayload, LedgerRow
from archive.storage import ArchiveStore
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from rehearsal.batch_scope import UnknownBatch
from rehearsal.report import HistoryUnavailable, read_slot_history, simulate
from seal.commit import PublicationError
from seal.cut import close_day, close_day_with_history, load_cut
from tests import DAY, SAMPLES, LakeCase


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


def _row(observation_id, batch, reading, slot='S01'):
    return LedgerRow(slot, observation_id, batch, reading)


class SlotHistoryTests(LakeCase):
    def history_handoff(self, revision):
        account = close_day_with_history(self.source, self.published, DAY, revision)
        self.assertEqual(exchange_day(self.published, self.station, account), account)
        return account

    def test_interval_orders_differ_between_shifts(self):
        self.observation('A', 'a', 1, 10)
        self.observation('B', 'b', 2, 20)
        revision = add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        self.observation('C', 'c', 3, 30)
        early = self.history_handoff(revision)
        self.detach_source()
        self.assertEqual(read_slot_history(self.station, early, 'S01'),
                         ((1, 2, _row('a', 'A', 10)), (2, 4, _row('b', 'B', 20))))
        self.assertEqual(read_slot_history(self.station, early, 'S99'), ((1, 4, None),))
        self.assert_ledger(read_day(self.station, early), (('S01', 'b', 'B', 20),), 20)

    def test_blank_slot_between_versions_is_preserved(self):
        revision = self.incident()
        self.observation('K', 'k', 5, 50)
        account = self.history_handoff(revision)
        second = self.history_handoff(revision)
        self.detach_source()
        expected = ((1, 2, _row('a', 'A', 10)), (2, 3, None), (3, 5, _row('b', 'B', 20)))
        self.assertEqual(read_slot_history(self.station, account, 'S01'), expected)
        self.assert_ledger(read_day(self.station, second), (('S01', 'b', 'B', 20),), 20)
        self.assertEqual(read_slot_history(self.station, second, 'S01'), expected)

    def test_interrupted_history_seal_is_unclaimable(self):
        self.observation('A', 'a', 1, 10)
        revision = add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        attempted = []

        def stop(account):
            attempted.append(account)
            raise OSError('interrupted before commit')

        with self.assertRaises(PublicationError):
            close_day_with_history(self.source, self.published, DAY, revision, before_commit=stop)
        self.published = ArchiveStore(self.published.path)
        self.station = ArchiveStore(self.station.path)
        self.assertEqual(len(attempted), 1)
        self.assertEqual(self.archive_state(self.published), ((), 0))
        with self.assertRaises(UnknownDay):
            read_slot_history(self.published, attempted[0], 'S01')
        account = self.history_handoff(revision)
        self.detach_source()
        self.assertEqual(read_slot_history(self.station, account, 'S01'),
                         ((1, 2, _row('a', 'A', 10)), (2, 3, None)))
        self.assert_ledger(read_day(self.station, account), (), 0)

    def test_old_payload_has_no_history(self):
        old = accept_fixed_day(self.station, (SAMPLES / 'manual_fixed_day.json').read_bytes())
        self.assert_ledger(read_day(self.station, old), (('S01', 'b', 'B', 20),), 20)
        self.assertEqual(simulate(self.station, old, {'B', 'H'}).total, 10)
        with self.assertRaises(HistoryUnavailable):
            read_slot_history(self.station, old, 'S01')
        for slot in ('', ' S01', 'S01\x00'):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):
                    read_slot_history(self.station, old, slot)

    def shift_source(self, tag, order):
        store = SourceStore(self.root / f'{tag}.sqlite')
        store.initialize()
        from intake.batches import admit
        from intake.observations import ObservationInput

        for operation in order:
            if operation == 'H':
                add_disposition(store, DAY, 'H', 'a', 1, 'disable')
            elif operation == 'A':
                admit(store, DAY, 'A', [ObservationInput('S01', 'a', 1, 10)])
            else:
                admit(store, DAY, 'B', [ObservationInput('S01', 'b', 2, 20)])
        return store

    def rebind(self, raw, account):
        import json

        doc = json.loads(raw)
        doc['account'] = account
        return json.dumps(doc, sort_keys=True).encode('utf-8')

    def test_history_conflict_preserves_first_fixed_result(self):
        # 两种交班在修订 3 的原账同为 b，但 ABH 与 AHB 的逐槽区间不同。
        source = self.shift_source('abh', 'ABH')
        handoff = close_day_with_history(source, self.published, DAY, 3)
        exchange_day(self.published, self.station, handoff)
        raw = export_fixed_day(self.station, handoff)

        alternate_source = self.shift_source('ahb', 'AHB')
        alternate_published = ArchiveStore(self.root / 'alternate-published.sqlite')
        alternate_published.initialize()
        alternate = close_day_with_history(alternate_source, alternate_published, DAY, 3)
        alternate_doc = self.rebind(export_fixed_day(alternate_published, alternate), handoff)
        self.assertNotEqual(alternate_doc, raw)
        control = ArchiveStore(self.root / 'control.sqlite')
        control.initialize()
        self.assertEqual(accept_fixed_day(control, alternate_doc), handoff)
        self.assertEqual(read_slot_history(control, handoff, 'S01'),
                         ((1, 2, _row('a', 'A', 10)), (2, 3, None), (3, 4, _row('b', 'B', 20))))
        with self.assertRaises(ExchangeConflict):
            accept_fixed_day(self.station, alternate_doc)
        self.assertEqual(export_fixed_day(self.station, handoff), raw)
        self.assertEqual(read_slot_history(self.station, handoff, 'S01'),
                         ((1, 2, _row('a', 'A', 10)), (2, 4, _row('b', 'B', 20))))

    def test_broken_history_is_rejected(self):
        source = self.shift_source('broken', 'ABH')
        account = close_day_with_history(source, self.published, DAY, 3)
        exchange_day(self.published, self.station, account)
        raw = export_fixed_day(self.station, account)
        import json

        broken = json.loads(raw)
        broken['history']['transactions'][0]['revision'] = '2'
        with self.assertRaises(InvalidPayload):
            accept_fixed_day(self.station, json.dumps(broken).encode('utf-8'))
        broken = json.loads(raw)
        broken['history']['transactions'][0]['observations'] = []
        with self.assertRaises(InvalidPayload):
            accept_fixed_day(self.station, json.dumps(broken).encode('utf-8'))
        broken = json.loads(raw)
        broken['history']['transactions'][0]['observations'][0]['reading'] = '11'
        with self.assertRaises(InvalidPayload):
            accept_fixed_day(self.station, json.dumps(broken).encode('utf-8'))
        broken = json.loads(raw)
        broken['history']['transactions'].pop()
        with self.assertRaises(InvalidPayload):
            accept_fixed_day(self.station, json.dumps(broken).encode('utf-8'))
        self.assertEqual(self.archive_state(self.station), ((account,), 1))
        self.assertEqual(export_fixed_day(self.station, account), raw)

    def test_adjacent_intervals_merge_only_when_identical(self):
        from intake.batches import admit
        from intake.observations import ObservationInput

        admit(self.source, DAY, 'A', [ObservationInput('S01', 'a', 1, 10)])
        admit(self.source, DAY, 'B', [ObservationInput('S02', 'b', 1, 20)])
        add_disposition(self.source, DAY, 'H', 'a', 1, 'disable')
        revision = admit(
            self.source, DAY, 'C', [ObservationInput('S01', 'c', 3, 30)]
        ).revision
        account = self.history_handoff(revision)
        self.detach_source()
        # a 在修订 1、2 都可用而合并；b 在修订 2、3、4 不变而合并；S03 始终为空。
        self.assertEqual(read_slot_history(self.station, account, 'S01'),
                         ((1, 3, _row('a', 'A', 10)), (3, 4, None), (4, 5, _row('c', 'C', 30))))
        self.assertEqual(read_slot_history(self.station, account, 'S02'),
                         ((1, 2, None), (2, 5, _row('b', 'B', 20, slot='S02'))))
        self.assertEqual(read_slot_history(self.station, account, 'S03'), ((1, 5, None),))
