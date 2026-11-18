from typing import Iterable

from archive.payloads import DayEvidence, FrozenDisposition, FrozenObservation
from intake.observations import Observation
from quality.history import Disposition


def build_evidence(
    observations: Iterable[Observation], dispositions: Iterable[Disposition], batches: Iterable[str]
) -> DayEvidence:
    candidates = tuple(
        FrozenObservation(record.slot, record.observation_id, record.batch,
                          record.version, record.reading)
        for record in observations
    )
    treatment_history = tuple(
        FrozenDisposition(record.observation_id, record.batch, record.sequence, record.action)
        for record in dispositions
    )
    return DayEvidence(tuple(batches), candidates, treatment_history)
