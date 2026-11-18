from typing import Iterable, Mapping

from archive.payloads import Ledger, LedgerRow, make_ledger
from intake.observations import Observation, latest_by_slot
from quality.history import Disposition


def build_original_ledger(
    observations: Iterable[Observation], latest: Mapping[str, Disposition]
) -> Ledger:
    disabled = {target for target, record in latest.items() if record.action == 'disable'}
    eligible = (record for record in observations if record.observation_id not in disabled)
    winners = latest_by_slot(eligible)
    return make_ledger(
        LedgerRow(record.slot, record.observation_id, record.batch, record.reading)
        for record in winners.values()
    )
