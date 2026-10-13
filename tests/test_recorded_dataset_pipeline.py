"""Coordinator tests exercise public metadata/integrity stages without rewriting checks."""
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examples import recorded_dataset_pipeline as pipeline

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'examples/recorded_datasets'


def inputs(tmp_path,metadata='passed',integrity='verified'):
    data=json.loads((FIXTURES/'quality_warnings.json').read_text())
    data['sources'][0]['recording_reference']='data.bin'
    for i,record in enumerate(data['records']):
        record['sequence_index']=i;record['timestamp']['value']=i
    if metadata=='failed':data['records'][0]['metadata']['complete']=False
    elif metadata=='not_evaluated':del data['records'][0]['metadata']['complete']
    payload=b'opaque\x00synthetic\xff'
    (tmp_path/'data.bin').write_bytes(payload)
    if integrity=='not_evaluated':
        (tmp_path/'data.bin').rename(tmp_path/'inside.bin')
        (tmp_path/'data.bin').symlink_to(tmp_path/'inside.bin')
    manifest={'schema_version':1,'manifest_id':'pipeline-test-only','dataset_reference':'dataset.json',
        'entries':[{'source_id':data['sources'][0]['source_id'],'recording_reference':'data.bin',
            'expected_size_bytes':len(payload),'expected_sha256':'0'*64 if integrity=='mismatch' else hashlib.sha256(payload).hexdigest()}]}
    path=tmp_path/'dataset.json';path.write_text(json.dumps(data))
    mfile=tmp_path/'manifest.json';mfile.write_text(json.dumps(manifest))
    return path,mfile


def cli(tmp_path,*args):
    code='import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["pipeline"]+sys.argv[3:];runpy.run_module("examples.recorded_dataset_pipeline",run_name="__main__")'
    return subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),*args],
        cwd=tmp_path,env={},capture_output=True,timeout=30)


@pytest.mark.parametrize('metadata,integrity,overall',[
    ('passed','verified','passed'),('failed','verified','failed'),('passed','mismatch','failed'),
    ('not_evaluated','verified','not_evaluated'),('failed','mismatch','failed'),
    ('passed','not_evaluated','not_evaluated'),('not_evaluated','not_evaluated','not_evaluated'),
    ('failed','not_evaluated','failed'),('not_evaluated','mismatch','failed')])
def test_independent_status_combinations(tmp_path,metadata,integrity,overall):
    path,mfile=inputs(tmp_path,metadata,integrity);before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    result=pipeline.run_pipeline(path,mfile)
    assert result['metadata_status']==metadata and result['integrity_status']==integrity and result['overall_status']==overall
    assert result['metadata_summary']['report']['status']==metadata
    assert result['integrity_summary']['report']['verification_status']==integrity
    assert result['metadata_summary']['unavailable_reason'] is None and result['integrity_summary']['unavailable_reason'] is None
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before
    if overall=='not_evaluated':assert any(item['required'] for item in result['unevaluated_checks'])


def test_public_api_call_order_single_loading_and_detached_lossless_reports(tmp_path,monkeypatch):
    path,mfile=inputs(tmp_path);events=[];loaded=[];originals=[];checks_before=[]
    def wrap(name,fn):
        def call(*args):
            events.append(name)
            if name=='load_dataset':
                value=fn(*args);loaded.append(value);return value
            if name in ('validate_dataset','verify_dataset'):
                assert args[0] is loaded[0]
                value=fn(*args);originals.append(value);checks_before.append(deepcopy(value));return value
            return fn(*args)
        return call
    for module,name in [(pipeline.metadata,'load_dataset'),(pipeline.integrity,'load_manifest'),
                        (pipeline.metadata,'validate_dataset'),(pipeline.integrity,'verify_dataset')]:
        monkeypatch.setattr(module,name,wrap(name,getattr(module,name)))
    result=pipeline.run_pipeline(path,mfile)
    assert events==['load_dataset','load_manifest','validate_dataset','verify_dataset']
    assert result['metadata_summary']['report']==checks_before[0]
    assert result['integrity_summary']['report']==checks_before[1]
    originals[0]['diagnostics'].clear();originals[1]['entries'].clear()
    assert result['metadata_summary']['report']==checks_before[0] and result['integrity_summary']['report']==checks_before[1]


def test_warnings_do_not_fail_and_existing_fixtures_are_unchanged():
    path=FIXTURES/'quality_warnings.json';mfile=FIXTURES/'integrity_match.json'
    result=pipeline.run_pipeline(path,mfile)
    assert result['overall_status']=='passed' and result['diagnostics']
    assert all(item['stage']=='metadata' and item['severity']=='Warning' for item in result['diagnostics'])
    assert any(item['required'] is False for item in result['unevaluated_checks'])


def test_stable_diagnostic_order_fields_and_original_record_indices(tmp_path):
    path,mfile=inputs(tmp_path,'failed','mismatch');a=pipeline.run_pipeline(path,mfile);b=pipeline.run_pipeline(path,mfile)
    assert a==b
    assert [(d['stage'],d['code'],d['record_index'],d['entry_index']) for d in a['diagnostics']]==[
        ('metadata','INCOMPLETE_RECORD',0,None),('integrity','DIGEST_MISMATCH',None,0)]
    assert all(set(d)=={'stage','code','severity','source_id','record_id','record_index','entry_index','recording_reference','explanation'} for d in a['diagnostics'])
    assert all(d['severity']=='Invalid' and d['recording_reference']=='data.bin' for d in a['diagnostics'])


def test_dataset_source_order_and_manifest_order_preserved_independently(tmp_path):
    path,mfile=inputs(tmp_path);data=json.loads(path.read_text());original=data['sources'][0]
    data['sources']=[{**original,'source_id':name,'recording_reference':name+'.bin','clock_domain':'recording:'+name} for name in ('b','a')]
    data['records']=[{**data['records'][i],'record_id':name+str(i),'source_id':name} for i in range(2) for name in ('b','a')]
    manifest=json.loads(mfile.read_text());manifest['entries']=[]
    for name in ('a','b'):
        payload=name.encode();(tmp_path/(name+'.bin')).write_bytes(payload)
        manifest['entries'].append({'source_id':name,'recording_reference':name+'.bin','expected_size_bytes':1,'expected_sha256':hashlib.sha256(payload).hexdigest()})
    path.write_text(json.dumps(data));mfile.write_text(json.dumps(manifest))
    result=pipeline.run_pipeline(path,mfile)
    assert result['overall_status']=='passed'
    assert [row['source_id'] for row in result['source_inventory']]==['b','a']
    assert [row['source_id'] for row in result['metadata_summary']['report']['source_inventory']]==['b','a']
    assert [row['source_id'] for row in result['integrity_summary']['report']['entries']]==['a','b']
    assert [row['record_count'] for row in result['source_inventory']]==[2,2]


def test_recording_disappears_after_loading_retains_metadata_result(tmp_path,monkeypatch):
    path,mfile=inputs(tmp_path);original=pipeline.metadata.validate_dataset
    def remove(dataset):
        result=original(dataset);(tmp_path/'data.bin').unlink();return result
    monkeypatch.setattr(pipeline.metadata,'validate_dataset',remove)
    result=pipeline.run_pipeline(path,mfile)
    assert result['metadata_status']=='passed' and result['integrity_status']==result['overall_status']=='not_evaluated'
    assert result['metadata_summary']['report'] is not None
    assert result['integrity_summary']['report']['entries'][0]['diagnostic_codes']==['FILE_UNAVAILABLE']


@pytest.mark.parametrize('stage',['metadata','integrity','both'])
def test_explicit_stage_unavailability_isolated(tmp_path,monkeypatch,stage):
    path,mfile=inputs(tmp_path)
    def unavailable(*args):raise NotImplementedError('host-specific text must not appear')
    if stage in ('metadata','both'):monkeypatch.setattr(pipeline.metadata,'validate_dataset',unavailable)
    if stage in ('integrity','both'):monkeypatch.setattr(pipeline.integrity,'verify_dataset',unavailable)
    result=pipeline.run_pipeline(path,mfile)
    assert result['overall_status']=='not_evaluated'
    for name in ('metadata','integrity'):
        summary=result[name+'_summary']
        if stage in (name,'both'):
            assert summary['report'] is None and summary['unavailable_reason']['code']=='STAGE_UNAVAILABLE'
            assert result[name+'_status']=='not_evaluated'
        else:
            assert summary['report'] is not None and summary['unavailable_reason'] is None
    if stage in ('metadata','both'):assert result['source_inventory'][0]['record_count'] is None
    assert 'host-specific text' not in pipeline.render_json(result)


def test_integrity_io_unavailable_preserves_metadata_failure(tmp_path,monkeypatch):
    path,mfile=inputs(tmp_path,'failed')
    def unavailable(*args):raise PermissionError('absolute host path')
    monkeypatch.setattr(pipeline.integrity,'verify_dataset',unavailable)
    result=pipeline.run_pipeline(path,mfile)
    assert result['overall_status']=='failed' and result['metadata_status']=='failed'
    assert result['integrity_summary']['report'] is None
    assert result['integrity_summary']['unavailable_reason']['code']=='STAGE_IO_UNAVAILABLE'


@pytest.mark.parametrize('stage',['metadata','integrity'])
def test_unexpected_programming_errors_not_swallowed(tmp_path,monkeypatch,stage):
    path,mfile=inputs(tmp_path)
    def bug(*args):raise RuntimeError('unexpected bug')
    monkeypatch.setattr(pipeline.metadata if stage=='metadata' else pipeline.integrity,
        'validate_dataset' if stage=='metadata' else 'verify_dataset',bug)
    with pytest.raises(RuntimeError,match='unexpected bug'):pipeline.run_pipeline(path,mfile)


@pytest.mark.parametrize('case',['invalid_dataset','invalid_manifest','wrong_dataset','missing_sources','missing_recording'])
def test_invalid_input_errors_no_partial_stdout(tmp_path,case):
    path,mfile=inputs(tmp_path)
    if case=='invalid_dataset':path.write_text('{')
    elif case=='invalid_manifest':mfile.write_text('{')
    elif case=='missing_recording':(tmp_path/'data.bin').unlink()
    else:
        data=json.loads(mfile.read_text())
        if case=='wrong_dataset':data['dataset_reference']='other.json'
        else:data['entries']=[]
        mfile.write_text(json.dumps(data))
    with pytest.raises(pipeline.PipelineInputError):pipeline.run_pipeline(path,mfile)
    p=cli(tmp_path,'--dataset',str(path),'--manifest',str(mfile),'--strict')
    assert p.returncode==2 and p.stdout==b'' and b'error:' in p.stderr


def test_closed_versioned_report_and_canonical_json(tmp_path):
    path,mfile=inputs(tmp_path);result=pipeline.run_pipeline(path,mfile)
    assert tuple(result)==pipeline.REPORT_FIELDS
    text=pipeline.render_json(result)
    assert json.loads(text)==result
    assert text==json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n'
    assert pipeline.render_json(dict(reversed(list(result.items()))))==text
    for field,value in [('schema_version',True),('schema_version',2),('overall_status','failed'),('unknown',1)]:
        changed=deepcopy(result);changed[field]=value
        with pytest.raises(pipeline.PipelineInputError):pipeline.render_json(changed)
    bad=deepcopy(result);bad['metadata_summary']['extra']=0
    with pytest.raises(pipeline.PipelineInputError):pipeline.render_html(bad)


class Markup(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','link','img')
        assert not any(key in ('src','href') for key,value in attrs)


def test_static_html_escaping_all_report_areas_and_determinism(tmp_path):
    path,mfile=inputs(tmp_path,'failed','mismatch');result=pipeline.run_pipeline(path,mfile)
    hostile='<script>"& Ω</script>'
    result['dataset_id']=result['manifest_id']=hostile
    result['source_inventory'][0]['source_id']=hostile
    result['diagnostics'][0]['explanation']=hostile
    result['unevaluated_checks'][0]['check']=hostile
    result['metadata_summary']['report']['dataset_id']=hostile
    html=pipeline.render_html(result)
    assert html==pipeline.render_html(result) and hostile not in html and escape(hostile,quote=True) in html
    assert html.startswith('<!DOCTYPE html>') and html.endswith('</html>\n')
    assert '<caption>' in html and '<th scope="col">' in html and 'Independent stage reports' in html
    Markup().feed(html)


@pytest.mark.parametrize('metadata,integrity,strict,code',[
    ('passed','verified',True,0),('failed','verified',True,1),('passed','mismatch',True,1),
    ('not_evaluated','verified',True,2),('passed','not_evaluated',True,2),
    ('failed','mismatch',False,0),('not_evaluated','not_evaluated',False,0)])
@pytest.mark.parametrize('format',['json','html'])
def test_cli_statuses_stable_reports_and_no_writes(tmp_path,metadata,integrity,strict,code,format):
    path,mfile=inputs(tmp_path,metadata,integrity);before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    args=['--dataset',str(path),'--manifest',str(mfile),'--format',format,*(['--strict'] if strict else [])]
    a,b=cli(tmp_path,*args),cli(tmp_path,*args)
    assert a.returncode==b.returncode==code and a.stdout==b.stdout and not a.stderr and not b.stderr
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before
    if format=='json':
        result=json.loads(a.stdout);assert result['metadata_status']==metadata and result['integrity_status']==integrity
    else:Markup().feed(a.stdout.decode())


def test_cli_invalid_invocation_and_missing_paths(tmp_path):
    path,mfile=inputs(tmp_path);args=['--dataset',str(path),'--manifest',str(mfile)]
    for bad in ([],['--dataset',str(path)],args+['--format','csv'],args+['--unknown'],
        ['--dataset',str(tmp_path/'absent'),'--manifest',str(mfile)],
        ['--dataset',str(path),'--manifest',str(tmp_path/'absent')]):
        p=cli(tmp_path,*bad);assert p.returncode==2 and not p.stdout and p.stderr


def test_no_writes_network_subprocesses_or_media_decoding(tmp_path):
    path,mfile=inputs(tmp_path);before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    code='''
import sys,os
sys.path[:0]=sys.argv[1:3]
from examples.recorded_dataset_pipeline import run_pipeline,render_json,render_html
def audit(event,args):
    if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
        raise AssertionError('unexpected write')
    if event.startswith(('socket.','subprocess.')) or event in ('os.remove','os.rename','os.mkdir'):
        raise AssertionError('unexpected operation')
    if event=='import' and args[0].split('.')[0] in ('cv2','numpy','PIL','torch','ultralytics'):
        raise AssertionError('media/inference import')
sys.addaudithook(audit)
report=run_pipeline(sys.argv[3],sys.argv[4]);render_json(report);render_html(report)
assert report['overall_status']=='passed'
'''
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(path),str(mfile)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stdout and not p.stderr
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before


def test_existing_metadata_cli_captured_hash(tmp_path):
    code='import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["recorded","--dataset",sys.argv[3],"--strict"];runpy.run_module("examples.recorded_sensor_metadata",run_name="__main__")'
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(FIXTURES/'quality_warnings.json')],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stderr
    assert hashlib.sha256(p.stdout).hexdigest()=='be27e15513a310d9f16b08add8407a2c04e4ad838f8d3e8145ce1dd812ff155b'
