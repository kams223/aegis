"""Gazebo-only preparation/checker. Importing this module never launches processes."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time

BASE = 'ubuntu:24.04@sha256:a2d43bffc46670d7108bb3c0468c67c5557c4c92e83e1e34cbff1322ad1b94dc'
VERSION = '8.15.0'
WORLD_SHA256 = '65848e88edfc59c775168258ece22f359c2ed22ecf727e12e343a30cc7eab22b'
MIB = 1024**2
GIB = 1024**3
HERE = Path(__file__).resolve().parent


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def load_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'Duplicate JSON key')
            out[key] = value
        return out
    with Path(path).open('rb') as stream:
        data = stream.read(MIB + 1)
    require(len(data) <= MIB, 'Oversized JSON')
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, 'Nonfinite JSON'))


def validate_profile(profile, world):
    expected = dict(schema_version=1, profile_id='gazebo-only-8.15.0-candidate',
                    status='prepared_unverified', expected_gazebo_version=VERSION,
                    phase74a_gazebo_version='8.3.0', phase74a_compatible=False,
                    platform='linux/amd64', base_image=BASE, world_sha256=digest(world),
                    minimum_available_memory_bytes=2 * GIB,
                    minimum_free_swap_bytes=256 * MIB, minimum_free_disk_bytes=5 * GIB,
                    build_minimum_available_memory_bytes=3 * GIB,
                    runtime_memory_limit_bytes=GIB, cpus=1, pids_limit=128,
                    iterations=2000, timeout_seconds=30, step_ns=1000000)
    require(digest(world) == WORLD_SHA256, 'Unrecognized smoke world')
    require(json.dumps(profile, sort_keys=True) == json.dumps(expected, sort_keys=True),
            'Unsupported profile, world hash, version or resource-policy change')


def check_version(output):
    versions = re.findall(r'(?<![\d.])\d+\.\d+\.\d+(?![\d.])', output)
    require(versions == [VERSION], f'Expected only Gazebo {VERSION}; got {versions}')


def resource_blockers(profile, available, swap, disk, cpus, *, build=False):
    require(all(type(v) is int and v >= 0 for v in (available, swap, disk, cpus)),
            'Invalid resource observation')
    memory_floor = profile['build_minimum_available_memory_bytes'] if build else profile['minimum_available_memory_bytes']
    return [name for name, value, minimum in (
        ('available_memory', available, memory_floor),
        ('free_swap', swap, profile['minimum_free_swap_bytes']),
        ('backing_disk', disk, profile['minimum_free_disk_bytes']), ('cpu', cpus, 1),
    ) if value < minimum]


def verify_bundle(inventory, artifacts):
    """Fail closed on incomplete reviewed lock; rehash every archive before use."""
    require(inventory['base_image'] == BASE, 'Base identity mismatch')
    require(inventory['closure_complete'] is True, 'Authenticated dependency closure is incomplete')
    entries = inventory['closure_packages']
    require(type(entries) is list and 1 <= len(entries) <= 1024, 'Missing bounded package lock')
    paths, identities = set(), set()
    for item in entries:
        require(set(item) == {'name', 'version', 'architecture', 'filename', 'sha256', 'source', 'release_sha256'},
                'Unexpected package lock fields')
        require(type(item['filename']) is str and re.fullmatch(r'[A-Za-z0-9_.+%:~\-]+\.deb', item['filename']),
                'Unsafe package filename')
        require(item['architecture'] in ('amd64', 'all'), 'Wrong package architecture')
        require(item['source'] in ('ubuntu', 'osrf'), 'Unknown package authority')
        require(all(type(item[k]) is str and re.fullmatch('[0-9a-f]{64}', item[k])
                    for k in ('sha256', 'release_sha256')), 'Missing authenticated package hashes')
        require(type(item['name']) is str and re.fullmatch('[a-z0-9][a-z0-9+.-]*', item['name']), 'Invalid package name')
        require(type(item['version']) is str and re.fullmatch(r'[A-Za-z0-9.+:~\-]{1,128}', item['version']), 'Invalid package version')
        identity = (item['name'], item['architecture'])
        require(identity not in identities and item['filename'] not in paths, 'Duplicate locked package')
        identities.add(identity)
        paths.add(item['filename'])
        path = artifacts / 'debs' / item['filename']
        require(not path.is_symlink() and path.is_file() and digest(path) == item['sha256'],
                'Missing or corrupt package archive: ' + item['filename'])
    require({p.name for p in (artifacts / 'debs').iterdir()} == paths, 'Unlisted package files')
    # The lock must include the advertised, authenticated OSRF direct dependencies.
    for expected in inventory['advertised_packages']:
        require(any(p['name'] == expected['Package'] and p['version'] == expected['Version']
                    and p['sha256'] == expected['SHA256'] for p in entries), 'Missing exact Gazebo package')
    return entries


def verify_installed(inventory):
    require(inventory['closure_complete'] is True, 'Incomplete installed package lock')
    for item in inventory['closure_packages']:
        actual = subprocess.run(['dpkg-query', '-W', '-f=${Version}', '--', item['name']],
                                capture_output=True, text=True, timeout=5, check=True).stdout
        require(actual == item['version'], 'Installed dependency version mismatch: ' + item['name'])


def analyze(poses, stats, exit_code, timed_out):
    """Only actual supplied observations; no interpolation or clock-domain conversion."""
    require(not timed_out and exit_code == 0, 'Server timeout or nonzero exit')
    require(5 <= len(poses) <= 512 and 2 <= len(stats) <= 512, 'Missing or excessive runtime evidence')
    for rows in (poses, stats):
        times = [p['time_ns'] for p in rows]
        require(all(type(t) is int and 0 <= t <= 2_000_000_000 for t in times), 'Invalid simulation timestamp')
        require(all(a < b for a, b in zip(times, times[1:])), 'Simulation time did not advance monotonically')
    require(all(p['frame'] == 'aegis_gravity' and p['name'] == 'falling_box' for p in poses),
            'Unknown model or coordinate frame')
    require(all(all(type(p[k]) in (float, int) and math.isfinite(p[k]) for k in ('x', 'y', 'z'))
                for p in poses), 'Nonfinite position')
    require(all(abs(p['x']) < 0.02 and abs(p['y']) < 0.02 for p in poses), 'Unexpected horizontal motion')
    early = [p for p in poses if 20_000_000 <= p['time_ns'] <= 300_000_000]
    require(len(early) >= 5, 'Insufficient free-fall observations')
    require(all(abs(p['z'] - (1 - 4.905 * (p['time_ns'] / 1e9)**2)) < 0.04 for p in early),
            'Position does not match bounded gravity expectation')
    late = [p for p in poses if p['time_ns'] >= 1_500_000_000]
    require(len(late) >= 5 and all(0.08 <= p['z'] <= 0.14 for p in late), 'Box did not settle on the ground')
    require(stats[-1]['time_ns'] >= 1_500_000_000, 'Insufficient simulated duration')
    require(all(type(p['iterations']) is int and 0 < p['iterations'] <= 2000
                and p['iterations'] * 1_000_000 == p['time_ns'] for p in stats), 'Iteration/time mismatch')
    return {'world_loaded': True, 'physics_advanced': True, 'gravity_verified': True}


def read_cgroup(name):
    text = (Path('/sys/fs/cgroup') / name).read_text().strip()
    require(text != 'max', 'Unbounded cgroup: ' + name)
    return int(text)


def stop_group(process):
    # Only the process group created with start_new_session=True below is owned.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Also remove residual children if the group leader has already exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def inside(profile, inventory):
    """Explicit container-only execution; called only by the gated host launcher."""
    require(read_cgroup('memory.max') <= GIB and read_cgroup('pids.max') <= 128,
            'Runtime cgroup limits missing')
    require(read_cgroup('memory.swap.max') == 0, 'Additional swap is not permitted')
    quota, period = (Path('/sys/fs/cgroup/cpu.max').read_text().split())
    require(quota != 'max' and int(quota) <= int(period), 'CPU limit missing')
    require(os.geteuid() == 10001, 'Nonroot runtime identity required')
    verify_installed(inventory)
    receipt = load_json(HERE / 'build-receipt.json')
    require(receipt == {'inputs_sha256': digest(HERE / 'inputs.json'), 'gazebo_version': VERSION},
            'Build receipt mismatch')
    version = subprocess.run(['gz', 'sim', '--versions'], capture_output=True, text=True,
                             timeout=5, check=True).stdout
    check_version(version)
    for package in ('gz-sim8-cli', 'libgz-sim8', 'libgz-sim8-plugins'):
        installed = subprocess.run(['dpkg-query', '-W', '-f=${Version}', package],
                                   capture_output=True, text=True, timeout=5, check=True).stdout
        require(installed == '8.15.0-1~noble', 'Installed Gazebo package mismatch')
    require(inventory['closure_complete'] is True, 'Unverified image inputs')
    # Import only inside the image, after resource, artifact and version checks.
    from gz.transport13 import Node
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.msgs10.world_stats_pb2 import WorldStatistics
    poses, stats, errors = [], [], []
    lock = threading.Lock()
    def append(rows, row):
        with lock:
            if len(rows) >= 512:
                errors[:] = ['Observation bound exceeded']
            else:
                rows.append(row)
    def pose_callback(message):
        for pose in message.pose:
            if pose.name == 'falling_box':
                frame = [v for d in pose.header.data if d.key == 'frame_id' for v in d.value]
                append(poses, dict(time_ns=pose.header.stamp.sec * 10**9 + pose.header.stamp.nsec,
                                   frame=frame[0] if len(frame) == 1 else None, name=pose.name,
                                   x=pose.position.x, y=pose.position.y, z=pose.position.z))
    def stats_callback(message):
        append(stats, dict(time_ns=message.sim_time.sec * 10**9 + message.sim_time.nsec,
                           iterations=message.iterations))
    node = Node()
    topics = ('/aegis/smoke/pose', '/world/aegis_gravity/stats')
    require(node.subscribe(Pose_V, topics[0], pose_callback), 'Pose subscription failed')
    require(node.subscribe(WorldStatistics, topics[1], stats_callback), 'Stats subscription failed')
    report = dict(success=False, physics_executed=False, version_output=version,
                  timed_out=False, exit_code=None, peak_memory_bytes=None)
    started = time.monotonic()
    process = None
    with tempfile.TemporaryDirectory(prefix='aegis-gravity-', dir='/work') as work:
        log = Path(work) / 'server.log'
        try:
            with log.open('wb') as output:
                process = subprocess.Popen(
                    ['gz', 'sim', '-s', '-r', '--iterations', str(profile['iterations']),
                     '-v', '4', str(HERE / 'gravity.sdf')], stdout=output,
                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
                report['server_process_started'] = True
                peak = read_cgroup('memory.current')
                while process.poll() is None:
                    peak = max(peak, read_cgroup('memory.current'))
                    if time.monotonic() - started > profile['timeout_seconds']:
                        report['timed_out'] = True
                        break
                    require(log.stat().st_size <= MIB, 'Server log bound exceeded')
                    require(peak <= int(0.9 * GIB), 'Runtime memory guard exceeded')
                    with lock:
                        require(not errors, 'Observation bounds exceeded')
                    time.sleep(0.05)
                if report['timed_out']:
                    stop_group(process)
                report['exit_code'] = process.wait(timeout=2)
                report['peak_memory_bytes'] = max(peak, read_cgroup('memory.peak'))
            # Allow already-delivered callbacks to finish; never invent missing samples.
            with lock:
                require(not errors, 'Observation bound exceeded')
                report['poses'] = list(poses)
                report['stats'] = list(stats)
            report.update(analyze(report['poses'], report['stats'], report['exit_code'], report['timed_out']))
            report['physics_executed'] = True
            report['success'] = True
        except Exception as error:
            report['error'] = str(error)
        finally:
            if process is not None:
                stop_group(process)
                report['exit_code'] = process.returncode
            report['peak_memory_bytes'] = read_cgroup('memory.peak')
            report['memory_events'] = Path('/sys/fs/cgroup/memory.events').read_text()
            report['cpu_stat'] = Path('/sys/fs/cgroup/cpu.stat').read_text()
            for topic in topics:
                node.unsubscribe(topic)
            report['wall_duration_seconds'] = time.monotonic() - started
            report['server_log'] = log.read_text(errors='replace')[:MIB] if log.exists() else ''
            print(json.dumps(report, allow_nan=False), flush=True)
    return 0 if report['success'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--verify-bundle', type=Path)
    parser.add_argument('--verify-installed', action='store_true')
    args = parser.parse_args()
    try:
        profile = load_json(HERE / 'profile.json')
        inventory = load_json(HERE / 'inputs.json')
        validate_profile(profile, HERE / 'gravity.sdf')
        if args.verify_bundle:
            verify_bundle(inventory, args.verify_bundle)
        elif args.verify_installed:
            verify_installed(inventory)
        elif args.inside:
            return inside(profile, inventory)
        else:
            print(json.dumps({'status': profile['status'], 'gazebo': VERSION,
                              'phase74a_compatible': False, 'physics_executed': False,
                              'build_blockers': inventory['blockers']}))
        return 0
    except Exception as error:
        print(json.dumps({'success': False, 'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
