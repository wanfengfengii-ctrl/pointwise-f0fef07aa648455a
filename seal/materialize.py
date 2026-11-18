from dataclasses import dataclass
from typing import TYPE_CHECKING

from archive.payloads import DayEvidence, Ledger
from quality.history import latest_dispositions
from seal.evidence import build_evidence
from seal.original_ledger import build_original_ledger

if TYPE_CHECKING:
    from seal.cut import SourceDayCut


@dataclass(frozen=True)
class DayMaterialization:
    day: str
    revision: int
    original: Ledger
    evidence: DayEvidence


def materialize_day(cut: 'SourceDayCut') -> DayMaterialization:
    latest = latest_dispositions(cut.dispositions)
    original = build_original_ledger(cut.observations, latest)
    evidence = build_evidence(cut.observations, cut.dispositions, cut.batches)
    return DayMaterialization(cut.day, cut.revision, original, evidence)
