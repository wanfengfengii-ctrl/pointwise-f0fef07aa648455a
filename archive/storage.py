import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from archive.payloads import InvalidPayload


_ARCHIVE_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS fixed_payloads (
           payload_id INTEGER PRIMARY KEY,
           content BLOB NOT NULL
       )''',
    '''CREATE TABLE IF NOT EXISTS fixed_catalog (
           account TEXT NOT NULL PRIMARY KEY,
           day TEXT NOT NULL,
           revision TEXT NOT NULL,
           payload_id INTEGER NOT NULL UNIQUE REFERENCES fixed_payloads (payload_id)
       )''',
)


class ArchiveStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        with self.transaction() as connection:
            for statement in _ARCHIVE_SCHEMA:
                connection.execute(statement)

    @contextmanager
    def _session(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        target = self.path if write else self.path.absolute().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(target, uri=not write, isolation_level=None)) as connection:
            connection.execute('PRAGMA foreign_keys = ON')
            with connection:
                connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield connection

    def transaction(self):
        return self._session(write=True)

    def snapshot(self):
        return self._session(write=False)

    def write_payload(self, connection: sqlite3.Connection, content: bytes) -> int:
        result = connection.execute('INSERT INTO fixed_payloads (content) VALUES (?)', (content,))
        return result.lastrowid

    def read_payload(self, connection: sqlite3.Connection, payload_id: int) -> bytes:
        row = connection.execute(
            'SELECT content FROM fixed_payloads WHERE payload_id = ?', (payload_id,)
        ).fetchone()
        if row is None or type(row[0]) is not bytes:
            raise InvalidPayload('catalog refers to an invalid payload')
        return row[0]
