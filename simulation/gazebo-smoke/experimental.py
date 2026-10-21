"""Explicit experimental prebuilt-image path. No launch on import or default invocation."""
import argparse
import math
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

import smoke
import launch

HERE = Path(__file__).resolve().parent
IMAGE = 'ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6'
WORLD_HASH = 'b1a97a4bd9c0ac9908f7bc853ca439bbe3bc1921aa7be9f8dff1ee55788241e8'


def profile():
    value = smoke.load_json(HERE / 'experimental-profile.json')
    expected = dict(schema_version=1, profile_id='gazebo-prebuilt-8.15.0-experimental',
                    image=IMAGE, platform='linux/amd64', expected_gazebo_version='8.15.0',
                    image_os='ubuntu-22.04', world_sha256=WORLD_HASH, phase74a_compatible=False,
                    memory_bytes=smoke.GIB, cpus=1, pids=128, iterations=2000, step_ns=1000000,
                    timeout_seconds=35, host_timeout_seconds=55,
                    minimum_available_memory_bytes=2 * smoke.GIB)
    smoke.require(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True), 'Experimental profile mismatch')
    smoke.require(smoke.digest(HERE / 'experimental-gravity.sdf') == WORLD_HASH, 'Experimental world hash mismatch')
    return value


def verdict(poses, clocks, contacts, exit_code, timed_out):
    # Keep all raw clocks, including paused startup, in evidence. Only running clocks
    # go to the existing strict checker; no samples are sorted or interpolated.
    smoke.require(len(clocks) >= 3, 'Missing clock observations')
    times = [row['time_ns'] for row in clocks]
    smoke.require(all(type(t) is int and 0 <= t <= 2_000_000_000 for t in times), 'Invalid clock timestamp')
    smoke.require(all(a <= b for a, b in zip(times, times[1:])), 'Clock regressed')
    running = [row for row in clocks if not row['paused'] and row['iterations'] > 0]
    smoke.analyze(poses, running, exit_code, timed_out)
    smoke.require(poses[0]['time_ns'] <= 20_000_000 and 0.995 <= poses[0]['z'] <= 1.005,
                  'Initial height was not observed early enough')
    smoke.require(max(p['z'] for p in poses[:5]) - min(p['z'] for p in poses if p['time_ns'] >= 300000000) > 0.8,
                  'No substantial downward motion')
    named = [c for c in contacts if (
        {'ground_collision', 'box_collision'} == {c['collision1'].split('::')[-1], c['collision2'].split('::')[-1]}
        and c['positions'] and 300000000 <= c['time_ns'] <= 2000000000)]
    smoke.require(bool(named), 'No measured ground/box collision contact')
    smoke.require(all(all(type(p[k]) in (int, float) and math.isfinite(p[k]) for k in ('x','y','z'))
                      and abs(p['z']) <= 0.02 for c in named for p in c['positions']), 'Invalid ground contact position')
    late = [p for p in poses if p['time_ns'] >= 1500000000]
    spread = max(p['z'] for p in late) - min(p['z'] for p in late)
    duration = late[-1]['time_ns'] - late[0]['time_ns']
    smoke.require(duration >= 300000000 and spread <= 0.002, 'Model has not stably settled')
    return dict(passed=True, initial_height_m=poses[0]['z'], initial_time_ns=poses[0]['time_ns'],
                final_height_m=late[-1]['z'], settled_height_range_m=spread,
                settled_duration_ns=duration, ground_contact_samples=len(named),
                downward_motion=True, ground_contact=True, settled=True, clock_advancing=True)


def stamp(value):
    return value.sec * 10**9 + value.nsec


def inside():
    config = profile()
    smoke.require(os.geteuid() == 10001, 'Expected nonroot user')
    smoke.require(smoke.read_cgroup('memory.max') <= config['memory_bytes'], 'Memory cap mismatch')
    smoke.require(smoke.read_cgroup('pids.max') <= config['pids'], 'PID cap mismatch')
    smoke.require(smoke.read_cgroup('memory.swap.max') == 0, 'Unexpected swap allowance')
    quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
    smoke.require(quota != 'max' and int(quota) <= int(period), 'CPU cap mismatch')
    version = subprocess.run(['gz', 'sim', '--versions'], capture_output=True, text=True, check=True, timeout=5).stdout
    smoke.check_version(version)
    from gz.transport13 import Node
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.msgs10.world_stats_pb2 import WorldStatistics
    from gz.msgs10.contacts_pb2 import Contacts
    from gz.msgs10.world_control_pb2 import WorldControl
    from gz.msgs10.boolean_pb2 import Boolean
    poses, clocks, contacts, errors = [], [], [], []
    mutex = threading.Lock()
    def append(rows, value):
        with mutex:
            if len(rows) >= 512:
                errors[:] = ['Observation bound exceeded']
            else:
                rows.append(value)
    def pose_callback(message):
        try:
            for pose in message.pose:
                if pose.name == 'falling_box':
                    frame = [v for d in pose.header.data if d.key == 'frame_id' for v in d.value]
                    append(poses, dict(time_ns=stamp(pose.header.stamp), frame=frame[0] if len(frame) == 1 else None,
                                       name=pose.name, x=pose.position.x, y=pose.position.y, z=pose.position.z))
        except Exception as error:
            with mutex:
                errors[:] = [str(error)]
    def clock_callback(message):
        append(clocks, dict(time_ns=stamp(message.sim_time), iterations=message.iterations, paused=message.paused))
    def contact_callback(message):
        try:
            for contact in message.contact:
                when = stamp(contact.header.stamp) if contact.HasField('header') else stamp(message.header.stamp)
                row = dict(time_ns=when, collision1=contact.collision1.name, collision2=contact.collision2.name,
                           collision1_id=contact.collision1.id, collision2_id=contact.collision2.id,
                           positions=[dict(x=p.x, y=p.y, z=p.z) for p in contact.position],
                           depths=list(contact.depth))
                with mutex:
                    # Time-based decimation retains actual measurements, never invented samples.
                    if not contacts or when - contacts[-1]['time_ns'] >= 10000000:
                        if len(contacts) >= 512:
                            errors[:] = ['Contact observation bound exceeded']
                        else:
                            contacts.append(row)
        except Exception as error:
            with mutex:
                errors[:] = [str(error)]
    node = Node()
    topics = ['/aegis/smoke/pose', '/world/aegis_gravity/stats', '/world/aegis_gravity/model/falling_box/link/body/sensor/ground_contact/contact']
    for kind, topic, callback in zip((Pose_V, WorldStatistics, Contacts), topics,
                                     (pose_callback, clock_callback, contact_callback)):
        smoke.require(node.subscribe(kind, topic, callback), 'Subscription failed: ' + topic)
    report = dict(schema_version=1, evidence_kind='real_gazebo_transport', synthetic=False,
                  image_digest=IMAGE, gazebo_version=version.strip(), world_name='aegis_gravity',
                  world_sha256=WORLD_HASH, physics_engine='gz-physics-dartsim-plugin',
                  clock_domain='isolated_gazebo_simulation', time_unit='ns', length_unit='m',
                  phase74a_compatible=False, success=False, timed_out=False, server_exit_code=None)
    server = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='gravity-', dir='/work') as work:
        log = Path(work) / 'gazebo.log'
        try:
            with log.open('wb') as output:
                server = subprocess.Popen(['gz', 'sim', '-s', '--iterations', '2000', '-v', '4',
                                           str(HERE / 'experimental-gravity.sdf')], stdout=output,
                                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
                # Wait for actual paused-world stats and transport discovery before unpausing.
                while True:
                    smoke.require(server.poll() is None, 'Server exited before observation readiness')
                    smoke.require(time.monotonic() - started < 15, 'World/transport startup timeout')
                    with mutex:
                        ready = bool(clocks)
                    if ready:
                        break
                    time.sleep(0.05)
                time.sleep(0.5)
                ok, response = node.request('/world/aegis_gravity/control', WorldControl(pause=False),
                                            WorldControl, Boolean, 3000)
                smoke.require(ok and response.data, 'World unpause request failed')
                while server.poll() is None:
                    if time.monotonic() - started > config['timeout_seconds']:
                        report['timed_out'] = True
                        raise ValueError('Server wall timeout')
                    smoke.require(log.stat().st_size <= smoke.MIB, 'Server log limit exceeded')
                    smoke.require(smoke.read_cgroup('memory.current') < int(0.9 * config['memory_bytes']), 'Memory reserve reached')
                    with mutex:
                        smoke.require(not errors, 'Observation callback failed: ' + str(errors))
                    time.sleep(0.05)
                report['server_exit_code'] = server.wait(timeout=2)
            with mutex:
                smoke.require(not errors, str(errors))
                report.update(pose_samples=list(poses), clock_observations=list(clocks), contact_samples=list(contacts))
            report['verdict'] = verdict(report['pose_samples'], report['clock_observations'], report['contact_samples'],
                                        report['server_exit_code'], report['timed_out'])
            report['success'] = True
        except Exception as error:
            report['error'] = str(error)
        finally:
            if server is not None:
                smoke.stop_group(server)
                report['server_exit_code'] = server.returncode
            for topic in topics:
                node.unsubscribe(topic)
            with mutex:
                report.update(pose_samples=list(poses), clock_observations=list(clocks), contact_samples=list(contacts))
            report['peak_memory_bytes'] = smoke.read_cgroup('memory.peak')
            report['memory_limit_bytes'] = smoke.read_cgroup('memory.max')
            report['memory_events'] = Path('/sys/fs/cgroup/memory.events').read_text()
            report['cpu_stat'] = Path('/sys/fs/cgroup/cpu.stat').read_text()
            report['wall_seconds'] = time.monotonic() - started
            report['server_log'] = log.read_text(errors='replace')[:smoke.MIB] if log.exists() else ''
            print(json.dumps(report, allow_nan=False), flush=True)
    return 0 if report['success'] else 2


def run(output_dir, disk_path):
    config = profile()
    observed = launch.resources(disk_path)
    smoke.require(observed[0] >= config['minimum_available_memory_bytes'], 'Insufficient available host RAM')
    smoke.require(observed[2] >= 5 * smoke.GIB and observed[3] >= 1, 'Insufficient disk/CPU')
    info = json.loads(launch.docker('image', 'inspect', IMAGE).stdout)[0]
    smoke.require(IMAGE in info['RepoDigests'] and info['Architecture'] == 'amd64' and info['Os'] == 'linux', 'Pinned image identity mismatch')
    output_dir.mkdir(parents=True, exist_ok=False)
    name = 'aegis-smoke-' + uuid.uuid4().hex
    command = launch.container_args(info['Id'], name)[:-2]
    command = [s.replace('GZ_SIM_RESOURCE_PATH=/opt/smoke', 'GZ_SIM_RESOURCE_PATH=/opt/aegis') for s in command]
    command += ['--log-opt', 'compress=false', '--mount', 'type=bind,source=' + str(HERE) + ',target=/opt/aegis,readonly',
                info['Id'], 'python3', '-B', '/opt/aegis/experimental.py', '--inside']
    report = dict(schema_version=1, evidence_kind='real_gazebo_transport', image_digest=IMAGE,
                  image_id=info['Id'], profile=config, container_name=name,
                  success=False, cleanup_ok=False, host_resources_before=observed)
    created, attach = False, None
    log = output_dir / 'container.log'
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        created = True
        started = time.monotonic()
        minimum = observed[0]
        with log.open('wb') as output:
            attach = subprocess.Popen(['docker', 'start', '--attach', name], stdout=output, stderr=subprocess.STDOUT)
            while attach.poll() is None:
                minimum = min(minimum, launch.resources(disk_path)[0])
                smoke.require(time.monotonic() - started < config['host_timeout_seconds'], 'Host wall timeout')
                smoke.require(minimum >= 512 * smoke.MIB, 'Host memory reserve reached')
                smoke.require(log.stat().st_size <= 2 * smoke.MIB, 'Attached log limit exceeded')
                time.sleep(0.1)
        state = json.loads(launch.docker('inspect', name).stdout)[0]
        report['container_state'] = state['State']
        report['container_policy'] = {k:state['HostConfig'][k] for k in (
            'NetworkMode','Memory','MemorySwap','NanoCpus','PidsLimit','Privileged','ReadonlyRootfs','CapDrop','SecurityOpt','Devices','PortBindings')}
        report['minimum_host_available_memory_bytes'] = minimum
        smoke.require(log.stat().st_size <= 2 * smoke.MIB, 'Final log limit exceeded')
        smoke.require(not state['State'].get('Error'), 'Container startup failed: ' + state['State'].get('Error', ''))
        lines = log.read_text().splitlines()
        # A report must exist even on failure; startup-only output never passes.
        evidence = json.loads(lines[-1])
        report['evidence'] = evidence
        smoke.require(evidence.get('evidence_kind') == 'real_gazebo_transport' and evidence.get('synthetic') is False,
                      'Missing real evidence classification')
        smoke.require(evidence.get('success') is True and not state['State']['OOMKilled']
                      and state['State']['ExitCode'] == 0 and attach.returncode == 0, 'Physics verification failed')
        report['success'] = True
    except Exception as error:
        report['error'] = str(error)
    finally:
        if created:
            try:
                launch.docker('stop', '--time', '3', name)
                launch.docker('rm', name)
                report['cleanup_ok'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
                report['success'] = False
        if attach is not None:
            try:
                attach.wait(timeout=3)
            except subprocess.TimeoutExpired:
                attach.terminate()
                attach.wait(timeout=3)
        (output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'evidence'}))
    print('Evidence: ' + str(output_dir / 'report.json'))
    return 0 if report['success'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--disk-path', default='/mnt/c')
    args = parser.parse_args()
    try:
        if args.inside:
            return inside()
        if args.run:
            smoke.require(args.output_dir is not None, 'A new output directory is required')
            return run(args.output_dir, args.disk_path)
        print(json.dumps(profile()))
        return 0
    except Exception as error:
        print(json.dumps({'success':False,'error':str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
