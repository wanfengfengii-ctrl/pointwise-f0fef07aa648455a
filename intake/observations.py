import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Protocol, TypeVar


class AdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class ObservationInput:
    slot: str
    observation_id: str
    version: int
    reading: int


@dataclass(frozen=True)
class Observation:
    day: str
    slot: str
    observation_id: str
    batch: str
    version: int
    reading: int
    revision: int


def require_identifier(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip() or '\x00' in value:
        raise ValueError(f'{field} must be a nonempty identifier without surrounding whitespace or NUL')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be valid UTF-8') from exc
    return value


def require_integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f'{field} must be an integer')
    return value


def integer_text(value: int) -> str:
    return str(Decimal(value))


def read_integer_text(value: object) -> int:
    if type(value) is not str or re.fullmatch(r'0|-?[1-9][0-9]*', value) is None:
        raise ValueError('expected a canonical decimal integer string')
    return int(Decimal(value))


def normalize_observation(record: ObservationInput) -> ObservationInput:
    if not isinstance(record, ObservationInput):
        raise AdmissionError('each record must be an ObservationInput')
    try:
        return ObservationInput(
            require_identifier(record.slot, 'slot'),
            require_identifier(record.observation_id, 'observation_id'),
            require_integer(record.version, 'version'),
            require_integer(record.reading, 'reading'),
        )
    except ValueError as exc:
        raise AdmissionError(str(exc)) from exc


class _Versioned(Protocol):
    @property
    def slot(self) -> str: ...

    @property
    def version(self) -> int: ...


_Record = TypeVar('_Record', bound=_Versioned)


def latest_by_slot(records: Iterable[_Record]) -> dict[str, _Record]:
    winners: dict[str, _Record] = {}
    for record in records:
        winner = winners.get(record.slot)
        if winner is None or record.version > winner.version:
            winners[record.slot] = record
    return winners
