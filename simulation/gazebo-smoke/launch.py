"""Host preflight and explicit bounded launch of ONE owned Gazebo-only container."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

import smoke

HERE = Path(__file__).resolve().parent


def resources(disk_path):
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0]) * 1024
    return (memory['MemAvailable'], memory['SwapFree'], shutil.disk_usage(disk_path).free, os.cpu_count() or 0)


def container_args(image, name):
    smoke.require(re.fullmatch('sha256:[0-9a-f]{64}', image) is not None, 'Require immutable local image ID')
    smoke.require(re.fullmatch('aegis-smoke-[0-9a-f]{32}', name) is not None, 'Invalid owned container name')
    return ['docker', 'create', '--name', name, '--pull=never', '--platform=linux/amd64',
            '--network=none', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
            '--user=10001:10001', '--read-only', '--init', '--cpus=1', '--memory=1g',
            '--memory-swap=1g', '--pids-limit=128', '--shm-size=64m',
            '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            '--tmpfs=/run:rw,noexec,nosuid,nodev,size=16m',
            '--tmpfs=/work:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001',
            '--env=HOME=/work', '--env=PYTHONDONTWRITEBYTECODE=1', '--env=GZ_IP=127.0.0.1',
            '--env=GZ_SIM_RESOURCE_PATH=/opt/smoke', '--env=GZ_PARTITION=' + name,
            '--log-driver=local', '--log-opt=max-size=2m', '--log-opt=max-file=1', '--log-opt=compress=false',
            image, '--inside']


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True, timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-path', required=True)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--image-id')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    report = dict(success=False, launched=False)
    audit_created = False
    try:
        profile = smoke.load_json(HERE / 'profile.json')
        inventory = smoke.load_json(HERE / 'inputs.json')
        smoke.validate_profile(profile, HERE / 'gravity.sdf')
        measured = resources(args.disk_path)
        report.update(resource_observations=dict(zip(('available_memory_bytes', 'free_swap_bytes',
                                                      'free_disk_bytes', 'cpus'), measured)),
                      runtime_resource_blockers=smoke.resource_blockers(profile, *measured),
                      build_resource_blockers=smoke.resource_blockers(profile, *measured, build=True))
        try:
            smoke.verify_bundle(inventory, HERE / 'artifacts')
            report['bundle_verified'] = True
        except (ValueError, OSError) as error:
            report['bundle_verified'] = False
            report['bundle_error'] = str(error)
        if not args.launch:
            print(json.dumps(report))
            return 0 if report['bundle_verified'] and not report['runtime_resource_blockers'] else 2
        smoke.require(report['bundle_verified'] and not report['runtime_resource_blockers'],
                      'Launch blocked by unverified build inputs or resources')
        smoke.require(args.output_dir is not None, 'Specify a new output directory for retained audit logs')
        image = args.image_id or ''
        name = 'aegis-smoke-' + uuid.uuid4().hex
        command = container_args(image, name)
        identity = json.loads(docker('image', 'inspect', image).stdout)[0]
        smoke.require(identity['Id'] == image and identity['Architecture'] == 'amd64'
                      and identity['Os'] == 'linux', 'Image identity/platform mismatch')
        labels = identity['Config'].get('Labels') or {}
        smoke.require(labels.get('org.aegis.smoke.inputs-sha256') == smoke.digest(HERE / 'inputs.json')
                      and labels.get('org.aegis.smoke.world-sha256') == profile['world_sha256']
                      and labels.get('org.aegis.smoke.gazebo-version') == smoke.VERSION,
                      'Built image does not match reviewed inputs')
        args.output_dir.mkdir(parents=True, exist_ok=False)
        audit_created = True
        log_path = args.output_dir / 'container.log'
        created, attach = False, None
        cleanup_ok = True
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
            created = True
            report['container_name'] = name
            started = time.monotonic()
            minimum_available = measured[0]
            with log_path.open('wb') as log:
                attach = subprocess.Popen(['docker', 'start', '--attach', name], stdout=log, stderr=subprocess.STDOUT)
                report['launched'] = True
                while attach.poll() is None:
                    minimum_available = min(minimum_available, resources(args.disk_path)[0])
                    smoke.require(time.monotonic() - started < 45, 'Host wall timeout')
                    smoke.require(minimum_available >= 512 * smoke.MIB, 'Host memory reserve exhausted')
                    smoke.require(log_path.stat().st_size <= 2 * smoke.MIB, 'Container output limit exceeded')
                    time.sleep(0.1)
                report['attach_exit_code'] = attach.returncode
            state = json.loads(docker('inspect', name).stdout)[0]['State']
            report.update(container_state=state, minimum_host_available_memory_bytes=minimum_available,
                          host_wall_duration_seconds=time.monotonic() - started)
            smoke.require(not state['OOMKilled'] and state['ExitCode'] == 0 and attach.returncode == 0,
                          'Container failed or was OOM-killed')
            smoke.require(log_path.stat().st_size <= 2 * smoke.MIB, 'Final container output limit exceeded')
            lines = log_path.read_text().splitlines()
            result = json.loads(lines[-1])
            smoke.require(result.get('success') is True and result.get('physics_executed') is True,
                          'No successful runtime verification report')
            report['runtime'] = result
            report['success'] = True
        finally:
            if created:
                try:
                    docker('stop', '--time', '3', name)
                    docker('rm', name)
                except Exception as error:
                    cleanup_ok = False
                    report['cleanup_error'] = str(error)
            if attach is not None:
                try:
                    attach.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    attach.terminate()
                    attach.wait(timeout=3)
            report['cleanup_ok'] = cleanup_ok
            if not cleanup_ok:
                report['success'] = False
            (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    except Exception as error:
        report['success'] = False
        report['error'] = str(error)
    if audit_created:
        (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
