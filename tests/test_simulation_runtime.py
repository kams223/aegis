"""Offline runtime identity, failure boundaries and closed container policy."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from aegis.simulation.contracts import SimulationError, canonical_bytes, load_contract
from aegis.simulation.runtime import (
    PX4_COMMIT, RuntimeProfile, check_observations, check_scenario,
    read_profile, resource_blockers, validate_container_policy,
)
from aegis.simulation.scenarios import read_scenario

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'simulation/runtime'


@pytest.fixture
def profile():
    return read_profile(RUNTIME / 'profile.json')


@pytest.fixture
def policy():
    return json.loads((RUNTIME / 'compose.json').read_text())


def test_deterministic_profile_and_immutable_inputs(profile):
    assert profile == read_profile(RUNTIME / 'profile.json')
    assert canonical_bytes(profile) == canonical_bytes(read_profile(RUNTIME / 'profile.json'))
    assert load_contract(RuntimeProfile, canonical_bytes(profile)) == profile
    with pytest.raises(FrozenInstanceError):
        profile.gazebo_version = '8.3.0'
    assert profile.status == 'candidate_unverified'
    assert profile.base_digest is profile.runtime_image_digest is None
    assert profile.verified_gazebo_version is profile.verified_px4_commit is None


@pytest.mark.parametrize('key,value', [
    ('schema_version', 2), ('schema_version', True), ('compile_jobs', True),
    ('compile_jobs', 2), ('px4_commit', '0' * 40), ('px4_tag', 'main'),
    ('gazebo_version', '8.3.0'), ('gazebo_package_version', 'latest'),
    ('platform', 'linux/arm64'), ('status', 'verified'),
    ('base_digest', 'sha256:' + '0' * 64), ('verified_gazebo_version', '8.15.0'),
    ('verified_px4_commit', PX4_COMMIT), ('dependency_lock_sha256', '0' * 64),
    ('minimum_available_memory_bytes', 0), ('minimum_free_swap_bytes', 0),
    ('minimum_free_disk_bytes', 0), ('unexpected', 'value'),
])
def test_invalid_or_fabricated_manifest_rejected(key, value):
    data = json.loads((RUNTIME / 'profile.json').read_text())
    data[key] = value
    with pytest.raises(SimulationError):
        load_contract(RuntimeProfile, json.dumps(data).encode())


def test_missing_and_duplicate_manifest_fields():
    data = json.loads((RUNTIME / 'profile.json').read_text())
    del data['px4_commit']
    with pytest.raises(SimulationError):
        load_contract(RuntimeProfile, json.dumps(data).encode())
    with pytest.raises(SimulationError):
        load_contract(RuntimeProfile, b'{"schema_version":1,"schema_version":1}')


@pytest.mark.parametrize('gazebo,px4,code', [
    (None, None, 'UNAVAILABLE'), ('8.15.0', None, 'UNAVAILABLE'),
    (None, PX4_COMMIT, 'UNAVAILABLE'), ('8.3.0', PX4_COMMIT, 'VERSION'),
    ('8.15.0', 'v1.16.0', 'VERSION'), ('8.15.0', '0' * 40, 'VERSION'),
])
def test_missing_or_mismatched_observations(profile, gazebo, px4, code):
    with pytest.raises(SimulationError) as caught:
        check_observations(profile, gazebo_version=gazebo, px4_commit=px4)
    assert caught.value.diagnostic.code == code


def test_matching_observations_do_not_promote_candidate(profile):
    before = canonical_bytes(profile)
    check_observations(profile, gazebo_version='8.15.0', px4_commit=PX4_COMMIT)
    assert canonical_bytes(profile) == before
    assert profile.verified_px4_commit is None


def test_phase74a_remains_exact_and_incompatible(profile):
    scenario = read_scenario(ROOT / 'examples/simulation/virtual-hover.json')
    assert scenario.versions.simulator_version == '8.3.0'
    with pytest.raises(SimulationError, match='VERSION'):
        check_scenario(profile, scenario)


def resources(profile):
    return dict(available_memory_bytes=profile.minimum_available_memory_bytes,
                free_swap_bytes=profile.minimum_free_swap_bytes,
                free_disk_bytes=profile.minimum_free_disk_bytes, cpus=1)


def test_resource_boundaries(profile):
    assert resource_blockers(profile, **resources(profile)) == ()
    assert resource_blockers(profile, available_memory_bytes=1635 * 1024**2,
                             free_swap_bytes=1024**2, free_disk_bytes=200 * 1024**3,
                             cpus=4) == ('available_memory', 'free_swap')


@pytest.mark.parametrize('field,blocker', [
    ('available_memory_bytes', 'available_memory'), ('free_swap_bytes', 'free_swap'),
    ('free_disk_bytes', 'free_disk'), ('cpus', 'cpu'),
])
def test_each_resource_gate(profile, field, blocker):
    data = resources(profile)
    data[field] -= 1
    assert resource_blockers(profile, **data) == (blocker,)


@pytest.mark.parametrize('value', [-1, True, 1.0, None])
def test_invalid_resource_observation(profile, value):
    data = resources(profile)
    data['available_memory_bytes'] = value
    with pytest.raises(SimulationError):
        resource_blockers(profile, **data)


def test_policy_valid_and_does_not_mutate(policy):
    before = deepcopy(policy)
    validate_container_policy(policy)
    assert policy == before


@pytest.mark.parametrize('key,value', [
    ('privileged', True), ('network_mode', 'host'), ('ports', ['14550:14550']),
    ('devices', ['/dev/ttyUSB0:/dev/ttyUSB0']),
    ('volumes', ['/var/run/docker.sock:/var/run/docker.sock']),
    ('volumes', ['/dev:/dev']), ('cap_add', ['SYS_ADMIN']),
    ('cap_drop', []), ('security_opt', []), ('user', '0:0'),
    ('read_only', False), ('cpus', 0), ('mem_limit', '8g'),
    ('memswap_limit', '-1'), ('pids_limit', -1), ('pull_policy', 'always'),
    ('tmpfs', ['/work']), ('command', ['gz', 'sim']), ('build', '.'),
])
def test_unsafe_policy_changes_rejected(policy, key, value):
    policy['services']['inspect'][key] = value
    with pytest.raises(SimulationError, match='CONTAINER_POLICY'):
        validate_container_policy(policy)


def test_extra_service_and_top_level_injection_rejected(policy):
    policy['services']['other'] = {'image': 'ubuntu'}
    with pytest.raises(SimulationError):
        validate_container_policy(policy)
    del policy['services']['other']
    policy['include'] = ['override.yaml']
    with pytest.raises(SimulationError):
        validate_container_policy(policy)


def test_recipe_identity_and_no_compilation_or_startup():
    recipe = (RUNTIME / 'Dockerfile').read_text()
    assert PX4_COMMIT in recipe
    assert 'ARG BASE_IMAGE\nFROM ${BASE_IMAGE}' in recipe
    assert '--require-hashes' in recipe and '--no-index' in recipe
    assert 'python3 -m venv /opt/venv' in recipe
    assert 'libgz-sim8=8.15.0-1~noble' in recipe
    assert 'USER 10001:10001' in recipe
    assert 'ENTRYPOINT ["/opt/venv/bin/python"]' in recipe
    assert 'CMD ["--version"]' in recipe
    instructions = [line for line in recipe.splitlines() if not line.startswith('#')]
    assert not any('gz_x500' in line or 'gz sim' in line for line in instructions)
