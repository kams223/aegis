"""Atomic event replay, explicit rejections and deterministic offline reports."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.platform import contracts as c
from aegis.platform import monitoring as m
from aegis.platform.snapshot import snapshot_document, snapshot_from_document
from examples import platform_monitoring_demo as demo

ROOT=Path(__file__).resolve().parents[1]


def samples():
    initial,events=demo.demo_inputs()
    return events[:6]


@pytest.mark.parametrize('event',samples(),ids=lambda e:e.event_type)
def test_event_immutable_closed_owned_roundtrip(event):
    doc=c.to_document(event);before=deepcopy(doc)
    assert m.event_from_document(doc)==event and doc==before
    assert c.parse_json(type(event),json.dumps(doc).encode())==event
    doc['payload'].clear()
    assert c.to_document(event)==before
    with pytest.raises(FrozenInstanceError):event.event_id='changed'


@pytest.mark.parametrize('event',samples(),ids=lambda e:e.event_type)
@pytest.mark.parametrize('case',['version','bool_version','unknown_type','missing','extra','payload_type','payload_extra','bad_unit','nonfinite','long_id'])
def test_event_schema_rejects_invalid_values(event,case):
    doc=c.to_document(event)
    if case=='version':doc['schema_version']=2
    elif case=='bool_version':doc['schema_version']=True
    elif case=='unknown_type':doc['event_type']='dispatch'
    elif case=='missing':del doc['device_id']
    elif case=='extra':doc['heading']=0
    elif case=='payload_type':doc['payload']=[]
    elif case=='payload_extra':doc['payload']['target_coordinates']=[1,2]
    elif case=='bad_unit':doc['timestamp']['unit']='seconds'
    elif case=='nonfinite':doc['timestamp']['value']=float('inf')
    else:doc['event_id']='x'*129
    with pytest.raises(c.PlatformContractError):m.event_from_document(doc)


def test_demo_order_summary_relations_and_complete_final_snapshot():
    initial,events=demo.demo_inputs();before=deepcopy((initial,events))
    session=m.reduce_session(initial,events)
    assert session==m.reduce_session(initial,events) and (initial,events)==before
    assert session.summary.event_count==7 and session.summary.applied_count==6 and session.summary.rejected_count==1
    assert [r.event_id for r in session.event_results]==[e.event_id for e in events]
    assert [r.event_index for r in session.event_results]==list(range(7))
    assert session.event_results[-1].diagnostics[0].code=='CONFLICTING_UPDATE'
    final=session.final_snapshot
    assert final.registry.devices[0].connection_status==final.sentinels[0].connectivity=='recorded'
    assert final.registry.devices[0].health.status=='degraded' and final.sentinels[1].sensors[0].status=='unavailable'
    assert final.observations[-1].review_status=='reviewed' and final.observations[-1].quality=='uncertain'
    assert final.investigation_results[-1].status=='completed'
    assert final.review_history[-1].reviewer_id=='synthetic-operator'
    assert final.audit_entries[-1].reference_id==final.review_history[-1].decision_id
    assert snapshot_from_document(snapshot_document(final))==final
    assert c.from_document(m.MonitoringSession,c.to_document(session))==session


def test_empty_and_container_bounds_are_whole_session_errors():
    initial,events=demo.demo_inputs()
    assert m.reduce_session(initial,()).final_snapshot==initial
    for bad in (list(events),events*257,(events[0],{})):
        with pytest.raises(c.PlatformContractError):m.reduce_session(initial,bad)
    with pytest.raises(c.PlatformContractError):m.reduce_session({},())


def result(initial,event):
    session=m.reduce_session(initial,(event,))
    assert session.final_snapshot==initial and session.summary.rejected_count==1
    return session.event_results[0].diagnostics[0].code


@pytest.mark.parametrize('case,code',[
    ('unknown_device','UNKNOWN_DEVICE'),('foreign_source','SOURCE_ASSOCIATION'),('clock','CLOCK_DOMAIN_MISMATCH'),
    ('regression','TIMESTAMP_REGRESSION'),('connect_conflict','CONFLICTING_UPDATE'),('health_conflict','CONFLICTING_UPDATE'),
    ('availability_conflict','CONFLICTING_UPDATE'),('monitor_unavailable','MONITOR_UNAVAILABLE'),
    ('duplicate_evidence','DUPLICATE_EVIDENCE_ID'),('duplicate_observation','DUPLICATE_OBSERVATION_ID'),
    ('dangling_evidence','SNAPSHOT_REJECTED'),('review_source','REVIEW_ASSOCIATION')])
def test_individual_rejection_reasons_and_atomicity(case,code):
    initial,events=demo.demo_inputs();event=events[0]
    if case=='unknown_device':event=replace(event,device_id='absent')
    elif case=='foreign_source':event=replace(events[3],source_id='metadata-g',payload=replace(events[3].payload,source_id='metadata-g'))
    elif case=='clock':event=replace(event,timestamp=replace(event.timestamp,clock_domain='other:clock'))
    elif case=='regression':event=replace(event,timestamp=replace(event.timestamp,value=-1))
    elif case=='connect_conflict':event=replace(event,payload=m.ConnectivityPayload(previous_status='recorded',current_status='unknown'))
    elif case=='health_conflict':event=replace(events[1],payload=replace(events[1].payload,previous_health=replace(events[1].payload.previous_health,status='healthy')))
    elif case=='availability_conflict':event=replace(events[2],payload=replace(events[2].payload,previous_status='available'))
    elif case=='monitor_unavailable':
        event=m.AvailabilityEvent(event_id='unsupported-monitor',event_type='sensor_availability',device_id='third-party',source_id='display-r',timestamp=c.Timestamp(value=8,unit='s',clock_domain='demo:display-r'),payload=m.AvailabilityPayload(previous_status='unknown',availability=c.SensorAvailability(source_id='display-r',status='available')))
    elif case=='duplicate_evidence':event=replace(events[3],payload=initial.evidence[0])
    elif case=='duplicate_observation':
        obs=replace(initial.observations[1],timestamp=events[4].timestamp)
        event=replace(events[4],payload=replace(events[4].payload,observation=obs))
    elif case=='dangling_evidence':event=replace(events[4],payload=replace(events[4].payload,observation=replace(events[4].payload.observation,evidence_id='absent')))
    else:event=events[5] # new subject has not been announced
    assert result(initial,event)==code


def test_duplicate_id_reserved_after_rejection_without_clock_advance():
    initial,events=demo.demo_inputs()
    bad=replace(events[0],payload=m.ConnectivityPayload(previous_status='recorded',current_status='unknown'),timestamp=replace(events[0].timestamp,value=100))
    duplicate=replace(events[0],event_id=bad.event_id)
    later=replace(events[0],event_id='fresh-id')
    session=m.reduce_session(initial,(bad,duplicate,later))
    assert [r.status for r in session.event_results]==['rejected','rejected','applied']
    assert session.event_results[1].diagnostics[0].code=='DUPLICATE_EVENT_ID'
    assert session.final_snapshot==m.reduce_session(initial,(later,)).final_snapshot


def test_exact_mixed_unit_clock_order_and_no_cross_domain_alignment():
    initial,events=demo.demo_inputs()
    a=events[0]
    b=replace(events[1],timestamp=replace(events[1].timestamp,value=1000,unit='ms'),
        payload=replace(events[1].payload,current_health=replace(events[1].payload.current_health,timestamp=c.Timestamp(value=1000,unit='ms',clock_domain='demo:camera-a'))))
    session=m.reduce_session(initial,(a,b,events[2]))
    assert all(r.status=='applied' for r in session.event_results)
    old=replace(a,event_id='old',timestamp=replace(a.timestamp,value=999,unit='ms'),payload=m.ConnectivityPayload(previous_status='recorded',current_status='unknown'))
    assert m.reduce_session(initial,(a,old)).event_results[1].diagnostics[0].code=='TIMESTAMP_REGRESSION'


def test_event_order_not_repaired_and_bundle_atomic_when_duplicate_alert():
    initial,events=demo.demo_inputs()
    wrong=replace(events[4],payload=replace(events[4].payload,alerts=(replace(events[4].payload.alerts[0],alert_id=initial.alerts[0].alert_id),),investigations=(),copilot_actor_id=None,investigation_audit_id=None))
    assert result(initial,wrong)=='SNAPSHOT_REJECTED'
    forward=m.reduce_session(initial,(events[4],events[5]))
    reverse=m.reduce_session(initial,(events[5],events[4]))
    assert forward.final_snapshot.observations[-1].review_status=='reviewed'
    assert reverse.final_snapshot.observations[-1].review_status=='unreviewed'
    assert reverse.event_results[0].status=='rejected'


def test_missing_sensor_measurements_cannot_be_declared_quality():
    initial,events=demo.demo_inputs()
    obs=replace(initial.observations[0],observation_id='new-ground',timestamp=c.Timestamp(value=4,unit='s',clock_domain='demo:metadata-g'))
    event=m.ObservationEvent(event_id='ground-observation',event_type='observation_announcement',device_id='simulated-ground',source_id='metadata-g',timestamp=obs.timestamp,payload=m.ObservationPayload(observation=obs,alerts=(),investigations=(),copilot_actor_id=None,investigation_audit_id=None))
    assert result(initial,event)=='UNAVAILABLE_MEASUREMENT'
    missing=replace(event,payload=replace(event.payload,observation=replace(obs,quality='missing',uncertainty_note='Not measured.')))
    assert m.reduce_session(initial,(missing,)).event_results[0].status=='applied'


def test_reviews_and_invalid_transition_rejected():
    initial,events=demo.demo_inputs();session=m.reduce_session(initial,events[:6])
    repeat=replace(events[5],event_id='repeat-review',timestamp=replace(events[5].timestamp,value=6),
        payload=replace(events[5].payload,decision=replace(events[5].payload.decision,decision_id='repeat-decision',timestamp=replace(events[5].timestamp,value=6))))
    assert result(session.final_snapshot,repeat)=='CONFLICTING_UPDATE'
    with pytest.raises(c.PlatformContractError):
        replace(events[5].payload.decision,previous_status='reviewed',new_status='under_review')
    with pytest.raises(c.PlatformContractError):replace(events[5],timestamp=replace(events[5].timestamp,value=7))


def test_evidence_before_observation_and_unsafe_reference_rejection():
    initial,events=demo.demo_inputs();reference=replace(initial.evidence[2],evidence_id='new-evidence')
    announcement=m.EvidenceEvent(event_id='new-evidence-event',event_type='evidence_announcement',device_id='third-party',source_id='display-r',timestamp=c.Timestamp(value=3,unit='s',clock_domain='demo:display-r'),payload=reference)
    obs_event=replace(events[4],payload=replace(events[4].payload,observation=replace(events[4].payload.observation,evidence_id=reference.evidence_id),alerts=(),investigations=(),copilot_actor_id=None,investigation_audit_id=None))
    assert result(initial,obs_event)=='SNAPSHOT_REJECTED'
    assert all(r.status=='applied' for r in m.reduce_session(initial,(announcement,obs_event)).event_results)
    for path in ('../a','/tmp/a','https://example.com/a','a\\b'):
        with pytest.raises(c.PlatformContractError):replace(reference,local_path=path)


def test_no_silent_rewriting_of_existing_health_investigation():
    initial,events=demo.demo_inputs()
    from aegis.platform.investigation import investigate
    req=replace(initial.investigation_requests[0],action='summarize_device_health',reference_ids=('native-aerial',))
    res=investigate(req,registry=initial.registry,observations=initial.observations,evidence=initial.evidence,validation_results=())
    initial=replace(initial,investigation_requests=(req,),investigation_results=(res,))
    assert result(initial,events[1])=='SNAPSHOT_REJECTED'


def test_summary_and_result_schema_consistency():
    session=demo.demo_session()
    with pytest.raises(c.PlatformContractError):replace(session.summary,applied_count=0)
    with pytest.raises(c.PlatformContractError):replace(session,event_results=tuple(reversed(session.event_results)))
    with pytest.raises(c.PlatformContractError):replace(session.event_results[0],status='rejected')
    with pytest.raises(c.PlatformContractError):replace(session.event_results[0],event_index=-1)
    with pytest.raises(c.PlatformContractError):replace(session.event_results[-1].diagnostics[0],event_index=256)


class StaticHTML(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','link','iframe','img')
        assert not any(k in ('src','href') or k.startswith('on') for k,v in attrs)


def test_json_html_deterministic_and_escaped():
    session=demo.demo_session();hostile='<script>"& Ω</script>'
    session=replace(session,final_snapshot=replace(session.final_snapshot,description=hostile))
    assert demo.render_json(session)==demo.render_json(session)
    assert c.from_document(m.MonitoringSession,json.loads(demo.render_json(session)))==session
    html=demo.render_html(session)
    assert html==demo.render_html(session) and hostile not in html and escape(json.dumps(hostile,ensure_ascii=False)[1:-1],quote=True) in html
    StaticHTML().feed(html)


@pytest.mark.parametrize('format',['json','html'])
def test_cli_no_filesystem_network_subprocess_hardware_or_writes(tmp_path,format):
    code='''import sys,os
sys.path[:0]=sys.argv[1:3]
from examples import platform_monitoring_demo as demo
demo.argparse.ArgumentParser()
def guard(event,args):
    if event=='open' or event.startswith(('socket.','subprocess.')) or event in ('os.system','os.remove','os.rename','os.mkdir'):
        raise AssertionError('external effect')
    if event=='import' and args[0].split('.')[0] in ('cv2','numpy','PIL','torch','ultralytics','serial'):
        raise AssertionError('hardware/media import')
sys.addaudithook(guard)
sys.exit(demo.main(['--format',sys.argv[3]]))
'''
    args=[sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),format]
    a=subprocess.run(args,cwd=tmp_path,env={},capture_output=True,timeout=30)
    b=subprocess.run(args,cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert a.returncode==b.returncode==0 and a.stdout==b.stdout and not a.stderr and not b.stderr
    assert list(tmp_path.iterdir())==[]


def test_cli_invalid_input_no_partial_stdout_and_no_wall_clock(tmp_path,monkeypatch):
    import time
    import random
    def forbidden(*args,**kwargs):raise AssertionError('clock access')
    monkeypatch.setattr(time,'time',forbidden);monkeypatch.setattr(time,'monotonic',forbidden)
    monkeypatch.setattr(random,'random',forbidden);monkeypatch.setattr(random,'getrandbits',forbidden)
    assert demo.demo_session()==demo.demo_session()
    code='import sys;sys.path[:0]=sys.argv[1:3];from examples.platform_monitoring_demo import main;sys.exit(main(["--format","csv"]))'
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src')],cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==2 and not p.stdout and p.stderr


def test_known_review_timestamp_seeds_new_session_clock():
    initial,events=demo.demo_inputs()
    final=m.reduce_session(initial,events[:6]).final_snapshot
    event=replace(events[4],event_id='later-announcement',timestamp=c.Timestamp(value=4500,unit='ms',clock_domain='demo:display-r'),
        payload=replace(events[4].payload,observation=replace(events[4].payload.observation,observation_id='later-observation',timestamp=c.Timestamp(value=4500,unit='ms',clock_domain='demo:display-r'))))
    assert result(final,event)=='TIMESTAMP_REGRESSION'


@pytest.mark.parametrize('field',['alerts','investigations'])
def test_payload_collection_bounds_and_bundle_cardinality(field):
    _,events=demo.demo_inputs();payload=events[4].payload
    for count in (2,257):
        with pytest.raises(c.PlatformContractError):replace(payload,**{field:getattr(payload,field)*count})


def test_investigation_audit_metadata_and_event_timestamp_agreement():
    _,events=demo.demo_inputs();payload=events[4].payload
    with pytest.raises(c.PlatformContractError):replace(payload,copilot_actor_id=None)
    with pytest.raises(c.PlatformContractError):replace(payload,investigations=())
    for event in (events[1],events[4],events[5]):
        with pytest.raises(c.PlatformContractError):replace(event,timestamp=replace(event.timestamp,value=99))


def test_invalid_input_preflight_and_unexpected_programming_errors(monkeypatch):
    initial,events=demo.demo_inputs();calls=[]
    original=m._apply
    def spy(*args):calls.append(args);return original(*args)
    monkeypatch.setattr(m,'_apply',spy)
    with pytest.raises(c.PlatformContractError):m.reduce_session(initial,(events[0],{}))
    assert calls==[]
    def bug(*args):raise RuntimeError('programming error')
    monkeypatch.setattr(m,'_apply',bug)
    with pytest.raises(RuntimeError,match='programming error'):m.reduce_session(initial,(events[0],))


@pytest.mark.parametrize('kind',['alert','sentinel'])
def test_other_review_subjects_use_existing_status_contracts(kind):
    initial,events=demo.demo_inputs()
    if kind=='alert':
        initial=m.reduce_session(initial,(events[4],)).final_snapshot
        decision=replace(events[5].payload.decision,subject_kind='alert',subject_id='monitor-alert',new_status='dismissed')
        event=replace(events[5],payload=replace(events[5].payload,decision=decision))
    else:
        time=c.Timestamp(value=3,unit='s',clock_domain='demo:camera-a')
        decision=replace(events[5].payload.decision,subject_kind='sentinel',subject_id='native-aerial',timestamp=time)
        event=replace(events[5],device_id='native-aerial',source_id=None,timestamp=time,payload=replace(events[5].payload,decision=decision))
    session=m.reduce_session(initial,(event,))
    assert session.event_results[0].status=='applied' and session.final_snapshot.audit_entries[-1].event=='human_review'
