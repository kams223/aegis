"""Phase 75B real Gazebo sensor observations; separate passive experimental assets."""
import argparse
from datetime import datetime, timezone
import math
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

import smoke
import launch
import experimental
import aircraft
from sensor_checks import analyze_sensors, decode_sensor, SENSOR_CONFIG
from sensor_startup import StartupTrace, classify_startup

HERE = Path(__file__).resolve().parent
IMAGE = 'ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6'
WORLD_HASH = '138378cf8fbd70fe2c7e2f53c823782a37cd6d9a56869485fe952077436e866c'
MODEL_HASH = 'f678b817f6e03dcce142ae81c59440dfe86dc3344855657846d9ed15a04bf4a9'


def profile():
    value = dict(experimental.profile())
    value.update(profile_id='sensor-aircraft-8.15.0-experimental', world_sha256=WORLD_HASH,
                 model_sha256=MODEL_HASH)
    smoke.require(smoke.digest(HERE / 'sensor-aircraft-world.sdf') == WORLD_HASH, 'Aircraft world hash mismatch')
    smoke.require(smoke.digest(HERE / 'sensor-aircraft.sdf') == MODEL_HASH, 'Aircraft model hash mismatch')
    return value


def verdict(poses, clocks, contacts, exit_code, timed_out):
    # The separate world has identical ENU gravity/geometry. Validate its native
    # frame first, then adapt the identity for the unchanged Phase 75A checker.
    smoke.require(all(p['frame'] == 'aegis_sensor_aircraft' for p in poses), 'Wrong sensor-world pose frame')
    result = aircraft.verdict([dict(p, frame='aegis_passive_aircraft') for p in poses],
                              clocks, contacts, exit_code, timed_out)
    for key in ('initial_pose', 'final_pose'):
        result[key] = dict(result[key], frame='aegis_sensor_aircraft')
    return result


derived_velocities = aircraft.derived_velocities
stamp = aircraft.stamp


def json_safe(value):
    """Preserve rejected nonfinite observations as tagged values in strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_float': str(value)}
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def wait_for_start(server, ready, started, report):
    """Readiness must be an actual transport observation, bounded by wall time."""
    while True:
        smoke.require(server.poll() is None, 'Server exited before observation readiness')
        if time.monotonic() - started >= 15:
            report['timed_out'] = True
            raise ValueError('World/transport startup timeout')
        if ready():
            return
        time.sleep(0.05)


def monitor_server(server, log, started, config, report, callback_errors, startup=None):
    last_poll = time.monotonic()
    while server.poll() is None:
        now = time.monotonic()
        report["observer_monitor_max_gap_seconds"] = max(report.get("observer_monitor_max_gap_seconds", 0), now-last_poll)
        last_poll = now
        if startup is not None:
            if startup.verified():
                startup.mark("startup_verified")
                report["startup_verified"] = True
            elif now-started > 25:
                report["timed_out"] = True
                raise ValueError("Advancing clock and required observations startup timeout")
        if time.monotonic() - started > config['timeout_seconds']:
            report['timed_out'] = True
            raise ValueError('Server wall timeout')
        smoke.require(log.stat().st_size <= smoke.MIB, 'Server log limit exceeded')
        smoke.require(smoke.read_cgroup('memory.current') < int(0.9 * config['memory_bytes']), 'Memory reserve reached')
        smoke.require(not callback_errors(), 'Observation callback failed: ' + str(callback_errors()))
        time.sleep(0.05)


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
    from gz.msgs10.imu_pb2 import IMU
    from gz.msgs10.navsat_pb2 import NavSat
    from gz.msgs10.fluid_pressure_pb2 import FluidPressure
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.msgs10.world_stats_pb2 import WorldStatistics
    from gz.msgs10.contacts_pb2 import Contacts
    startup = StartupTrace()
    startup.mark("observer_initialized")
    poses, clocks, contacts, errors = [], [], [], []
    sensors = {name: [] for name in SENSOR_CONFIG}
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
                    startup.mark('first_pose', sim_time_ns=stamp(pose.header.stamp))
                    frame = [v for d in pose.header.data if d.key == 'frame_id' for v in d.value]
                    append(poses, dict(time_ns=stamp(pose.header.stamp), frame=frame[0] if len(frame) == 1 else None,
                                       name=pose.name, x=pose.position.x, y=pose.position.y, z=pose.position.z,
                                       qx=pose.orientation.x, qy=pose.orientation.y, qz=pose.orientation.z, qw=pose.orientation.w))
        except Exception as error:
            with mutex:
                errors[:] = [str(error)]
    def clock_callback(message):
        startup.mark('first_clock', sim_time_ns=stamp(message.sim_time), paused=message.paused)
        if stamp(message.sim_time) > 0 and not message.paused:
            startup.mark('first_advancing_clock', sim_time_ns=stamp(message.sim_time))
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
    topics = ['/aegis/aircraft/pose', '/world/aegis_sensor_aircraft/stats', '/world/aegis_sensor_aircraft/model/passive_aircraft/link/body/sensor/ground_contact/contact']
    for kind, topic, callback in zip((Pose_V, WorldStatistics, Contacts), topics,
                                     (pose_callback, clock_callback, contact_callback)):
        smoke.require(node.subscribe(kind, topic, callback), 'Subscription failed: ' + topic)
    def callback_for(name):
        def callback(message):
            try:
                row = decode_sensor(name, message)
                startup.mark('first_' + name, sim_time_ns=row['time_ns'])
                append(sensors[name], row)
            except Exception as error:
                with mutex:
                    errors.append(name + ': ' + str(error))
        return callback
    for name, kind in zip(SENSOR_CONFIG, (IMU, NavSat, FluidPressure)):
        topic = SENSOR_CONFIG[name]['topic']
        smoke.require(node.subscribe(kind, topic, callback_for(name)), 'Subscription failed: ' + topic)
        topics.append(topic)
    startup.mark('subscriptions_registered', topics=topics)
    report = dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(), sensor_configurations=SENSOR_CONFIG, schema_version=1, evidence_kind='real_gazebo_transport', synthetic=False,
                  image_digest=IMAGE, gazebo_version=version.strip(), world_name='aegis_sensor_aircraft',
                  world_sha256=WORLD_HASH, model_sha256=MODEL_HASH, runtime_label='experimental Gazebo 8.15.0', physics_engine='gz-physics-dartsim-plugin',
                  clock_domain='isolated_gazebo_simulation', time_unit='ns', length_unit='m',
                  phase74a_compatible=False, success=False, timed_out=False, server_exit_code=None)
    server, controller, server_reader, control_reader = None, None, None, None
    control_events = []
    report['startup_verified'] = False
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='sensors-', dir='/work') as work:
        log = Path(work) / 'gazebo.log'
        control_log = Path(work) / 'control.log'
        def read_server(pipe):
            with log.open('wb') as output:
                for line in iter(lambda: pipe.readline(65536), b''):
                    if output.tell() + len(line) <= smoke.MIB:
                        output.write(line)
                        output.flush()
                    else:
                        with mutex:
                            errors[:] = ['Server log limit exceeded']
                    text = line.decode(errors='replace')
                    # ANSI escapes split markers, so remove them before matching.
                    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
                    if 'Gazebo Sim Server v' in text:
                        startup.mark('server_initialization_log_received')
                    if 'initialized with [' in text:
                        startup.mark('world_initialization_log_received')
                    if 'Serving world names' in text:
                        startup.mark('world_discovery_log_received')
        def read_control(pipe):
            with control_log.open('wb') as output:
                for line in iter(lambda: pipe.readline(65536), b''):
                    if output.tell() + len(line) > 65536:
                        with mutex:
                            errors[:] = ['Controller log limit exceeded']
                        continue
                    output.write(line)
                    output.flush()
                    try:
                        event = json.loads(line)
                        smoke.require(len(control_events) < 16, 'Controller event bound exceeded')
                        with mutex:
                            control_events.append(event)
                        startup.mark(event['event'], emitted=event)
                        if event['event'] == 'control_result':
                            report['control_result'] = event
                            report['unpause_acknowledged'] = event['acknowledged']
                        if event['event'] == 'control_failure':
                            with mutex:
                                errors.append('Controller: ' + event['error'])
                    except Exception as error:
                        with mutex:
                            errors.append('Controller diagnostics: ' + str(error))
        try:
            startup.mark('server_spawn_requested')
            server = subprocess.Popen(['gz', 'sim', '-s', '--iterations', '2000', '-v', '4',
                                       str(HERE / 'sensor-aircraft-world.sdf')], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            startup.mark('server_process_created', pid=server.pid)
            server_reader = threading.Thread(target=read_server, args=(server.stdout,), daemon=True)
            server_reader.start()
            def ready():
                with mutex:
                    return bool(clocks)
            wait_for_start(server, ready, started, report)
            # The pinned request binding holds the GIL. Keep control/discovery in
            # a process with no subscriptions so it cannot starve this observer.
            startup.mark('controller_spawn_requested')
            controller = subprocess.Popen(['python3', '-B', str(HERE / 'sensor_startup.py')],
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, start_new_session=True)
            control_reader = threading.Thread(target=read_control, args=(controller.stdout,), daemon=True)
            control_reader.start()
            def callback_errors():
                with mutex:
                    return list(errors)
            monitor_server(server, log, started, config, report, callback_errors, startup)
            report['server_exit_code'] = server.wait(timeout=2)
            startup.mark('server_exit_observed', exit_code=server.returncode)
            # Waiting on a separate process releases the observer's GIL; also
            # preserve a late control result instead of killing it at server exit.
            controller.wait(timeout=4)
            control_reader.join(timeout=2)
            if startup.verified():
                startup.mark('startup_verified')
                report['startup_verified'] = True
            smoke.require(report['startup_verified'], 'No verified advancing clock and required observations')
            with mutex:
                smoke.require(not errors, str(errors))
                report.update(pose_samples=list(poses), clock_observations=list(clocks), contact_samples=list(contacts))
            report['verdict'] = verdict(report['pose_samples'], report['clock_observations'], report['contact_samples'],
                                        report['server_exit_code'], report['timed_out'])
            report['sensor_analysis'] = analyze_sensors(sensors, report['pose_samples'])
            smoke.require(report['sensor_analysis']['passed'], 'Sensor validation failed: ' + str(report['sensor_analysis']['diagnostics']))
            report['success'] = True
        except Exception as error:
            report['error'] = str(error)
        finally:
            if server is not None:
                smoke.stop_group(server)
                report['server_exit_code'] = server.returncode
            if controller is not None:
                smoke.stop_group(controller)
                report['controller_exit_code'] = controller.returncode
            for reader in (server_reader, control_reader):
                if reader is not None:
                    reader.join(timeout=2)
                    if reader.is_alive():
                        report['success'] = False
                        errors.append('Diagnostic reader did not stop')
            for topic in topics:
                node.unsubscribe(topic)
            report['startup_events'] = startup.snapshot()
            report['control_events'] = list(control_events)
            report['startup_classification'] = classify_startup(report['startup_events'], report.get('control_result', {}), clocks)
            report['control_log'] = control_log.read_text(errors='replace')[:65536] if control_log.exists() else ''
            with mutex:
                report.update(pose_samples=list(poses), clock_observations=list(clocks), contact_samples=list(contacts))
            report['callback_diagnostics'] = list(errors)
            report['sensor_samples'] = sensors
            report.setdefault('sensor_analysis', analyze_sensors(sensors, report['pose_samples']))
            report['velocity_samples'] = derived_velocities(report['pose_samples'])
            report['velocity_source'] = 'finite_difference_of_observed_model_pose; m/s; interval average; not native twist'
            report['peak_pids'] = smoke.read_cgroup('pids.peak')
            report['peak_memory_bytes'] = smoke.read_cgroup('memory.peak')
            report['memory_limit_bytes'] = smoke.read_cgroup('memory.max')
            report['memory_events'] = Path('/sys/fs/cgroup/memory.events').read_text()
            pid_events = Path('/sys/fs/cgroup/pids.events')
            report['pids_events'] = pid_events.read_text() if pid_events.exists() else None
            report['cpu_stat'] = Path('/sys/fs/cgroup/cpu.stat').read_text()
            report['wall_seconds'] = time.monotonic() - started
            report['server_log'] = log.read_text(errors='replace')[:smoke.MIB] if log.exists() else ''
            print(json.dumps(json_safe(report), allow_nan=False), flush=True)
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
                info['Id'], 'python3', '-B', '/opt/aegis/sensors.py', '--inside']
    report = dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(), schema_version=1, evidence_kind='real_gazebo_transport', image_digest=IMAGE,
                  harness_sha256={name: smoke.digest(HERE / name) for name in ('sensors.py','sensor_checks.py','sensor_startup.py','aircraft.py','experimental.py','smoke.py','launch.py','sensor-aircraft.sdf','sensor-aircraft-world.sdf')},
                  image_id=info['Id'], profile=config, container_name=name,
                  success=False, cleanup_ok=False, host_resources_before=observed)
    host_trace = StartupTrace()
    report['host_events'] = {}
    created, attach = False, None
    log = output_dir / 'container.log'
    try:
        created = True
        host_trace.mark('container_create_requested')
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        host_trace.mark('container_created')
        started = time.monotonic()
        minimum = observed[0]
        with log.open('wb') as output:
            host_trace.mark('container_start_requested')
            attach = subprocess.Popen(['docker', 'start', '--attach', name], stdout=output, stderr=subprocess.STDOUT)
            while attach.poll() is None:
                minimum = min(minimum, launch.resources(disk_path)[0])
                smoke.require(time.monotonic() - started < config['host_timeout_seconds'], 'Host wall timeout')
                smoke.require(minimum >= 512 * smoke.MIB, 'Host memory reserve reached')
                smoke.require(log.stat().st_size <= 2 * smoke.MIB, 'Attached log limit exceeded')
                time.sleep(0.1)
        host_trace.mark('container_exit_observed')
        state = json.loads(launch.docker('inspect', name).stdout)[0]
        report['container_state'] = state['State']
        report['container_policy'] = {k:state['HostConfig'][k] for k in (
            'NetworkMode','Memory','MemorySwap','NanoCpus','PidsLimit','Privileged','ReadonlyRootfs','CapDrop','SecurityOpt','Devices','PortBindings')}
        report['attach_exit_code'] = attach.returncode
        report['minimum_host_available_memory_bytes'] = minimum
        smoke.require(log.stat().st_size <= 2 * smoke.MIB, 'Final log limit exceeded')
        smoke.require(not state['State'].get('Error'), 'Container startup failed: ' + state['State'].get('Error', ''))
        lines = log.read_text().splitlines()
        # A report must exist even on failure; startup-only output never passes.
        smoke.require(bool(lines), 'Container produced no runtime report')
        evidence = json.loads(lines[-1])
        report['evidence'] = evidence
        smoke.require(evidence.get('evidence_kind') == 'real_gazebo_transport' and evidence.get('synthetic') is False,
                      'Missing real evidence classification: ' + str(evidence.get('error', 'no diagnostic')))
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
                remaining = json.loads(launch.docker('ps', '-a', '--filter', 'name=^/' + name + '$', '--format', '{{json .Names}}').stdout or 'null')
                smoke.require(remaining is None, 'Owned container still exists after removal')
                report['cleanup_ok'] = True
                host_trace.mark('container_removal_verified')
            except Exception as error:
                report['cleanup_error'] = str(error)
                report['success'] = False
        if attach is not None:
            try:
                attach.wait(timeout=3)
            except subprocess.TimeoutExpired:
                attach.terminate()
                attach.wait(timeout=3)
        report['host_events'] = host_trace.snapshot()
        (output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'evidence'}))
    print('Evidence: ' + str(output_dir / 'report.json'))
    return 0 if report['success'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--disk-path', default='/')
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
