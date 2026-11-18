from dataclasses import dataclass
from typing import Iterable, Protocol, TypeVar


class DispositionError(ValueError):
    pass


@dataclass(frozen=True)
class Disposition:
    day: str
    observation_id: str
    batch: str
    sequence: int
    action: str
    revision: int


def require_unused_disposition_sequence(sequence: int, history: Iterable[Disposition]) -> None:
    if any(record.sequence == sequence for record in history):
        raise DispositionError('disposition sequence already used for this observation')


class _Sequenced(Protocol):
    @property
    def observation_id(self) -> str: ...

    @property
    def sequence(self) -> int: ...


_Record = TypeVar('_Record', bound=_Sequenced)


def latest_dispositions(dispositions: Iterable[_Record]) -> dict[str, _Record]:
    latest: dict[str, _Record] = {}
    for record in dispositions:
        previous = latest.get(record.observation_id)
        if previous is None or previous.sequence < record.sequence:
            latest[record.observation_id] = record
    return latest
