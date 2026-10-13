"""Metadata-only schema, path confinement, immutable ingestion and quality reporting."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examples import recorded_sensor_metadata as recorded

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'examples/recorded_datasets'


def document(name='valid'):
    return json.loads((FIXTURES/(name+'.json')).read_text())


def load(data):
    return recorded.dataset_from_document(data,FIXTURES)


def cli(tmp_path,*args):
    code='import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["recorded"]+sys.argv[3:];runpy.run_module("examples.recorded_sensor_metadata",run_name="__main__")'
    return subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),*args],
        cwd=tmp_path,env={},capture_output=True,timeout=30)


@pytest.mark.parametrize('name,status,codes',[
    ('valid','passed',[]),('quality_warnings','passed',['REPEATED_TIMESTAMP','OUT_OF_ORDER_DELIVERY','SEQUENCE_GAP']),
    ('quality_failures','failed',['DUPLICATE_SEQUENCE_INDEX','TIMESTAMP_REGRESSION','INCOMPLETE_RECORD','REPEATED_TIMESTAMP','SEQUENCE_GAP'])])
def test_fixtures_deterministic_order_nonmutation_and_report_schema(name,status,codes):
    raw=document(name);before=deepcopy(raw);dataset=load(raw);values=asdict(dataset)
    a,b=recorded.validate_dataset(dataset),recorded.validate_dataset(recorded.load_dataset(FIXTURES/(name+'.json')))
    assert a==b and a['status']==status and [d['code'] for d in a['diagnostics']]==codes
    assert list(a)==['schema_version','dataset_id','source_inventory','record_count','per_source_counts',
        'timestamp_domains','diagnostics','status','unevaluated_checks']
    assert recorded.render_json(a)==recorded.render_json(b) and json.loads(recorded.render_json(a))==a
    assert recorded.render_html(a)==recorded.render_html(b)
    assert raw==before and asdict(dataset)==values
    assert tuple(r.record_id for r in dataset.records)==tuple(r['record_id'] for r in raw['records'])
    assert all(set(d)=={'code','severity','source_id','record_id','record_index','explanation'} for d in a['diagnostics'])


def test_immutable_owned_values():
    raw=document();dataset=load(raw);before=asdict(dataset)
    raw['records'][0]['metadata']['complete']=False;raw['sources'].clear()
    assert asdict(dataset)==before and isinstance(dataset.sources,tuple) and isinstance(dataset.records,tuple)
    with pytest.raises(FrozenInstanceError):dataset.records[0].sequence_index=9
    with pytest.raises(FrozenInstanceError):dataset.records[0].metadata.complete=False


@pytest.mark.parametrize('field,value',[('schema_version',2),('schema_version',True),('schema_version',1.0),
    ('dataset_id',''),('dataset_id',None),('dataset_id','x'*129),('description','x'*1025),
    ('description',chr(0xD800)),('sources',{}),('records',None),('unknown',0)])
def test_root_rejections(field,value):
    raw=document();raw[field]=value
    with pytest.raises(recorded.RecordedInputError):load(raw)


@pytest.mark.parametrize('field,value',[('source_id',''),('source_id','x'*129),('source_kind','live'),
    ('clock_domain',''),('clock_domain','x'*129),('recording_reference','x'*257),('unknown',1)])
def test_source_rejections(field,value):
    raw=document();raw['sources'][0][field]=value
    with pytest.raises(recorded.RecordedInputError):load(raw)


@pytest.mark.parametrize('field,value',[('record_id',''),('record_id','x'*129),('source_id','missing'),
    ('source_id',False),('sequence_index',True),('sequence_index',-1),('sequence_index',1.0),
    ('sequence_index',recorded.MAX_SEQUENCE+1),('timestamp','2026-01-01'),('metadata',[]),('unknown',1)])
def test_record_rejections(field,value):
    raw=document();raw['records'][0][field]=value
    with pytest.raises(recorded.RecordedInputError):load(raw)


@pytest.mark.parametrize('value,unit',[(True,'s'),(None,'s'),('1','s'),(float('nan'),'s'),
    (float('inf'),'s'),(-float('inf'),'s'),(recorded.MAX_TIMESTAMP+1,'s'),(0,'minutes'),(0,None)])
def test_timestamp_formats_units_and_numbers(value,unit):
    raw=document();raw['records'][0]['timestamp']={'value':value,'unit':unit}
    with pytest.raises(recorded.RecordedInputError):load(raw)


@pytest.mark.parametrize('metadata',[{'complete':'yes'},{'complete':None},{'byte_count':True},
    {'byte_count':-1},{'byte_count':2**63},{'content_digest':'bad'},{'content_digest':'A'*64},
    {'note':''},{'note':'x'*257},{'note':chr(0xD800)},{'target_coordinates':[1,2,3]},
    {'class_id':0},{'confidence':1},{'track_id':'a'},{'trajectory':[]},{'threat_score':0}])
def test_narrow_optional_metadata_types_and_prohibited_fields(metadata):
    raw=document();raw['records'][0]['metadata']=metadata
    with pytest.raises(recorded.RecordedInputError):load(raw)


def test_required_fields_duplicates_and_bounds():
    for location,field in [('root','description'),('source','recording_reference'),
                           ('record','timestamp'),('timestamp','unit')]:
        raw=document();target=raw if location=='root' else raw['sources'][0] if location=='source' else raw['records'][0] if location=='record' else raw['records'][0]['timestamp']
        del target[field]
        with pytest.raises(recorded.RecordedInputError):load(raw)
    for kind in ('sources','records'):
        raw=document();raw[kind].append(deepcopy(raw[kind][0]))
        with pytest.raises(recorded.RecordedInputError,match='duplicate'):load(raw)
        raw=document();raw[kind]=[raw[kind][0]]*((recorded.MAX_SOURCES if kind=='sources' else recorded.MAX_RECORDS)+1)
        with pytest.raises(recorded.RecordedInputError,match='bounded array'):load(raw)
    raw=document();raw['records'][0]['timestamp']['extra']=0
    with pytest.raises(recorded.RecordedInputError):load(raw)


@pytest.mark.parametrize('raw',[b'{',b'[]',b'"\xff"',b'{"x":1,"x":2}',b'{"x":NaN}',
    b'{"x":Infinity}',b'{"x":1e309}',b'['*2000,b' '*(recorded.MAX_BYTES+1)])
def test_json_input_rules(tmp_path,raw):
    path=tmp_path/'dataset.json';path.write_bytes(raw)
    with pytest.raises(recorded.RecordedInputError):recorded.load_dataset(path)


def test_nested_duplicate_and_missing_json_file(tmp_path):
    path=tmp_path/'dataset.json';path.write_text(json.dumps(document()).replace('"unit": "s"','"unit": "s", "unit": "s"'))
    with pytest.raises(recorded.RecordedInputError,match='duplicate'):recorded.load_dataset(path)
    with pytest.raises(recorded.RecordedInputError):recorded.load_dataset(tmp_path/'absent')
    with pytest.raises(recorded.RecordedInputError):recorded.load_dataset(tmp_path)


@pytest.mark.parametrize('reference',['../placeholder.txt','/tmp/placeholder.txt','https://example.com/video',
    'file:///tmp/video','C:\\video','sub\\file','./placeholder.txt','sub/../file','sub//file',
    'placeholder.txt/','\x00','missing.txt',''])
def test_unsafe_and_missing_recording_references(reference):
    raw=document();raw['sources'][0]['recording_reference']=reference
    with pytest.raises(recorded.RecordedInputError):load(raw)


def test_symlink_confinement_and_non_regular_files(tmp_path):
    base=tmp_path/'dataset';base.mkdir();(base/'placeholder.txt').write_text('not opened')
    outside=tmp_path/'outside';outside.write_text('outside')
    (base/'escape').symlink_to(outside);(base/'internal').symlink_to(base/'placeholder.txt')
    raw=document();raw['sources'][0]['recording_reference']='escape'
    with pytest.raises(recorded.RecordedInputError,match='escapes'):recorded.dataset_from_document(raw,base)
    raw['sources'][0]['recording_reference']='internal'
    assert recorded.dataset_from_document(raw,base).sources[0].recording_reference=='internal'
    raw['sources'][0]['recording_reference']='directory';(base/'directory').mkdir()
    with pytest.raises(recorded.RecordedInputError):recorded.dataset_from_document(raw,base)


def test_clock_domains_never_compare_across_sources_and_units_are_exact():
    raw=document();raw['records'][0]['timestamp']={'value':100,'unit':'s'}
    raw['records'][2]['timestamp']={'value':100000,'unit':'ms'}
    raw['records'][1]['timestamp']={'value':-1000,'unit':'ns'}
    raw['records'][3]['timestamp']={'value':-1,'unit':'us'}
    report=recorded.validate_dataset(load(raw))
    assert report['status']=='passed' and [d['code'] for d in report['diagnostics']]==['REPEATED_TIMESTAMP','REPEATED_TIMESTAMP']
    assert len(report['timestamp_domains'])==2
    raw['sources'][1]['clock_domain']=raw['sources'][0]['clock_domain']
    assert recorded.validate_dataset(load(raw))['status']=='passed'


@pytest.mark.parametrize('domain,status,code',[('unknown','not_evaluated','UNKNOWN_CLOCK_DOMAIN'),
    ('utc','failed','UNSUPPORTED_CLOCK_DOMAIN'),('recording:','failed','UNSUPPORTED_CLOCK_DOMAIN')])
def test_unknown_unsupported_domains(domain,status,code):
    raw=document();raw['sources'][0]['clock_domain']=domain
    report=recorded.validate_dataset(load(raw))
    assert report['status']==status and report['diagnostics'][0]['code']==code
    assert any(item['required'] for item in report['unevaluated_checks'])


def test_missing_completeness_empty_and_insufficient_records_status_precedence():
    raw=document();del raw['records'][0]['metadata']['complete']
    assert recorded.validate_dataset(load(raw))['status']=='not_evaluated'
    raw['records'][1]['metadata']['complete']=False
    assert recorded.validate_dataset(load(raw))['status']=='failed'
    raw=document();raw['records']=raw['records'][:1]
    assert recorded.validate_dataset(load(raw))['status']=='not_evaluated'
    raw['sources']=[];raw['records']=[]
    assert recorded.validate_dataset(load(raw))['status']=='not_evaluated'
    with pytest.raises(recorded.RecordedInputError):recorded.validate_dataset(raw)


def test_gap_ranges_bounded_and_record_indices_stable():
    raw=document();raw['records'][2]['sequence_index']=recorded.MAX_SEQUENCE
    report=recorded.validate_dataset(load(raw))
    gap=next(d for d in report['diagnostics'] if d['code']=='SEQUENCE_GAP')
    assert f'1..{recorded.MAX_SEQUENCE-1}' in gap['explanation'] and len(report['diagnostics'])==1
    report=recorded.validate_dataset(load(document('quality_failures')))
    assert [d['record_index'] for d in report['diagnostics']]==[1,1,1,2,None]


def test_optional_declarations_are_not_content_verification():
    raw=document();raw['records'][0]['metadata'].update(byte_count=99,content_digest='0'*64)
    report=recorded.validate_dataset(load(raw))
    assert report['status']=='passed'
    assert report['unevaluated_checks'][-1]['required'] is False
    assert 'declared digests/byte counts' in report['unevaluated_checks'][-1]['explanation']


class Markup(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','link','img')
        assert not any(key in ('src','href') for key,value in attrs)


def test_html_injection_and_offline_document():
    raw=document('quality_failures');hostile='<script>"& Ω</script>'
    raw['dataset_id']=hostile;raw['records'][0]['record_id']=hostile
    report=recorded.validate_dataset(load(raw));report['diagnostics'][0]['explanation']=hostile
    html=recorded.render_html(report)
    assert html.startswith('<!DOCTYPE html>') and html.endswith('</html>\n')
    assert hostile not in html and escape(hostile,quote=True) in html
    Markup().feed(html)
    assert '<caption>' in html and '<th scope="col">' in html


@pytest.mark.parametrize('name,strict,expected',[('valid',True,0),('quality_warnings',True,0),
    ('quality_failures',True,1),('quality_failures',False,0)])
@pytest.mark.parametrize('format',['json','html'])
def test_cli_modes_deterministic_no_writes(tmp_path,name,strict,expected,format):
    args=['--dataset',str(FIXTURES/(name+'.json')),'--format',format,*(['--strict'] if strict else [])]
    a,b=cli(tmp_path,*args),cli(tmp_path,*args)
    assert a.returncode==b.returncode==expected and not a.stderr and not b.stderr and a.stdout==b.stdout
    assert not list(tmp_path.iterdir())
    if format=='json':assert json.loads(a.stdout)['status']==('failed' if name=='quality_failures' else 'passed')
    else:Markup().feed(a.stdout.decode())


def test_cli_unevaluated_invalid_inputs_and_no_partial_stdout(tmp_path):
    (tmp_path/'placeholder.txt').write_text('not opened')
    raw=document();del raw['records'][0]['metadata']['complete']
    path=tmp_path/'dataset.json';path.write_text(json.dumps(raw))
    p=cli(tmp_path,'--dataset',str(path),'--strict');assert p.returncode==2 and not p.stderr and json.loads(p.stdout)['status']=='not_evaluated'
    p=cli(tmp_path,'--dataset',str(path));assert p.returncode==0 and not p.stderr
    for args in ([],['--dataset',str(tmp_path/'missing')],['--dataset',str(path),'--format','csv'],
                 ['--dataset',str(path),'--unknown']):
        p=cli(tmp_path,*args);assert p.returncode==2 and p.stdout==b'' and b'error:' in p.stderr
    raw['sources'][0]['recording_reference']='missing';path.write_text(json.dumps(raw))
    p=cli(tmp_path,'--dataset',str(path),'--strict');assert p.returncode==2 and not p.stdout and b'sources[0]' in p.stderr


def test_audit_never_reads_recording_contents_or_writes_or_networks(tmp_path):
    path=tmp_path/'dataset.json';path.write_text(json.dumps(document()))
    (tmp_path/'placeholder.txt').write_bytes(b'\x00not media\xff')
    code='''
import sys
sys.path[:0]=sys.argv[1:3]
from examples.recorded_sensor_metadata import load_dataset,validate_dataset,render_json,render_html
from pathlib import Path
allowed=Path(sys.argv[3]).resolve()
def audit(event,args):
    if event=='open' and (args[1]!='r' or Path(args[0]).resolve()!=allowed):
        raise AssertionError('unexpected open')
    if event.startswith(('socket.','subprocess.')) or event in ('os.remove','os.rename','os.mkdir'):
        raise AssertionError('unexpected I/O')
sys.addaudithook(audit)
report=validate_dataset(load_dataset(allowed));render_json(report);render_html(report)
'''
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(path)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stdout and not p.stderr


def test_existing_demo_cli_compatibility(tmp_path):
    code='import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2],sys.argv[1]+"/examples"];sys.argv=["demo"];runpy.run_module("examples.synthetic_observation_demo",run_name="__main__")'
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src')],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stderr
    assert hashlib.sha256(p.stdout).hexdigest()=='d9caedddee1ae850fac263f1b457713441276df665035380c7791817b2f610d8'
