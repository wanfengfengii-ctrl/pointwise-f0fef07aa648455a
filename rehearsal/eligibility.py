from typing import Iterable, Iterator

from archive.payloads import FrozenDisposition, FrozenObservation
from quality.history import latest_dispositions


def resolve_eligible_observations(
    observations: Iterable[FrozenObservation], dispositions: Iterable[FrozenDisposition]
) -> Iterator[FrozenObservation]:
    latest = latest_dispositions(dispositions)
    for record in observations:
        treatment = latest.get(record.observation_id)
        if treatment is None or treatment.action == 'enable':
            yield record
