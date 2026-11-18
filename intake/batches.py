from dataclasses import dataclass
from typing import Iterable

from intake.observations import (
    AdmissionError,
    ObservationInput,
    normalize_observation,
    require_identifier,
)
from intake.revisions import allocate_revision, register_batch, write_observations
from intake.sequence import validate_observation_identity, validate_slot_versions
from intake.source_store import SourceStore


@dataclass(frozen=True)
class AdmissionReceipt:
    revision: int
    observation_ids: tuple[str, ...]


def admit(
    store: SourceStore, day: str, batch: str, records: Iterable[ObservationInput]
) -> AdmissionReceipt:
    try:
        day = require_identifier(day, 'day')
        batch = require_identifier(batch, 'batch')
        iterator = iter(records)
    except (ValueError, TypeError) as exc:
        raise AdmissionError(str(exc)) from exc
    observations = tuple(normalize_observation(record) for record in iterator)
    if not observations:
        raise AdmissionError('an instrument batch must contain observations')

    with store.mutation() as connection:
        validate_observation_identity(connection, observations)
        validate_slot_versions(connection, day, observations)
        revision = allocate_revision(connection, day)
        register_batch(connection, day, batch, revision)
        write_observations(connection, day, batch, revision, observations)
    return AdmissionReceipt(revision, tuple(record.observation_id for record in observations))
