"""Bounded offline Phase 75B report replay; stdout is deterministic derived JSON."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import math

from aegis.simulation.contracts import require, SimulationError
from aegis.simulation.sensor_realism import (Observation, Field, FIELDS, transform,
    load_config, encode, summarize, statistics, validate_stream)
from sensor_checks import analyze_sensors, pressure_altitude, world_to_sensor

MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def read_json(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    require(len(data) <= MAX_REPORT_BYTES, 'BOUND', 'report', 'Report exceeds 16 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'SCHEMA', 'report', 'Duplicate JSON key')
            result[key] = value
        return result
    def finite_number(text):
        value = float(text)
        require(math.isfinite(value), 'SCHEMA', 'report', 'Nonfinite JSON number')
        return value
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_float=finite_number, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        require(type(value) is dict, 'SCHEMA', 'report', 'Require report object')
        return data, value
    except SimulationError:
        raise
    except (ValueError, RecursionError, UnicodeError) as error:
        raise SimulationError('SCHEMA', 'report', 'Malformed or nonfinite JSON') from error


def normalize(streams, digest):
    require(type(streams) is dict and set(streams) == set(FIELDS), 'IDENTITY', 'streams', 'Require exact known sensors')
    observations = []
    for sensor, rows in streams.items():
        require(type(rows) is list and len(rows) <= 256, 'BOUND', sensor, 'Require <=256 samples per sensor')
        for row in rows:
            require(type(row) is dict, 'SCHEMA', sensor, 'Require native row object')
            values = []
            for name, unit in FIELDS[sensor].items():
                if '.' in name:
                    group, axis = name.split('.')
                    vector = row[group]
                    require(type(vector) is list and len(vector) == (4 if group == 'orientation' else 3), 'SCHEMA', group, 'Invalid vector shape')
                    value = vector['xyzw'.index(axis)]
                else: value = row[name]
                require(type(value) in (int, float), 'SCHEMA', name, 'Numeric value required')
                values.append(Field(name=name, unit=unit, value=float(value)))
            frames = [row.get('message_frame')] if sensor == 'gnss' else row['header_frames']
            require(frames == ['passive_aircraft::body::' + sensor], 'FRAME', sensor, 'Unknown frame')
            observations.append(Observation(sensor=sensor, acquisition_ns=row['time_ns'], simulation_ns=row['time_ns'], delivery_ns=row['time_ns'], frame=frames[0], source_sha256=digest, native_json=encode(row).decode().strip(), values=tuple(values)))
    return tuple(observations)


def comparisons(derived, poses, impaired):
    errors = {}
    # Residual aggregation order must not depend on seed-dependent delivery order.
    for d in sorted(derived, key=lambda d: (d.original.sensor, d.original.acquisition_ns)):
        fields = d.values if impaired else d.original.values
        if fields is None or (impaired and any(r in d.diagnostics for r in ('PRESSURE_DOMAIN', 'GEOGRAPHIC_RANGE', 'QUATERNION_NORM'))): continue
        obs = d.original
        pose = min(poses, key=lambda p: abs(p['time_ns'] - obs.acquisition_ns))
        if abs(pose['time_ns'] - obs.acquisition_ns) > 11_000_000: continue
        v = {f.name: f.value for f in fields}
        def add(name, value): errors.setdefault(name, []).append(value)
        if obs.sensor == 'gnss':
            add('gnss.altitude_error_m', v['altitude'] - pose['z'])
            add('gnss.north_error_m', math.radians(v['latitude'])*6335439-pose['y'])
            add('gnss.east_error_m', math.radians(v['longitude'])*6378137-pose['x'])
        elif obs.sensor == 'barometer':
            if v['pressure'] > 0: add('barometer.altitude_error_m', pressure_altitude(v['pressure'])-pose['z'])
        elif obs.acquisition_ns >= 1_500_000_000:
            expected = world_to_sensor([0, 0, 9.81], [pose[k] for k in ('qx','qy','qz','qw')])
            for axis, target in zip('xyz', expected): add('imu.settled_force_'+axis+'_error_m_s2', v['acceleration.'+axis]-target)
    return {key: statistics(values) for key, values in errors.items()}


def replay(report_path, config_path, expected_digest):
    raw, report = read_json(report_path)
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == expected_digest, 'PROVENANCE', 'report', 'Report digest differs from supplied verified evidence digest')
    require(type(report.get('schema_version')) is int and report['schema_version'] == 1, 'VERSION', 'report', 'Require Phase 75B report version 1')
    require(report.get('evidence_kind') == 'real_gazebo_transport', 'PROVENANCE', 'report', 'Require recorded Gazebo transport evidence')
    require(report.get('success') is True and report.get('cleanup_ok') is True, 'PROVENANCE', 'report', 'Require successful cleaned-up evidence')
    evidence = report.get('evidence')
    require(type(evidence) is dict, 'SCHEMA', 'evidence', 'Require native evidence object')
    streams, poses = evidence['sensor_samples'], evidence['pose_samples']
    require(type(poses) is list and len(poses) <= 512, 'BOUND', 'poses', 'Excessive ground truth')
    observations = normalize(streams, digest)
    source_check = analyze_sensors(streams, poses)
    require(source_check['passed'], 'TELEMETRY', 'source', str(source_check['diagnostics']))
    with Path(config_path).open('rb') as stream: config = load_config(stream.read(1024*1024+1))
    derived = transform(observations, config)
    return dict(schema_version=1, artifact_kind='offline_derived_sensor_replay', source_sha256=digest,
        config=asdict(config), source_diagnostics=validate_stream(observations),
        summary=summarize(derived, config),
        invalid_count=sum(any(r in d.diagnostics for r in ('PRESSURE_DOMAIN', 'GEOGRAPHIC_RANGE', 'QUATERNION_NORM')) for d in derived),
        rejection_diagnostics=[dict(sensor=d.original.sensor, acquisition_ns=d.original.acquisition_ns, reasons=d.diagnostics) for d in derived if d.diagnostics],
        ground_truth=dict(original=comparisons(derived, poses, False), impaired=comparisons(derived, poses, True), matching='nearest native pose <=11 ms; equatorial sub-metre local tangent; IMU settled window only'),
        observations=[asdict(d) for d in derived])


def replay_bytes(value):
    """Build bounded output before writing any bytes; never emit partial JSON."""
    output = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(value):
        data = chunk.encode('utf-8')
        require(len(output) + len(data) + 1 <= MAX_OUTPUT_BYTES,
                'BOUND', 'output', 'Replay output exceeds 8 MiB')
        output.extend(data)
    output.extend(b'\n')
    return bytes(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('config')
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    try:
        print(replay_bytes(replay(args.report, args.config, args.source_sha256)).decode(), end='')
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as error:
        diagnostic = asdict(error.diagnostic) if isinstance(error, SimulationError) else dict(code='SCHEMA', path='input', explanation=type(error).__name__)
        print(encode(dict(schema_version=1, rejected=True, diagnostic=diagnostic)).decode(), end='')
        raise SystemExit(2)
