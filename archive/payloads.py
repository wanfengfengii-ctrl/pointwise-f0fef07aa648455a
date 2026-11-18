import re
from dataclasses import dataclass
from typing import Iterable

from intake.observations import require_identifier, require_integer


class InvalidPayload(ValueError):
    pass


@dataclass(frozen=True)
class FrozenObservation:
    slot: str
    observation_id: str
    batch: str
    version: int
    reading: int


@dataclass(frozen=True)
class FrozenDisposition:
    observation_id: str
    batch: str
    sequence: int
    action: str


@dataclass(frozen=True)
class DayEvidence:
    batches: tuple[str, ...]
    observations: tuple[FrozenObservation, ...]
    dispositions: tuple[FrozenDisposition, ...]


@dataclass(frozen=True)
class LedgerRow:
    slot: str
    observation_id: str
    batch: str
    reading: int


@dataclass(frozen=True)
class Ledger:
    rows: tuple[LedgerRow, ...]
    count: int
    total: int


@dataclass(frozen=True)
class FixedDay:
    account: str
    day: str
    revision: int
    original: Ledger
    evidence: DayEvidence


def valid_account(value: object) -> bool:
    return type(value) is str and re.fullmatch(r'D-[0-9a-f]{32}', value) is not None


def make_ledger(rows: Iterable[LedgerRow]) -> Ledger:
    ordered = tuple(sorted(rows, key=lambda row: row.slot))
    return Ledger(ordered, len(ordered), sum(row.reading for row in ordered))


def _check_batch_catalog(batches: tuple[str, ...]) -> set[str]:
    if type(batches) is not tuple or not batches:
        raise InvalidPayload('expected a nonempty batch catalog')
    names = {require_identifier(batch, 'batch') for batch in batches}
    if len(names) != len(batches):
        raise InvalidPayload('duplicate batch in evidence')
    return names


def _check_observations(
    records: tuple[FrozenObservation, ...], batches: set[str]
) -> dict[str, FrozenObservation]:
    if type(records) is not tuple:
        raise InvalidPayload('invalid candidate collection')
    by_id: dict[str, FrozenObservation] = {}
    versions: set[tuple[str, int]] = set()
    for record in records:
        if not isinstance(record, FrozenObservation):
            raise InvalidPayload('bad frozen observation')
        require_identifier(record.slot, 'slot')
        require_identifier(record.observation_id, 'observation_id')
        require_identifier(record.batch, 'batch')
        require_integer(record.version, 'version')
        require_integer(record.reading, 'reading')
        version_key = (record.slot, record.version)
        if record.batch not in batches:
            raise InvalidPayload('observation batch absent from catalog')
        if record.observation_id in by_id or version_key in versions:
            raise InvalidPayload('duplicate observation identity or slot version')
        by_id[record.observation_id] = record
        versions.add(version_key)
    return by_id


def _check_dispositions(
    records: tuple[FrozenDisposition, ...], batches: set[str], candidates: dict[str, FrozenObservation]
) -> None:
    if type(records) is not tuple:
        raise InvalidPayload('invalid disposition collection')
    keys: set[tuple[str, int]] = set()
    for record in records:
        if not isinstance(record, FrozenDisposition):
            raise InvalidPayload('bad frozen disposition')
        require_identifier(record.observation_id, 'observation_id')
        require_identifier(record.batch, 'batch')
        require_integer(record.sequence, 'sequence')
        if type(record.action) is not str or record.action not in ('disable', 'enable'):
            raise InvalidPayload('invalid disposition action')
        if record.batch not in batches or record.observation_id not in candidates:
            raise InvalidPayload('disposition refers to an absent batch or observation')
        key = (record.observation_id, record.sequence)
        if key in keys:
            raise InvalidPayload('duplicate disposition sequence')
        keys.add(key)


def _check_ledger(ledger: Ledger, candidates: dict[str, FrozenObservation]) -> None:
    if not isinstance(ledger, Ledger) or type(ledger.rows) is not tuple:
        raise InvalidPayload('invalid original ledger')
    require_integer(ledger.count, 'count')
    require_integer(ledger.total, 'total')
    previous_slot = None
    total = 0
    for row in ledger.rows:
        if not isinstance(row, LedgerRow):
            raise InvalidPayload('invalid ledger row')
        require_identifier(row.slot, 'slot')
        require_identifier(row.observation_id, 'observation_id')
        require_identifier(row.batch, 'batch')
        require_integer(row.reading, 'reading')
        candidate = candidates.get(row.observation_id)
        if candidate is None or (candidate.slot, candidate.batch, candidate.reading) != (
            row.slot, row.batch, row.reading
        ):
            raise InvalidPayload('ledger row disagrees with its observation')
        if previous_slot is not None and row.slot <= previous_slot:
            raise InvalidPayload('original rows must be ordered by distinct slots')
        previous_slot = row.slot
        total += row.reading
    if ledger.count != len(ledger.rows) or ledger.total != total:
        raise InvalidPayload('incorrect original ledger totals')


def validate_payload(fixed: FixedDay) -> None:
    if not isinstance(fixed, FixedDay) or not valid_account(fixed.account):
        raise InvalidPayload('invalid fixed day account')
    try:
        require_identifier(fixed.day, 'day')
        if require_integer(fixed.revision, 'revision') <= 0:
            raise InvalidPayload('source revision must be positive')
        if not isinstance(fixed.evidence, DayEvidence):
            raise InvalidPayload('invalid evidence object')
        batches = _check_batch_catalog(fixed.evidence.batches)
        candidates = _check_observations(fixed.evidence.observations, batches)
        _check_dispositions(fixed.evidence.dispositions, batches, candidates)
        _check_ledger(fixed.original, candidates)
    except InvalidPayload:
        raise
    except ValueError as exc:
        raise InvalidPayload(str(exc)) from exc
