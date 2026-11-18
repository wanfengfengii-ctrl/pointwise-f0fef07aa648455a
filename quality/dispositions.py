from intake.observations import require_identifier, require_integer
from intake.revisions import allocate_revision, register_batch
from intake.source_store import SourceStore
from quality.history import Disposition, DispositionError, require_unused_disposition_sequence
from quality.store import append_disposition, read_target_history
from quality.targets import require_same_day_observation


def add_disposition(
    store: SourceStore, day: str, batch: str, observation_id: str, sequence: int, action: str
) -> int:
    try:
        day = require_identifier(day, 'day')
        batch = require_identifier(batch, 'batch')
        observation_id = require_identifier(observation_id, 'observation_id')
        sequence = require_integer(sequence, 'sequence')
        if type(action) is not str or action not in ('disable', 'enable'):
            raise ValueError('action must be disable or enable')
    except ValueError as exc:
        raise DispositionError(str(exc)) from exc

    with store.mutation() as connection:
        target = require_same_day_observation(connection, day, observation_id)
        history = read_target_history(connection, day, target.observation_id)
        require_unused_disposition_sequence(sequence, history)
        revision = allocate_revision(connection, day)
        register_batch(connection, day, batch, revision)
        append_disposition(
            connection, Disposition(day, target.observation_id, batch, sequence, action, revision)
        )
    return revision
