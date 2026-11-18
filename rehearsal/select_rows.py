from typing import Iterable, Iterator

from archive.payloads import FrozenObservation, LedgerRow
from intake.observations import latest_by_slot


def select_rows(eligible: Iterable[FrozenObservation]) -> Iterator[LedgerRow]:
    for record in latest_by_slot(eligible).values():
        yield LedgerRow(record.slot, record.observation_id, record.batch, record.reading)
