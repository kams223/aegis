"""Preparation tests use synthetic observations, never evidence of executed physics."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'simulation/gazebo-smoke'


def load_module(name):
    spec = importlib.util.spec_from_file_location('aegis_smoke_test_' + name, RUNTIME / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke(monkeypatch):
    module = load_module('smoke')
    monkeypatch.setitem(sys.modules, 'smoke', module)
    return module


@pytest.fixture
def profile(smoke):
    return smoke.load_json(RUNTIME / 'profile.json')


@pytest.fixture
def inventory(smoke):
    return smoke.load_json(RUNTIME / 'inputs.json')


def test_profile_world_and_deterministic_loading(smoke, profile):
    smoke.validate_profile(profile, RUNTIME / 'gravity.sdf')
    assert profile == smoke.load_json(RUNTIME / 'profile.json')
    assert profile['phase74a_compatible'] is False
    assert '8.15.0' == profile['expected_gazebo_version']
    assert profile['base_image'] == smoke.BASE


@pytest.mark.parametrize('key,value', [
    ('schema_version', True), ('schema_version', 2), ('status', 'verified'),
    ('expected_gazebo_version', '8.3.0'), ('phase74a_gazebo_version', '8.15.0'),
    ('phase74a_compatible', True), ('minimum_available_memory_bytes', 0),
    ('build_minimum_available_memory_bytes', 0), ('runtime_memory_limit_bytes', 2**40),
    ('cpus', True), ('pids_limit', 0), ('base_image', 'ubuntu:24.04'),
    ('world_sha256', '0' * 64), ('timeout_seconds', 3600), ('iterations', 0),
])
def test_profile_cannot_silently_change_identity_or_limits(smoke, profile, key, value):
    profile[key] = value
    with pytest.raises(ValueError):
        smoke.validate_profile(profile, RUNTIME / 'gravity.sdf')


def test_modified_world_rejected_even_if_manifest_rehashed(smoke, profile, tmp_path):
    world = tmp_path / 'gravity.sdf'
    world.write_text((RUNTIME / 'gravity.sdf').read_text().replace('-9.81', '0'))
    profile['world_sha256'] = smoke.digest(world)
    with pytest.raises(ValueError, match='Unrecognized'):
        smoke.validate_profile(profile, world)


def test_world_is_self_contained_non_actuated():
    root = ET.parse(RUNTIME / 'gravity.sdf').getroot()
    world = root.find('world')
    assert world.attrib['name'] == 'aegis_gravity'
    assert world.findtext('gravity') == '0 0 -9.81'
    assert world.findtext('physics/max_step_size') == '0.001'
    assert len(world.findall('model')) == 2
    assert world.find("model[@name='ground']/static").text == 'true'
    box = world.find("model[@name='falling_box']")
    assert box.findtext('pose') == '0 0 1 0 0 0'
    assert box.findtext('link/inertial/mass') == '1'
    assert box.findtext('link/collision/geometry/box/size') == '0.2 0.2 0.2'
    assert all(not list(root.iter(tag)) for tag in ('include', 'uri', 'joint', 'sensor', 'actor'))
    assert {p.attrib['filename'] for p in root.iter('plugin')} == {
        'gz-sim-physics-system', 'gz-sim-pose-publisher-system'}


@pytest.mark.parametrize('text', ['8.3.0', '8.15.0\n8.3.0', '8.15', '', '18.15.0'])
def test_version_mismatch_or_missing_rejected(smoke, text):
    with pytest.raises(ValueError):
        smoke.check_version(text)


def test_exact_version(smoke):
    smoke.check_version('8.15.0\n')


def test_resource_policy_is_specific_to_smoke(smoke, profile):
    data = (2 * smoke.GIB, 256 * smoke.MIB, 5 * smoke.GIB, 1)
    assert smoke.resource_blockers(profile, *data) == []
    assert smoke.resource_blockers(profile, *data, build=True) == ['available_memory']
    assert smoke.resource_blockers(profile, 3 * smoke.GIB, *data[1:], build=True) == []
    full = json.loads((ROOT / 'simulation/runtime/profile.json').read_text())
    assert full['minimum_available_memory_bytes'] == 3 * smoke.GIB
    assert full['minimum_free_disk_bytes'] == 30 * smoke.GIB


@pytest.mark.parametrize('index,expected', [(0, 'available_memory'), (1, 'free_swap'), (2, 'backing_disk'), (3, 'cpu')])
def test_resource_boundaries(smoke, profile, index, expected):
    data = [2 * smoke.GIB, 256 * smoke.MIB, 5 * smoke.GIB, 1]
    data[index] -= 1
    assert smoke.resource_blockers(profile, *data) == [expected]


@pytest.mark.parametrize('invalid', [True, -1, 1.0, None])
def test_invalid_resource_observation(smoke, profile, invalid):
    with pytest.raises(ValueError):
        smoke.resource_blockers(profile, invalid, 1, 1, 1)


def synthetic_evidence():
    # Deliberately invented test fixture for the checker only; never runtime output.
    poses = []
    for ms in range(20, 2001, 10):
        t = ms / 1000
        poses.append(dict(time_ns=ms * 1000000, frame='aegis_gravity', name='falling_box',
                          x=0.0, y=0.0, z=max(0.1, 1 - 4.905 * t**2)))
    stats = [dict(time_ns=ms * 1000000, iterations=ms) for ms in (100, 500, 1500, 2000)]
    return poses, stats


def test_checker_accepts_synthetic_expected_evidence_without_mutation(smoke):
    poses, stats = synthetic_evidence()
    before = deepcopy((poses, stats))
    assert smoke.analyze(poses, stats, 0, False)['gravity_verified'] is True
    assert (poses, stats) == before


@pytest.mark.parametrize('mutation', [
    'stationary', 'rising', 'wrong_frame', 'wrong_model', 'nan', 'horizontal',
    'missing_pose', 'missing_stats', 'duplicate_time', 'backward_time', 'wrong_step',
    'wrong_ground', 'missing_early', 'missing_late', 'wrong_clock', 'overbound',
])
def test_checker_rejects_insufficient_or_contradictory_evidence(smoke, mutation):
    poses, stats = synthetic_evidence()
    if mutation == 'stationary':
        for row in poses:
            row['z'] = 1.0
    elif mutation == 'rising':
        for row in poses:
            row['z'] = 1 + row['time_ns'] / 1e9
    elif mutation == 'wrong_frame':
        poses[0]['frame'] = 'autopilot_ned'
    elif mutation == 'wrong_model':
        poses[0]['name'] = 'drone'
    elif mutation == 'nan':
        poses[0]['z'] = float('nan')
    elif mutation == 'horizontal':
        poses[0]['x'] = 1.0
    elif mutation == 'missing_pose':
        poses = []
    elif mutation == 'missing_stats':
        stats = []
    elif mutation == 'duplicate_time':
        poses[1]['time_ns'] = poses[0]['time_ns']
    elif mutation == 'backward_time':
        poses.reverse()
    elif mutation == 'wrong_step':
        stats[-1]['iterations'] -= 1
    elif mutation == 'wrong_ground':
        for row in poses:
            if row['time_ns'] >= 1500000000:
                row['z'] = -1
    elif mutation == 'missing_early':
        poses = poses[50:]
    elif mutation == 'missing_late':
        poses = poses[:40]
    elif mutation == 'wrong_clock':
        stats[-1]['time_ns'] = 1700000000000000000
    elif mutation == 'overbound':
        poses *= 4
    with pytest.raises(ValueError):
        smoke.analyze(poses, stats, 0, False)


@pytest.mark.parametrize('code,timed_out', [(1, False), (-9, False), (0, True)])
def test_timeout_and_abnormal_exit_never_pass(smoke, code, timed_out):
    with pytest.raises(ValueError):
        smoke.analyze(*synthetic_evidence(), code, timed_out)


def test_missing_closure_fails_before_file_access(smoke, inventory, tmp_path):
    assert inventory['closure_complete'] is False
    assert inventory['closure_packages'] is None
    assert inventory['signature_and_index_hash_verified'] is True
    with pytest.raises(ValueError, match='incomplete'):
        smoke.verify_bundle(inventory, tmp_path)


@pytest.fixture
def synthetic_bundle(smoke, tmp_path):
    # Fake archive bytes test checksums only, not Debian parsing or authentication.
    path = tmp_path / 'debs'
    path.mkdir()
    archive = path / 'test_1_amd64.deb'
    archive.write_bytes(b'synthetic unit-test archive bytes')
    sha = smoke.digest(archive)
    row = dict(name='test', version='1', architecture='amd64', filename=archive.name,
               sha256=sha, source='ubuntu', release_sha256='a' * 64)
    inventory = dict(base_image=smoke.BASE, closure_complete=True, closure_packages=[row], advertised_packages=[])
    return inventory, tmp_path, archive


def test_archive_checksum_and_exact_file_set(smoke, synthetic_bundle):
    inventory, path, archive = synthetic_bundle
    assert len(smoke.verify_bundle(inventory, path)) == 1
    archive.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='corrupt'):
        smoke.verify_bundle(inventory, path)


@pytest.mark.parametrize('mutation', ['path', 'symlink', 'extra', 'duplicate', 'wrong_base', 'missing_pin', 'architecture', 'hash'])
def test_bundle_rejects_unsafe_or_incomplete_inputs(smoke, synthetic_bundle, mutation):
    inventory, path, archive = synthetic_bundle
    row = inventory['closure_packages'][0]
    if mutation == 'path':
        row['filename'] = '../test.deb'
    elif mutation == 'symlink':
        archive.unlink()
        archive.symlink_to('/etc/passwd')
    elif mutation == 'extra':
        (path / 'debs/extra.deb').write_bytes(b'unknown')
    elif mutation == 'duplicate':
        inventory['closure_packages'].append(dict(row))
    elif mutation == 'wrong_base':
        inventory['base_image'] = 'ubuntu:latest'
    elif mutation == 'missing_pin':
        inventory['advertised_packages'] = [{'Package': 'gz-sim8-cli', 'Version': '8.15.0', 'SHA256': 'b' * 64}]
    elif mutation == 'architecture':
        row['architecture'] = 'arm64'
    elif mutation == 'hash':
        row['release_sha256'] = None
    with pytest.raises(ValueError):
        smoke.verify_bundle(inventory, path)


def test_closed_json_duplicates_and_oversize_rejected(smoke, tmp_path):
    path = tmp_path / 'bad.json'
    for content in ('{"x":1,"x":2}', '{"x":NaN}', ' ' * (smoke.MIB + 1)):
        path.write_text(content)
        with pytest.raises(ValueError):
            smoke.load_json(path)


def test_gated_launcher_never_calls_docker_with_missing_inputs(smoke, monkeypatch, tmp_path, capsys):
    launch = load_module('launch')
    monkeypatch.setattr(launch, 'resources', lambda _: (3 * smoke.GIB, smoke.GIB, 100 * smoke.GIB, 4))
    monkeypatch.setattr(sys, 'argv', ['launch.py', '--disk-path', str(tmp_path), '--launch',
                                    '--image-id', 'sha256:' + 'a' * 64, '--output-dir', str(tmp_path / 'audit')])
    def forbidden(*args, **kwargs):
        raise AssertionError('No Docker command allowed before input gate')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert launch.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result['launched'] is False and result['bundle_verified'] is False
    assert not (tmp_path / 'audit').exists()


def test_default_checker_does_not_execute_processes(smoke, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['smoke.py'])
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected subprocess')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert smoke.main() == 0
    assert json.loads(capsys.readouterr().out)['physics_executed'] is False


def test_container_args_are_isolated_and_bounded(smoke):
    launch = load_module('launch')
    image = 'sha256:' + 'a' * 64
    args = launch.container_args(image, 'aegis-smoke-' + '1' * 32)
    for option in ('--pull=never', '--network=none', '--cap-drop=ALL', '--read-only',
                   '--user=10001:10001', '--memory=1g', '--memory-swap=1g', '--cpus=1',
                   '--pids-limit=128', '--security-opt=no-new-privileges:true', '--log-opt=compress=false'):
        assert option in args
    assert args[-2:] == [image, '--inside']
    assert not any(arg.startswith(('--privileged', '--device', '--volume', '--mount', '--publish')) for arg in args)
    with pytest.raises(ValueError):
        launch.container_args('ubuntu:latest', 'aegis-smoke-' + '1' * 32)
    with pytest.raises(ValueError):
        launch.container_args(image, 'nginx-proxy-manager')


def test_compose_default_never_starts_physics_and_is_isolated():
    config = json.loads((RUNTIME / 'compose.json').read_text())
    assert set(config['services']) == {'smoke'}
    service = config['services']['smoke']
    assert service['network_mode'] == 'none'
    assert service['read_only'] and service['user'] == '10001:10001'
    assert service['cap_drop'] == ['ALL']
    assert service['security_opt'] == ['no-new-privileges:true']
    assert service['mem_limit'] == service['memswap_limit'] == '1g'
    assert service['pids_limit'] == 128 and service['cpus'] == 1.0
    assert service['pull_policy'] == 'never'
    assert service['logging']['options']['compress'] == 'false'
    assert not set(service) & {'ports', 'devices', 'volumes', 'privileged', 'cap_add', 'command'}


def test_prepared_recipe_has_offline_checks_without_px4(smoke):
    recipe = (RUNTIME / 'Dockerfile').read_text()
    assert 'FROM ' + smoke.BASE in recipe
    assert '--network=none' in recipe and '--no-download' in recipe
    assert 'sha256sum --check --strict' in recipe
    assert '--verify-bundle' in recipe and '--verify-installed' in recipe
    assert 'apt-get update' not in recipe and 'git clone' not in recipe
    assert 'CMD []' in recipe


def test_installed_dependency_mismatch_fails(smoke, synthetic_bundle, monkeypatch):
    inventory, _, _ = synthetic_bundle
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout='wrong'))
    with pytest.raises(ValueError, match='Installed dependency version mismatch'):
        smoke.verify_installed(inventory)


def test_cgroup_unlimited_or_missing_fails_before_start(smoke, profile, inventory, monkeypatch):
    def unlimited(_):
        raise ValueError('Unbounded cgroup')
    monkeypatch.setattr(smoke, 'read_cgroup', unlimited)
    with pytest.raises(ValueError, match='Unbounded'):
        smoke.inside(profile, inventory)


def test_process_cleanup_targets_only_owned_group(smoke, monkeypatch):
    signals = []
    monkeypatch.setattr(smoke.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    class Owned:
        pid = 123456
        def wait(self, timeout):
            return 0
    smoke.stop_group(Owned())
    assert signals == [(123456, smoke.signal.SIGTERM), (123456, smoke.signal.SIGKILL)]


@pytest.mark.parametrize('host_timeout', [False, True])
def test_launcher_cleanup_and_retained_audit_without_real_container(smoke, monkeypatch, tmp_path, capsys, host_timeout):
    # Entire Docker interaction is mocked; no Gazebo or container runs in this test.
    launch = load_module('launch')
    image = 'sha256:' + 'a' * 64
    output = tmp_path / 'audit'
    commands = []
    profile = smoke.load_json(RUNTIME / 'profile.json')
    monkeypatch.setattr(launch, 'resources', lambda _: (3 * smoke.GIB, smoke.GIB, 100 * smoke.GIB, 4))
    monkeypatch.setattr(smoke, 'verify_bundle', lambda *a: [])
    monkeypatch.setattr(sys, 'argv', ['launch.py', '--disk-path', str(tmp_path), '--launch',
                                    '--image-id', image, '--output-dir', str(output)])
    def run(args, **kwargs):
        commands.append(args)
        text = ''
        if args[:3] == ['docker', 'image', 'inspect']:
            text = json.dumps([dict(Id=image, Architecture='amd64', Os='linux', Config=dict(Labels={
                'org.aegis.smoke.inputs-sha256': smoke.digest(RUNTIME / 'inputs.json'),
                'org.aegis.smoke.world-sha256': profile['world_sha256'],
                'org.aegis.smoke.gazebo-version': smoke.VERSION}))])
        elif args[:2] == ['docker', 'inspect']:
            text = json.dumps([dict(State=dict(OOMKilled=False, ExitCode=0))])
        return subprocess.CompletedProcess(args, 0, stdout=text)
    class MockAttach:
        returncode = 0
        def __init__(self, args, **kwargs):
            commands.append(args)
            kwargs['stdout'].write(b'{"success":true,"physics_executed":true}\n')
            kwargs['stdout'].flush()
        def poll(self):
            return None if host_timeout else 0
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(subprocess, 'Popen', MockAttach)
    if host_timeout:
        times = iter((0, 60))
        monkeypatch.setattr(launch.time, 'monotonic', lambda: next(times))
    assert launch.main() == (2 if host_timeout else 0)
    report = json.loads(capsys.readouterr().out)
    persisted = json.loads((output / 'report.json').read_text())
    assert persisted == report
    assert report['cleanup_ok'] is True
    assert (output / 'container.log').exists()
    created = next(args for args in commands if args[:2] == ['docker', 'create'])
    name = created[created.index('--name') + 1]
    assert re.fullmatch('aegis-smoke-[0-9a-f]{32}', name)
    assert ['docker', 'stop', '--time', '3', name] in commands
    assert ['docker', 'rm', name] in commands
    assert all('nginx-proxy-manager' not in args and 'duckdns' not in args for args in commands)
    if host_timeout:
        assert 'Host wall timeout' in report['error']
