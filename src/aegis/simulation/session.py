"""Pure lifecycle transitions. Callers supply both clocks and runtime observations."""
from dataclasses import replace
from .contracts import ALLOWED, Clock, Diagnostic, Scenario, Session, Timestamp, Transition, require
from .scenarios import scenario_digest


def create_session(scenario: Scenario, session_id: str, wall_time: Timestamp) -> Session:
    simulation_clock = Clock(domain=f'sim:{session_id}', kind='simulation', unit='ns', epoch='session_start')
    wall_clock = Clock(domain='wall:unix', kind='wall', unit='ns', epoch='unix')
    simulation_time = Timestamp(value_ns='0', domain=simulation_clock.domain)
    initial = Transition(sequence=0, previous=None, state='created', simulation_time=simulation_time,
                         wall_time=wall_time, verification=None, diagnostic=None)
    return Session(session_id=session_id, scenario_id=scenario.scenario_id, scenario_sha256=scenario_digest(scenario),
                   data_origin='simulated', state='created', simulation_clock=simulation_clock, wall_clock=wall_clock,
                   simulation_time=simulation_time, wall_time=wall_time, duration_ns=scenario.duration_ns,
                   step_ns=scenario.step_ns, time_verification=None, history=(initial,))


def validate_session_scenario(scenario: Scenario, session: Session) -> Session:
    require(scenario.scenario_id == session.scenario_id and scenario_digest(scenario) == session.scenario_sha256
            and scenario.duration_ns == session.duration_ns and scenario.step_ns == session.step_ns,
            'PROVENANCE', 'scenario', 'Session identity or timing parameters differ from the hashed scenario')
    return session


def transition(session: Session, target: str, simulation_time: Timestamp, wall_time: Timestamp,
               *, verification: str | None = None, diagnostic: Diagnostic | None = None) -> Session:
    require(len(session.history) < 128, 'BOUND', 'history', 'Lifecycle history is full')
    require(target in ALLOWED[session.state], 'INVALID_TRANSITION', 'state', 'Illegal or terminal lifecycle transition')
    session.check_times(simulation_time, wall_time)
    require(int(simulation_time.value_ns) >= int(session.simulation_time.value_ns), 'CLOCK_DOMAIN', 'simulation_time', 'Simulation time cannot regress')
    if session.state != 'running':
        require(simulation_time == session.simulation_time, 'CLOCK_DOMAIN', 'simulation_time', 'Only a running session may advance simulation time')
    event = Transition(sequence=len(session.history), previous=session.state, state=target,
                       simulation_time=simulation_time, wall_time=wall_time, verification=verification, diagnostic=diagnostic)
    return replace(session, state=target, simulation_time=simulation_time, wall_time=wall_time,
                   history=session.history + (event,), time_verification=verification)


def advance(session: Session, simulation_time: Timestamp, wall_time: Timestamp, *, verification: str) -> Session:
    require(session.state == 'running', 'INVALID_TRANSITION', 'state', 'Only running sessions accept simulator time observations')
    require(type(verification) is str and bool(verification.strip()) and len(verification) <= 1024, 'UNVERIFIED', 'verification', 'Require explicit runtime observation reference')
    session.check_times(simulation_time, wall_time)
    require(int(simulation_time.value_ns) >= int(session.simulation_time.value_ns), 'CLOCK_DOMAIN', 'simulation_time', 'Simulation time cannot regress')
    # No wall-clock delta drives simulation time. Both values are supplied, never inferred.
    return replace(session, simulation_time=simulation_time, wall_time=wall_time, time_verification=verification)
