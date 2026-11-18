from dataclasses import dataclass
from typing import Callable

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
