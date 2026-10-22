"""Offline derived sensor evidence. No clocks, acquisition, or control interfaces."""
from dataclasses import dataclass, asdict, replace
import hashlib
import json
import math
import random

from .contracts import Contract, require, load_contract, UINT64_MAX

# Native sensor frames are identities, not automatic coordinate conversions.
FIELDS = {
    'imu': {'acceleration.' + a: 'm/s^2' for a in 'xyz'} | {'angular_velocity.' + a: 'rad/s' for a in 'xyz'} | {'orientation.' + a: '1' for a in 'xyzw'},
    'gnss': {'latitude': 'deg', 'longitude': 'deg', 'altitude': 'm'},
    'barometer': {'pressure': 'Pa', 'variance': 'Pa^2'},
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Field(Contract):
    name: str
    value: float
    unit: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation(Contract):
    sensor: str
    acquisition_ns: int
    simulation_ns: int
    delivery_ns: int
    frame: str
    source_sha256: str
    native_json: str
    values: tuple[Field, ...]

    def validate(self):
        require(self.sensor in FIELDS, 'IDENTITY', 'sensor', 'Unexpected sensor identity')
        require(self.frame == 'passive_aircraft::body::' + self.sensor, 'FRAME', 'frame', 'Unknown native frame')
        require(len(self.source_sha256) == 64 and all(c in '0123456789abcdef' for c in self.source_sha256), 'PROVENANCE', 'source_sha256', 'Require report SHA-256')
        require({f.name: f.unit for f in self.values} == FIELDS[self.sensor] and len(self.values) == len(FIELDS[self.sensor]), 'UNITS', 'values', 'Require exact fields and physical units')
        require(self.acquisition_ns <= self.simulation_ns <= self.delivery_ns, 'TIMESTAMP', 'times', 'Acquisition, simulation and delivery times disagree')


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule(Contract):
    sensor: str
    field: str
    unit: str
    noise_std: float = 0.0
    bias: float = 0.0
    drift_per_second: float = 0.0

    def validate(self):
        require(self.sensor in FIELDS and FIELDS[self.sensor].get(self.field) == self.unit, 'UNITS', 'rule', 'Unknown sensor, numeric field or unit')
        require(not self.field.startswith('orientation.') and self.field != 'variance', 'SCHEMA', 'rule', 'Quaternion and variance impairments unsupported')
        require(self.noise_std >= 0, 'BOUND', 'noise_std', 'Gaussian standard deviation must be nonnegative')


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorPolicy(Contract):
    sensor: str
    dropout_probability: float = 0.0
    latency_ns: int = 0
    jitter_ns: int = 0

    def validate(self):
        require(self.sensor in FIELDS and 0 <= self.dropout_probability <= 1, 'BOUND', 'policy', 'Invalid sensor/dropout probability')
        require(self.jitter_ns <= self.latency_ns <= 10**12, 'BOUND', 'latency', 'Require jitter <= latency <= 1000 s; no pre-acquisition delivery')


@dataclass(frozen=True, slots=True, kw_only=True)
class ImpairmentConfig(Contract):
    seed: int = 0
    reference_ns: int = 0
    stale_after_ns: int = 100_000_000
    rules: tuple[Rule, ...] = ()
    policies: tuple[SensorPolicy, ...] = ()

    def validate(self):
        require(len({(r.sensor, r.field) for r in self.rules}) == len(self.rules), 'SCHEMA', 'rules', 'Duplicate rule')
        require(len(self.policies) <= 3 and len({p.sensor for p in self.policies}) == len(self.policies), 'SCHEMA', 'policies', 'Duplicate policy')


@dataclass(frozen=True, slots=True)
class Derived:
    original: Observation
    config_sha256: str
    config_version: int
    seed_identifier: str
    delivery_ns: int
    values: tuple[Field, ...] | None
    transformations: tuple[str, ...]
    diagnostics: tuple[str, ...]


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def rng(seed, sensor, field, timestamp, purpose):
    # Keyed substreams: adding another sensor/field cannot consume this stream.
    key = encode([seed, sensor, field, timestamp, purpose])
    return random.Random(int.from_bytes(hashlib.sha256(key).digest(), 'big'))


def value_diagnostics(sensor, fields):
    """Read-only physical-domain checks; no clipping or value repair."""
    v = {f.name: f.value for f in fields}
    reasons = []
    if sensor == 'gnss' and not (-90 <= v['latitude'] <= 90 and -180 <= v['longitude'] <= 180):
        reasons.append('GEOGRAPHIC_RANGE')
    if sensor == 'barometer' and (v['pressure'] <= 0 or v['variance'] < 0):
        reasons.append('PRESSURE_DOMAIN')
    if sensor == 'imu' and abs(sum(v['orientation.'+a]**2 for a in 'xyzw')-1) > 1e-5:
        reasons.append('QUATERNION_NORM')
    return reasons


def load_observation(data):
    return load_contract(Observation, data)


def validate_stream(observations, stale_after_ns=100_000_000, expected=('imu', 'gnss', 'barometer')):
    require(type(observations) is tuple and len(observations) <= 1024, 'BOUND', 'observations', 'Require <=1024 immutable observations')
    require(type(stale_after_ns) is int and 0 <= stale_after_ns <= UINT64_MAX, 'BOUND', 'staleness', 'Invalid staleness threshold')
    diagnostics = []
    seen, watermarks, deliveries, present = set(), {}, {}, set()
    for index, obs in enumerate(observations):
        require(type(obs) is Observation, 'SCHEMA', 'observations', 'Require validated immutable observations')
        present.add(obs.sensor)
        reasons = value_diagnostics(obs.sensor, obs.values)
        key = (obs.sensor, obs.acquisition_ns)
        if obs.sensor not in expected: reasons.append('UNEXPECTED_SENSOR')
        if key in seen: reasons.append('DUPLICATE')
        if obs.acquisition_ns < watermarks.get(obs.sensor, -1): reasons.append('ACQUISITION_REGRESSION')
        if obs.delivery_ns < deliveries.get(obs.sensor, -1): reasons.append('DELIVERY_REGRESSION')
        if obs.delivery_ns - obs.acquisition_ns > stale_after_ns: reasons.append('STALE')
        if reasons: diagnostics.append({'index': index, 'reasons': reasons})
        seen.add(key)
        watermarks[obs.sensor] = max(obs.acquisition_ns, watermarks.get(obs.sensor, -1))
        deliveries[obs.sensor] = max(obs.delivery_ns, deliveries.get(obs.sensor, -1))
    for sensor in expected:
        if sensor not in present: diagnostics.append({'sensor': sensor, 'reasons': ['MISSING_STREAM']})
    return diagnostics


def transform(observations, config=ImpairmentConfig()):
    require(type(config) is ImpairmentConfig, 'SCHEMA', 'config', 'Require validated impairment configuration')
    rejected = validate_stream(observations, config.stale_after_ns, expected=tuple(FIELDS))
    fatal = [d for d in rejected if any(r != 'MISSING_STREAM' for r in d['reasons'])]
    require(not fatal, 'TELEMETRY', 'observations', f'{len(fatal)} rejected observations; first: {fatal[0]}' if fatal else '')
    digest = hashlib.sha256(encode(asdict(config))).hexdigest()
    result = []
    for obs in observations:
        policy = next((p for p in config.policies if p.sensor == obs.sensor), SensorPolicy(sensor=obs.sensor))
        drop = rng(config.seed, obs.sensor, '', obs.acquisition_ns, 'dropout').random() < policy.dropout_probability
        jitter = rng(config.seed, obs.sensor, '', obs.acquisition_ns, 'jitter').randint(-policy.jitter_ns, policy.jitter_ns)
        delivery = obs.delivery_ns + policy.latency_ns + jitter
        require(delivery <= UINT64_MAX, 'BOUND', 'delivery', 'Timestamp overflow')
        values, provenance = [], []
        for f in obs.values:
            rule = next((r for r in config.rules if (r.sensor, r.field) == (obs.sensor, f.name)), None)
            value = f.value
            if rule:
                value += rule.bias + rule.drift_per_second * ((obs.simulation_ns - config.reference_ns) / 1e9)
                value += rng(config.seed, obs.sensor, f.name, obs.acquisition_ns, 'normal').gauss(0, rule.noise_std)
                provenance.append('additive Gaussian/bias/linear drift:' + f.name)
            values.append(Field(name=f.name, unit=f.unit, value=value))
        if policy != SensorPolicy(sensor=obs.sensor): provenance.append('seeded dropout/uniform integer delivery jitter/fixed latency')
        result.append(Derived(obs, digest, config.schema_version, str(config.seed), delivery, None if drop else tuple(values), tuple(provenance), ('MISSING_OBSERVATION',) if drop else ()))
    # Delivery order is explicit; stable timestamp ties retain supplied order.
    result.sort(key=lambda d: d.delivery_ns)
    high = {}
    for i, d in enumerate(result):
        flags = list(d.diagnostics)
        if d.values is not None: flags.extend(value_diagnostics(d.original.sensor, d.values))
        if d.values is not None:
            if d.original.acquisition_ns < high.get(d.original.sensor, -1): flags.append('OUT_OF_ORDER')
            high[d.original.sensor] = max(d.original.acquisition_ns, high.get(d.original.sensor, -1))
        if d.delivery_ns - d.original.acquisition_ns > config.stale_after_ns: flags.append('STALE')
        result[i] = replace(d, diagnostics=tuple(flags))
    return tuple(result)


def load_config(data):
    return load_contract(ImpairmentConfig, data)


def statistics(values):
    if not values: return {'count': 0, 'mean': None, 'rmse': None, 'minimum': None, 'maximum': None}
    return dict(count=len(values), mean=sum(values)/len(values), rmse=math.sqrt(sum(v*v for v in values)/len(values)), minimum=min(values), maximum=max(values))


def summarize(derived, config):
    summary = {}
    for sensor in FIELDS:
        rows = [d for d in derived if d.original.sensor == sensor]
        kept = [d for d in rows if d.values is not None]
        summary[sensor] = dict(samples=len(rows), delivered=len(kept), dropped=len(rows)-len(kept), dropout_rate=(len(rows)-len(kept))/len(rows) if rows else None,
            latency_ns=statistics([d.delivery_ns-d.original.acquisition_ns for d in kept]),
            out_of_order=sum('OUT_OF_ORDER' in d.diagnostics for d in kept), stale=sum('STALE' in d.diagnostics for d in kept),
            perturbation={f: statistics([next(v.value for v in d.values if v.name == f)-next(v.value for v in d.original.values if v.name == f) for d in kept]) for f in FIELDS[sensor]},
            bias_and_drift=[asdict(r) for r in config.rules if r.sensor == sensor])
    return summary
