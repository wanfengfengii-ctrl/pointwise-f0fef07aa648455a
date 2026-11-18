from typing import Iterable, Sequence

from archive.payloads import (
    DayHistory,
    FixedDay,
    FrozenDisposition,
    FrozenObservation,
    HistoryTransaction,
    InvalidPayload,
    Ledger,
    LedgerRow,
    make_ledger,
)
from intake.observations import require_identifier, require_integer
from quality.history import latest_dispositions


def slot_row(
    slot: str,
    observations: Iterable[FrozenObservation],
    dispositions: Iterable[FrozenDisposition],
) -> LedgerRow | None:
    latest = latest_dispositions(dispositions)
    disabled = {target for target, record in latest.items() if record.action == 'disable'}
    winner = None
    for record in observations:
        if record.slot != slot or record.observation_id in disabled:
            continue
        if winner is None or record.version > winner.version:
            winner = record
    if winner is None:
        return None
    return LedgerRow(winner.slot, winner.observation_id, winner.batch, winner.reading)


def _ordered(history: DayHistory) -> Sequence[HistoryTransaction]:
    return sorted(history.transactions, key=lambda item: item.revision)


def slot_intervals(
    history: DayHistory, slot: str, revision: int
) -> tuple[tuple[int, int, LedgerRow | None], ...]:
    if revision < 1:
        return ()
    observations: list[FrozenObservation] = []
    dispositions: list[FrozenDisposition] = []
    segments: list[tuple[int, int, LedgerRow | None]] = []
    start = 1

    def close(end: int) -> None:
        segments.append((start, end, slot_row(slot, observations, dispositions)))

    for transaction in _ordered(history):
        if transaction.revision > revision or transaction.revision < 1:
            continue
        if transaction.revision > start:
            close(transaction.revision)
            start = transaction.revision
        observations.extend(transaction.observations)
        dispositions.extend(transaction.dispositions)
    close(revision + 1)
    merged: list[tuple[int, int, LedgerRow | None]] = []
    for segment in segments:
        if merged and merged[-1][2] == segment[2]:
            merged[-1] = (merged[-1][0], segment[1], segment[2])
        else:
            merged.append(segment)
    return tuple(merged)


def final_rows(history: DayHistory, revision: int) -> Ledger:
    observations: list[FrozenObservation] = []
    dispositions: list[FrozenDisposition] = []
    slots: set[str] = set()
    for transaction in _ordered(history):
        if transaction.revision > revision:
            continue
        observations.extend(transaction.observations)
        dispositions.extend(transaction.dispositions)
    for record in observations:
        slots.add(record.slot)
    rows = []
    for slot in sorted(slots):
        row = slot_row(slot, observations, dispositions)
        if row is not None:
            rows.append(row)
    return make_ledger(rows)


def _observation_key(record: FrozenObservation) -> tuple:
    return (record.slot, record.observation_id, record.batch, record.version, record.reading)


def _disposition_key(record: FrozenDisposition) -> tuple:
    return (record.observation_id, record.batch, record.sequence, record.action)


def _check_frozen_observation(record: object) -> None:
    if not isinstance(record, FrozenObservation):
        raise InvalidPayload('bad frozen observation in history')
    require_identifier(record.slot, 'slot')
    require_identifier(record.observation_id, 'observation_id')
    require_identifier(record.batch, 'batch')
    require_integer(record.version, 'version')
    require_integer(record.reading, 'reading')


def _check_frozen_disposition(record: object) -> None:
    if not isinstance(record, FrozenDisposition):
        raise InvalidPayload('bad frozen disposition in history')
    require_identifier(record.observation_id, 'observation_id')
    require_identifier(record.batch, 'batch')
    require_integer(record.sequence, 'sequence')
    if type(record.action) is not str or record.action not in ('disable', 'enable'):
        raise InvalidPayload('invalid disposition action in history')


def validate_history(fixed: FixedDay) -> None:
    history = fixed.history
    if not isinstance(history, DayHistory) or type(history.transactions) is not tuple:
        raise InvalidPayload('invalid day history')
    transactions = _ordered(history)
    if not transactions:
        raise InvalidPayload('day history carries no transaction')
    revision = fixed.revision
    expected = 1
    observation_revision: dict[str, int] = {}
    slot_versions: set[tuple[str, int]] = set()
    disposition_sequences: set[tuple[str, int]] = set()
    batch_first: dict[str, int] = {}
    observations: list[FrozenObservation] = []
    dispositions: list[FrozenDisposition] = []
    for transaction in transactions:
        if not isinstance(transaction, HistoryTransaction):
            raise InvalidPayload('invalid history transaction')
        require_integer(transaction.revision, 'history revision')
        if transaction.revision != expected:
            raise InvalidPayload('history revisions must each appear once from 1 up')
        expected += 1
        if type(transaction.observations) is not tuple or type(transaction.dispositions) is not tuple:
            raise InvalidPayload('invalid history transaction contents')
        if not transaction.observations and not transaction.dispositions:
            raise InvalidPayload('history transaction carries no record')
        if transaction.observations and transaction.dispositions:
            raise InvalidPayload('history transaction mixes admission and treatment')
        if len(transaction.dispositions) > 1:
            raise InvalidPayload('history transaction adds more than one disposition')
        batches = set()
        for record in transaction.observations:
            _check_frozen_observation(record)
            if record.observation_id in observation_revision:
                raise InvalidPayload('history admits an observation twice')
            if (record.slot, record.version) in slot_versions:
                raise InvalidPayload('history reuses a slot version')
            slot_versions.add((record.slot, record.version))
            observation_revision[record.observation_id] = transaction.revision
            batches.add(record.batch)
        if len(batches) > 1:
            raise InvalidPayload('history admission spans several batches')
        for batch in batches:
            batch_first.setdefault(batch, transaction.revision)
        for record in transaction.dispositions:
            _check_frozen_disposition(record)
            if record.observation_id not in observation_revision:
                raise InvalidPayload('history treatment targets an invisible observation')
            if observation_revision[record.observation_id] >= transaction.revision:
                raise InvalidPayload('history treatment is not preceded by its target')
            key = (record.observation_id, record.sequence)
            if key in disposition_sequences:
                raise InvalidPayload('history reuses a disposition sequence')
            disposition_sequences.add(key)
            batch_first.setdefault(record.batch, transaction.revision)
        observations.extend(transaction.observations)
        dispositions.extend(transaction.dispositions)
    if expected - 1 != revision:
        raise InvalidPayload('history does not cover exactly the sealed revision')
    if sorted(map(_observation_key, observations)) != sorted(
        map(_observation_key, fixed.evidence.observations)
    ):
        raise InvalidPayload('history observations disagree with the fixed evidence')
    if sorted(map(_disposition_key, dispositions)) != sorted(
        map(_disposition_key, fixed.evidence.dispositions)
    ):
        raise InvalidPayload('history dispositions disagree with the fixed evidence')
    if set(batch_first) != set(fixed.evidence.batches):
        raise InvalidPayload('history batches disagree with the fixed evidence')
    if final_rows(history, revision) != fixed.original:
        raise InvalidPayload('history final state disagrees with the original ledger')
