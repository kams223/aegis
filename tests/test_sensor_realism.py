"""Synthetic unit fixtures; these never attest Gazebo operation."""
from dataclasses import replace, asdict
import json
import pytest
from aegis.simulation.sensor_realism import *
from aegis.simulation.contracts import SimulationError


def sample(t=0):
    return Observation(sensor='barometer', acquisition_ns=t, simulation_ns=t, delivery_ns=t,
        frame='passive_aircraft::body::barometer', source_sha256='a'*64, native_json='{}',
        values=(Field(name='pressure', value=101325.0, unit='Pa'), Field(name='variance', value=0.0, unit='Pa^2')))


def rule(**kw):
    return Rule(sensor='barometer', field='pressure', unit='Pa', **kw)


def test_identity_and_immutable():
    stream = tuple(sample(i*10**7) for i in range(10))
    before = encode([asdict(o) for o in stream])
    out = transform(stream)
    assert all(d.values == d.original.values and d.delivery_ns == d.original.delivery_ns for d in out)
    assert before == encode([asdict(o) for o in stream])
    with pytest.raises(AttributeError): stream[0].sensor = 'imu'


def test_noise_replay_independence():
    stream = tuple(sample(i*10**7) for i in range(30))
    cfg = ImpairmentConfig(seed=1, rules=(rule(noise_std=0.1),))
    a = transform(stream, cfg)
    assert a == transform(stream, cfg)
    assert a != transform(stream, replace(cfg, seed=2))
    assert a[10].values == transform((stream[10],), cfg)[0].values


def test_drift_zero_negative_and_reference():
    cfg = ImpairmentConfig(reference_ns=10**9, rules=(rule(drift_per_second=-2.0),))
    assert transform((sample(2*10**9),), cfg)[0].values[0].value == 101323.0
    assert transform((sample(0),), cfg)[0].values[0].value == 101327.0
    assert transform((sample(),), ImpairmentConfig(rules=(rule(),)))[0].values == sample().values


def test_dropout_preserves_evidence():
    out = transform((sample(),), ImpairmentConfig(policies=(SensorPolicy(sensor='barometer', dropout_probability=1.0),)))
    assert out[0].values is None and out[0].original == sample()
    assert 'MISSING_OBSERVATION' in out[0].diagnostics


def test_jitter_stale_reordering_and_ties():
    stream = tuple(sample(i*10**6) for i in range(60))
    out = transform(stream, ImpairmentConfig(stale_after_ns=1, policies=(SensorPolicy(sensor='barometer', latency_ns=10**8, jitter_ns=10**8),)))
    assert any('OUT_OF_ORDER' in d.diagnostics for d in out)
    assert any('STALE' in d.diagnostics for d in out)
    assert {d.original.acquisition_ns for d in out} == {o.acquisition_ns for o in stream}
    assert 'DUPLICATE' in validate_stream((sample(), sample()))[0]['reasons']
    assert 'STALE' in validate_stream((replace(sample(), delivery_ns=10**9),))[0]['reasons']
    assert 'ACQUISITION_REGRESSION' in validate_stream((sample(2), sample(1)))[0]['reasons']
    assert 'DELIVERY_REGRESSION' in validate_stream((replace(sample(), delivery_ns=10), sample(1)))[0]['reasons']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite(value):
    with pytest.raises(SimulationError): Field(name='pressure', value=value, unit='Pa')


def test_rejections_and_bounds():
    for kwargs in ({'frame': 'unknown'}, {'sensor': 'unknown'}, {'schema_version': 2}, {'acquisition_ns': True}):
        with pytest.raises(SimulationError): replace(sample(), **kwargs)
    with pytest.raises(SimulationError): replace(sample(), values=(Field(name='pressure', value=1.0, unit='psi'),))
    with pytest.raises(SimulationError): transform((sample(),)*1025)
    for raw in (b'{}', b'{', b'{"schema_version":1,"schema_version":1}', b' '* (1024*1024+1), b'['*2000):
        with pytest.raises(SimulationError): load_config(raw)
    assert len(validate_stream(())) == 3
    assert transform(()) == ()
    with pytest.raises(SimulationError): transform((sample(),sample()))
    with pytest.raises(SimulationError): SensorPolicy(sensor='barometer', latency_ns=0, jitter_ns=1)


def test_config_roundtrip():
    cfg = ImpairmentConfig(rules=(rule(bias=0.1),))
    assert load_config(encode(asdict(cfg))) == cfg


def test_normalization_and_ground_truth(monkeypatch):
    import sys
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    from realism_replay import normalize, comparisons, read_json
    streams = dict(imu=[], gnss=[], barometer=[dict(time_ns=0, header_frames=['passive_aircraft::body::barometer'], pressure=101325.0, variance=0.0)])
    observations = normalize(streams, 'a'*64)
    assert json.loads(observations[0].native_json) == streams['barometer'][0]
    pose = dict(time_ns=0, z=0)
    assert comparisons(transform(observations), [pose], True)['barometer.altitude_error_m']['maximum'] == 0
    streams['barometer'][0]['header_frames'] = ['unknown']
    with pytest.raises(SimulationError): normalize(streams, 'a'*64)
    streams['barometer'] = [{}] * 257
    with pytest.raises(SimulationError): normalize(streams, 'a'*64)


def test_bounded_report(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    from realism_replay import read_json
    path = tmp_path / 'bad.json'
    for data in (b'[]', b'null', b'{', b'{"a":1,"a":2}', b'{"a":NaN}', b'['*2000, b' '*(16*1024*1024+1)):
        path.write_bytes(data)
        with pytest.raises(SimulationError): read_json(path)


def test_invalid_derived_retains_value_and_diagnostics():
    out = transform((sample(),), ImpairmentConfig(rules=(rule(bias=-200000.0),)))
    assert out[0].values[0].value < 0
    assert 'PRESSURE_DOMAIN' in out[0].diagnostics
    assert out[0].original.values[0].value == 101325.0
    assert load_observation(encode(asdict(sample()))) == sample()


def test_simulation_clock_drives_drift(monkeypatch):
    import time
    monkeypatch.setattr(time, 'time', lambda: (_ for _ in ()).throw(AssertionError('wall clock used')))
    obs = replace(sample(), simulation_ns=2*10**9, delivery_ns=2*10**9)
    cfg = ImpairmentConfig(stale_after_ns=3*10**9, rules=(rule(drift_per_second=-1.0),))
    assert transform((obs,), cfg)[0].values[0].value == 101323.0


def test_timestamp_ties_between_sensors():
    gnss = Observation(sensor='gnss', acquisition_ns=0, simulation_ns=0, delivery_ns=0,
        frame='passive_aircraft::body::gnss', source_sha256='a'*64, native_json='{}',
        values=tuple(Field(name=k, value=0.0, unit=u) for k,u in FIELDS['gnss'].items()))
    out = transform((sample(), gnss))
    assert [d.original.sensor for d in out] == ['barometer', 'gnss']
    assert not any('OUT_OF_ORDER' in d.diagnostics for d in out)


def test_replay_entry_point_determinism_and_rejections(tmp_path, monkeypatch):
    from pathlib import Path
    import hashlib
    from test_gazebo_sensors import samples
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    from realism_replay import replay
    streams, poses = samples()
    report = dict(schema_version=1, evidence_kind='real_gazebo_transport', success=True, cleanup_ok=True,
        evidence=dict(sensor_samples=streams, pose_samples=poses))
    source = tmp_path / 'fixture.json'
    config = tmp_path / 'config.json'
    config.write_bytes(encode(asdict(ImpairmentConfig())))
    source.write_bytes(encode(report))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert encode(replay(source, config, digest)) == encode(replay(source, config, digest))
    with pytest.raises(SimulationError): replay(source, config, '0'*64)
    for key, value in [('schema_version', 2), ('success', False), ('evidence_kind', 'synthetic')]:
        bad = dict(report, **{key: value})
        source.write_bytes(encode(bad))
        with pytest.raises(SimulationError): replay(source, config, hashlib.sha256(source.read_bytes()).hexdigest())


@pytest.mark.parametrize('timestamp', [-1, 1.0, '0', None, True, 2**64])
def test_invalid_timestamps(timestamp):
    for name in ('acquisition_ns', 'simulation_ns', 'delivery_ns'):
        with pytest.raises(SimulationError): replace(sample(), **{name: timestamp})
    with pytest.raises(SimulationError): replace(sample(5), simulation_ns=4)
    with pytest.raises(SimulationError): replace(sample(5), delivery_ns=4)


@pytest.mark.parametrize('path', [(), ('rules', 0), ('policies', 0)])
def test_unknown_config_fields_and_versions(path):
    cfg = asdict(ImpairmentConfig(rules=(rule(),), policies=(SensorPolicy(sensor='imu'),)))
    nested = cfg
    for part in path: nested = nested[part]
    nested['unknown'] = 0
    with pytest.raises(SimulationError): load_config(encode(cfg))
    del nested['unknown']
    nested['schema_version'] = 2
    with pytest.raises(SimulationError): load_config(encode(cfg))


def test_rng_cross_field_sensor_and_purpose_independence(monkeypatch):
    from test_gazebo_sensors import samples
    from pathlib import Path
    import importlib.util
    spec = importlib.util.spec_from_file_location('realism_independence', Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke/realism_replay.py')
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    streams, _ = samples()
    original = encode(streams)
    observations = module.normalize(streams, 'a'*64)
    base = ImpairmentConfig(seed=3, rules=(rule(noise_std=0.1),))
    additional = replace(base, rules=base.rules + (Rule(sensor='gnss', field='altitude', unit='m', noise_std=0.5),))
    a, b = transform(observations, base), transform(observations, additional)
    def keyed(rows): return {(d.original.sensor, d.original.acquisition_ns): d for d in rows}
    aa, bb = keyed(a), keyed(b)
    assert all(d.values == bb[k].values for k, d in aa.items() if k[0] != 'gnss')
    assert original == encode(streams)
    # Additional field noise on the same sensor cannot consume pressure's stream.
    gnss = tuple(o for o in observations if o.sensor == 'gnss')
    first = ImpairmentConfig(seed=3, rules=(Rule(sensor='gnss', field='altitude', unit='m', noise_std=0.5),))
    second = replace(first, rules=first.rules + (Rule(sensor='gnss', field='latitude', unit='deg', noise_std=0.01),))
    def alt(rows): return [next(f.value for f in d.values if f.name == 'altitude') for d in rows]
    assert alt(transform(gnss, first)) == alt(transform(gnss, second))
    assert rng(3, 'gnss', 'altitude', 0, 'normal').random() != rng(3, 'gnss', 'latitude', 0, 'normal').random()
    assert rng(3, 'gnss', '', 0, 'dropout').random() != rng(3, 'gnss', '', 0, 'jitter').random()


def test_output_bound_and_large_rejection(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    import realism_replay
    assert realism_replay.replay_bytes({'test': 1}) == encode({'test': 1})
    monkeypatch.setattr(realism_replay, 'MAX_OUTPUT_BYTES', 10)
    with pytest.raises(SimulationError, match='output'): realism_replay.replay_bytes({'test': 'large output'})
    rows = (sample(),) * 1024
    diagnostics = validate_stream(rows)
    assert sum('DUPLICATE' in d['reasons'] for d in diagnostics) == 1023
    with pytest.raises(SimulationError, match='1023 rejected observations'): transform(rows)


def test_report_overflow_number_and_missing_evidence(tmp_path, monkeypatch):
    from pathlib import Path
    import hashlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'simulation/gazebo-smoke'))
    from realism_replay import read_json, replay
    path = tmp_path / 'bad.json'
    path.write_bytes(b'{"metadata":1e999999}')
    with pytest.raises(SimulationError): read_json(path)
    path.write_bytes(encode(dict(schema_version=1, evidence_kind='real_gazebo_transport', success=True, cleanup_ok=True, evidence=[])))
    with pytest.raises(SimulationError, match='evidence'): replay(path, path, hashlib.sha256(path.read_bytes()).hexdigest())
