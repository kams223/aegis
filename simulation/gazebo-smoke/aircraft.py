"""Phase 75A passive aircraft; orchestration adapted from the verified Phase 74B experimental path."""
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
import experimental

HERE = Path(__file__).resolve().parent
IMAGE = 'ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6'
WORLD_HASH = 'a2444761884218b419c71a8ba5c2249d304ca13b94850b4752b3c74f11be3035'
MODEL_HASH = 'b3e2086296198b5ecff61606f92db3ef3cd071f943f55b913f5d51289a3f24bc'


def profile():
    value = dict(experimental.profile())
    value.update(profile_id='passive-aircraft-8.15.0-experimental', world_sha256=WORLD_HASH,
                 model_sha256=MODEL_HASH)
    smoke.require(smoke.digest(HERE / 'passive-aircraft-world.sdf') == WORLD_HASH, 'Aircraft world hash mismatch')
    smoke.require(smoke.digest(HERE / 'passive-aircraft.sdf') == MODEL_HASH, 'Aircraft model hash mismatch')
    return value


def verdict(poses, clocks, contacts, exit_code, timed_out):
    smoke.require(exit_code == 0 and not timed_out, 'Abnormal exit or timeout')
    smoke.require(100 <= len(poses) <= 512 and 3 <= len(clocks) <= 512 and len(contacts) <= 512, 'Missing or excessive observations')
    for rows in (poses, clocks):
        times = [r['time_ns'] for r in rows]
        smoke.require(all(type(t) is int and 0 <= t <= 2000000000 for t in times), 'Invalid timestamp')
        smoke.require(all(a < b if rows is poses else a <= b for a,b in zip(times,times[1:])), 'Regressed timestamps')
    running = [c for c in clocks if not c['paused'] and c['iterations'] > 0]
    smoke.require(len(running) >= 2 and running[-1]['time_ns'] >= 1500000000 and
                  all(type(c['iterations']) is int and c['time_ns'] == c['iterations'] * 1000000 for c in running), 'Clock/step mismatch')
    for p in poses:
        smoke.require(p['name'] == 'passive_aircraft' and p['frame'] == 'aegis_passive_aircraft', 'Wrong pose identity')
        smoke.require(all(type(p[k]) in (int,float) and math.isfinite(p[k]) for k in ('x','y','z','qx','qy','qz','qw')), 'Invalid pose')
        smoke.require(abs(sum(p[k]**2 for k in ('qx','qy','qz','qw'))-1) < 1e-5, 'Invalid quaternion')
        smoke.require(abs(p['x']) < .05 and abs(p['y']) < .05 and .07 < p['z'] <= 1.005, 'Pose outside expected envelope')
    first=poses[0]
    smoke.require(first['time_ns'] <= 20000000 and .995 <= first['z'] <= 1.005 and
                  all(abs(first[k]) < .001 for k in ('x','y','qx','qy','qz')) and abs(first['qw']) > .999, 'Invalid initial pose')
    fall=[p for p in poses if 50000000 <= p['time_ns'] <= 300000000]
    smoke.require(len(fall) >= 10 and all(abs(p['z']-(1-4.905*(p['time_ns']/1e9)**2)) < .01 for p in fall), 'Gravity trajectory mismatch')
    named=[]
    for c in contacts:
        names = {c['collision1'], c['collision2']}
        aircraft_collisions = {'passive_aircraft::body::' + part + '_collision'
                               for part in ('fuselage', 'wing', 'tailplane', 'fin')}
        smoke.require(type(c['time_ns']) is int and 300000000 <= c['time_ns'] <= 2000000000, 'Invalid contact timestamp')
        smoke.require('ground::plane::ground_collision' in names and bool(names & aircraft_collisions), 'Wrong collision pair')
        smoke.require(c['positions'] and all(all(math.isfinite(p[k]) for k in ('x','y','z')) and abs(p['z']) < .02 for p in c['positions']), 'Invalid contact position')
        smoke.require(len(c['depths']) == len(c['positions']) and
                      all(math.isfinite(d) and 0 <= d < .02 for d in c['depths']), 'Invalid contact depth')
        named.append(c)
    smoke.require(named and any(c['time_ns'] >= 1500000000 for c in named), 'Missing measured ground contact')
    late=[p for p in poses if p['time_ns'] >= 1500000000]
    smoke.require(len(late) >= 30 and late[-1]['time_ns'] >= 1950000000 and late[-1]['time_ns']-late[0]['time_ns'] >= 300000000, 'Missing late poses')
    spreads={k:max(p[k] for p in late)-min(p[k] for p in late) for k in ('x','y','z','qx','qy','qz','qw')}
    smoke.require(all(v < .002 for v in spreads.values()) and all(abs(p['z']-.08) < .005 for p in late), 'Aircraft not settled')
    return dict(passed=True, initial_pose=first, final_pose=late[-1], gravity_verified=True,
                ground_contact=True, settled=True, settled_ranges=spreads, clock_advancing=True,
                ground_contact_samples=len(named))


def derived_velocities(poses):
    # Finite differences of observed poses, not a native Gazebo velocity stream.
    result=[]
    for a,b in zip(poses,poses[1:]):
        dt=(b['time_ns']-a['time_ns'])/1e9
        if dt > 0:
            result.append(dict(time_ns=b['time_ns'], interval_start_ns=a['time_ns'],
                               **{k:(b[k]-a[k])/dt for k in ('x','y','z')}))
    return result


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
                if pose.name == 'passive_aircraft':
                    frame = [v for d in pose.header.data if d.key == 'frame_id' for v in d.value]
                    append(poses, dict(time_ns=stamp(pose.header.stamp), frame=frame[0] if len(frame) == 1 else None,
                                       name=pose.name, x=pose.position.x, y=pose.position.y, z=pose.position.z,
                                       qx=pose.orientation.x, qy=pose.orientation.y, qz=pose.orientation.z, qw=pose.orientation.w))
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
    topics = ['/aegis/aircraft/pose', '/world/aegis_passive_aircraft/stats', '/world/aegis_passive_aircraft/model/passive_aircraft/link/body/sensor/ground_contact/contact']
    for kind, topic, callback in zip((Pose_V, WorldStatistics, Contacts), topics,
                                     (pose_callback, clock_callback, contact_callback)):
        smoke.require(node.subscribe(kind, topic, callback), 'Subscription failed: ' + topic)
    report = dict(schema_version=1, evidence_kind='real_gazebo_transport', synthetic=False,
                  image_digest=IMAGE, gazebo_version=version.strip(), world_name='aegis_passive_aircraft',
                  world_sha256=WORLD_HASH, model_sha256=MODEL_HASH, runtime_label='experimental Gazebo 8.15.0', physics_engine='gz-physics-dartsim-plugin',
                  clock_domain='isolated_gazebo_simulation', time_unit='ns', length_unit='m',
                  phase74a_compatible=False, success=False, timed_out=False, server_exit_code=None)
    server = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='gravity-', dir='/work') as work:
        log = Path(work) / 'gazebo.log'
        try:
            with log.open('wb') as output:
                server = subprocess.Popen(['gz', 'sim', '-s', '--iterations', '2000', '-v', '4',
                                           str(HERE / 'passive-aircraft-world.sdf')], stdout=output,
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
                ok, response = node.request('/world/aegis_passive_aircraft/control', WorldControl(pause=False),
                                            WorldControl, Boolean, 3000)
                # Transport may lose the reply even when Gazebo applies the request.
                # Record the acknowledgement; only measured physics can pass the test.
                report['unpause_acknowledged'] = bool(ok and response.data)
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
            report['velocity_samples'] = derived_velocities(report['pose_samples'])
            report['velocity_source'] = 'finite_difference_of_observed_model_pose; m/s; interval average; not native twist'
            report['peak_pids'] = smoke.read_cgroup('pids.peak')
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
                info['Id'], 'python3', '-B', '/opt/aegis/aircraft.py', '--inside']
    report = dict(schema_version=1, evidence_kind='real_gazebo_transport', image_digest=IMAGE,
                  harness_sha256={name: smoke.digest(HERE / name) for name in ('aircraft.py','experimental.py','smoke.py','launch.py')},
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
