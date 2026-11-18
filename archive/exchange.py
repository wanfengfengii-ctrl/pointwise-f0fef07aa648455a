from archive.catalog import CatalogEntry, find_entry, insert_entry
from archive.lookup import load_fixed_day
from archive.storage import ArchiveStore
from archive.transfer_codec import decode_fixed_day, encode_fixed_day


class ExchangeConflict(ValueError):
    pass


def export_fixed_day(store: ArchiveStore, account: str) -> bytes:
    return encode_fixed_day(load_fixed_day(store, account))


def accept_fixed_day(store: ArchiveStore, data: bytes) -> str:
    fixed = decode_fixed_day(data)
    canonical = encode_fixed_day(fixed)
    with store.transaction() as connection:
        previous = find_entry(connection, fixed.account)
        if previous is None:
            payload_id = store.write_payload(connection, canonical)
            insert_entry(connection, CatalogEntry(fixed.account, fixed.day, fixed.revision, payload_id))
        else:
            existing = store.read_payload(connection, previous.payload_id)
            if (previous.day, previous.revision) != (fixed.day, fixed.revision) or existing != canonical:
                raise ExchangeConflict(f'conflicting contents for {fixed.account}')
    return fixed.account


def exchange_day(published: ArchiveStore, isolated: ArchiveStore, account: str) -> str:
    return accept_fixed_day(isolated, export_fixed_day(published, account))
