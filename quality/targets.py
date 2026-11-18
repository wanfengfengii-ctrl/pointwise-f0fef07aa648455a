import sqlite3

from intake.observations import Observation
from intake.revisions import find_observation
from quality.history import DispositionError


def require_same_day_observation(
    connection: sqlite3.Connection, day: str, observation_id: str
) -> Observation:
    target = find_observation(connection, day, observation_id)
    if target is None:
        raise DispositionError(f'unknown observation for {day}: {observation_id}')
    return target
