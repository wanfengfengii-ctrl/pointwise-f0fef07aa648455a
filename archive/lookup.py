from archive.catalog import require_entry
from archive.payloads import FixedDay, InvalidPayload, Ledger
from archive.storage import ArchiveStore
from archive.transfer_codec import decode_fixed_day


def load_fixed_day(store: ArchiveStore, account: str) -> FixedDay:
    with store.snapshot() as connection:
        entry = require_entry(connection, account)
        data = store.read_payload(connection, entry.payload_id)
    fixed = decode_fixed_day(data)
    if (fixed.account, fixed.day, fixed.revision) != (entry.account, entry.day, entry.revision):
        raise InvalidPayload('fixed contents disagree with catalog binding')
    return fixed


def read_day(store: ArchiveStore, account: str) -> Ledger:
    return load_fixed_day(store, account).original
