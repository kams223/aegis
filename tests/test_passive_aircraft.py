"""Synthetic checker tests are distinct from the explicitly enabled real Docker test."""
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'simulation/gazebo-smoke'


@pytest.fixture
def aircraft(monkeypatch):
    for name in ('smoke', 'launch', 'experimental', 'aircraft'):
        spec = importlib.util.spec_from_file_location(name, RUNTIME / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return module


def fixture():
    poses = [dict(time_ns=ms*1000000, frame='aegis_passive_aircraft', name='passive_aircraft',
                  x=0., y=0., z=max(.08, 1-4.905*(ms/1000)**2), qx=0., qy=0., qz=0., qw=1.)
             for ms in range(10,2001,10)]
    clocks = [dict(time_ns=0, iterations=0, paused=True)] + [
        dict(time_ns=ms*1000000, iterations=ms, paused=False) for ms in (100,500,1500,1990)]
    contacts = [dict(time_ns=ms*1000000, collision1='ground::plane::ground_collision',
                     collision2='passive_aircraft::body::fuselage_collision',
                     positions=[dict(x=0., y=0., z=0.)], depths=[.00001]) for ms in (440,1600,1990)]
    return poses, clocks, contacts


def test_profile_identity_and_read_only_default(aircraft, monkeypatch, capsys):
    p=aircraft.profile()
    assert p['phase74a_compatible'] is False
    assert p['image'] == aircraft.experimental.IMAGE
    assert p['iterations'] == 2000 and p['memory_bytes'] == 1024**3
    monkeypatch.setattr(sys, 'argv', ['aircraft.py'])
    monkeypatch.setattr(subprocess, 'run', lambda *a,**k: pytest.fail('Unexpected execution'))
    assert aircraft.main() == 0
    assert json.loads(capsys.readouterr().out) == p


def test_model_mass_inertia_geometry_and_passivity():
    model=ET.parse(RUNTIME/'passive-aircraft.sdf').getroot()
    link=model.find('model/link')
    assert float(link.findtext('inertial/mass')) == 2
    assert list(map(float,link.findtext('inertial/pose').split())) == pytest.approx([-.048,0,.027,0,0,0])
    # Independent composite-body calculation, with the parallel-axis theorem.
    parts=[(1.2,(0,0,0),(1.2,.12,.16)),(.6,(0,0,.06),(.24,1.8,.04)),
           (.15,(-.48,0,.06),(.18,.6,.03)),(.05,(-.48,0,.18),(.18,.03,.24))]
    center = tuple(sum(m*c[k] for m,c,_ in parts)/sum(m for m,_,_ in parts) for k in range(3))
    assert center == pytest.approx((-.048, 0, .027))
    for collision, (_, position, size) in zip(link.findall('collision'), parts):
        assert tuple(map(float, collision.findtext('pose').split()[:3])) == position
        assert tuple(map(float, collision.findtext('geometry/box/size').split())) == size
    for tag,a,b in [('ixx',0,0),('iyy',1,1),('izz',2,2),('ixy',0,1),('ixz',0,2),('iyz',1,2)]:
        expected=0
        for m,c,size in parts:
            d=[c[k]-center[k] for k in range(3)]
            expected+=m*(sum(size[k]**2/12+d[k]**2 for k in range(3) if k!=a) if a==b else -d[a]*d[b])
        assert float(link.findtext('inertial/inertia/'+tag)) == pytest.approx(expected,abs=1e-12)
    ixx,iyy,izz=[float(link.findtext('inertial/inertia/'+k)) for k in ('ixx','iyy','izz')]
    ixz=float(link.findtext('inertial/inertia/ixz'))
    principal = [iyy, (ixx+izz-math.sqrt((ixx-izz)**2+4*ixz**2))/2,
                 (ixx+izz+math.sqrt((ixx-izz)**2+4*ixz**2))/2]
    assert min(principal)>0 and 2*max(principal) <= sum(principal)
    assert len(link.findall('collision')) == len(link.findall('visual')) == 4
    for c,v in zip(link.findall('collision'),link.findall('visual')):
        assert c.findtext('pose') == v.findtext('pose')
        assert c.findtext('geometry/box/size') == v.findtext('geometry/box/size')
    assert len(link.findall('sensor/contact/collision')) == 4
    assert all(not list(model.iter(t)) for t in ('joint','actor','include','uri'))
    assert {p.attrib['filename'] for p in model.iter('plugin')} == {'gz-sim-pose-publisher-system'}
    world=ET.parse(RUNTIME/'passive-aircraft-world.sdf').getroot().find('world')
    assert world.attrib['name']=='aegis_passive_aircraft'
    assert world.findtext('gravity')=='0 0 -9.81'
    assert world.findtext('include/uri')=='file:///opt/aegis/passive-aircraft.sdf'
    assert world.findtext('include/pose')=='0 0 1 0 0 0'
    assert len(world.findall('include')) == len(world.findall('model')) == 1
    assert {p.attrib['filename'] for p in world.iter('plugin')} == {'gz-sim-physics-system','gz-sim-contact-system'}


def test_synthetic_verdict_and_velocity_provenance(aircraft):
    poses,clocks,contacts=fixture()
    result=aircraft.verdict(poses,clocks,contacts,0,False)
    assert result['passed'] and result['settled'] and 'evidence_kind' not in result
    v=aircraft.derived_velocities(poses)
    assert len(v)==len(poses)-1
    assert v[0]['z']==pytest.approx((poses[1]['z']-poses[0]['z'])/.01)
    assert v[-1]['z']==0


@pytest.mark.parametrize('mutation',['missing_pose','missing_clock','missing_contact','wrong_model','wrong_frame',
    'nan','bad_quaternion','bad_initial_orientation','late_initial','no_fall','clock_regression','bad_iteration',
    'wrong_contact','wrong_contact_scope','empty_depth','nan_contact','bad_depth','no_late_contact','no_late_pose','unstable','exit','timeout'])
def test_incomplete_or_invalid_evidence_fails(aircraft,mutation):
    p,c,t=fixture();code=0;timeout=False
    if mutation=='missing_pose': p=[]
    elif mutation=='missing_clock': c=[]
    elif mutation=='missing_contact': t=[]
    elif mutation=='wrong_model': p[0]['name']='other'
    elif mutation=='wrong_frame': p[0]['frame']='other'
    elif mutation=='nan': p[0]['z']=math.nan
    elif mutation=='bad_quaternion': p[0]['qw']=2.
    elif mutation=='bad_initial_orientation': p[0].update(qz=1.,qw=0.)
    elif mutation=='late_initial': p=p[5:]
    elif mutation=='no_fall':
        for row in p: row['z']=1.
    elif mutation=='clock_regression': c.reverse()
    elif mutation=='bad_iteration': c[-1]['iterations']-=1
    elif mutation=='wrong_contact': t[0]['collision2']='other'
    elif mutation=='wrong_contact_scope': t[0]['collision2']='other_aircraft::body::fuselage_collision'
    elif mutation=='empty_depth': t[0]['depths']=[]
    elif mutation=='nan_contact': t[0]['positions'][0]['z']=math.nan
    elif mutation=='bad_depth': t[0]['depths']=[-.1]
    elif mutation=='no_late_contact': t=t[:1]
    elif mutation=='no_late_pose': p=p[:160]
    elif mutation=='unstable':
        for n,row in enumerate(p[150:]): row['x']=.004*(n%2)
    elif mutation=='exit': code=-9
    elif mutation=='timeout': timeout=True
    with pytest.raises(ValueError): aircraft.verdict(p,c,t,code,timeout)


def test_model_hash_change_fails_before_launch(aircraft,monkeypatch):
    original=aircraft.smoke.digest
    monkeypatch.setattr(aircraft.smoke,'digest',lambda p:'0'*64 if p.name=='passive-aircraft.sdf' else original(p))
    with pytest.raises(ValueError,match='model hash'): aircraft.profile()


@pytest.mark.skipif(os.environ.get('AEGIS_REAL_GAZEBO')!='1', reason='Explicit opt-in required for bounded real Docker physics')
def test_real_bounded_passive_aircraft(tmp_path):
    result=subprocess.run([sys.executable,'-B',str(RUNTIME/'aircraft.py'),'--run',
        '--disk-path',os.environ.get('AEGIS_DISK_PATH','/mnt/c'),'--output-dir',str(tmp_path/'real')],
        capture_output=True,text=True,timeout=80)
    assert result.returncode==0, result.stdout+result.stderr
    report=json.loads((tmp_path/'real/report.json').read_text())
    assert report['success'] and report['cleanup_ok']
    assert report['evidence']['synthetic'] is False
    assert report['evidence']['verdict']['passed']
    assert report['evidence']['server_exit_code']==report['container_state']['ExitCode']==0


@pytest.mark.parametrize('physics_passes',[False,True])
def test_owned_cleanup_and_isolation_with_mocked_docker(aircraft,monkeypatch,tmp_path,physics_passes):
    calls=[]
    image='sha256:'+'a'*64
    monkeypatch.setattr(aircraft.launch,'resources',lambda _: (3*1024**3,1024**3,10*1024**3,2))
    def docker(*args):
        calls.append(args)
        data=''
        if args[:2]==('image','inspect'):
            data=json.dumps([dict(RepoDigests=[aircraft.IMAGE],Architecture='amd64',Os='linux',Id=image)])
        elif args[:1]==('inspect',):
            keys=('NetworkMode','Memory','MemorySwap','NanoCpus','PidsLimit','Privileged','ReadonlyRootfs','CapDrop','SecurityOpt','Devices','PortBindings')
            data=json.dumps([dict(State=dict(OOMKilled=False,ExitCode=0,Error=''),HostConfig=dict.fromkeys(keys))])
        return subprocess.CompletedProcess(args,0,stdout=data)
    monkeypatch.setattr(aircraft.launch,'docker',docker)
    monkeypatch.setattr(subprocess,'run',lambda args,**kw: calls.append(tuple(args)))
    class Attached:
        returncode=0
        def __init__(self,args,**kw):
            kw['stdout'].write(json.dumps(dict(evidence_kind='real_gazebo_transport',synthetic=False,success=physics_passes)).encode()+b'\n')
        def poll(self): return 0
        def wait(self,timeout): return 0
    monkeypatch.setattr(subprocess,'Popen',Attached)
    output=tmp_path/'audit'
    assert aircraft.run(output,str(tmp_path)) == (0 if physics_passes else 2)
    report=json.loads((output/'report.json').read_text())
    assert report['cleanup_ok'] and report['success'] is physics_passes
    name=report['container_name']
    assert ('stop','--time','3',name) in calls and ('rm',name) in calls
    command=next(c for c in calls if c[:2]==('docker','create'))
    for option in ('--network=none','--cpus=1','--memory=1g','--pids-limit=128','--read-only','--cap-drop=ALL'):
        assert option in command
    assert command[command.index('--mount')+1].endswith('target=/opt/aegis,readonly')
    assert not any(v.startswith(('--device','--publish','--privileged')) for v in command)


def test_summary_has_portable_paths_and_qualified_claims():
    summary = json.loads((RUNTIME/'passive-aircraft-results.json').read_text())
    assert summary['artifact_kind'] == 'measured_summary'
    assert summary['raw_artifacts_tracked'] is False
    def inspect(value):
        if isinstance(value, dict):
            for child in value.values(): inspect(child)
        elif isinstance(value, list):
            for child in value: inspect(child)
        elif isinstance(value, str):
            assert not re.search(r'(?:^|[\s=])/(?!/)', value), value
            assert not re.search(r'[A-Za-z]:[\\/]', value), value
    inspect(summary)
    failed = [r for r in summary['runs'] if not r['success']]
    assert len(failed) >= 2 and all(r['error'] and r['cleanup_ok'] for r in failed)
