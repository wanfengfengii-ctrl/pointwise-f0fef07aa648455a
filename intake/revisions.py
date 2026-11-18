import sqlite3
from typing import Iterable

from intake.observations import (
    Observation,
    ObservationInput,
    integer_text,
    read_integer_text,
    require_identifier,
)


class UnknownRevision(LookupError):
    pass


def require_revision(connection: sqlite3.Connection, day: str, revision: int) -> int:
    try:
        require_identifier(day, 'day')
    except ValueError as exc:
        raise UnknownRevision('invalid source day') from exc
    if type(revision) is not int or not 1 <= revision <= 2**63 - 1:
        raise UnknownRevision('invalid source revision')
    found = connection.execute(
        'SELECT 1 FROM source_revisions WHERE day = ? AND revision = ?', (day, revision)
    ).fetchone()
    if found is None:
        raise UnknownRevision(f'{day}: no source revision {revision}')
    return revision


def allocate_revision(connection: sqlite3.Connection, day: str) -> int:
    latest, = connection.execute(
        'SELECT COALESCE(MAX(revision), 0) FROM source_revisions WHERE day = ?', (day,)
    ).fetchone()
    revision = latest + 1
    connection.execute('INSERT INTO source_revisions VALUES (?, ?)', (day, revision))
    return revision


def register_batch(connection: sqlite3.Connection, day: str, batch: str, revision: int) -> None:
    connection.execute(
        '''INSERT INTO source_batches (day, batch, first_revision) VALUES (?, ?, ?)
           ON CONFLICT(day, batch) DO NOTHING''',
        (day, batch, revision),
    )


def write_observations(
    connection: sqlite3.Connection,
    day: str,
    batch: str,
    revision: int,
    records: Iterable[ObservationInput],
) -> None:
    connection.executemany(
        '''INSERT INTO source_observations
           (day, slot, observation_id, batch, version, reading, revision)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            (day, record.slot, record.observation_id, batch, integer_text(record.version),
             integer_text(record.reading), revision)
            for record in records
        ),
    )


def _observation(row: tuple) -> Observation:
    day, slot, observation_id, batch, version, reading, revision = row
    return Observation(day, slot, observation_id, batch, read_integer_text(version),
                       read_integer_text(reading), revision)


def find_observation(
    connection: sqlite3.Connection, day: str, observation_id: str
) -> Observation | None:
    row = connection.execute(
        '''SELECT day, slot, observation_id, batch, version, reading, revision
           FROM source_observations WHERE day = ? AND observation_id = ?''',
        (day, observation_id),
    ).fetchone()
    return _observation(row) if row is not None else None


def read_observations_at(
    connection: sqlite3.Connection, day: str, revision: int
) -> tuple[Observation, ...]:
    rows = connection.execute(
        '''SELECT day, slot, observation_id, batch, version, reading, revision
           FROM source_observations WHERE day = ? AND revision <= ?
           ORDER BY revision, observation_id''',
        (day, revision),
    )
    return tuple(_observation(row) for row in rows)


def read_batches_at(connection: sqlite3.Connection, day: str, revision: int) -> tuple[str, ...]:
    rows = connection.execute(
        '''SELECT batch FROM source_batches WHERE day = ? AND first_revision <= ?
           ORDER BY batch''',
        (day, revision),
    )
    return tuple(batch for (batch,) in rows)
