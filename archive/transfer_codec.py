import json

from archive.payloads import (
    DayEvidence,
    DayHistory,
    FixedDay,
    FrozenDisposition,
    FrozenObservation,
    HistoryTransaction,
    InvalidPayload,
    Ledger,
    LedgerRow,
    validate_payload,
)
from intake.observations import integer_text, read_integer_text


_FORMAT = 1
_HISTORY_FORMAT = 2


def _ledger_row(row: LedgerRow) -> dict:
    return {
        'slot': row.slot,
        'observation_id': row.observation_id,
        'batch': row.batch,
        'reading': integer_text(row.reading),
    }


def _observation(record: FrozenObservation) -> dict:
    return {
        'slot': record.slot,
        'observation_id': record.observation_id,
        'batch': record.batch,
        'version': integer_text(record.version),
        'reading': integer_text(record.reading),
    }


def _disposition(record: FrozenDisposition) -> dict:
    return {
        'observation_id': record.observation_id,
        'batch': record.batch,
        'sequence': integer_text(record.sequence),
        'action': record.action,
    }


def _history(fixed: FixedDay) -> dict | None:
    if fixed.history is None:
        return None
    transactions = []
    for transaction in sorted(fixed.history.transactions, key=lambda item: item.revision):
        transactions.append({
            'revision': integer_text(transaction.revision),
            'observations': [_observation(record) for record in sorted(
                transaction.observations, key=lambda item: item.observation_id
            )],
            'dispositions': [_disposition(record) for record in sorted(
                transaction.dispositions, key=lambda item: (item.observation_id, item.sequence)
            )],
        })
    return {'transactions': transactions}


def encode_fixed_day(fixed: FixedDay) -> bytes:
    validate_payload(fixed)
    evidence = fixed.evidence
    original = fixed.original
    observations = sorted(evidence.observations, key=lambda record: record.observation_id)
    dispositions = sorted(evidence.dispositions, key=lambda record: (record.observation_id, record.sequence))
    history = _history(fixed)
    document = {
        'format': _FORMAT if history is None else _HISTORY_FORMAT,
        'account': fixed.account,
        'day': fixed.day,
        'revision': integer_text(fixed.revision),
        'original': {
            'rows': [_ledger_row(row) for row in original.rows],
            'count': original.count,
            'total': integer_text(original.total),
        },
        'evidence': {
            'batches': sorted(evidence.batches),
            'observations': [_observation(record) for record in observations],
            'dispositions': [_disposition(record) for record in dispositions],
        },
    }
    if history is not None:
        document['history'] = history
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidPayload(f'duplicate field: {key}')
        result[key] = value
    return result


def _reject_constant(token: str):
    raise InvalidPayload(f'invalid JSON constant: {token}')


def _object(value: object, *fields: str) -> dict:
    if type(value) is not dict or value.keys() != set(fields):
        raise InvalidPayload(f'expected fields {", ".join(fields)}')
    return value


def _array(value: object) -> list:
    if type(value) is not list:
        raise InvalidPayload('expected an array')
    return value


def _decode_row(value: object) -> LedgerRow:
    row = _object(value, 'slot', 'observation_id', 'batch', 'reading')
    return LedgerRow(row['slot'], row['observation_id'], row['batch'], read_integer_text(row['reading']))


def _decode_observation(value: object) -> FrozenObservation:
    row = _object(value, 'slot', 'observation_id', 'batch', 'version', 'reading')
    return FrozenObservation(row['slot'], row['observation_id'], row['batch'],
                             read_integer_text(row['version']), read_integer_text(row['reading']))


def _decode_disposition(value: object) -> FrozenDisposition:
    row = _object(value, 'observation_id', 'batch', 'sequence', 'action')
    return FrozenDisposition(row['observation_id'], row['batch'],
                             read_integer_text(row['sequence']), row['action'])


def _decode_history(value: object) -> DayHistory:
    doc = _object(value, 'transactions')
    transactions = []
    for item in _array(doc['transactions']):
        record = _object(item, 'revision', 'observations', 'dispositions')
        transactions.append(HistoryTransaction(
            read_integer_text(record['revision']),
            tuple(_decode_observation(row) for row in _array(record['observations'])),
            tuple(_decode_disposition(row) for row in _array(record['dispositions'])),
        ))
    return DayHistory(tuple(transactions))


def decode_fixed_day(data: bytes) -> FixedDay:
    if type(data) is not bytes:
        raise InvalidPayload('fixed day contents must be bytes')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        field = 'format', 'account', 'day', 'revision', 'original', 'evidence'
        if type(value) is not dict:
            raise InvalidPayload('invalid fixed day encoding')
        version = value.get('format')
        if type(version) is not int or version not in (_FORMAT, _HISTORY_FORMAT):
            raise InvalidPayload('unsupported fixed day format')
        doc = _object(value, *field) if version == _FORMAT else _object(value, *field, 'history')
        original = _object(doc['original'], 'rows', 'count', 'total')
        evidence = _object(doc['evidence'], 'batches', 'observations', 'dispositions')
        fixed = FixedDay(
            doc['account'],
            doc['day'],
            read_integer_text(doc['revision']),
            Ledger(tuple(_decode_row(row) for row in _array(original['rows'])),
                   original['count'], read_integer_text(original['total'])),
            DayEvidence(
                tuple(_array(evidence['batches'])),
                tuple(_decode_observation(row) for row in _array(evidence['observations'])),
                tuple(_decode_disposition(row) for row in _array(evidence['dispositions'])),
            ),
            None if version == _FORMAT else _decode_history(doc['history']),
        )
        validate_payload(fixed)
        return fixed
    except InvalidPayload:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidPayload('invalid fixed day encoding') from exc
