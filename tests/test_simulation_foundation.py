"""Simulation foundation tests use declared test fixtures, never physics/hardware."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys

import pytest
from aegis.simulation import adapter as a
from aegis.simulation import contracts as c
from aegis.simulation import recording as r
from aegis.simulation import session as s
from aegis.simulation.scenarios import load_scenario, read_scenario, scenario_digest
from aegis.simulation.service import request_transition
from aegis.simulation.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'examples/simulation/virtual-hover.json'


@pytest.fixture
def scenario():
    return read_scenario(SCENARIO)


def wall(value='1700000000000000000'):
    return c.Timestamp(value_ns=value, domain='wall:unix')


def stamp(session, value='0'):
    return c.Timestamp(value_ns=value, domain=session.simulation_clock.domain)


def created(scenario):
    return s.create_session(scenario, 'test-session', wall())


def running(scenario):
    session = created(scenario)
    session = s.transition(session, 'ready', stamp(session), wall(), verification='test-only:prepared')
    return s.transition(session, 'running', stamp(session), wall(), verification='test-only:running')


def record(scenario, session, sequence=0, **changes):
    source = c.SourceIdentity(session_id=session.session_id, vehicle_id='virtual-quad-01', component_id='test-component', source_id='test-source', data_origin='simulated', clock_domain=session.simulation_clock.domain)
    provenance = c.Provenance(scenario_sha256=scenario_digest(scenario), producer='unit-test-only', reference_id='test-reference', original_origin='simulated', simulator_version=None, autopilot_version=None)
    # This explicitly synthetic unit-test value is not a measurement from a simulator.
    result = c.Record(sequence=sequence, source=source, simulation_time=stamp(session), receipt_time=wall(),
                      measurement=c.Measurement(quantity='battery_fraction', values=(0.0,), unit='1', frame=None),
                      provenance=provenance, diagnostics=())
    return replace(result, **changes)


def recording(scenario, session, records=None, **changes):
    value = c.Recording(session_id=session.session_id, scenario_id=scenario.scenario_id,
                        scenario_sha256=scenario_digest(scenario), data_origin='simulated',
                        records=(record(scenario, session),) if records is None else records)
    return replace(value, **changes)


def test_scenario_deterministic_closed_owned_and_content_addressed(scenario):
    data = json.loads(SCENARIO.read_bytes())
    before = json.dumps(data)
    loaded = load_scenario(json.dumps(data).encode())
    assert loaded == scenario and json.dumps(data) == before
    assert c.load_contract(c.Scenario, c.canonical_bytes(scenario)) == scenario
    assert scenario_digest(loaded) == scenario_digest(load_scenario(json.dumps(data, sort_keys=True).encode()))
    data['vehicles'][0]['vehicle_id'] = 'modified'
    assert loaded.vehicles[0].vehicle_id == 'virtual-quad-01'
    with pytest.raises(FrozenInstanceError):
        loaded.seed = 9
    assert scenario_digest(replace(scenario, seed=9)) != scenario_digest(scenario)
    assert scenario.data_origin == 'simulated' and scenario.frame_mapping == 'not_implemented'


@pytest.mark.parametrize('case', ['version', 'bool_version', 'extra', 'missing', 'runtime', 'origin', 'duration', 'step', 'seed', 'duplicate', 'position', 'frame', 'units', 'model', 'count', 'no_aerial', 'altitude'])
def test_invalid_scenarios_fail_closed(case):
    doc = json.loads(SCENARIO.read_bytes())
    if case == 'version': doc['schema_version'] = 2
    elif case == 'bool_version': doc['schema_version'] = True
    elif case == 'extra': doc['hardware_endpoint'] = 'forbidden'
    elif case == 'missing': del doc['provenance']
    elif case == 'runtime': doc['versions']['simulator_version'] = '99.0.0'
    elif case == 'origin': doc['data_origin'] = 'real'
    elif case == 'duration': doc['duration_ns'] = '120000000001'
    elif case == 'step': doc['step_ns'] = '0'
    elif case == 'seed': doc['seed'] = True
    elif case == 'duplicate': doc['vehicles'][1]['vehicle_id'] = doc['vehicles'][0]['vehicle_id']
    elif case == 'position': doc['vehicles'][0]['initial_position_m'] = [999.0, 0.0, 0.0]
    elif case == 'frame': doc['environment']['world_frame'] = 'WGS84'
    elif case == 'units': doc['environment']['length_unit'] = 'feet'
    elif case == 'model': doc['vehicles'][0]['model'] = 'physical-drone'
    elif case == 'count': doc['vehicles'] = doc['vehicles'] * 5
    elif case == 'no_aerial': doc['vehicles'] = [doc['vehicles'][1]]
    else: doc['hover_altitude_m'] = 4.0
    with pytest.raises(c.SimulationError) as error:
        load_scenario(json.dumps(doc).encode())
    assert error.value.diagnostic.severity == 'error'


@pytest.mark.parametrize('value', ['0', '9007199254740993', str(c.UINT64_MAX)])
def test_timestamp_exact_uint64_roundtrip(value):
    time = c.Timestamp(value_ns=value, domain='test:clock')
    assert c.load_contract(c.Timestamp, c.canonical_bytes(time)) == time
    assert c.document(time)['value_ns'] == value


@pytest.mark.parametrize('value', [0, True, 1.0, '-1', '+1', '01', '1e9', ' 1', str(c.UINT64_MAX + 1), '9' * 21])
def test_invalid_timestamp_representation(value):
    with pytest.raises(c.SimulationError):
        c.Timestamp(value_ns=value, domain='test:clock')


@pytest.mark.parametrize('data', [b'{', b'[]', b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}', b'\xff', b'[' * 2000, b' ' * (c.MAX_BYTES + 1)])
def test_invalid_or_unbounded_json(data):
    with pytest.raises(c.SimulationError):
        load_scenario(data)


def test_lifecycle_all_states_and_clock_separation(scenario):
    initial = created(scenario)
    assert initial.state == 'created' and initial.simulation_time.value_ns == '0'
    session = running(scenario)
    session = s.advance(session, stamp(session, '10000000'), wall('1'), verification='test-only:tick')
    assert session.wall_time.value_ns == '1'  # Wall adjustment does not drive or reorder simulation.
    assert session.time_verification == 'test-only:tick'
    paused = s.transition(session, 'paused', stamp(session, '10000000'), wall('0'), verification='test-only:paused')
    resumed = s.transition(paused, 'running', paused.simulation_time, wall(), verification='test-only:resumed')
    done = s.transition(resumed, 'completed', resumed.simulation_time, wall(), verification='test-only:done')
    assert [t.state for t in done.history] == ['created', 'ready', 'running', 'paused', 'running', 'completed']
    assert c.load_contract(c.Session, c.canonical_bytes(done)) == done
    assert initial.state == 'created' and initial.simulation_time.value_ns == '0'
    with pytest.raises(c.SimulationError):
        s.transition(done, 'running', done.simulation_time, wall(), verification='not-allowed')


@pytest.mark.parametrize('case', ['skip', 'no_verification', 'wrong_sim_clock', 'wrong_wall_clock', 'off_step', 'past_duration', 'regression', 'paused_advance', 'ready_advance', 'direct_mutation'])
def test_lifecycle_invalid_or_unverified_transitions(scenario, case):
    session = running(scenario)
    with pytest.raises(c.SimulationError):
        if case == 'skip': s.transition(created(scenario), 'running', stamp(session), wall(), verification='test-only')
        elif case == 'no_verification': s.transition(session, 'paused', stamp(session), wall())
        elif case == 'wrong_sim_clock': s.advance(session, wall('0'), wall(), verification='test-only')
        elif case == 'wrong_wall_clock': s.advance(session, stamp(session), stamp(session), verification='test-only')
        elif case == 'off_step': s.advance(session, stamp(session, '1'), wall(), verification='test-only')
        elif case == 'past_duration': s.advance(session, stamp(session, '10010000000'), wall(), verification='test-only')
        elif case == 'regression':
            later = s.advance(session, stamp(session, '10000000'), wall(), verification='test-only')
            s.advance(later, stamp(session), wall(), verification='test-only')
        elif case == 'ready_advance': s.transition(created(scenario), 'ready', stamp(session, '10000000'), wall(), verification='test-only')
        else:
            paused = s.transition(session, 'paused', stamp(session), wall(), verification='test-only')
            if case == 'paused_advance': s.advance(paused, stamp(session, '10000000'), wall(), verification='test-only')
            else: replace(paused, simulation_time=stamp(session, '10000000'))


class TestOnlyAdapter:
    __test__ = False
    def probe(self, scenario):
        return a.Availability(state='available', capabilities=('prepare', 'start', 'pause', 'resume', 'complete'), dependencies=(), verification='unit-test-only:not-a-runtime', diagnostics=())

    def observe_transition(self, scenario, session, target):
        return a.RuntimeObservation(session_id=session.session_id, scenario_sha256=session.scenario_sha256, state=target,
                                    simulation_time=session.simulation_time, simulator_version=scenario.versions.simulator_version,
                                    autopilot_version=scenario.versions.autopilot_version, verification='unit-test-only:not-a-runtime')


def test_service_requires_verified_adapter_and_preserves_inputs(scenario):
    initial = created(scenario)
    session = initial
    for target in ('ready', 'running', 'paused', 'running', 'completed'):
        session = request_transition(scenario, session, TestOnlyAdapter(), target, wall())
        assert session.state == target
    assert initial.state == 'created'
    with pytest.raises(c.SimulationError):
        request_transition(scenario, session, TestOnlyAdapter(), 'running', wall())


@pytest.mark.parametrize('case', ['unavailable', 'timeout', 'oserror', 'wrong_session', 'wrong_clock', 'wrong_version', 'wrong_state', 'bad_contract'])
def test_service_adapter_failures_are_failed_not_running(scenario, case):
    class Broken(TestOnlyAdapter):
        def observe_transition(self, scenario, session, target):
            if case == 'timeout': raise TimeoutError('test timeout')
            if case == 'oserror': raise OSError('test failure')
            if case == 'bad_contract': return object()
            result = super().observe_transition(scenario, session, target)
            if case == 'wrong_session': return replace(result, session_id='unrelated')
            if case == 'wrong_clock': return replace(result, simulation_time=wall('0'))
            if case == 'wrong_version': return replace(result, simulator_version='99.0.0')
            return replace(result, state='running')
    initial = created(scenario)
    adapter = a.GazeboPx4Adapter() if case == 'unavailable' else Broken()
    failed = request_transition(scenario, initial, adapter, 'ready', wall())
    assert failed.state == 'failed' and failed.simulation_time == initial.simulation_time
    assert failed.history[-1].diagnostic.code == ('ADAPTER_UNAVAILABLE' if case == 'unavailable' else 'ADAPTER_FAILED')
    assert initial.state == 'created'


def test_dependency_discovery_never_executes_or_attests_runtime(scenario, monkeypatch):
    monkeypatch.setattr(a.shutil, 'which', lambda command: f'/test-only/{command}')
    report = a.GazeboPx4Adapter().probe(scenario)
    assert report.state == 'unavailable' and report.capabilities == ()
    assert all(d.status == 'located_unverified' and d.version is None for d in report.dependencies)
    assert report.verification is None
    with pytest.raises(a.AdapterUnavailable):
        a.GazeboPx4Adapter().observe_transition(scenario, created(scenario), 'ready')
    with pytest.raises(a.AdapterUnavailable):
        a.GazeboPx4Adapter().read_recording(scenario, created(scenario))


@pytest.mark.parametrize('error', [False, True])
def test_missing_or_failed_dependency_probe(scenario, monkeypatch, error):
    def locate(command):
        if error: raise OSError('test probe denied')
        return None
    monkeypatch.setattr(a.shutil, 'which', locate)
    report = a.GazeboPx4Adapter().probe(scenario)
    assert report.state == 'unavailable'
    assert all(d.status == ('probe_failed' if error else 'not_found') for d in report.dependencies)


def test_recording_roundtrip_immutability_null_versions_and_zero(scenario):
    session = running(scenario)
    value = recording(scenario, session)
    loaded = r.load_recording(c.canonical_bytes(value), scenario, session)
    assert loaded == value and loaded.records[0].measurement.values == (0.0,)
    assert loaded.records[0].provenance.simulator_version is None
    assert loaded.records[0].simulation_time.domain != loaded.records[0].receipt_time.domain
    doc = c.document(loaded); doc['records'][0]['source']['source_id'] = 'modified'
    assert loaded.records[0].source.source_id == 'test-source'
    with pytest.raises(FrozenInstanceError):
        loaded.records[0].sequence = 5
    assert r.recording_diagnostics(c.canonical_bytes(value), scenario, session) == ()


def test_explicit_missing_measurement_retains_unavailable_diagnostic(scenario):
    session = running(scenario)
    missing = replace(record(scenario, session), measurement=None, diagnostics=(c.Diagnostic(code='MISSING_MEASUREMENT', path='measurement', explanation='No test measurement supplied', severity='unavailable'),))
    loaded = r.load_recording(c.canonical_bytes(recording(scenario, session, (missing,))), scenario, session)
    assert loaded.records[0].measurement is None and loaded.records[0].diagnostics == missing.diagnostics
    with pytest.raises(c.SimulationError):
        replace(missing, diagnostics=())


@pytest.mark.parametrize('case', ['session', 'scenario', 'digest', 'vehicle', 'clock', 'receipt', 'version', 'origin', 'original_origin', 'order', 'future', 'regression', 'too_many', 'unknown_field', 'no_provenance'])
def test_recording_rejects_inconsistent_or_unbounded_inputs(scenario, case):
    session = s.advance(running(scenario), stamp(created(scenario), '20000000'), wall(), verification='test-only')
    doc = c.document(recording(scenario, session))
    rec = doc['records'][0]
    if case == 'session': doc['session_id'] = 'different'
    elif case == 'scenario': doc['scenario_id'] = 'different'
    elif case == 'digest': doc['scenario_sha256'] = 'a' * 64
    elif case == 'vehicle': rec['source']['vehicle_id'] = 'unknown'
    elif case == 'clock': rec['simulation_time']['domain'] = 'different-clock'
    elif case == 'receipt': rec['receipt_time']['domain'] = rec['simulation_time']['domain']
    elif case == 'version': rec['provenance']['simulator_version'] = '99.0.0'
    elif case == 'origin': doc['data_origin'] = 'real'
    elif case == 'original_origin': rec['provenance']['original_origin'] = 'real'
    elif case == 'order': rec['sequence'] = 2
    elif case == 'future': rec['simulation_time']['value_ns'] = '30000000'
    elif case == 'regression':
        rec['simulation_time']['value_ns'] = '10000000'
        second = json.loads(json.dumps(rec)); second['sequence'] = 1; second['simulation_time']['value_ns'] = '0'; doc['records'].append(second)
    elif case == 'too_many': doc['records'] = [rec] * 257
    elif case == 'unknown_field': rec['source']['device_endpoint'] = 'forbidden'
    else: del rec['provenance']
    data = json.dumps(doc).encode()
    with pytest.raises(c.SimulationError): r.load_recording(data, scenario, session)
    diagnostics = r.recording_diagnostics(data, scenario, session)
    assert len(diagnostics) == 1 and diagnostics[0].severity == 'error'


def test_independent_source_order_and_recorded_origin_are_explicit(scenario):
    session = s.advance(running(scenario), stamp(created(scenario), '20000000'), wall(), verification='test-only')
    first = record(scenario, session, simulation_time=stamp(session, '10000000'))
    second = record(scenario, session, 1, receipt_time=wall('1'))
    second = replace(second, source=replace(second.source, component_id='other-component'))
    batch = recording(scenario, session, (first, second))
    assert r.load_recording(c.canonical_bytes(batch), scenario, session).records == (first, second)
    recorded = replace(batch, data_origin='recorded', records=tuple(replace(rec, source=replace(rec.source, data_origin='recorded')) for rec in batch.records))
    assert r.load_recording(c.canonical_bytes(recorded), scenario, session).data_origin == 'recorded'
    assert recorded.records[0].provenance.original_origin == 'simulated'


@pytest.mark.parametrize('case', ['wrong_unit', 'no_frame', 'vector_size', 'nan', 'battery_range', 'body_position'])
def test_measurements_require_exact_units_frames_and_finite_values(case):
    values = dict(quantity='position', values=(0.0, 0.0, 0.0), unit='m', frame='world_enu')
    if case == 'wrong_unit': values['unit'] = 'm/s'
    elif case == 'no_frame': values['frame'] = None
    elif case == 'vector_size': values['values'] = (0.0,)
    elif case == 'nan': values['values'] = (float('nan'), 0.0, 0.0)
    elif case == 'body_position': values['frame'] = 'body_flu'
    else: values.update(quantity='battery_fraction', values=(1.1,), unit='1', frame=None)
    with pytest.raises(c.SimulationError): c.Measurement(**values)


def test_cli_validates_reports_unavailable_and_handles_errors(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(a.shutil, 'which', lambda _: None)
    assert main(['--scenario', str(SCENARIO), '--detect-dependencies']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['physics_running'] is False and report['adapter']['state'] == 'unavailable'
    assert main(['--scenario', str(tmp_path / 'missing.json')]) == 2
    assert json.loads(capsys.readouterr().err)['code'] == 'SCENARIO_IO'
    bad = tmp_path / 'invalid.json'; bad.write_bytes(b'{}')
    assert main(['--scenario', str(bad)]) == 2
    assert json.loads(capsys.readouterr().err)['severity'] == 'error'


def test_probe_and_default_failure_have_no_hardware_network_or_process_access(scenario, monkeypatch):
    import socket
    import builtins
    def forbidden(*args, **kwargs): raise AssertionError('I/O forbidden in simulation foundation')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(builtins, 'open', forbidden)
    monkeypatch.setattr(a.shutil, 'which', lambda _: None)
    assert a.GazeboPx4Adapter().probe(scenario).state == 'unavailable'
    assert request_transition(scenario, created(scenario), a.GazeboPx4Adapter(), 'ready', wall()).state == 'failed'
    package = ROOT / 'src/aegis/simulation'
    for path in package.glob('*.py'):
        text = path.read_text()
        for forbidden_import in ('cv2', 'mavsdk', 'pymavlink', 'serial', 'aegis.api', 'aegis.platform', 'subprocess', 'socket'):
            assert f'import {forbidden_import}' not in text and f'from {forbidden_import}' not in text


def test_imports_are_inert_in_a_fresh_process():
    script = """
import builtins, socket, subprocess, sys

def forbidden(*args, **kwargs):
    raise AssertionError('hardware/network/process access during import')

builtins.open = forbidden
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
import aegis.simulation.adapter, aegis.simulation.contracts
import aegis.simulation.scenarios, aegis.simulation.recording
import aegis.simulation.session, aegis.simulation.service
assert not any(name in sys.modules for name in ('cv2', 'serial', 'aegis.api', 'aegis.platform.monitoring'))
"""
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


@pytest.mark.parametrize('field,value', [('step_ns', '1000000'), ('duration_ns', '20000000000')])
def test_scenario_binding_rejects_session_parameter_tampering_before_adapter_calls(scenario, field, value):
    altered = replace(created(scenario), **{field: value})
    class NeverCalled(TestOnlyAdapter):
        def probe(self, scenario): raise AssertionError('invalid session reached adapter')
    with pytest.raises(c.SimulationError, match='PROVENANCE'):
        request_transition(scenario, altered, NeverCalled(), 'ready', wall())
    with pytest.raises(c.SimulationError, match='PROVENANCE'):
        r.validate_recording(recording(scenario, altered, ()), scenario, altered)


@pytest.mark.parametrize('case', ['present_but_missing', 'fatal'])
def test_recording_diagnostics_cannot_contradict_measurement_validity(scenario, case):
    good = record(scenario, created(scenario))
    diagnostic = c.Diagnostic(code='MISSING_MEASUREMENT' if case == 'present_but_missing' else 'INVALID_MEASUREMENT', path='measurement', explanation='Explicit test diagnostic', severity='unavailable' if case == 'present_but_missing' else 'error')
    with pytest.raises(c.SimulationError):
        replace(good, diagnostics=(diagnostic,))


def test_maximum_recording_size_empty_and_uint64_wall_time(scenario):
    session = created(scenario)
    records = tuple(record(scenario, session, index, receipt_time=wall(str(c.UINT64_MAX))) for index in range(256))
    value = recording(scenario, session, records)
    assert r.load_recording(c.canonical_bytes(value), scenario, session) == value
    assert r.load_recording(c.canonical_bytes(recording(scenario, session, ())), scenario, session).records == ()


def test_bounded_history_rejects_before_adapter_work(scenario):
    session = running(scenario)
    while len(session.history) < 128:
        target = 'paused' if session.state == 'running' else 'running'
        session = s.transition(session, target, session.simulation_time, wall(), verification='test-only:bounded-history')
    class NeverCalled(TestOnlyAdapter):
        def probe(self, scenario): raise AssertionError('history overflow reached adapter')
    target = 'paused' if session.state == 'running' else 'running'
    with pytest.raises(c.SimulationError, match='BOUND'):
        request_transition(scenario, session, NeverCalled(), target, wall())


def test_clock_identity_epochs_and_unknown_closed_fields(scenario):
    with pytest.raises(c.SimulationError):
        c.Clock(domain='x', kind='wall', unit='ns', epoch='session_start')
    with pytest.raises(c.SimulationError):
        s.create_session(scenario, 'wrong-clock', c.Timestamp(value_ns='0', domain='sim:wrong-clock'))
    value = created(scenario)
    with pytest.raises(c.SimulationError):
        replace(value, wall_clock=replace(value.wall_clock, domain=value.simulation_clock.domain))
    doc = c.document(value); doc['history'][0]['extra'] = 'unexpected'
    with pytest.raises(c.SimulationError):
        c.load_contract(c.Session, json.dumps(doc).encode())
