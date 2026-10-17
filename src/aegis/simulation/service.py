"""Local orchestration boundary, with explicit failure states and no web service."""
from .adapter import AdapterUnavailable, Availability, RuntimeObservation, SimulatorAdapter
from .contracts import ALLOWED, Diagnostic, Scenario, Session, Timestamp, require
from .session import transition, validate_session_scenario


def request_transition(scenario: Scenario, session: Session, adapter: SimulatorAdapter,
                       target: str, wall_time: Timestamp) -> Session:
    validate_session_scenario(scenario, session)
    require(len(session.history) < 128, 'BOUND', 'history', 'Lifecycle history is full')
    require(target in ALLOWED[session.state] and target != 'failed', 'INVALID_TRANSITION', 'state', 'Unsupported requested transition')
    session.check_times(session.simulation_time, wall_time)
    operation = {'ready': 'prepare', 'paused': 'pause', 'completed': 'complete',
                 'running': 'resume' if session.state == 'paused' else 'start'}[target]
    try:
        available = adapter.probe(scenario)
        require(type(available) is Availability, 'UNVERIFIED', 'adapter', 'Require validated availability contract')
        if available.state != 'available' or operation not in available.capabilities:
            raise AdapterUnavailable('Required verified adapter capability is unavailable')
        observation = adapter.observe_transition(scenario, session, target)
        require(type(observation) is RuntimeObservation, 'UNVERIFIED', 'adapter', 'Require validated runtime observation')
        require(observation.session_id == session.session_id and observation.scenario_sha256 == session.scenario_sha256
                and observation.state == target and observation.simulator_version == scenario.versions.simulator_version
                and observation.autopilot_version == scenario.versions.autopilot_version,
                'UNVERIFIED', 'adapter', 'Runtime observation does not match the requested session, state or versions')
        return transition(session, target, observation.simulation_time, wall_time, verification=observation.verification)
    except Exception as error:
        # An adapter must never make failures look like a ready/running simulator.
        # Future concrete runtimes must clean up their resources before reporting failure.
        code = 'ADAPTER_UNAVAILABLE' if isinstance(error, AdapterUnavailable) else 'ADAPTER_FAILED'
        diagnostic = Diagnostic(code=code, path='adapter', severity='error',
                                explanation='Verified simulator transition unavailable; no new runtime state or measurements accepted.')
        return transition(session, 'failed', session.simulation_time, wall_time, diagnostic=diagnostic)
