"""Offline candidate runtime validation. No Docker, subprocesses, or startup."""
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Literal

from .contracts import Contract, SimulationError, load_contract, require

PX4_COMMIT = '6ea3539157ca358c70a515878b77077af7d4611d'


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeProfile(Contract):
    profile_id: Literal['gazebo-harmonic-px4-1.16-candidate']
    status: Literal['candidate_unverified']
    platform: Literal['linux/amd64']
    base_tag: Literal['ubuntu:24.04']
    base_digest: None
    runtime_image_digest: None
    gazebo_version: Literal['8.15.0']
    gazebo_package_version: Literal['8.15.0-1~noble']
    px4_tag: Literal['v1.16.0']
    px4_commit: str
    source_verification: str
    verified_gazebo_version: None
    verified_px4_commit: None
    dependency_lock_sha256: None
    minimum_available_memory_bytes: int
    minimum_free_swap_bytes: int
    minimum_free_disk_bytes: int
    compile_jobs: Literal[1]

    def validate(self):
        require(self.px4_commit == PX4_COMMIT, 'VERSION', 'px4_commit', 'Unexpected PX4 source identity')
        require(self.minimum_available_memory_bytes >= 3 * 1024**3
                and self.minimum_free_swap_bytes >= 256 * 1024**2
                and self.minimum_free_disk_bytes >= 30 * 1024**3,
                'RESOURCE', 'minimum', 'Resource floors cannot be weakened')


def read_profile(path):
    with Path(path).open('rb') as stream:
        return load_contract(RuntimeProfile, stream.read(1024 * 1024 + 1))


def check_observations(profile, *, gazebo_version, px4_commit):
    """Match supplied observations only; this never attests compatibility or installation."""
    require(gazebo_version is not None and px4_commit is not None,
            'UNAVAILABLE', 'observations', 'Both actual version observations are required')
    require(gazebo_version == profile.gazebo_version and px4_commit == profile.px4_commit,
            'VERSION', 'observations', 'Observed runtime differs from candidate')


def check_scenario(profile, scenario):
    require(scenario.versions.simulator_version == profile.gazebo_version
            and scenario.versions.autopilot_version == profile.px4_tag.removeprefix('v'),
            'VERSION', 'scenario', 'Phase 74A scenario is not compatible with this candidate')


def resource_blockers(profile, *, available_memory_bytes, free_swap_bytes, free_disk_bytes, cpus):
    values = (available_memory_bytes, free_swap_bytes, free_disk_bytes, cpus)
    require(all(type(v) is int and v >= 0 for v in values),
            'RESOURCE', 'measurements', 'Require nonnegative integer resource measurements')
    return tuple(name for name, actual, minimum in (
        ('available_memory', available_memory_bytes, profile.minimum_available_memory_bytes),
        ('free_swap', free_swap_bytes, profile.minimum_free_swap_bytes),
        ('free_disk', free_disk_bytes, profile.minimum_free_disk_bytes),
        ('cpu', cpus, 1),
    ) if actual < minimum)


def validate_container_policy(config):
    """Closed Compose policy: unknown keys/overrides fail rather than escape isolation."""
    expected = {
        'name': 'aegis-simulation-candidate',
        'services': {'inspect': {
            'image': 'aegis-physics-runtime:candidate', 'pull_policy': 'never',
            'platform': 'linux/amd64', 'user': '10001:10001', 'read_only': True,
            'network_mode': 'none', 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'], 'init': True,
            'cpus': 1.0, 'mem_limit': '2g', 'memswap_limit': '2g',
            'pids_limit': 128, 'shm_size': '64m', 'restart': 'no',
            'tmpfs': ['/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
                      '/run:rw,noexec,nosuid,nodev,size=16m',
                      '/work:rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001'],
            'environment': {'PYTHONDONTWRITEBYTECODE': '1', 'HOME': '/work',
                            'CMAKE_BUILD_PARALLEL_LEVEL': '1', 'MAKEFLAGS': '-j1'},
            'entrypoint': ['/opt/venv/bin/python'], 'command': ['--version'],
        }},
    }
    # Canonical JSON comparison distinguishes bools from numeric resource limits.
    require(json.dumps(config, sort_keys=True) == json.dumps(expected, sort_keys=True),
            'CONTAINER_POLICY', 'compose', 'Unsupported container configuration or override')


def main():
    import argparse
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--compose', required=True)
    parser.add_argument('--disk-path', required=True,
                        help='Physical backing filesystem path, e.g. /mnt/c for a C: backed WSL VHD')
    args = parser.parse_args()
    try:
        profile = read_profile(args.profile)
        validate_container_policy(json.loads(Path(args.compose).read_text()))
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.split()[0]) * 1024
        blockers = resource_blockers(
            profile, available_memory_bytes=memory['MemAvailable'],
            free_swap_bytes=memory['SwapFree'], free_disk_bytes=shutil.disk_usage(args.disk_path).free,
            cpus=os.cpu_count() or 0)
        print(json.dumps({'profile_status': profile.status, 'resource_blockers': blockers,
                          'build_allowed': False, 'physics_running': False,
                          'remaining_locks': ['base_digest', 'dependency_lock', 'runtime_image_digest']}))
        return 2 if blockers else 0
    except (OSError, ValueError, KeyError, SimulationError) as error:
        print(str(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
