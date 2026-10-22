"""Version 1 offline sensor telemetry; no acquisition, control, or implicit clocks."""
from dataclasses import dataclass, asdict, fields
import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from .contracts import (Contract, Timestamp, SourceIdentity, SimulationError,
                        require, load_contract, uint64)
from .sensor_realism import Derived, Field, FIELDS, encode, load_observation, load_config

MAX_INPUT = 16 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
MAX_ROWS = 1024
DERIVED_DIAGNOSTICS = frozenset(('MISSING_OBSERVATION', 'OUT_OF_ORDER', 'STALE',
                                 'PRESSURE_DOMAIN', 'GEOGRAPHIC_RANGE', 'QUATERNION_NORM'))
UNITS = {k: dict(v) for k, v in FIELDS.items()}
UNITS['barometer']['derived_altitude'] = 'm'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorTelemetry(Contract):
    observation_type: Literal['imu', 'gnss', 'barometer']
    source: SourceIdentity
    acquisition: Timestamp
    simulation: Timestamp
    delivery: Timestamp | None
    frame: str
    origin: Literal['raw', 'impaired']
    source_sha256: str
    config_json: str | None
    config_sha256: str | None
    seed_identifier: str | None
    values: tuple[Field, ...] | None

    def validate(self):
        sensor = self.observation_type
        require(self.source.data_origin == 'recorded' and self.source.vehicle_id == 'passive_aircraft' and self.source.component_id == sensor
                and self.source.source_id == 'passive_aircraft::body::' + sensor,
                'IDENTITY', 'source', 'Require recorded passive sensor identity')
        require(self.frame == self.source.source_id, 'FRAME', 'frame', 'Unknown native sensor frame')
        require(all(t.domain == self.source.clock_domain for t in (self.acquisition, self.simulation, self.delivery) if t is not None),
                'CLOCK_DOMAIN', 'timestamps', 'Require one explicit simulation clock domain')
        require(int(self.acquisition.value_ns) <= int(self.simulation.value_ns)
                and (self.delivery is None or int(self.simulation.value_ns) <= int(self.delivery.value_ns)),
                'TIMESTAMP', 'timestamps', 'Require acquisition <= simulation <= delivery when known')
        require(sha(self.source_sha256), 'PROVENANCE', 'source_sha256', 'Require source digest')
        if self.origin == 'raw':
            require(self.config_json is self.config_sha256 is self.seed_identifier is None,
                    'PROVENANCE', 'config', 'Raw records cannot declare impairment')
        else:
            require(self.config_json is not None, 'PROVENANCE', 'config', 'Impaired records require configuration')
            cfg = load_config(self.config_json.encode())
            require(self.config_json == encode(asdict(cfg)).decode().strip()
                    and self.config_sha256 == digest(encode(asdict(cfg))) and self.seed_identifier == str(cfg.seed),
                    'PROVENANCE', 'config', 'Configuration digest or seed differs')
        if self.values is not None:
            names = {f.name for f in self.values}
            allowed = UNITS[sensor]
            require(bool(names) and len(names) == len(self.values) and all(allowed.get(f.name) == f.unit for f in self.values),
                    'UNITS', 'values', 'Unknown, duplicate, or incorrectly declared fields/units')
            for group, axes in (('acceleration', 'xyz'), ('angular_velocity', 'xyz'), ('orientation', 'xyzw')):
                present = {n for n in names if n.startswith(group + '.')}
                require(not present or present == {group+'.'+a for a in axes}, 'SCHEMA', 'values', 'Partial vector')
            required = {'latitude', 'longitude', 'altitude'} if sensor == 'gnss' else {'pressure'} if sensor == 'barometer' else set()
            require(required <= names, 'SCHEMA', 'values', 'Missing required measurements')


def bounded_bytes(value):
    output = bytearray()
    for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(value):
        part = chunk.encode()
        require(len(output)+len(part)+1 <= MAX_OUTPUT, 'BOUND', 'output', 'Output exceeds 8 MiB')
        output.extend(part)
    return bytes(output) + b'\n'


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_INPUT+1)
    require(len(raw) <= MAX_INPUT, 'BOUND', 'input', 'Input exceeds 16 MiB')
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'SCHEMA', 'json', 'Duplicate JSON key')
            result[k] = v
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        # Reject overflow floats as well as NaN, including in unused metadata.
        def finite(v):
            if type(v) is float: require(math.isfinite(v), 'SCHEMA', 'json', 'Nonfinite number')
            elif type(v) is dict:
                for item in v.values(): finite(item)
            elif type(v) is list:
                for item in v: finite(item)
        finite(value)
        return raw, value
    except (ValueError, RecursionError, UnicodeError) as error:
        if isinstance(error, SimulationError): raise
        raise SimulationError('SCHEMA', 'json', 'Malformed or nonfinite JSON') from error


def inspect(records, evaluation, stale_after_ns):
    require(type(records) is tuple and len(records) <= MAX_ROWS, 'BOUND', 'records', 'Require <=1024 immutable records')
    require(type(evaluation) is Timestamp, 'SCHEMA', 'evaluation', 'Require validated evaluation timestamp')
    uint64(str(stale_after_ns), 'stale_after_ns')
    require(type(stale_after_ns) is int, 'BOUND', 'stale_after_ns', 'Require integer threshold')
    accepted, rejected, anomalies = [], [], []
    seen, high, deliveries = set(), {}, {}
    for index, record in enumerate(records):
        try:
            require(type(record) is SensorTelemetry, 'SCHEMA', 'record', 'Require validated telemetry')
            require(record.source.clock_domain == evaluation.domain, 'CLOCK_DOMAIN', 'evaluation', 'Evaluation domain differs')
            key = (record.source, record.acquisition, record.origin)
            require(key not in seen, 'DUPLICATE', 'record', 'Duplicate sensor acquisition/origin')
            seen.add(key)
            source = (record.source, record.origin)
            t = int(record.acquisition.value_ns)
            if t < high.get(source, -1): anomalies.append(dict(index=index, code='OUT_OF_ORDER'))
            high[source] = max(t, high.get(source, -1))
            if record.delivery is not None:
                delivery = int(record.delivery.value_ns)
                if delivery < deliveries.get(source, -1): anomalies.append(dict(index=index, code='DELIVERY_REGRESSION'))
                deliveries[source] = max(delivery, deliveries.get(source, -1))
            accepted.append(record)
        except SimulationError as error:
            rejected.append(dict(index=index, sensor=record.observation_type if type(record) is SensorTelemetry else None, diagnostic=asdict(error.diagnostic)))
    def freshness(r):
        now, acquisition = int(evaluation.value_ns), int(r.acquisition.value_ns)
        if r.values is None: return 'missing'
        if acquisition > now: return 'future'
        if r.delivery is not None and int(r.delivery.value_ns) > now: return 'pending'
        return 'stale' if now-acquisition > stale_after_ns else 'fresh'
    accepted.sort(key=lambda r: (int((r.delivery or r.acquisition).value_ns), r.source.source_id, int(r.acquisition.value_ns), r.origin, r.source.session_id))
    summary = {}
    for sensor in FIELDS:
        rows = [r for r in accepted if r.observation_type == sensor]
        valid = [r for r in rows if freshness(r) in ('fresh', 'stale')]
        latest = max(valid, key=lambda r: int(r.acquisition.value_ns), default=None)
        summary[sensor] = dict(count=len(rows), rejected=sum(d.get('sensor') == sensor for d in rejected), missing=sum(r.values is None for r in rows),
            latest_acquisition_ns=latest.acquisition.value_ns if latest else None,
            freshness=freshness(latest) if latest else 'missing',
            origins={o: sum(r.origin == o for r in rows) for o in ('raw', 'impaired')},
            units={f.name: f.unit for r in rows for f in (r.values or ())}, frames=sorted({r.frame for r in rows}))
    return dict(schema_version=1, artifact_kind='offline_sensor_telemetry_inspection', evaluation=asdict(evaluation),
                stale_after_ns=str(stale_after_ns), summary=summary, rejected=rejected, anomalies=anomalies,
                observations=[dict(record=asdict(r), freshness=freshness(r)) for r in accepted])


def replay(path, *, input_kind, source_sha256, domain, evaluation_ns, stale_after_ns):
    raw, report = read_json(path)
    require(digest(raw) == source_sha256, 'PROVENANCE', 'input', 'Input digest differs')
    require(type(report) is dict and type(report.get('schema_version')) is int and report['schema_version'] == 1,
            'VERSION', 'input', 'Require version 1 object')
    evaluation = Timestamp(value_ns=evaluation_ns, domain=domain)
    records, rejected, indices, source_diagnostics = [], [], [], []
    if input_kind == 'telemetry':
        require(set(report) == {'schema_version', 'observations'}, 'SCHEMA', 'input', 'Unknown envelope fields')
        rows = report['observations']
    elif input_kind == 'impaired':
        require(report.get('artifact_kind') == 'offline_derived_sensor_replay', 'SCHEMA', 'input', 'Require Phase 75C replay')
        rows = report.get('observations')
        config = load_config(encode(report['config']))
    elif input_kind == 'raw':
        require(report.get('evidence_kind') == 'real_gazebo_transport' and report.get('success') is True and report.get('cleanup_ok') is True,
                'PROVENANCE', 'input', 'Require successful recorded Gazebo evidence')
        require(type(report.get('evidence')) is dict, 'SCHEMA', 'evidence', 'Require evidence object')
        streams = report['evidence'].get('sensor_samples')
        require(type(streams) is dict and set(streams) == set(FIELDS), 'SCHEMA', 'streams', 'Require known sensor streams')
        rows = []
        for sensor, samples in streams.items():
            require(type(samples) is list and len(samples) <= 256, 'BOUND', 'streams', 'Require <=256 samples per sensor')
            rows.extend((sensor, row) for row in samples)
    else:
        raise SimulationError('SCHEMA', 'input_kind', 'Unknown input kind')
    require(type(rows) is list and len(rows) <= MAX_ROWS, 'BOUND', 'observations', 'Require <=1024 rows; summary files are not recordings')
    for index, row in enumerate(rows):
        try:
            if input_kind == 'telemetry':
                record = load_contract(SensorTelemetry, encode(row))
            else:
                if input_kind == 'impaired':
                    require(type(row) is dict and set(row) == {f.name for f in fields(Derived)},
                            'SCHEMA', 'row', 'Require exact Phase 75C derived fields')
                    require(type(row['config_version']) is int and row['config_version'] == 1,
                            'VERSION', 'config_version', 'Require integer derived configuration version 1')
                    require(type(row['diagnostics']) is list and len(row['diagnostics']) <= 8
                            and all(type(d) is str and d in DERIVED_DIAGNOSTICS for d in row['diagnostics'])
                            and len(set(row['diagnostics'])) == len(row['diagnostics']),
                            'SCHEMA', 'diagnostics', 'Require bounded distinct known Phase 75C diagnostics')
                    require(type(row['transformations']) is list and len(row['transformations']) <= 16
                            and all(type(t) is str and 0 < len(t) <= 1024 for t in row['transformations']),
                            'BOUND', 'transformations', 'Require bounded transformation descriptions')
                    require(row['values'] is None or type(row['values']) is list and len(row['values']) <= 10,
                            'BOUND', 'values', 'Require bounded derived measurements or null')
                    require((row['values'] is None) == ('MISSING_OBSERVATION' in row['diagnostics']),
                            'MEASUREMENT', 'values', 'Dropout diagnostic and unavailable values must agree')
                    original = load_observation(encode(row['original']))
                    require(original.source_sha256 == report['source_sha256'] and row['config_sha256'] == digest(encode(asdict(config)))
                            and row['config_version'] == 1 and row['seed_identifier'] == str(config.seed), 'PROVENANCE', 'row', 'Derived provenance differs')
                    sensor, t, sim, delivery, frame = original.sensor, original.acquisition_ns, original.simulation_ns, row['delivery_ns'], original.frame
                    values = None if row['values'] is None else tuple(load_contract(Field, encode(f)) for f in row['values'])
                else:
                    sensor, native = row
                    require(type(native) is dict, 'SCHEMA', 'row', 'Require native object')
                    t = native['time_ns']; sim = t; delivery = native.get('delivery_ns')
                    frame = native.get('message_frame') if sensor == 'gnss' else native['header_frames'][0]
                    if sensor != 'gnss':
                        require(native['header_frames'] == [frame], 'FRAME', 'header_frames', 'Require one native frame')
                    values = []
                    for name, unit in UNITS[sensor].items():
                        if '.' in name:
                            group, axis = name.split('.')
                            if group not in native: continue
                            vector = native[group]
                            require(type(vector) is list and len(vector) == (4 if group == 'orientation' else 3), 'SCHEMA', group, 'Invalid vector')
                            v = vector['xyzw'.index(axis)]
                        else:
                            if name not in native: continue
                            v = native[name]
                        require(type(v) in (int, float), 'SCHEMA', name, 'Require number')
                        values.append(Field(name=name, value=float(v), unit=unit))
                    values = tuple(values)
                for stamp in (t, sim, delivery):
                    require(stamp is None or type(stamp) is int, 'TIMESTAMP', 'row', 'Require native integer nanoseconds')
                ts = lambda n: Timestamp(value_ns=str(n), domain=domain)
                record = SensorTelemetry(observation_type=sensor, source=SourceIdentity(session_id='gazebo-'+(report['source_sha256'] if input_kind == 'impaired' else source_sha256), vehicle_id='passive_aircraft', component_id=sensor, source_id='passive_aircraft::body::'+sensor, data_origin='recorded', clock_domain=domain),
                    acquisition=ts(t), simulation=ts(sim), delivery=None if delivery is None else ts(delivery), frame=frame,
                    origin='impaired' if input_kind == 'impaired' else 'raw', source_sha256=report['source_sha256'] if input_kind == 'impaired' else source_sha256,
                    config_json=encode(asdict(config)).decode().strip() if input_kind == 'impaired' else None,
                    config_sha256=digest(encode(asdict(config))) if input_kind == 'impaired' else None,
                    seed_identifier=str(config.seed) if input_kind == 'impaired' else None, values=values)
            if input_kind == 'impaired' and row['diagnostics']:
                source_diagnostics.append(dict(index=index, sensor=record.observation_type,
                    acquisition_ns=record.acquisition.value_ns, reasons=list(row['diagnostics'])))
            records.append(record)
            indices.append(index)
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
            diagnostic = asdict(error.diagnostic) if isinstance(error, SimulationError) else dict(code='SCHEMA', path='row', explanation=type(error).__name__)
            rejected.append(dict(index=index, sensor=(row.get('observation_type') if input_kind == 'telemetry' and type(row) is dict else row.get('original', {}).get('sensor') if input_kind == 'impaired' and type(row) is dict and type(row.get('original')) is dict else row[0] if input_kind == 'raw' else None), diagnostic=diagnostic))
    result = inspect(tuple(records), evaluation, stale_after_ns)
    for item in result['rejected'] + result['anomalies']:
        item['index'] = indices[item['index']]
    result['rejected'] = sorted(rejected + result['rejected'], key=lambda item: item['index'])
    for sensor, summary in result['summary'].items():
        summary['rejected'] = sum(item.get('sensor') == sensor for item in result['rejected'])
    if input_kind == 'impaired':
        result['source_diagnostics'] = source_diagnostics
    result['input_sha256'] = source_sha256
    return bounded_bytes(result)
