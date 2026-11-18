from typing import Iterable

from archive.lookup import load_fixed_day
from archive.payloads import FixedDay, Ledger, make_ledger
from archive.storage import ArchiveStore
from rehearsal.batch_scope import resolve_quarantine, retain_unquarantined
from rehearsal.eligibility import resolve_eligible_observations
from rehearsal.select_rows import select_rows


def build_rehearsal_report(fixed: FixedDay, bad_batches: Iterable[str] = ()) -> Ledger:
    quarantine = resolve_quarantine(fixed.evidence, bad_batches)
    observations, dispositions = retain_unquarantined(fixed.evidence, quarantine)
    eligible = resolve_eligible_observations(observations, dispositions)
    return make_ledger(select_rows(eligible))


def simulate(store: ArchiveStore, account: str, bad_batches: Iterable[str] = ()) -> Ledger:
    fixed = load_fixed_day(store, account)
    return build_rehearsal_report(fixed, bad_batches)
