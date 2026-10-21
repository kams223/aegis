"""Synthetic fixtures exercise rejection logic only; integration evidence is separate."""
import importlib.util
import sys
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

HERE=Path(__file__).resolve().parents[1]/'simulation/gazebo-smoke'

@pytest.fixture
def sensors(monkeypatch):
    for name in ('smoke','launch','experimental','aircraft','sensor_checks','sensors'):
        spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
        mod=importlib.util.module_from_spec(spec); monkeypatch.setitem(sys.modules,name,mod);spec.loader.exec_module(mod)
    return mod


def samples():
    poses=[dict(time_ns=t*1000000,frame="aegis_sensor_aircraft",x=0,y=0,z=0,qx=0,qy=0,qz=0,qw=1) for t in range(0,2001,10)]
    streams={}
    for name,hz in [('imu',100),('gnss',20),('barometer',50)]:
        rows=[]
        for t in range(0,2000,1000//hz):
            row=dict(time_ns=t*1000000,header_frames=['passive_aircraft::body::'+name])
            if name=='imu':row.update(acceleration=[0,0,0 if t<400 else 9.81],angular_velocity=[0,0,0],orientation=[0,0,0,1])
            elif name=='gnss':row.update(latitude=0,longitude=0,altitude=0,message_frame="passive_aircraft::body::gnss")
            else:row.update(pressure=101325,variance=0)
            rows.append(row)
        streams[name]=rows
    return streams,poses


def test_definitions_and_baseline_identity(sensors):
    sensors.aircraft.profile(); sensors.profile()
    model=ET.parse(HERE/'sensor-aircraft.sdf');base=ET.parse(HERE/'passive-aircraft.sdf')
    for sensor in list(model.findall('model/link/sensor')):
        if sensor.get('name')!='ground_contact':model.find('model/link').remove(sensor)
    ET.indent(model); ET.indent(base)
    assert ET.tostring(model.getroot())==ET.tostring(base.getroot())
    model=ET.parse(HERE/'sensor-aircraft.sdf')
    for name,cfg in sensors.SENSOR_CONFIG.items():
        s=model.find("model/link/sensor[@name='"+name+"']")
        assert s.findtext('topic')==cfg['topic'] and float(s.findtext('update_rate'))==cfg['rate_hz']
        assert s.findtext('pose')=='0 0 0 0 0 0'
    world=ET.parse(HERE/'sensor-aircraft-world.sdf')
    assert world.findtext('world/spherical_coordinates/elevation')=='0'
    assert world.findtext('world/spherical_coordinates/world_frame_orientation')=='ENU'
    assert {p.get('name') for p in world.findall('world/plugin')} >= {'gz::sim::systems::Imu','gz::sim::systems::NavSat','gz::sim::systems::AirPressure'}


def test_valid_checker_fixture_and_units(sensors):
    streams,poses=samples()
    assert sensors.analyze_sensors(streams,poses)['passed']
    assert sensors.SENSOR_CONFIG['imu']['units']['acceleration']=='m/s^2'
    assert sensors.SENSOR_CONFIG['barometer']['units']['pressure']=='Pa'
    assert sensors.SENSOR_CONFIG['gnss']['message']=='gz.msgs.NavSat'
    assert sys.modules['sensor_checks'].pressure_altitude(101325)==pytest.approx(0)

@pytest.mark.parametrize('mutation',['missing','duplicate','regression','nan','frame','dropout','delay','tail','latitude','altitude','pressure','quaternion','force','truth'])
def test_invalid_observations(sensors,mutation):
    s,p=samples()
    if mutation=='missing':s['imu']=[]
    elif mutation=='duplicate':s['imu'][1]['time_ns']=0
    elif mutation=='regression':s['gnss'].reverse()
    elif mutation=='nan':s['imu'][0]['acceleration'][0]=math.nan
    elif mutation=='frame':s['barometer'][0]['header_frames']=[]
    elif mutation=='dropout':del s['barometer'][5]
    elif mutation=='delay':s['gnss']=s['gnss'][3:]
    elif mutation=='tail':s['gnss']=s['gnss'][:-4]
    elif mutation=='latitude':s['gnss'][0]['latitude']=100
    elif mutation=='altitude':s['gnss'][0]['altitude']=4
    elif mutation=='pressure':s['barometer'][0]['pressure']=0
    elif mutation=='quaternion':s['imu'][0]['orientation'][3]=2
    elif mutation=='force':s['imu'][10]['acceleration'][2]=9.81
    elif mutation=='truth':p=[]
    assert not sensors.analyze_sensors(s,p)['passed']

# Exercise the inherited orchestration with this phase's actual module and command.
from test_passive_aircraft import test_owned_cleanup_and_isolation_with_mocked_docker as cleanup_check
@pytest.mark.parametrize('physics_passes',[False,True])
def test_cleanup_policy(sensors,monkeypatch,tmp_path,physics_passes):
    cleanup_check(sensors,monkeypatch,tmp_path,physics_passes)

@pytest.mark.parametrize('name',['imu','gnss','barometer'])
def test_missing_message_timestamp_rejected(sensors,name):
    class Missing:
        def HasField(self,field): return False
    with pytest.raises(ValueError,match='timestamp'): sensors.decode_sensor(name,Missing())


def test_host_timeout_cleans_owned_container(sensors,monkeypatch,tmp_path):
    calls=[]
    image='sha256:'+'a'*64
    monkeypatch.setattr(sensors.launch,'resources',lambda _: (3*1024**3,0,10*1024**3,2))
    def docker(*args):
        calls.append(args)
        data=json.dumps([dict(RepoDigests=[sensors.IMAGE],Architecture='amd64',Os='linux',Id=image)]) if args[:2]==('image','inspect') else ''
        return subprocess.CompletedProcess(args,0,stdout=data)
    import json,subprocess
    monkeypatch.setattr(sensors.launch,'docker',docker)
    monkeypatch.setattr(sensors.subprocess,'run',lambda *a,**k:None)
    class Attached:
        def __init__(self,*a,**k):pass
        def poll(self):return None
        def wait(self,timeout):return 0
    monkeypatch.setattr(sensors.subprocess,'Popen',Attached)
    ticks=iter([0,60]);monkeypatch.setattr(sensors.time,'monotonic',lambda:next(ticks))
    assert sensors.run(tmp_path/'audit',str(tmp_path))==2
    r=json.loads((tmp_path/'audit/report.json').read_text())
    assert r['cleanup_ok'] and r['error']=='Host wall timeout'
    assert ('rm',r['container_name']) in calls


def test_rejected_nonfinite_samples_remain_strict_json(sensors):
    import json
    value=sensors.json_safe({'raw':[math.nan,math.inf,-math.inf]})
    assert json.loads(json.dumps(value,allow_nan=False))['raw'][0]=={'invalid_float':'nan'}


def test_bad_vector_shape_rejected(sensors):
    s,p=samples();s['imu'][0]['orientation']=[1]
    assert not sensors.analyze_sensors(s,p)['passed']


def test_pressure_inverse_independent_reference(sensors):
    # Standard-atmosphere reference at 100 m (Pa); cm tolerance permits rounding.
    assert sys.modules['sensor_checks'].pressure_altitude(100129.46)==pytest.approx(100,abs=.02)


def test_new_world_identity_adapter(sensors):
    from test_passive_aircraft import fixture
    p,c,t=fixture()
    with pytest.raises(ValueError,match='frame'):sensors.verdict(p,c,t,0,False)
    for row in p:row['frame']='aegis_sensor_aircraft'
    result=sensors.verdict(p,c,t,0,False)
    assert result['passed'] and result['initial_pose']['frame']=='aegis_sensor_aircraft'
    assert p[0]['frame']=='aegis_sensor_aircraft'


@pytest.mark.skipif(__import__('os').environ.get('AEGIS_REAL_GAZEBO')!='1',reason='Explicit opt-in for bounded real sensors')
def test_real_sensor_transport(tmp_path):
    import os,subprocess,json
    result=subprocess.run([sys.executable,'-B',str(HERE/'sensors.py'),'--run','--disk-path',
        os.environ.get('AEGIS_DISK_PATH','/'),'--output-dir',str(tmp_path/'real')],capture_output=True,text=True,timeout=80)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads((tmp_path/'real/report.json').read_text())
    assert report['success'] and report['cleanup_ok']
    assert report['evidence']['sensor_analysis']['passed'] and report['evidence']['synthetic'] is False

@pytest.mark.parametrize('name',['imu','gnss','barometer'])
def test_native_message_schema_decode(sensors,name):
    from types import SimpleNamespace as N
    class Message(N):
        def HasField(self,field):return hasattr(self,field)
    stamp=Message(sec=1,nsec=123)
    message=Message(header=Message(stamp=stamp,data=[N(key='frame_id',value=['native'])]),
                    linear_acceleration=N(x=1,y=2,z=3),angular_velocity=N(x=4,y=5,z=6),
                    orientation=N(x=0,y=0,z=0,w=1),latitude_deg=0,longitude_deg=0,
                    altitude=1,frame_id='gnss-native',pressure=101325,variance=0)
    row=sensors.decode_sensor(name,message)
    assert row['time_ns']==1000000123
    if name=='imu':assert row['acceleration']==[1,2,3] and row['orientation']==[0,0,0,1]
    elif name=='gnss':assert row['altitude']==1 and row['message_frame']=='gnss-native'
    else:assert row['pressure']==101325 and 'altitude' not in row
    stamp.nsec=10**9
    with pytest.raises(ValueError,match='timestamp'):sensors.decode_sensor(name,message)


@pytest.mark.parametrize('mode',['exit','startup_timeout','ready'])
def test_server_readiness_failure_and_timeout(sensors,monkeypatch,mode):
    from types import SimpleNamespace
    server=SimpleNamespace(poll=lambda: 1 if mode=='exit' else None)
    monkeypatch.setattr(sensors.time,'monotonic',lambda:16 if mode=='startup_timeout' else 0)
    report={'timed_out':False}
    if mode=='ready':sensors.wait_for_start(server,lambda:True,0,report)
    else:
        with pytest.raises(ValueError,match='startup timeout' if mode=='startup_timeout' else 'exited'):
            sensors.wait_for_start(server,lambda:False,0,report)
    assert report['timed_out'] is (mode=='startup_timeout')


@pytest.mark.parametrize('mode',['timeout','callback','memory','log'])
def test_server_monitor_failure_diagnostics(sensors,monkeypatch,tmp_path,mode):
    from types import SimpleNamespace
    server=SimpleNamespace(poll=lambda:None)
    log=tmp_path/'server.log';log.write_bytes(b'x'*(sensors.smoke.MIB+1) if mode=='log' else b'')
    monkeypatch.setattr(sensors.time,'monotonic',lambda:36 if mode=='timeout' else 0)
    monkeypatch.setattr(sensors.smoke,'read_cgroup',lambda _:sensors.smoke.GIB if mode=='memory' else 0)
    report={'timed_out':False}
    expected={'timeout':'wall timeout','callback':'callback failed','memory':'Memory reserve','log':'log limit'}[mode]
    with pytest.raises(ValueError,match=expected):
        sensors.monitor_server(server,log,0,sensors.profile(),report,lambda:['malformed IMU'] if mode=='callback' else [])
    assert report['timed_out'] is (mode=='timeout')


@pytest.mark.parametrize('mode',['empty_log','startup_error','malformed_json','create_timeout','cleanup_error'])
def test_host_startup_failures_keep_report_and_attempt_cleanup(sensors,monkeypatch,tmp_path,mode):
    import json,subprocess
    calls=[];image='sha256:'+'b'*64
    monkeypatch.setattr(sensors.launch,'resources',lambda _: (3*1024**3,0,10*1024**3,2))
    def docker(*args):
        calls.append(args)
        if args[:2]==('image','inspect'):
            data=[dict(RepoDigests=[sensors.IMAGE],Architecture='amd64',Os='linux',Id=image)]
        elif args[:1]==('inspect',):
            keys=('NetworkMode','Memory','MemorySwap','NanoCpus','PidsLimit','Privileged','ReadonlyRootfs','CapDrop','SecurityOpt','Devices','PortBindings')
            data=[dict(State=dict(OOMKilled=False,ExitCode=2 if mode=='startup_error' else 0,Error=''),HostConfig=dict.fromkeys(keys))]
        elif args[:1]==('rm',) and mode=='cleanup_error': raise RuntimeError('removal failed')
        else:return subprocess.CompletedProcess(args,0,stdout='')
        return subprocess.CompletedProcess(args,0,stdout=json.dumps(data))
    monkeypatch.setattr(sensors.launch,'docker',docker)
    def create(*args,**kwargs):
        if mode=='create_timeout':raise subprocess.TimeoutExpired(args[0],10)
    monkeypatch.setattr(sensors.subprocess,'run',create)
    class Attached:
        returncode=0
        def __init__(self,args,**kwargs):
            data=(b'' if mode=='empty_log' else b'not json\n' if mode=='malformed_json' else
                  json.dumps({'success':False,'error':'sensor module unavailable'}).encode()+b'\n' if mode=='startup_error' else
                  json.dumps({'success':True,'synthetic':False,'evidence_kind':'real_gazebo_transport'}).encode()+b'\n')
            kwargs['stdout'].write(data)
        def poll(self):return 0
        def wait(self,timeout):return 0
    monkeypatch.setattr(sensors.subprocess,'Popen',Attached)
    assert sensors.run(tmp_path/'audit',str(tmp_path))==2
    r=json.loads((tmp_path/'audit/report.json').read_text())
    assert not r['success']
    assert ('stop','--time','3',r['container_name']) in calls
    assert ('rm',r['container_name']) in calls
    assert r['cleanup_ok'] is (mode!='cleanup_error')
    if mode=='empty_log':assert 'no runtime report' in r['error']
    if mode=='startup_error':assert 'sensor module unavailable' in r['error']


@pytest.mark.parametrize('mode',['streams','rows','row','vector','truth_nan','truth_frame','truth_regression'])
def test_malformed_observation_collection_rejected(sensors,mode):
    s,p=samples()
    if mode=='streams':s=None
    elif mode=='rows':s['imu']=None
    elif mode=='row':s['imu'][0]=None
    elif mode=='vector':s['imu'][0]['acceleration']=None
    elif mode=='truth_nan':p[0]['z']=math.nan
    elif mode=='truth_frame':p[0]['frame']='body_flu'
    elif mode=='truth_regression':p[1]['time_ns']=p[0]['time_ns']
    assert not sensors.analyze_sensors(s,p)['passed']


def test_geographic_axes_and_nearest_pose_alignment(sensors):
    s,p=samples()
    for pose in p:pose.update(x=.02,y=.01)
    for row in s['gnss']:row.update(longitude=.02/6378137*180/math.pi,latitude=.01/6335439*180/math.pi)
    assert sensors.analyze_sensors(s,p)['comparisons']['gnss']['max_position_residual_m'] < 1e-10
    for row in s['gnss']:row['longitude']=1/6378137*180/math.pi
    assert not sensors.analyze_sensors(s,p)['passed']
    s,p=samples()
    assert not sensors.analyze_sensors(s,p[5:])['passed']


def test_imu_inverse_rotation_and_supported_force_direction(sensors):
    check=sys.modules['sensor_checks']
    # Body +90 degrees around x: world up is body +y.
    q=[math.sqrt(.5),0,0,math.sqrt(.5)]
    assert check.world_to_sensor([0,0,9.81],q)==pytest.approx([0,9.81,0],abs=1e-12)
    s,p=samples()
    for row in s['imu']:
        if row['time_ns']>=1500000000:row['acceleration']=[0,0,-9.81]
    result=sensors.analyze_sensors(s,p)
    assert not result['passed']
    assert result['comparisons']['imu']['settled_max_specific_force_vector_error_m_s2']==pytest.approx(19.62)
