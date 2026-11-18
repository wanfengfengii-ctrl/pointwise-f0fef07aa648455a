from dataclasses import dataclass
from typing import Callable

from archive.payloads import FrozenDisposition, FrozenObservation, HistoryTransaction
from archive.storage import ArchiveStore
from intake.observations import Observation
from intake.revisions import read_batches_at, read_observations_at, require_revision
from intake.source_store import SourceStore
from quality.history import Disposition
from quality.store import read_dispositions_at
from seal.commit import commit_day
from seal.materialize import materialize_day


@dataclass(frozen=True)
class SourceDayCut:
    day: str
    revision: int
    batches: tuple[str, ...]
    observations: tuple[Observation, ...]
    dispositions: tuple[Disposition, ...]
    history: tuple[HistoryTransaction, ...] | None = None


def load_cut(store: SourceStore, day: str, revision: int) -> SourceDayCut:
    with store.snapshot() as connection:
        require_revision(connection, day, revision)
        return SourceDayCut(
            day,
            revision,
            read_batches_at(connection, day, revision),
            read_observations_at(connection, day, revision),
            read_dispositions_at(connection, day, revision),
        )


def build_source_history(
    observations: tuple[Observation, ...], dispositions: tuple[Disposition, ...]
) -> tuple[HistoryTransaction, ...]:
    grouped: dict[int, tuple[list[FrozenObservation], list[FrozenDisposition]]] = {}
    for record in observations:
        frozen = FrozenObservation(record.slot, record.observation_id, record.batch,
                                   record.version, record.reading)
        grouped.setdefault(record.revision, ([], []))[0].append(frozen)
    for record in dispositions:
        frozen = FrozenDisposition(record.observation_id, record.batch, record.sequence, record.action)
        grouped.setdefault(record.revision, ([], []))[1].append(frozen)
    return tuple(
        HistoryTransaction(number, tuple(grouped[number][0]), tuple(grouped[number][1]))
        for number in sorted(grouped)
    )


def load_cut_with_history(store: SourceStore, day: str, revision: int) -> SourceDayCut:
    with store.snapshot() as connection:
        require_revision(connection, day, revision)
        observations = read_observations_at(connection, day, revision)
        dispositions = read_dispositions_at(connection, day, revision)
        return SourceDayCut(
            day,
            revision,
            read_batches_at(connection, day, revision),
            observations,
            dispositions,
            build_source_history(observations, dispositions),
        )


def close_day(
    source: SourceStore,
    archive: ArchiveStore,
    day: str,
    revision: int,
    *,
    before_commit: Callable[[str], None] | None = None,
) -> str:
    cut = load_cut(source, day, revision)
    materialization = materialize_day(cut)
    return commit_day(archive, materialization, before_commit=before_commit)


def close_day_with_history(
    source: SourceStore,
    archive: ArchiveStore,
    day: str,
    revision: int,
    *,
    before_commit: Callable[[str], None] | None = None,
) -> str:
    cut = load_cut_with_history(source, day, revision)
    materialization = materialize_day(cut)
    return commit_day(archive, materialization, before_commit=before_commit)
