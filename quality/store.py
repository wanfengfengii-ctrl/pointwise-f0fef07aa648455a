import sqlite3

from intake.observations import integer_text, read_integer_text
from quality.history import Disposition


def initialize_dispositions(connection: sqlite3.Connection) -> None:
    connection.execute(
        '''CREATE TABLE IF NOT EXISTS source_dispositions (
               day TEXT NOT NULL,
               observation_id TEXT NOT NULL,
               batch TEXT NOT NULL,
               sequence TEXT NOT NULL,
               action TEXT NOT NULL CHECK (action IN ('disable', 'enable')),
               revision INTEGER NOT NULL,
               PRIMARY KEY (day, observation_id, sequence),
               FOREIGN KEY (day, observation_id)
                   REFERENCES source_observations (day, observation_id),
               FOREIGN KEY (day, batch) REFERENCES source_batches (day, batch),
               FOREIGN KEY (day, revision) REFERENCES source_revisions (day, revision)
           )'''
    )
    connection.execute(
        '''CREATE INDEX IF NOT EXISTS dispositions_by_revision
           ON source_dispositions (day, revision, observation_id)'''
    )


def append_disposition(connection: sqlite3.Connection, record: Disposition) -> None:
    connection.execute(
        '''INSERT INTO source_dispositions (day, observation_id, batch, sequence, action, revision)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (record.day, record.observation_id, record.batch, integer_text(record.sequence),
         record.action, record.revision),
    )


def _disposition(row: tuple) -> Disposition:
    day, target, batch, sequence, action, revision = row
    return Disposition(day, target, batch, read_integer_text(sequence), action, revision)


def read_target_history(
    connection: sqlite3.Connection, day: str, observation_id: str
) -> tuple[Disposition, ...]:
    rows = connection.execute(
        '''SELECT day, observation_id, batch, sequence, action, revision
           FROM source_dispositions WHERE day = ? AND observation_id = ? ORDER BY revision''',
        (day, observation_id),
    )
    return tuple(_disposition(row) for row in rows)


def read_dispositions_at(
    connection: sqlite3.Connection, day: str, revision: int
) -> tuple[Disposition, ...]:
    rows = connection.execute(
        '''SELECT day, observation_id, batch, sequence, action, revision
           FROM source_dispositions WHERE day = ? AND revision <= ?
           ORDER BY revision, observation_id''',
        (day, revision),
    )
    return tuple(_disposition(row) for row in rows)
