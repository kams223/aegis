"""Simulator-only boundary. Discovery never executes binaries or opens a connection."""
from dataclasses import dataclass
import shutil
from typing import Literal, Protocol
from .contracts import Contract, Diagnostic, Recording, Scenario, Session, Timestamp, require


@dataclass(frozen=True, slots=True, kw_only=True)
class Dependency(Contract):
    name: Literal['gazebo', 'px4', 'ros2', 'docker']
    executable: str | None
    status: Literal['not_found', 'located_unverified', 'probe_failed']
    version: str | None

    def validate(self):
        require((self.executable is not None) == (self.status == 'located_unverified') and self.version is None,
                'UNVERIFIED', 'dependency', 'Executable discovery cannot attest installation version or runtime')


@dataclass(frozen=True, slots=True, kw_only=True)
class Availability(Contract):
    state: Literal['available', 'unavailable']
    capabilities: tuple[Literal['prepare', 'start', 'pause', 'resume', 'complete', 'read_recording'], ...]
    dependencies: tuple[Dependency, ...]
    verification: str | None
    diagnostics: tuple[Diagnostic, ...]

    def validate(self):
        if self.state == 'available':
            require(self.verification is not None and not self.diagnostics, 'UNVERIFIED', 'availability', 'Available requires adapter verification without failure diagnostics')
        else:
            require(bool(self.diagnostics) and not self.capabilities, 'UNAVAILABLE', 'availability', 'Unavailable requires diagnostics and no executable capabilities')


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeObservation(Contract):
    session_id: str
    scenario_sha256: str
    state: Literal['ready', 'running', 'paused', 'completed']
    simulation_time: Timestamp
    simulator_version: str
    autopilot_version: str
    verification: str


class AdapterUnavailable(RuntimeError):
    pass


class SimulatorAdapter(Protocol):
    def probe(self, scenario: Scenario) -> Availability: ...
    def observe_transition(self, scenario: Scenario, session: Session, target: str) -> RuntimeObservation: ...
    def read_recording(self, scenario: Scenario, session: Session) -> Recording: ...
    # Future implementation must own an isolated virtual runtime and verify it.
    # No host/port, serial device, arbitrary shell command, or real-vehicle endpoint.


def detect_dependencies() -> tuple[Dependency, ...]:
    dependencies = []
    for name, command in (('gazebo', 'gz'), ('px4', 'px4'), ('ros2', 'ros2'), ('docker', 'docker')):
        try:
            path = shutil.which(command)
            status = 'located_unverified' if path else 'not_found'
        except OSError:
            path, status = None, 'probe_failed'
        dependencies.append(Dependency(name=name, executable=path, status=status, version=None))
    return tuple(dependencies)


class GazeboPx4Adapter:
    """Explicitly unavailable foundation adapter; no simulator launch or hardware I/O."""
    def probe(self, scenario: Scenario) -> Availability:
        dependencies = detect_dependencies()
        missing = ', '.join(d.name for d in dependencies if d.name in ('gazebo', 'px4') and d.status != 'located_unverified')
        note = f'Missing or undetected required executables: {missing}. ' if missing else ''
        return Availability(state='unavailable', capabilities=(), dependencies=dependencies, verification=None,
                            diagnostics=(Diagnostic(code='ADAPTER_UNAVAILABLE', path='adapter', severity='unavailable',
                                                    explanation=note + 'Runtime integration and version verification are not implemented; no simulator state is attested.'),))

    def observe_transition(self, scenario: Scenario, session: Session, target: str) -> RuntimeObservation:
        raise AdapterUnavailable('Gazebo/PX4 runtime integration is not implemented')

    def read_recording(self, scenario: Scenario, session: Session) -> Recording:
        raise AdapterUnavailable('No simulator recording is available')
