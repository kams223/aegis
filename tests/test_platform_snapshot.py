"""Relationship integrity, read-only investigation, and offline demo behavior."""

from copy import deepcopy
from dataclasses import replace
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.platform import build_snapshot, snapshot_document, snapshot_from_document, investigate
from aegis.platform import contracts as c
from examples import platform_snapshot_demo as demo

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_closed_roundtrip_owned_and_repeatable():
    a = demo.demo_snapshot()
    assert a == demo.demo_snapshot()
    doc = snapshot_document(a)
    assert snapshot_from_document(doc) == a
    before = deepcopy(doc)
    b = snapshot_from_document(doc)
    assert doc == before
    doc['registry']['devices'].clear()
    assert b == a
    assert demo.render_json(a) == demo.render_json(b)
    assert json.loads(demo.render_json(a)) == before


@pytest.mark.parametrize('group,key', [('evidence','evidence_id'),('observations','observation_id'),
    ('sentinels','device_id'),('alerts','alert_id'),('investigation_requests','request_id'),
    ('investigation_results','result_id'),('review_history','decision_id'),('audit_entries','audit_id')])
def test_all_collection_duplicate_and_mutable_rejection(group, key):
    snap = demo.demo_snapshot()
    items = getattr(snap, group)
    with pytest.raises(c.PlatformContractError):
        replace(snap, **{group:items + (items[0],)})
    with pytest.raises(c.PlatformContractError):
        replace(snap, **{group:list(items)})


@pytest.mark.parametrize('case', ['evidence_source','source_evidence','observation_source','observation_evidence',
    'observation_clock','evidence_pair','unsupported_display','sentinel_device','sentinel_category',
    'sentinel_connectivity','sentinel_sensors','sentinel_camera','unsupported_camera','alert_observation',
    'alert_evidence','alert_evidence_pair','request_alert','request_observation','result_request','result_summary',
    'review_subject','review_chain','review_final','audit_reference','audit_actor','audit_timestamp','audit_event'])
def test_dangling_or_inconsistent_relationships_rejected(case):
    snap = demo.demo_snapshot()
    doc = snapshot_document(snap)
    devices = doc['registry']['devices']
    if case == 'evidence_source':doc['evidence'][0]['source_id']='absent'
    elif case == 'source_evidence':devices[0]['sources'][0]['evidence_id']='absent'
    elif case == 'observation_source':doc['observations'][0]['source_id']='absent'
    elif case == 'observation_evidence':doc['observations'][0]['evidence_id']='absent'
    elif case == 'observation_clock':doc['observations'][0]['timestamp']['clock_domain']='different:clock'
    elif case == 'evidence_pair':doc['observations'][0]['evidence_id']=doc['evidence'][0]['evidence_id']
    elif case == 'unsupported_display':devices[1]['capabilities'][1]['support']='unsupported'
    elif case == 'sentinel_device':doc['sentinels'][0]['device_id']='absent'
    elif case == 'sentinel_category':doc['sentinels'][0]['sentinel_category']='ground'
    elif case == 'sentinel_connectivity':doc['sentinels'][0]['connectivity']='recorded'
    elif case == 'sentinel_sensors':doc['sentinels'][0]['sensors']=[]
    elif case == 'sentinel_camera':doc['sentinels'][0]['camera_evidence_id']=doc['evidence'][1]['evidence_id']
    elif case == 'unsupported_camera':devices[0]['capabilities'][2]['support']='unsupported'
    elif case == 'alert_observation':doc['alerts'][0]['observation_id']='absent'
    elif case == 'alert_evidence':doc['alerts'][0]['explanation']['evidence_ids']=['absent']
    elif case == 'alert_evidence_pair':doc['alerts'][0]['explanation']['evidence_ids']=[doc['evidence'][0]['evidence_id']]
    elif case == 'request_alert':doc['investigation_requests'][0]['alert_id']='absent'
    elif case == 'request_observation':doc['investigation_requests'][0]['reference_ids']=['display-normal']
    elif case == 'result_request':doc['investigation_results'][0]['request_id']='absent'
    elif case == 'result_summary':doc['investigation_results'][0]['summary']='Fabricated summary'
    elif case == 'review_subject':doc['review_history'][0]['subject_id']='absent'
    elif case == 'review_chain':doc['review_history'][0]['previous_status']='under_review'
    elif case == 'review_final':doc['alerts'][0]['status']='unreviewed'
    elif case == 'audit_reference':doc['audit_entries'][0]['reference_id']='absent'
    elif case == 'audit_actor':doc['audit_entries'][1]['actor_id']='other-reviewer'
    elif case == 'audit_timestamp':doc['audit_entries'][1]['timestamp']['value']=100
    else:doc['audit_entries'][0]['event']='investigation_not_evaluated'
    with pytest.raises(c.PlatformContractError):
        snapshot_from_document(doc)


def test_source_and_record_order_are_supplied_not_sorted():
    snap = demo.demo_snapshot()
    reordered = replace(snap, registry=c.build_registry(tuple(reversed(snap.registry.devices))),
                        evidence=tuple(reversed(snap.evidence)), observations=tuple(reversed(snap.observations)))
    assert snapshot_document(reordered)['registry']['devices'][0]['device_id']=='third-party'
    assert snapshot_document(reordered)['observations'][0]['observation_id']=='display-unusual'
    assert demo.render_json(reordered) != demo.render_json(snap)


def context():
    snap = demo.demo_snapshot()
    source = snap.evidence[1].source_id
    refs = tuple(c.EvidenceReference(evidence_id='report-'+str(i), source_id=source, kind='dataset_report',
        local_path='synthetic/report-'+str(i)+'.json', dataset_id='dataset') for i in range(2))
    outcomes = tuple(c.ValidationEvidence(evidence_id=ref.evidence_id, dataset_id='dataset',
        metadata_status='passed' if i == 0 else 'failed', integrity_status='verified') for i, ref in enumerate(refs))
    return snap, snap.evidence + refs, outcomes


@pytest.mark.parametrize('action,keys', [('retrieve_evidence',('camera-a:evidence',)),
    ('summarize_device_health',('native-aerial',)),('explain_observation',('display-unusual',)),
    ('inspect_dataset_report',('report-0',)),('compare_validation_results',('report-0','report-1'))])
def test_all_five_actions_deterministic_and_read_only(action, keys):
    snap, refs, outcomes = context()
    request = replace(snap.investigation_requests[0], action=action, reference_ids=keys)
    args = dict(registry=snap.registry, observations=snap.observations, evidence=refs, validation_results=outcomes)
    before = deepcopy((snap, refs, outcomes))
    a, b = investigate(request, **args), investigate(request, **args)
    assert a == b and a.status=='completed'
    assert (snap, refs, outcomes)==before
    assert set(a.evidence_ids) <= {ref.evidence_id for ref in refs}
    if action=='compare_validation_results':
        assert 'changed' in a.summary and 'metadata=failed' in a.summary
    if action=='retrieve_evidence':assert 'Content not opened' in a.summary
    # A complete snapshot accepts the same request and generated result.
    audit = replace(snap.audit_entries[0], reference_id=a.result_id)
    combined = replace(snap, evidence=refs, validation_results=outcomes,
        investigation_requests=(request,), investigation_results=(a,), audit_entries=(audit, snap.audit_entries[1]))
    assert combined.investigation_results==(a,)


@pytest.mark.parametrize('action,keys', [('inspect_dataset_report',('report-0',)),
    ('compare_validation_results',('report-0','report-1'))])
def test_missing_outcomes_are_unevaluated_without_file_loading(action, keys):
    snap, refs, _ = context()
    request = replace(snap.investigation_requests[0], action=action, reference_ids=keys)
    result = investigate(request, registry=snap.registry, observations=snap.observations, evidence=refs, validation_results=())
    assert result.status=='not_evaluated' and 'not opened' in result.summary


def test_comparison_of_failed_outcomes_preserves_failure_and_can_be_unchanged():
    snap, refs, outcomes = context()
    request = replace(snap.investigation_requests[0], action='compare_validation_results', reference_ids=('report-0','report-1'))
    outcomes = tuple(replace(outcome, metadata_status='failed', integrity_status='mismatch') for outcome in outcomes)
    result = investigate(request, registry=snap.registry, observations=snap.observations, evidence=refs, validation_results=outcomes)
    assert 'unchanged' in result.summary and 'metadata=failed' in result.summary and 'integrity=mismatch' in result.summary


@pytest.mark.parametrize('action,keys', [('retrieve_evidence',('absent',)), ('summarize_device_health',('absent',)),
    ('explain_observation',('absent',)),('inspect_dataset_report',('camera-a:evidence',))])
def test_action_specific_reference_rejection(action, keys):
    snap = demo.demo_snapshot()
    request = replace(snap.investigation_requests[0], action=action, reference_ids=keys)
    with pytest.raises(c.PlatformContractError):
        investigate(request, registry=snap.registry, observations=snap.observations, evidence=snap.evidence, validation_results=())


def test_outcome_relationship_rejection_without_investigation():
    snap, refs, outcomes = context()
    with pytest.raises(c.PlatformContractError):
        replace(snap, evidence=refs, validation_results=(replace(outcomes[0], dataset_id='other'),),
            investigation_requests=(), investigation_results=(), audit_entries=(snap.audit_entries[1],))
    with pytest.raises(c.PlatformContractError):
        replace(snap, evidence=refs, validation_results=(outcomes[0],outcomes[0]))


def test_review_history_chain_and_final_state():
    snap = demo.demo_snapshot()
    decision = snap.review_history[0]
    first = replace(decision, decision_id='first-review', new_status='under_review')
    second = replace(decision, previous_status='under_review')
    assert replace(snap, review_history=(first,second)).alerts[0].status=='reviewed'
    with pytest.raises(c.PlatformContractError):
        replace(snap, review_history=(second,first))


class StaticHTML(HTMLParser):
    def handle_starttag(self, tag, attrs):
        assert tag not in ('script','link','iframe','img')
        assert not any(key in ('src','href') or key.startswith('on') for key,value in attrs)


def test_html_escaping_all_user_strings():
    snap = demo.demo_snapshot()
    hostile = '<script>"& Ω</script>'
    snap = replace(snap, description=hostile)
    html = demo.render_html(snap)
    assert hostile not in html and escape(hostile, quote=True) in html
    assert demo.render_html(snap)==html
    StaticHTML().feed(html)
    assert '<h1>' in html and '<h2>' in html and html.endswith('</html>\n')
    assert json.loads(demo.render_json(snap))['description']==hostile


def demo_cli(tmp_path, *args, audit=False):
    code = '''import sys,os,runpy
sys.path[:0]=sys.argv[1:3]
from examples import platform_snapshot_demo
# Initialize argparse's lazy standard-library locale imports before auditing
# application execution. Evidence and hardware opens remain forbidden below.
platform_snapshot_demo.argparse.ArgumentParser()
if sys.argv[3]=='audit':
    def guard(event,args):
        if event=='open':
            raise AssertionError('file or device access')
        if event.startswith(('socket.','subprocess.')) or event in ('os.system','os.remove','os.rename','os.mkdir'):
            raise AssertionError('external effect')
        if event=='import' and args[0].split('.')[0] in ('cv2','numpy','PIL','torch','ultralytics','serial'):
            raise AssertionError('hardware or media import')
    sys.addaudithook(guard)
sys.exit(platform_snapshot_demo.main(sys.argv[4:]))
'''
    return subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),
        'audit' if audit else 'normal',*args], cwd=tmp_path,env={},capture_output=True,timeout=30)


@pytest.mark.parametrize('format', ['json','html'])
def test_cli_deterministic_offline_no_hardware_or_writes(tmp_path, format):
    a = demo_cli(tmp_path,'--format',format,audit=True)
    b = demo_cli(tmp_path,'--format',format,audit=True)
    assert a.returncode==b.returncode==0 and a.stdout==b.stdout and not a.stderr and not b.stderr
    assert list(tmp_path.iterdir())==[]
    if format=='json':assert snapshot_from_document(json.loads(a.stdout))==demo.demo_snapshot()
    else:StaticHTML().feed(a.stdout.decode())


@pytest.mark.parametrize('args', [('--format','csv'),('--unknown',),('--format',)])
def test_invalid_cli_empty_stdout(tmp_path, args):
    p = demo_cli(tmp_path,*args)
    assert p.returncode==2 and not p.stdout and b'error:' in p.stderr


def test_no_implicit_clock_or_environment_state(monkeypatch):
    import time
    import os
    def forbidden(*args, **kwargs):raise AssertionError('environment-dependent operation')
    for name in ('time','monotonic','perf_counter'):
        monkeypatch.setattr(time,name,forbidden)
    monkeypatch.setattr(os,'getenv',forbidden)
    assert demo.demo_snapshot()==demo.demo_snapshot()
