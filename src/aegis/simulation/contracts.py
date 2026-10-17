"""Closed, immutable simulation contracts. No I/O, implicit clocks, or device access."""
from dataclasses import asdict, dataclass, fields, is_dataclass
import json
from math import isfinite
import re
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

MAX_BYTES = 1024 * 1024
MAX_RECORDS = 256
UINT64_MAX = (1 << 64) - 1
State = Literal['created', 'ready', 'running', 'paused', 'completed', 'failed']
ALLOWED = {
    'created': ('ready', 'failed'), 'ready': ('running', 'failed'),
    'running': ('paused', 'completed', 'failed'),
    'paused': ('running', 'completed', 'failed'), 'completed': (), 'failed': (),
}


class SimulationError(ValueError):
    def __init__(self, code, path, explanation):
        self.diagnostic = Diagnostic(code=code, path=path, explanation=explanation, severity='error')
        super().__init__(f'{code} at {path}: {explanation}')


def require(condition, code, path, explanation):
    if not condition:
        raise SimulationError(code, path, explanation)


def uint64(value, path):
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None,
            'TIMESTAMP', path, 'Require canonical unsigned decimal string')
    require(int(value) <= UINT64_MAX, 'TIMESTAMP', path, 'Value exceeds uint64')
    return int(value)


def _check(value, hint, path):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (UnionType, Union):
        if value is None and type(None) in args:
            return
        _check(value, next(h for h in args if h is not type(None)), path)
    elif origin is Literal:
        require(any(type(value) is type(a) and value == a for a in args), 'SCHEMA', path, 'Unsupported declared value')
    elif origin is tuple:
        require(type(value) is tuple and len(value) <= MAX_RECORDS, 'BOUND', path, 'Require bounded immutable tuple')
        for item in value:
            _check(item, args[0], path)
    elif hint is str:
        require(type(value) is str and 0 < len(value) <= 1024 and bool(value.strip()), 'SCHEMA', path, 'Require bounded nonempty string')
        require(not any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff for c in value), 'SCHEMA', path, 'Invalid text encoding')
        if path.endswith('_id') or path.endswith('domain'):
            require(len(value) <= 128 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', value) is not None, 'IDENTITY', path, 'Require opaque ASCII identity')
    elif hint is int:
        require(type(value) is int and 0 <= value <= UINT64_MAX, 'BOUND', path, 'Require bounded nonnegative integer, not bool')
    elif hint is float:
        require(type(value) is float and isfinite(value) and abs(value) <= 1e6, 'BOUND', path, 'Require finite bounded float')
    elif hint is bool:
        require(type(value) is bool, 'SCHEMA', path, 'Require bool')
    else:
        require(type(value) is hint, 'SCHEMA', path, 'Wrong nested contract type')


@dataclass(frozen=True, slots=True, kw_only=True)
class Contract:
    schema_version: int = 1

    def __post_init__(self):
        require(type(self.schema_version) is int and self.schema_version == 1, 'VERSION', 'schema_version', 'Only integer version 1 is supported')
        hints = get_type_hints(type(self))
        for field in fields(self):
            _check(getattr(self, field.name), hints[field.name], field.name)
        self.validate()

    def validate(self):
        pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic(Contract):
    code: str
    path: str
    explanation: str
    severity: Literal['error', 'unavailable']


@dataclass(frozen=True, slots=True, kw_only=True)
class Clock(Contract):
    domain: str
    kind: Literal['simulation', 'wall']
    unit: Literal['ns']
    epoch: Literal['session_start', 'unix']

    def validate(self):
        require(self.epoch == ('session_start' if self.kind == 'simulation' else 'unix'), 'CLOCK_DOMAIN', 'epoch', 'Clock kind and epoch differ')


@dataclass(frozen=True, slots=True, kw_only=True)
class Timestamp(Contract):
    value_ns: str
    domain: str
    unit: Literal['ns'] = 'ns'

    def validate(self):
        uint64(self.value_ns, 'value_ns')


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeVersions(Contract):
    simulator: Literal['gz-sim']
    simulator_version: Literal['8.3.0']
    autopilot: Literal['PX4-SITL']
    autopilot_version: Literal['1.16.0']


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment(Contract):
    environment_id: str
    description: str
    world: Literal['fictional_flat_plane']
    bounds_m: tuple[float, ...]
    world_frame: Literal['world_enu']
    length_unit: Literal['m']
    angle_unit: Literal['rad']

    def validate(self):
        require(len(self.bounds_m) == 3 and all(0 < v <= 50 for v in self.bounds_m), 'BOUND', 'bounds_m', 'Require three positive extents of at most 50 m')


@dataclass(frozen=True, slots=True, kw_only=True)
class Vehicle(Contract):
    vehicle_id: str
    kind: Literal['aerial', 'ground']
    model: Literal['x500', 'ground_placeholder']
    initial_position_m: tuple[float, ...]
    body_frame: Literal['body_flu']

    def validate(self):
        require(len(self.initial_position_m) == 3, 'SCHEMA', 'initial_position_m', 'Require three declared coordinates')
        require(self.model == ('x500' if self.kind == 'aerial' else 'ground_placeholder'), 'SCHEMA', 'model', 'Vehicle kind and model differ')


@dataclass(frozen=True, slots=True, kw_only=True)
class Scenario(Contract):
    scenario_id: str
    description: str
    data_origin: Literal['simulated']
    provenance: str
    versions: RuntimeVersions
    environment: Environment
    vehicles: tuple[Vehicle, ...]
    seed: int
    duration_ns: str
    step_ns: str
    objective: Literal['virtual_hover']
    hover_altitude_m: float
    autopilot_world_frame: Literal['autopilot_ned']
    autopilot_body_frame: Literal['autopilot_frd']
    frame_mapping: Literal['not_implemented']

    def validate(self):
        duration, step = uint64(self.duration_ns, 'duration_ns'), uint64(self.step_ns, 'step_ns')
        require(0 < step <= 1_000_000_000 and 0 < duration <= 120_000_000_000 and duration % step == 0, 'BOUND', 'duration_ns', 'Require bounded whole simulation steps within 120 s')
        require(self.seed <= (1 << 32) - 1 and 1 <= len(self.vehicles) <= 8, 'BOUND', 'scenario', 'Seed or vehicle count outside limits')
        require(len({v.vehicle_id for v in self.vehicles}) == len(self.vehicles), 'IDENTITY', 'vehicles', 'Duplicate vehicle identity')
        require(any(v.kind == 'aerial' for v in self.vehicles), 'SCHEMA', 'vehicles', 'Hover scenario requires an aerial declaration')
        require(0 < self.hover_altitude_m <= min(3.0, self.environment.bounds_m[2]), 'BOUND', 'hover_altitude_m', 'Hover objective outside declared environment')
        for vehicle in self.vehicles:
            x, y, z = vehicle.initial_position_m
            bx, by, bz = self.environment.bounds_m
            require(abs(x) <= bx / 2 and abs(y) <= by / 2 and 0 <= z <= bz, 'BOUND', 'initial_position_m', 'Initial position outside declared extents')


@dataclass(frozen=True, slots=True, kw_only=True)
class Transition(Contract):
    sequence: int
    previous: State | None
    state: State
    simulation_time: Timestamp
    wall_time: Timestamp
    verification: str | None
    diagnostic: Diagnostic | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Session(Contract):
    session_id: str
    scenario_id: str
    scenario_sha256: str
    data_origin: Literal['simulated']
    state: State
    simulation_clock: Clock
    wall_clock: Clock
    simulation_time: Timestamp
    wall_time: Timestamp
    duration_ns: str
    step_ns: str
    time_verification: str | None
    history: tuple[Transition, ...]

    def validate(self):
        require(re.fullmatch('[0-9a-f]{64}', self.scenario_sha256) is not None, 'IDENTITY', 'scenario_sha256', 'Require SHA-256 hex digest')
        require(self.simulation_clock.kind == 'simulation' and self.wall_clock.kind == 'wall' and self.simulation_clock.domain != self.wall_clock.domain, 'CLOCK_DOMAIN', 'clocks', 'Simulation and wall clocks must remain distinct')
        duration, step = uint64(self.duration_ns, 'duration_ns'), uint64(self.step_ns, 'step_ns')
        require(0 < step <= 1_000_000_000 and 0 < duration <= 120_000_000_000 and duration % step == 0, 'BOUND', 'step_ns', 'Invalid duration or step')
        require(0 < len(self.history) <= 128, 'BOUND', 'history', 'Require 1..128 lifecycle entries')
        prior, prior_time = None, 0
        for index, event in enumerate(self.history):
            require(event.sequence == index and event.previous == prior, 'LIFECYCLE', 'history', 'Lifecycle sequence or predecessor differs')
            require(event.state == 'created' if index == 0 else event.state in ALLOWED[prior], 'LIFECYCLE', 'state', 'Illegal lifecycle transition')
            self.check_times(event.simulation_time, event.wall_time)
            now = int(event.simulation_time.value_ns)
            require(now >= prior_time and (index != 0 or now == 0), 'CLOCK_DOMAIN', 'history', 'Simulation time regressed or did not start at zero')
            if index and prior != 'running':
                require(now == prior_time, 'CLOCK_DOMAIN', 'history', 'Non-running lifecycle predecessor cannot advance time')
            require(event.diagnostic is not None if event.state == 'failed' else event.diagnostic is None, 'LIFECYCLE', 'diagnostic', 'Failure diagnostic required only on failed transition')
            if event.state == 'failed':
                require(event.diagnostic.severity == 'error' and event.verification is None, 'LIFECYCLE', 'diagnostic', 'Failed state requires error diagnostic without runtime attestation')
            if event.state not in ('created', 'failed'):
                require(event.verification is not None, 'UNVERIFIED', 'verification', 'Runtime observation is required')
            prior, prior_time = event.state, now
        self.check_times(self.simulation_time, self.wall_time)
        if self.state == 'running':
            require(self.time_verification is not None, 'UNVERIFIED', 'time_verification', 'Running time requires runtime observation reference')
        else:
            require(self.time_verification == self.history[-1].verification, 'UNVERIFIED', 'time_verification', 'Transition attestation differs')
            require(self.simulation_time == self.history[-1].simulation_time and self.wall_time == self.history[-1].wall_time, 'CLOCK_DOMAIN', 'state', 'Non-running state must retain transition timestamps')
        require(self.state == prior and int(self.simulation_time.value_ns) >= prior_time, 'LIFECYCLE', 'state', 'Current state disagrees with history')

    def check_times(self, simulation, wall):
        require(simulation.domain == self.simulation_clock.domain and wall.domain == self.wall_clock.domain, 'CLOCK_DOMAIN', 'timestamp', 'Timestamp uses the wrong clock domain')
        require(int(simulation.value_ns) <= int(self.duration_ns) and int(simulation.value_ns) % int(self.step_ns) == 0, 'BOUND', 'simulation_time', 'Simulation time outside scenario step bounds')


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceIdentity(Contract):
    session_id: str
    vehicle_id: str
    component_id: str
    source_id: str
    data_origin: Literal['simulated', 'recorded', 'real']
    clock_domain: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Measurement(Contract):
    quantity: Literal['position', 'linear_velocity', 'battery_fraction']
    values: tuple[float, ...]
    unit: Literal['m', 'm/s', '1']
    frame: Literal['world_enu', 'body_flu', 'autopilot_ned', 'autopilot_frd'] | None

    def validate(self):
        if self.quantity == 'battery_fraction':
            require(self.unit == '1' and self.frame is None and len(self.values) == 1 and 0 <= self.values[0] <= 1, 'MEASUREMENT', 'battery_fraction', 'Require fraction in [0,1] without coordinate frame')
        else:
            require(self.unit == ('m' if self.quantity == 'position' else 'm/s') and self.frame is not None and len(self.values) == 3, 'MEASUREMENT', 'measurement', 'Require explicit vector units and frame')
            if self.quantity == 'position':
                require(self.frame in ('world_enu', 'autopilot_ned'), 'MEASUREMENT', 'frame', 'Position requires a declared world frame')


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance(Contract):
    scenario_sha256: str
    producer: str
    reference_id: str
    original_origin: Literal['simulated', 'real']
    simulator_version: str | None
    autopilot_version: str | None

    def validate(self):
        require(re.fullmatch('[0-9a-f]{64}', self.scenario_sha256) is not None, 'IDENTITY', 'scenario_sha256', 'Require SHA-256 hex digest')


@dataclass(frozen=True, slots=True, kw_only=True)
class Record(Contract):
    sequence: int
    source: SourceIdentity
    simulation_time: Timestamp
    receipt_time: Timestamp
    measurement: Measurement | None
    provenance: Provenance
    diagnostics: tuple[Diagnostic, ...]

    def validate(self):
        require(self.sequence < MAX_RECORDS and len(self.diagnostics) <= 8, 'BOUND', 'record', 'Record index or diagnostic count outside limits')
        require(not any(d.severity == 'error' for d in self.diagnostics), 'MEASUREMENT', 'diagnostics', 'A recording cannot accept a record with a fatal diagnostic')
        if self.measurement is not None:
            require(not any(d.code == 'MISSING_MEASUREMENT' for d in self.diagnostics), 'MEASUREMENT', 'diagnostics', 'A present measurement cannot also be declared missing')
        if self.measurement is None:
            require(any(d.code == 'MISSING_MEASUREMENT' and d.severity == 'unavailable' for d in self.diagnostics), 'MEASUREMENT', 'diagnostics', 'Missing measurement requires explicit unavailable diagnostic')


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording(Contract):
    session_id: str
    scenario_id: str
    scenario_sha256: str
    data_origin: Literal['simulated', 'recorded', 'real']
    records: tuple[Record, ...]

    def validate(self):
        require(re.fullmatch('[0-9a-f]{64}', self.scenario_sha256) is not None, 'IDENTITY', 'scenario_sha256', 'Require SHA-256 hex digest')
        require(self.data_origin != 'real', 'ORIGIN', 'data_origin', 'Real-device data is unsupported by this simulation subsystem')
        watermarks = {}
        for index, record in enumerate(self.records):
            require(record.sequence == index, 'ORDER', 'sequence', 'Preserve contiguous supplied record order')
            require(record.source.session_id == self.session_id and record.source.data_origin == self.data_origin and record.provenance.scenario_sha256 == self.scenario_sha256, 'PROVENANCE', 'record', 'Recording and record provenance differ')
            require(record.provenance.original_origin == 'simulated', 'ORIGIN', 'original_origin', 'Only simulated-origin recordings are supported')
            require(record.source.clock_domain == record.simulation_time.domain and record.simulation_time.domain != record.receipt_time.domain, 'CLOCK_DOMAIN', 'record', 'Simulation source and receipt domains differ or are conflated')
            key = (record.source.session_id, record.source.vehicle_id, record.source.component_id, record.source.source_id, record.source.clock_domain)
            value = int(record.simulation_time.value_ns)
            require(value >= watermarks.get(key, 0), 'ORDER', 'simulation_time', 'Source simulation timestamp regressed')
            watermarks[key] = value


def document(value):
    require(is_dataclass(value) and isinstance(value, Contract), 'SCHEMA', 'document', 'Require simulation contract')
    # A JSON roundtrip produces owned lists/dicts, never references to frozen fields.
    return json.loads(json.dumps(asdict(value), ensure_ascii=False, allow_nan=False))


def canonical_bytes(value):
    return (json.dumps(document(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _decode(hint, value, path):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (UnionType, Union):
        return None if value is None and type(None) in args else _decode(next(h for h in args if h is not type(None)), value, path)
    if origin is tuple:
        require(type(value) is list and len(value) <= MAX_RECORDS, 'BOUND', path, 'Require bounded JSON array')
        return tuple(_decode(args[0], item, path) for item in value)
    if isinstance(hint, type) and issubclass(hint, Contract):
        require(type(value) is dict and set(value) == {f.name for f in fields(hint)}, 'SCHEMA', path, 'Missing or unexpected contract fields')
        hints = get_type_hints(hint)
        return hint(**{key: _decode(hints[key], item, f'{path}.{key}') for key, item in value.items()})
    _check(value, hint, path)
    return value


def load_contract(kind, data):
    require(isinstance(kind, type) and issubclass(kind, Contract), 'SCHEMA', 'kind', 'Require a simulation contract type')
    require(type(data) is bytes and len(data) <= MAX_BYTES, 'BOUND', 'json', 'Require bytes of at most 1 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'SCHEMA', 'json', 'Duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, RecursionError, UnicodeError) as error:
        if isinstance(error, SimulationError):
            raise
        raise SimulationError('SCHEMA', 'json', 'Malformed, nonfinite, or excessively nested JSON') from error
    return _decode(kind, value, kind.__name__)
