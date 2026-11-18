import sqlite3
from dataclasses import dataclass

from archive.payloads import valid_account
from intake.observations import integer_text, read_integer_text


class UnknownDay(LookupError):
    pass


@dataclass(frozen=True)
class CatalogEntry:
    account: str
    day: str
    revision: int
    payload_id: int


def insert_entry(connection: sqlite3.Connection, entry: CatalogEntry) -> None:
    connection.execute(
        'INSERT INTO fixed_catalog (account, day, revision, payload_id) VALUES (?, ?, ?, ?)',
        (entry.account, entry.day, integer_text(entry.revision), entry.payload_id),
    )


def find_entry(connection: sqlite3.Connection, account: str) -> CatalogEntry | None:
    if not valid_account(account):
        return None
    row = connection.execute(
        'SELECT account, day, revision, payload_id FROM fixed_catalog WHERE account = ?',
        (account,),
    ).fetchone()
    if row is None:
        return None
    return CatalogEntry(row[0], row[1], read_integer_text(row[2]), row[3])


def require_entry(connection: sqlite3.Connection, account: str) -> CatalogEntry:
    entry = find_entry(connection, account)
    if entry is None:
        raise UnknownDay(f'no fixed day for {account!r}')
    return entry
