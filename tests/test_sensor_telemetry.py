"""Synthetic fixtures plus optional local recorded evidence compatibility."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import pytest
from aegis.simulation.contracts import Timestamp, SourceIdentity, SimulationError, load_contract
from aegis.simulation.sensor_realism import Field, ImpairmentConfig, encode
from aegis.simulation.sensor_telemetry import SensorTelemetry, inspect, replay, bounded_bytes, read_json, MAX_INPUT


def sample(sensor='barometer', t=0, **kw):
    fields = {'barometer': [('pressure',101325.,'Pa')], 'gnss': [('latitude',0.,'deg'),('longitude',0.,'deg'),('altitude',0.,'m')],
              'imu': [('acceleration.'+a,0.,'m/s^2') for a in 'xyz']}
    ts=Timestamp(value_ns=str(t),domain='sim')
    return SensorTelemetry(observation_type=sensor,source=SourceIdentity(session_id='fixture',vehicle_id='passive_aircraft',component_id=sensor,source_id='passive_aircraft::body::'+sensor,data_origin='recorded',clock_domain='sim'),acquisition=ts,simulation=ts,delivery=None,frame='passive_aircraft::body::'+sensor,origin='raw',source_sha256='a'*64,config_json=None,config_sha256=None,seed_identifier=None,values=tuple(Field(name=n,value=v,unit=u) for n,v,u in fields[sensor]),**kw)


@pytest.mark.parametrize('sensor',['imu','gnss','barometer'])
def test_valid_optional_and_roundtrip(sensor):
    s=sample(sensor)
    assert load_contract(SensorTelemetry,encode(asdict(s))) == s
    out=inspect((s,),Timestamp(value_ns='0',domain='sim'),0)
    assert out['summary'][sensor]['freshness']=='fresh'
    with pytest.raises(AttributeError): s.frame='x'


@pytest.mark.parametrize('changes',[{'schema_version':2},{'frame':'world'},{'observation_type':'unknown'}, {'values':(Field(name='pressure',value=1.,unit='psi'),)}, {'values':()}, {'source_sha256':'bad'}])
def test_closed_rejections(changes):
    with pytest.raises(SimulationError): replace(sample(),**changes)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite(value):
    with pytest.raises(SimulationError): Field(name='pressure',value=value,unit='Pa')


def test_timing_missing_duplicates_and_order():
    evaluation=Timestamp(value_ns='20',domain='sim')
    out=inspect((sample(t=10),sample(t=0),sample(t=10)),evaluation,5)
    assert out['rejected'][0]['diagnostic']['code']=='DUPLICATE'
    assert out['anomalies'][0]['code']=='OUT_OF_ORDER'
    assert out['summary']['barometer']['freshness']=='stale'
    assert out['summary']['imu']['freshness']=='missing'
    assert inspect((sample(),),replace(evaluation,domain='other'),5)['rejected'][0]['diagnostic']['code']=='CLOCK_DOMAIN'
    pending=replace(sample(),delivery=Timestamp(value_ns='30',domain='sim'))
    assert inspect((pending,),evaluation,5)['observations'][0]['freshness']=='pending'
    assert inspect((sample(t=30),),evaluation,5)['observations'][0]['freshness']=='future'
    assert inspect((replace(sample(),values=None),),evaluation,5)['summary']['barometer']['missing']==1
    with pytest.raises(SimulationError): replace(sample(),delivery=Timestamp(value_ns='0',domain='other'))
    with pytest.raises(SimulationError): inspect((sample(),)*1025,evaluation,5)


def test_provenance_immutability_and_deterministic(tmp_path):
    cfg=encode(asdict(ImpairmentConfig(seed=75)))
    impaired=replace(sample(),origin='impaired',config_json=cfg.decode().strip(),config_sha256=hashlib.sha256(cfg).hexdigest(),seed_identifier='75')
    with pytest.raises(SimulationError): replace(impaired,seed_identifier='76')
    rows=[asdict(sample()),asdict(impaired),{'schema_version':2}]
    before=encode(rows)
    path=tmp_path/'input.json'; path.write_bytes(encode(dict(schema_version=1,observations=rows)))
    args=dict(input_kind='telemetry',source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),domain='sim',evaluation_ns='100',stale_after_ns=5)
    a=replay(path,**args)
    assert a==replay(path,**args) and before==encode(rows)
    assert len(json.loads(a)['rejected'])==1
    assert json.loads(a)['summary']['barometer']['origins']=={'raw':1,'impaired':1}
    assert path.read_bytes()==encode(dict(schema_version=1,observations=rows))
    with pytest.raises(SimulationError): replay(path,**dict(args,source_sha256='0'*64))


@pytest.mark.parametrize('raw',[b'{',b'[]'*5000,b'{"x":NaN}',b'{"x":1e999}',b'{"x":1,"x":2}',b'['*2000,b' '*(MAX_INPUT+1)])
def test_invalid_input(tmp_path,raw):
    path=tmp_path/'bad';path.write_bytes(raw)
    with pytest.raises(SimulationError): read_json(path)


def test_output_bound(monkeypatch):
    import aegis.simulation.sensor_telemetry as module
    monkeypatch.setattr(module,'MAX_OUTPUT',10)
    with pytest.raises(SimulationError): bounded_bytes({'large':'x'*20})


def test_native_and_derived_fixtures(tmp_path,monkeypatch):
    from test_gazebo_sensors import samples
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'simulation/gazebo-smoke'))
    from realism_replay import normalize
    from aegis.simulation.sensor_realism import transform
    streams,_=samples()
    raw=dict(schema_version=1,evidence_kind='real_gazebo_transport',success=True,cleanup_ok=True,evidence=dict(sensor_samples=streams))
    cfg=ImpairmentConfig(seed=75)
    derived=dict(schema_version=1,artifact_kind='offline_derived_sensor_replay',source_sha256='a'*64,config=asdict(cfg),observations=[asdict(d) for d in transform(normalize(streams,'a'*64),cfg)])
    for kind,value in [('raw',raw),('impaired',derived)]:
        path=tmp_path/kind;path.write_bytes(encode(value))
        out=json.loads(replay(path,input_kind=kind,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),domain='sim',evaluation_ns='2000000000',stale_after_ns=100000000))
        assert not out['rejected']
        assert all(out['summary'][s]['count']==len(streams[s]) for s in streams)
        assert all(r['record']['delivery'] is None for r in out['observations']) if kind=='raw' else all(r['record']['config_sha256'] for r in out['observations'])


def test_lossless_time_and_unknown_fields(tmp_path):
    s=sample(t=2**64-1)
    assert load_contract(SensorTelemetry,encode(asdict(s))).acquisition.value_ns==str(2**64-1)
    value=asdict(s);value['extra']=True
    with pytest.raises(SimulationError): load_contract(SensorTelemetry,encode(value))
    for timestamp in ('01',str(2**64),'-1'):
        with pytest.raises(SimulationError): Timestamp(value_ns=timestamp,domain='sim')


def test_optional_quantities_and_vectors():
    imu=sample('imu')
    angular=tuple(Field(name='angular_velocity.'+a,value=0.,unit='rad/s') for a in 'xyz')
    orientation=tuple(Field(name='orientation.'+a,value=float(a=='w'),unit='1') for a in 'xyzw')
    assert replace(imu,values=imu.values+angular+orientation)
    with pytest.raises(SimulationError): replace(imu,values=imu.values[:1])
    baro=sample()
    assert replace(baro,values=baro.values+(Field(name='derived_altitude',value=1.,unit='m'),))
    assert 'derived_altitude' not in [v.name for v in baro.values]


def test_delivery_regression_and_threshold():
    a=replace(sample(),delivery=Timestamp(value_ns='30',domain='sim'))
    b=replace(sample(t=1),delivery=Timestamp(value_ns='20',domain='sim'))
    out=inspect((a,b),Timestamp(value_ns='30',domain='sim'),29)
    assert out['anomalies']==[dict(index=1,code='DELIVERY_REGRESSION')]
    assert out['summary']['barometer']['freshness']=='fresh'


def derived_fixture(drop=False):
    from test_sensor_realism import sample as native_sample
    from aegis.simulation.sensor_realism import transform, SensorPolicy
    cfg = ImpairmentConfig(seed=75, policies=(SensorPolicy(sensor='barometer', dropout_probability=1.0 if drop else 0.0),))
    return dict(schema_version=1, artifact_kind='offline_derived_sensor_replay', source_sha256='a'*64,
                config=asdict(cfg), observations=[asdict(row) for row in transform((native_sample(),), cfg)])


def replay_fixture(tmp_path, document, kind='impaired'):
    path = tmp_path / 'fixture.json'
    before = encode(document)
    path.write_bytes(before)
    result = replay(path, input_kind=kind, source_sha256=hashlib.sha256(before).hexdigest(),
                    domain='sim', evaluation_ns='100', stale_after_ns=5)
    assert path.read_bytes() == before
    assert encode(document) == before
    return json.loads(result)


def test_dropout_diagnostics_and_synthetic_example(tmp_path):
    out = replay_fixture(tmp_path, derived_fixture(drop=True))
    assert not out['rejected']
    assert out['source_diagnostics'][0]['reasons'] == ['MISSING_OBSERVATION']
    assert out['observations'][0]['record']['values'] is None
    assert out['observations'][0]['freshness'] == 'missing'
    assert out['summary']['barometer']['latest_acquisition_ns'] is None
    example = json.loads((Path(__file__).resolve().parents[1] / 'examples/sensor_telemetry_example.json').read_bytes())
    assert example['example_kind'] == 'synthetic_fixture'
    assert 'not Gazebo or hardware evidence' in example['evidence_attestation']


@pytest.mark.parametrize('change', [
    {'config_version': True}, {'config_version': 1.0}, {'config_version': 2},
    {'extra': 0}, {'values': None}, {'diagnostics': ['MISSING_OBSERVATION']},
    {'diagnostics': ['UNKNOWN']}, {'diagnostics': ['STALE', 'STALE']},
    {'values': [{}]*11}, {'transformations': ['x'*1025]},
])
def test_strict_derived_rows(tmp_path, change):
    fixture = derived_fixture()
    fixture['observations'][0].update(change)
    out = replay_fixture(tmp_path, fixture)
    assert len(out['rejected']) == 1
    assert not out['observations']


def test_preserved_source_timing_diagnostics(tmp_path):
    fixture = derived_fixture()
    fixture['observations'][0]['diagnostics'] = ['OUT_OF_ORDER', 'STALE']
    out = replay_fixture(tmp_path, fixture)
    assert out['source_diagnostics'][0]['reasons'] == ['OUT_OF_ORDER', 'STALE']
    assert out['observations'][0]['freshness'] == 'stale'


@pytest.mark.parametrize('path', [('source',), ('acquisition',), ('simulation',), ('values', 0)])
@pytest.mark.parametrize('version', [True, 2])
def test_nested_versions(path, version):
    value = json.loads(encode(asdict(sample())))
    nested = value
    for part in path:
        nested = nested[part]
    nested['schema_version'] = version
    with pytest.raises(SimulationError):
        load_contract(SensorTelemetry, encode(value))


def test_bounds_and_diagnostic_indices(tmp_path):
    for value in (1000000.1, -1000000.1):
        with pytest.raises(SimulationError): Field(name='pressure', value=value, unit='Pa')
    with pytest.raises(SimulationError): replace(sample().source, session_id='x'*129)
    rows = [{}, asdict(sample(t=10)), asdict(sample(t=0)), asdict(sample(t=10))]
    out = replay_fixture(tmp_path, dict(schema_version=1, observations=rows), 'telemetry')
    assert [d['index'] for d in out['rejected']] == [0, 3]
    assert out['anomalies'] == [dict(index=2, code='OUT_OF_ORDER')]
    assert [o['record']['acquisition']['value_ns'] for o in out['observations']] == ['0', '10']
    with pytest.raises(SimulationError):
        replay_fixture(tmp_path, dict(schema_version=1, observations=[{}]*1025), 'telemetry')


def test_cli_rejects_without_partial_output(tmp_path):
    import os
    import subprocess
    import sys
    path = tmp_path / 'bad.json'
    path.write_bytes(b'{')
    command = [sys.executable, '-B', 'examples/sensor_telemetry_replay.py', str(path), '--input-kind', 'telemetry',
               '--source-sha256', hashlib.sha256(b'{').hexdigest(), '--domain', 'sim',
               '--evaluation-ns', '0', '--stale-after-ns', '0']
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(command, cwd=root, env=dict(os.environ, PYTHONPATH=str(root/'src')),
                            capture_output=True, check=False, timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)['rejected'] is True


def test_total_order_for_multiple_sessions():
    first = sample()
    second = replace(first, source=replace(first.source, session_id='another-fixture'))
    evaluation = Timestamp(value_ns='0', domain='sim')
    a = inspect((first, second), evaluation, 0)
    b = inspect((second, first), evaluation, 0)
    assert a == b


def test_canonical_configuration_required():
    config = asdict(ImpairmentConfig(seed=75))
    with pytest.raises(SimulationError):
        replace(sample(), origin='impaired', config_json=json.dumps(config),
                config_sha256=hashlib.sha256(encode(config)).hexdigest(), seed_identifier='75')
