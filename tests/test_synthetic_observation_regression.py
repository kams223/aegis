"""Regression artifacts describe software outcomes; test approval is never real authorization."""
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examples import synthetic_observation_regression as reg
from examples.synthetic_observation_batch import run_batch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'examples/synthetic_validation_batch.json'
FAULT = ROOT / 'examples/synthetic_validation_fault_batch.json'


def candidate(report=None):
    return reg.candidate_baseline(run_batch(MANIFEST) if report is None else report,
                                  'test-baseline', 'Test fixture only, not production approval')


def approved(report=None):
    value = candidate(report)
    value['approval'] = {'status': 'approved', 'approved_by': 'TEST-FIXTURE-ONLY',
                         'approval_note': 'Synthetic test authorization only'}
    return value


def cli(tmp_path, *args, optimized=False):
    code = 'import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["regression"]+sys.argv[3:];runpy.run_module("examples.synthetic_observation_regression",run_name="__main__")'
    return subprocess.run([sys.executable, '-I', '-S', '-B', *(['-O'] if optimized else []),
        '-c', code, str(ROOT), str(ROOT/'src'), *args], cwd=tmp_path, env={},
        capture_output=True, timeout=30)


def test_digest_precise_bytes_and_reordered_members():
    report = reg.semantic_report(run_batch(MANIFEST))
    raw = json.dumps(report, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    assert reg.canonical_report(report) == raw and not raw.endswith(b'\n')
    assert reg.report_digest(report) == hashlib.sha256(raw).hexdigest()
    assert reg.report_digest(dict(reversed(list(report.items())))) == reg.report_digest(report)
    assert candidate()['approval'] == {'status':'candidate','approved_by':None,'approval_note':None}


def test_identical_fault_report_exposes_invalid_metadata_and_no_mutation():
    report = run_batch(FAULT);baseline = approved(report)
    before = deepcopy((report,baseline))
    result = reg.compare_reports(report,baseline)
    assert result['comparison_status'] == 'unchanged' and result['difference_count'] == 0
    assert result['baseline_report_status'] == result['current_report_status'] == 'failed'
    assert result['summary']['current_outcomes'][-1]['metadata_validity'] == 'failed'
    assert result['summary']['current_outcomes'][-1]['profile_agreement'] == 'passed'
    assert (report,baseline) == before
    result['summary']['current_outcomes'].clear()
    assert (report,baseline) == before


def test_candidate_not_authoritative_even_when_changed():
    report = run_batch(MANIFEST);baseline = candidate(report)
    report['entries'][0]['final_status'] = 'failed'
    result = reg.compare_reports(report,baseline)
    assert result['comparison_status'] == 'not_evaluated' and result['differences'] == []
    assert 'NOT APPROVED' in result['summary']['reason']


@pytest.mark.parametrize('key,value,category', [
    ('scenario_id','changed scenario','scenario_identity'),('profile_id',None,'profile_identity'),
    ('metadata_validation_status','failed','metadata_validity'),
    ('profile_evaluation_status','failed','profile_evaluation'),('final_status','failed','validation_status'),
    ('scenario_loading','not_evaluated','evaluation_availability'),
    ('profile_loading','not_evaluated','evaluation_availability'),
    ('inventory_integrity_status','not_evaluated','evaluation_availability'),
    ('loading_error','explicit test error','evaluation_availability')])
def test_entry_field_differences(key,value,category):
    report=run_batch(MANIFEST);baseline=approved(report)
    report['entries'][0][key]=value
    result=reg.compare_reports(report,baseline)
    assert result['comparison_status']=='changed'
    assert result['differences']==[{'path':'/entries/0/'+key,'category':category,
        'baseline_value':baseline['report']['entries'][0][key], 'current_value':value,'classification':'changed'}]


def test_batch_identity_status_counts_checks_and_stable_order():
    report=run_batch(MANIFEST);baseline=approved(report)
    report['batch_id']='different batch';report['overall_status']='failed'
    report['entries'][0]['diagnostic_counts']['Invalid']=1
    report['entries'][0]['profile_evaluation']['checks'][0]['actual']=10
    result=reg.compare_reports(report,baseline)
    assert [d['path'] for d in result['differences']]==[
        '/batch_id','/entries/0/diagnostic_counts/Invalid','/entries/0/profile_checks/0/actual','/overall_status']
    assert result == reg.compare_reports(report,json.loads(json.dumps(baseline,sort_keys=True)))
    assert all(d['classification']=='changed' for d in result['differences'])
    report['description']='irrelevant presentation';report['scope']='presentation'
    report['entries'][0]['scenario_validation']['scope']='presentation'
    assert reg.compare_reports(report,baseline)==result


@pytest.mark.parametrize('action', ['added','removed','reordered'])
def test_entry_arrays(action):
    report=run_batch(MANIFEST);baseline=approved(report)
    if action=='added':
        row=deepcopy(report['entries'][0]);row['position']=2;report['entries'].append(row)
    elif action=='removed':report['entries'].pop()
    else:
        report['entries'].reverse()
        for i,row in enumerate(report['entries']):row['position']=i
    differences=reg.compare_reports(report,baseline)['differences']
    assert differences and differences==reg.compare_reports(report,baseline)['differences']
    if action!='reordered':assert differences[0]['classification']==action
    else:assert any(d['category']=='scenario_identity' for d in differences)


def test_profile_check_added_removed_and_availability():
    report=run_batch(MANIFEST);report['entries'][0]['profile_evaluation']['checks'].pop()
    baseline=approved(report)
    report['entries'][0]['profile_evaluation']['checks'].append(
        {'id':'metadata_validity','status':'not_evaluated','expected':'passed','actual':None})
    difference=reg.compare_reports(report,baseline)['differences'][0]
    assert difference['path']=='/entries/0/profile_checks/6' and difference['classification']=='added'
    assert reg.compare_reports(run_batch(MANIFEST),approved())['comparison_status']=='unchanged'


@pytest.mark.parametrize('change', [
    {'schema_version':2},{'schema_version':True},{'schema_version':1.0}, {'extra':0},
    {'baseline_id':''},{'description':None},{'source_batch_id':'other'}, {'report_digest':'0'*64},
    {'approval':{}},{'approval':{'status':'approved','approved_by':'','approval_note':'note'}},
    {'approval':{'status':'approved','approved_by':'TEST','approval_note':None}},
    {'approval':{'status':'candidate','approved_by':'TEST','approval_note':None}},
    {'approval':{'status':'automatic','approved_by':None,'approval_note':None}},
    {'approval':{'status':'candidate','approved_by':None,'approval_note':None,'extra':0}},
    {'baseline_id':chr(0xD800)}, {'report':{}},
])
def test_bad_baseline_schema(change):
    document=candidate();document.update(change)
    with pytest.raises(reg.RegressionInputError):reg.baseline_from_document(document)


@pytest.mark.parametrize('field,value', [('position',True),('position',9),('scenario_id',None),
    ('profile_id',7),('loading_error',{}),('final_status','unchanged'),('diagnostic_counts',{'Invalid':0}),
    ('diagnostic_counts',{'Invalid':True,'Warning':0,'Informational':0}),('profile_checks',{}),
    ('profile_checks',[{'id':'unknown','status':'passed','expected':1,'actual':1}]),
    ('profile_checks',[{'id':'source_count','status':'passed','expected':1,'actual':float('nan')}])])
def test_snapshot_types(field,value):
    report=candidate()['report'];report['entries'][0][field]=value
    with pytest.raises(reg.RegressionInputError):reg.validate_snapshot(report)


def test_unknown_nested_fields_order_and_digest_tampering():
    baseline=candidate();baseline['report']['entries'][0]['final_status']='failed'
    with pytest.raises(reg.RegressionInputError,match='digest'):reg.baseline_from_document(baseline)
    for edit in ('unknown','duplicate','order'):
        report=candidate()['report'];row=report['entries'][0]
        if edit=='unknown':row['profile_checks'][0]['extra']=0
        elif edit=='duplicate':row['profile_checks'].append(deepcopy(row['profile_checks'][0]))
        else:row['profile_checks'].reverse()
        with pytest.raises(reg.RegressionInputError):reg.validate_snapshot(report)
    report=candidate()['report'];report['entries']*=17
    with pytest.raises(reg.RegressionInputError):reg.validate_snapshot(report)


@pytest.mark.parametrize('raw', [b'{',b'[]',b'"\xff"',b'{"x":1,"x":2}',b'{"x":NaN}',
    b'{"x":Infinity}',b'{"x":-Infinity}',b'{"x":1e309}',b'['*2000,b' '*(reg.MAX_BYTES+1)])
def test_strict_local_json(tmp_path,raw):
    path=tmp_path/'baseline.json';path.write_bytes(raw)
    with pytest.raises(reg.RegressionInputError):reg.load_baseline(path)


def test_nested_duplicate_missing_required_missing_file_and_size(tmp_path):
    value=candidate();path=tmp_path/'baseline.json'
    path.write_text(json.dumps(value).replace('"status": "candidate"','"status": "candidate", "status": "candidate"'))
    with pytest.raises(reg.RegressionInputError,match='duplicate'):reg.load_baseline(path)
    del value['approval']
    with pytest.raises(reg.RegressionInputError):reg.baseline_from_document(value)
    with pytest.raises(reg.RegressionInputError,match='unable to read'):reg.load_baseline(tmp_path/'absent')
    value=candidate();value['description']='x'*reg.MAX_BYTES
    with pytest.raises(reg.RegressionInputError,match='limit'):reg.baseline_from_document(value)


def test_candidate_creation_exclusive_symlinks_and_no_approval(tmp_path):
    value=candidate();path=tmp_path/'candidate.json';reg.write_candidate(path,value)
    contents=path.read_bytes();assert reg.load_baseline(path)==value
    with pytest.raises(reg.RegressionInputError):reg.write_candidate(path,value)
    assert path.read_bytes()==contents
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(reg.RegressionInputError):reg.write_candidate(link,value)
    directory=tmp_path/'directory';directory.mkdir()
    (tmp_path/'parent-link').symlink_to(directory,target_is_directory=True)
    with pytest.raises(reg.RegressionInputError):reg.write_candidate(tmp_path/'parent-link/new.json',value)
    with pytest.raises(reg.RegressionInputError,match='candidates only'):reg.write_candidate(tmp_path/'approved.json',approved())
    for name in ['../escape.json','https://example.com/x','bad\\name','bad\x00name','missing/file.json']:
        with pytest.raises(reg.RegressionInputError):reg.write_candidate(tmp_path/name,value)
    assert not (tmp_path/'approved.json').exists()


@pytest.mark.parametrize('state,strict,code',[('unchanged',True,0),('changed',True,1),
    ('candidate',True,2),('changed',False,0),('candidate',False,0),('fault',True,0)])
@pytest.mark.parametrize('format',['json','html'])
def test_cli_reports(tmp_path,state,strict,code,format):
    manifest=FAULT if state=='fault' else MANIFEST
    value=candidate() if state=='candidate' else approved(run_batch(manifest))
    if state=='changed':
        value['report']['batch_id']=value['source_batch_id']='different'
        value['report_digest']=reg.report_digest(value['report'])
    path=tmp_path/'baseline.json';path.write_text(reg.render_json(value));before=path.read_bytes()
    args=['--manifest',str(manifest),'--baseline',str(path),'--format',format,*(['--strict'] if strict else [])]
    a,b=cli(tmp_path,*args),cli(tmp_path,*args)
    assert a.returncode==b.returncode==code and not a.stderr and a.stdout==b.stdout
    assert path.read_bytes()==before and set(p.name for p in tmp_path.iterdir())=={'baseline.json'}
    if format=='json':assert json.loads(a.stdout)['comparison_status']==('not_evaluated' if state=='candidate' else 'unchanged' if state=='fault' else state)
    else:assert a.stdout.startswith(b'<!DOCTYPE html>') and a.stdout.endswith(b'</html>\n')


def test_candidate_cli_and_invalid_modes(tmp_path):
    output=tmp_path/'candidate.json'
    args=['--manifest',str(MANIFEST),'--generate-candidate','--output',str(output),
          '--baseline-id','test','--description','Candidate for human review']
    p=cli(tmp_path,*args);assert p.returncode==0 and not p.stdout and not p.stderr
    assert reg.load_baseline(output)['approval']['status']=='candidate'
    saved=output.read_bytes()
    for options in (args,args+['--strict'],args+['--format','html'],args+['--baseline','x'],
        ['--manifest',str(MANIFEST),'--generate-candidate'],[],
        ['--manifest',str(MANIFEST),'--baseline',str(tmp_path/'absent')],
        ['--manifest',str(MANIFEST),'--baseline',str(output),'--output','bad']):
        p=cli(tmp_path,*options);assert p.returncode==2 and not p.stdout and p.stderr
    p=cli(tmp_path,'--manifest',str(MANIFEST),'--baseline',str(output),optimized=True)
    assert p.returncode==2 and not p.stdout and b'Run without -O' in p.stderr
    assert output.read_bytes()==saved


class Markup(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','link','img')
        assert not any(key in ('href','src') for key,value in attrs)


def test_html_escaping_every_dynamic_area():
    hostile='<script>"& Ω</script>'
    report=run_batch(MANIFEST);baseline=approved(report)
    report['batch_id']=hostile;report['entries'][0]['scenario_id']=hostile
    baseline['baseline_id']=hostile
    result=reg.compare_reports(report,baseline);result['summary']['reason']=hostile
    html=reg.render_html(result)
    assert hostile not in html and escape(hostile,quote=True) in html
    Markup().feed(html)
    assert '<caption>' in html and '<th scope="col">' in html


def test_offline_readonly_audit(tmp_path):
    baseline=tmp_path/'baseline.json';baseline.write_text(reg.render_json(approved()))
    code='''
import sys
sys.path[:0]=sys.argv[1:3]
from examples.synthetic_observation_regression import load_baseline,compare_reports,render_json,render_html
from examples.synthetic_observation_batch import run_batch
def audit(event,args):
    if event=='open' and args[1]!='r':raise AssertionError('unexpected write')
    if event.startswith(('socket.','subprocess.')) or event in ('os.remove','os.rename','os.mkdir','os.link'):
        raise AssertionError('unexpected operation')
sys.addaudithook(audit)
report=compare_reports(run_batch(sys.argv[3]),load_baseline(sys.argv[4]))
render_json(report);render_html(report)
'''
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(MANIFEST),str(baseline)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stdout and not p.stderr


@pytest.mark.parametrize('args,digest',[([], 'd9caedddee1ae850fac263f1b457713441276df665035380c7791817b2f610d8'),
    (['--html'],'e2f5bdfe61c6ce40eba747879ef397672386c8c34b5d0f88b433edf362c39a4c'),
    (['--html','--compare'],'ab4c5b5f1d011f8ba6fb143a9948f32218a3cfac293fd1487982e4f1f4bb2c59'),
    (['--html','--replay'],'7859e6304c3a37e9fa700858e21b65e33c488b1df0b00913365141a72d3a92d2'),
    (['--html','--compare','--replay'],'0a4b4183bf120ad06e67df9e890d5e5aff66cca6374f7fd0beca1a2b7ada87ac'),
    (['--validate-json'],'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'),
    (['--validate-html'],'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7'),
    (['--validate-json','--strict'],'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'),
    (['--validate-html','--strict'],'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7')])
def test_original_cli_compatibility(tmp_path,args,digest):
    code='import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2],sys.argv[1]+"/examples"];sys.argv=["demo"]+sys.argv[3:];runpy.run_module("examples.synthetic_observation_demo",run_name="__main__")'
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),*args],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stderr and hashlib.sha256(p.stdout).hexdigest()==digest
