from typing import Iterable

from archive.payloads import DayEvidence, FrozenDisposition, FrozenObservation
from intake.observations import require_identifier


class InvalidQuarantine(ValueError):
    pass


class UnknownBatch(InvalidQuarantine):
    def __init__(self, batches: Iterable[str]):
        self.batches = tuple(sorted(batches))
        super().__init__('batches outside the fixed revision: ' + ', '.join(self.batches))


def resolve_quarantine(evidence: DayEvidence, bad_batches: Iterable[str]) -> frozenset[str]:
    if isinstance(bad_batches, (str, bytes)):
        raise InvalidQuarantine('provide an iterable of batch identifiers')
    try:
        quarantine = frozenset(require_identifier(batch, 'batch') for batch in bad_batches)
    except (TypeError, ValueError) as exc:
        raise InvalidQuarantine(str(exc)) from exc
    unknown = quarantine.difference(evidence.batches)
    if unknown:
        raise UnknownBatch(unknown)
    return quarantine


def retain_unquarantined(
    evidence: DayEvidence, quarantine: frozenset[str]
) -> tuple[tuple[FrozenObservation, ...], tuple[FrozenDisposition, ...]]:
    observations = tuple(record for record in evidence.observations if record.batch not in quarantine)
    dispositions = tuple(record for record in evidence.dispositions if record.batch not in quarantine)
    return observations, dispositions
