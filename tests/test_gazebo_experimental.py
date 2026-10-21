"""Synthetic unit fixtures test verdict logic; they are never runtime evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'simulation/gazebo-smoke'


def load(name):
    spec = importlib.util.spec_from_file_location('test_experimental_' + name, RUNTIME / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exp(monkeypatch):
    smoke = load('smoke')
    monkeypatch.setitem(sys.modules, 'smoke', smoke)
    monkeypatch.setitem(sys.modules, 'launch', load('launch'))
    return load('experimental')


def observations():
    poses = [dict(time_ns=ms * 1000000, frame='aegis_gravity', name='falling_box',
                  x=0.0, y=0.0, z=max(0.1, 1-4.905*(ms/1000)**2)) for ms in range(10,2001,10)]
    clocks = [dict(time_ns=0, iterations=0, paused=True)] + [
        dict(time_ns=ms*1000000, iterations=ms, paused=False) for ms in (100,500,1500,2000)]
    contacts = [dict(time_ns=450000000, collision1='ground::plane::ground_collision',
                     collision2='falling_box::body::box_collision', positions=[dict(x=0.0,y=0.0,z=0.0)])]
    return poses, clocks, contacts


def test_separate_pinned_profile(exp):
    p = exp.profile()
    assert p['image'] == exp.IMAGE
    assert p['phase74a_compatible'] is False
    assert p['memory_bytes'] <= 2 * 1024**3 and p['cpus'] == 1 and p['pids'] == 128
    old = json.loads((ROOT/'examples/simulation/virtual-hover.json').read_text())
    assert old['versions']['simulator_version'] == '8.3.0'


def test_synthetic_verdict_does_not_claim_real_execution(exp):
    result = exp.verdict(*observations(), 0, False)
    assert result['passed'] and result['ground_contact'] and result['settled']
    assert 'evidence_kind' not in result


@pytest.mark.parametrize('mutation', ['no_pose','no_clock','no_contact','wrong_contact','late_initial',
                                    'unstable','clock_regression','contact_nan','wrong_contact_height','exit','timeout'])
def test_no_success_from_startup_or_incomplete_evidence(exp, mutation):
    poses, clocks, contacts = observations()
    code, timeout = 0, False
    if mutation == 'no_pose':
        poses = []
    elif mutation == 'no_clock':
        clocks = []
    elif mutation == 'no_contact':
        contacts = []
    elif mutation == 'wrong_contact':
        contacts[0]['collision1'] = 'other_collision'
    elif mutation == 'late_initial':
        poses = poses[10:]
    elif mutation == 'unstable':
        for n,row in enumerate(poses):
            if row['time_ns'] >= 1500000000:
                row['z'] += .003 * (n%2)
    elif mutation == 'clock_regression':
        clocks.reverse()
    elif mutation == 'contact_nan':
        contacts[0]['positions'][0]['z'] = float('nan')
    elif mutation == 'wrong_contact_height':
        contacts[0]['positions'][0]['z'] = 1.0
    elif mutation == 'exit':
        code = -9
    elif mutation == 'timeout':
        timeout = True
    with pytest.raises(ValueError):
        exp.verdict(poses, clocks, contacts, code, timeout)


def test_default_is_read_only(exp, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['experimental.py'])
    def forbidden(*a, **kw):
        raise AssertionError('No process permitted')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert exp.main() == 0
    assert json.loads(capsys.readouterr().out)['image'] == exp.IMAGE


def test_experimental_world_adds_only_observation_sensor():
    import xml.etree.ElementTree as ET
    root = ET.parse(RUNTIME/'experimental-gravity.sdf').getroot()
    assert len(list(root.iter('model'))) == 2
    assert all(not list(root.iter(tag)) for tag in ('joint','actor','include','uri'))
    sensors = list(root.iter('sensor'))
    assert len(sensors) == 1 and sensors[0].attrib['type'] == 'contact'
    assert sensors[0].findtext('contact/collision') == 'box_collision'
    assert {p.attrib['filename'] for p in root.iter('plugin')} == {
        'gz-sim-contact-system','gz-sim-physics-system','gz-sim-pose-publisher-system'}


def test_experimental_launcher_handles_observed_runtime_interfaces():
    source = (RUNTIME/'experimental.py').read_text()
    assert '/world/aegis_gravity/model/falling_box/link/body/sensor/ground_contact/contact' in source
    assert "'compress=false'" in source
    assert 'target=/opt/aegis,readonly' in source
    assert "smoke.read_cgroup('memory.peak')" in source
    assert "'real_gazebo_transport'" in source
