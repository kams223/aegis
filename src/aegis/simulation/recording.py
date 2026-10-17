"""Bounded simulation-origin recordings; no acquisition, synthesis, or clock alignment."""
from .contracts import Recording, Scenario, Session, SimulationError, load_contract, require
from .scenarios import scenario_digest
from .session import validate_session_scenario


def validate_recording(recording: Recording, scenario: Scenario, session: Session) -> Recording:
    validate_session_scenario(scenario, session)
    digest = scenario_digest(scenario)
    require(recording.session_id == session.session_id and recording.scenario_id == scenario.scenario_id == session.scenario_id
            and recording.scenario_sha256 == session.scenario_sha256 == digest,
            'PROVENANCE', 'recording', 'Scenario, session and recording identities differ')
    vehicles = {v.vehicle_id for v in scenario.vehicles}
    for index, record in enumerate(recording.records):
        path = f'records[{index}]'
        require(record.source.vehicle_id in vehicles, 'REFERENCE', path, 'Unknown virtual vehicle')
        session.check_times(record.simulation_time, record.receipt_time)
        require(int(record.simulation_time.value_ns) <= int(session.simulation_time.value_ns), 'BOUND', path, 'Record is ahead of the observed session time')
        # Absent measured versions remain null, never replaced by scenario targets.
        for value, expected in ((record.provenance.simulator_version, scenario.versions.simulator_version),
                                (record.provenance.autopilot_version, scenario.versions.autopilot_version)):
            require(value is None or value == expected, 'PROVENANCE', path, 'Supplied runtime version differs from scenario declaration')
    return recording


def load_recording(data: bytes, scenario: Scenario, session: Session) -> Recording:
    return validate_recording(load_contract(Recording, data), scenario, session)


def recording_diagnostics(data: bytes, scenario: Scenario, session: Session):
    """Fail closed, with a structured first error; no partially accepted recording."""
    try:
        load_recording(data, scenario, session)
        return ()
    except SimulationError as error:
        return (error.diagnostic,)
