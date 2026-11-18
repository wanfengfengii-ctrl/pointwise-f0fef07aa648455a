import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator


_SOURCE_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS source_revisions (
           day TEXT NOT NULL,
           revision INTEGER NOT NULL CHECK (revision > 0),
           PRIMARY KEY (day, revision)
       )''',
    '''CREATE TABLE IF NOT EXISTS source_batches (
           day TEXT NOT NULL,
           batch TEXT NOT NULL,
           first_revision INTEGER NOT NULL,
           PRIMARY KEY (day, batch),
           FOREIGN KEY (day, first_revision) REFERENCES source_revisions (day, revision)
       )''',
    '''CREATE TABLE IF NOT EXISTS source_observations (
           day TEXT NOT NULL,
           slot TEXT NOT NULL,
           observation_id TEXT NOT NULL PRIMARY KEY,
           batch TEXT NOT NULL,
           version TEXT NOT NULL,
           reading TEXT NOT NULL,
           revision INTEGER NOT NULL,
           UNIQUE (day, observation_id),
           UNIQUE (day, slot, version),
           FOREIGN KEY (day, revision) REFERENCES source_revisions (day, revision),
           FOREIGN KEY (day, batch) REFERENCES source_batches (day, batch)
       )''',
    '''CREATE INDEX IF NOT EXISTS observations_by_revision
       ON source_observations (day, revision, observation_id)''',
)


class SourceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        from quality.store import initialize_dispositions

        with self.mutation() as connection:
            for statement in _SOURCE_SCHEMA:
                connection.execute(statement)
            initialize_dispositions(connection)

    @contextmanager
    def _session(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        target = self.path if write else self.path.absolute().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(target, uri=not write, isolation_level=None)) as connection:
            connection.execute('PRAGMA foreign_keys = ON')
            with connection:
                connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield connection

    def mutation(self):
        return self._session(write=True)

    def snapshot(self):
        return self._session(write=False)
