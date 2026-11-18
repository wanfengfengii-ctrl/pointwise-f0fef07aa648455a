import sqlite3

from intake.observations import AdmissionError, ObservationInput, integer_text


def validate_observation_identity(
    connection: sqlite3.Connection, records: tuple[ObservationInput, ...]
) -> None:
    seen: set[str] = set()
    for record in records:
        key = record.observation_id
        if key in seen:
            raise AdmissionError(f'duplicate observation in batch: {key}')
        seen.add(key)
        existing = connection.execute(
            'SELECT 1 FROM source_observations WHERE observation_id = ?', (key,)
        ).fetchone()
        if existing is not None:
            raise AdmissionError(f'observation already admitted: {key}')


def validate_slot_versions(
    connection: sqlite3.Connection, day: str, records: tuple[ObservationInput, ...]
) -> None:
    seen: set[tuple[str, int]] = set()
    for record in records:
        key = (record.slot, record.version)
        if key in seen:
            raise AdmissionError(f'duplicate slot version in batch: {record.slot}')
        seen.add(key)
        existing = connection.execute(
            'SELECT 1 FROM source_observations WHERE day = ? AND slot = ? AND version = ?',
            (day, record.slot, integer_text(record.version)),
        ).fetchone()
        if existing is not None:
            raise AdmissionError(f'slot version already admitted: {record.slot}')
