import json

from archive.exchange import ExchangeConflict, accept_fixed_day, export_fixed_day
from archive.lookup import read_day
from archive.payloads import InvalidPayload
from archive.storage import ArchiveStore
from rehearsal.report import simulate
from tests import MANUAL_ACCOUNT, SAMPLES, LakeCase


def encoded(document):
    return json.dumps(document, indent=2).encode('utf-8')


class ExchangeTests(LakeCase):
    def test_exchange_replay_and_conflict(self):
        account = self.handoff(self.incident())
        raw = export_fixed_day(self.published, account)
        replay = json.loads(raw)
        for records in replay['evidence'].values():
            records.reverse()
        self.assertEqual(accept_fixed_day(self.station, encoded(replay)), account)
        self.assertEqual(self.archive_state(self.station), ((account,), 1))

        alternate = json.loads(raw)
        alternate['original']['rows'][0]['reading'] = '21'
        alternate['original']['total'] = '21'
        winner = next(record for record in alternate['evidence']['observations']
                      if record['observation_id'] == 'b')
        winner['reading'] = '21'
        with self.assertRaises(ExchangeConflict):
            accept_fixed_day(self.station, encoded(alternate))
        self.station = ArchiveStore(self.station.path)
        self.assertEqual(self.archive_state(self.station), ((account,), 1))
        self.assertEqual(export_fixed_day(self.station, account), raw)
        self.assert_ledger(read_day(self.station, account), (('S01', 'b', 'B', 20),), 20)

    def test_evidence_only_conflict(self):
        account = self.handoff(self.incident())
        original = export_fixed_day(self.station, account)
        alternate = json.loads(original)
        candidate = next(record for record in alternate['evidence']['observations']
                         if record['observation_id'] == 'a')
        candidate['reading'] = '11'
        other_station = ArchiveStore(self.root / 'control.sqlite')
        other_station.initialize()
        self.assertEqual(accept_fixed_day(other_station, encoded(alternate)), account)
        self.assert_ledger(simulate(other_station, account, {'B', 'H'}),
                           (('S01', 'a', 'A', 11),), 11)
        with self.assertRaises(ExchangeConflict):
            accept_fixed_day(self.station, encoded(alternate))
        self.station = ArchiveStore(self.station.path)
        self.assertEqual(self.archive_state(self.station), ((account,), 1))
        self.assertEqual(export_fixed_day(self.station, account), original)
        self.assert_ledger(read_day(self.station, account), (('S01', 'b', 'B', 20),), 20)
        self.assert_ledger(simulate(self.station, account, {'B', 'H'}),
                           (('S01', 'a', 'A', 10),), 10)

    def test_invalid_payload_preserves_existing_account(self):
        raw = (SAMPLES / 'manual_fixed_day.json').read_bytes()
        accept_fixed_day(self.station, raw)
        original = export_fixed_day(self.station, MANUAL_ACCOUNT)
        invalid = [b'{', b'{"format":1,"format":1}']
        for section, key, value in (
            ('original', 'total', '21'),
            ('original', 'count', True),
            ('evidence', 'batches', ['A', 'B']),
            ('evidence', 'dispositions', [
                {'observation_id': 'missing', 'batch': 'H', 'sequence': '1', 'action': 'disable'},
            ]),
        ):
            altered = json.loads(raw)
            altered[section][key] = value
            invalid.append(encoded(altered))
        altered = json.loads(raw)
        altered['evidence']['observations'][0]['version'] = '1'
        invalid.append(encoded(altered))
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(InvalidPayload):
                    accept_fixed_day(self.station, data)
        self.assertEqual(self.archive_state(self.station), ((MANUAL_ACCOUNT,), 1))
        self.assertEqual(export_fixed_day(self.station, MANUAL_ACCOUNT), original)
        self.assert_ledger(simulate(self.station, MANUAL_ACCOUNT, {'B', 'H'}),
                           (('S01', 'a', 'A', 10),), 10)
