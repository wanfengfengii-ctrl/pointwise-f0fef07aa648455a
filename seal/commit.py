import sqlite3
import uuid
from typing import Callable

from archive.catalog import CatalogEntry, insert_entry
from archive.payloads import FixedDay
from archive.storage import ArchiveStore
from archive.transfer_codec import encode_fixed_day
from seal.materialize import DayMaterialization


class PublicationError(RuntimeError):
    pass


def commit_day(
    store: ArchiveStore,
    materialization: DayMaterialization,
    *,
    before_commit: Callable[[str], None] | None = None,
) -> str:
    account = 'D-' + uuid.uuid4().hex
    fixed = FixedDay(account, materialization.day, materialization.revision,
                     materialization.original, materialization.evidence, materialization.history)
    contents = encode_fixed_day(fixed)
    try:
        with store.transaction() as connection:
            payload_id = store.write_payload(connection, contents)
            insert_entry(connection, CatalogEntry(account, fixed.day, fixed.revision, payload_id))
            if before_commit is not None:
                try:
                    before_commit(account)
                except Exception as exc:
                    raise PublicationError('publication interrupted before commit') from exc
    except sqlite3.Error as exc:
        raise PublicationError('fixed day publication failed') from exc
    return account
