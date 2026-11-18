import json

from archive.payloads import (
    DayEvidence,
    FixedDay,
    FrozenDisposition,
    FrozenObservation,
    InvalidPayload,
    Ledger,
    LedgerRow,
    validate_payload,
)
from intake.observations import integer_text, read_integer_text


_FORMAT = 1


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


def encode_fixed_day(fixed: FixedDay) -> bytes:
    validate_payload(fixed)
    evidence = fixed.evidence
    original = fixed.original
    observations = sorted(evidence.observations, key=lambda record: record.observation_id)
    dispositions = sorted(evidence.dispositions, key=lambda record: (record.observation_id, record.sequence))
    document = {
        'format': _FORMAT,
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


def decode_fixed_day(data: bytes) -> FixedDay:
    if type(data) is not bytes:
        raise InvalidPayload('fixed day contents must be bytes')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        doc = _object(value, 'format', 'account', 'day', 'revision', 'original', 'evidence')
        if type(doc['format']) is not int or doc['format'] != _FORMAT:
            raise InvalidPayload('unsupported fixed day format')
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
        )
        validate_payload(fixed)
        return fixed
    except InvalidPayload:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidPayload('invalid fixed day encoding') from exc
