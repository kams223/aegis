"""Opaque byte comparisons, descriptor safety and independent integrity outcomes."""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError
from html import escape
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tracemalloc

import pytest

from examples import recorded_sensor_integrity as integrity
from examples.recorded_sensor_metadata import load_dataset

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'examples/recorded_datasets'
DATASET = FIXTURES/'quality_warnings.json'


def declaration(size=0,digest=None,reference='data.bin',source='metadata-fixture'):
    return {'schema_version':1,'manifest_id':'test-integrity','dataset_reference':'dataset.json',
        'entries':[{'source_id':source,'recording_reference':reference,'expected_size_bytes':size,
                    'expected_sha256':hashlib.sha256(b'').hexdigest() if digest is None else digest}]}


def prepare(tmp_path,payload=b'opaque\x00bytes\xff'):
    path=tmp_path/'dataset.json';data=json.loads(DATASET.read_text())
    data['sources'][0]['recording_reference']='data.bin';path.write_text(json.dumps(data))
    recording=tmp_path/'data.bin';recording.write_bytes(payload)
    raw=declaration(len(payload),hashlib.sha256(payload).hexdigest())
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(raw))
    return path,manifest,recording,raw


def verify_loaded(path,raw):
    dataset=load_dataset(path);manifest=integrity.manifest_from_document(raw)
    return dataset,manifest


def report(path,dataset,manifest):
    return integrity.verify_dataset(dataset,manifest,path.parent,path)


def cli(tmp_path,*args):
    code='import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["integrity"]+sys.argv[3:];runpy.run_module("examples.recorded_sensor_integrity",run_name="__main__")'
    return subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),*args],
        cwd=tmp_path,env={},capture_output=True,timeout=30)


@pytest.mark.parametrize('name,status,codes',[('integrity_match','verified',[]),
    ('integrity_size_mismatch','mismatch',['SIZE_MISMATCH']),
    ('integrity_digest_mismatch','mismatch',['DIGEST_MISMATCH'])])
def test_example_manifests_stable_reports_and_schema(name,status,codes):
    a=integrity.run_verification(DATASET,FIXTURES/(name+'.json'))
    b=integrity.run_verification(DATASET,FIXTURES/(name+'.json'))
    assert a==b and a['verification_status']==status and a['entries'][0]['diagnostic_codes']==codes
    assert a['entries'][0]['actual_sha256']==hashlib.sha256((FIXTURES/'placeholder.txt').read_bytes()).hexdigest()
    assert a['entries'][0]['actual_size_bytes']==a['entries'][0]['bytes_read']==(FIXTURES/'placeholder.txt').stat().st_size
    assert list(a)==['schema_version','manifest_id','dataset_id','verification_status','file_count',
        'verified_count','mismatch_count','not_evaluated_count','entries','diagnostics','limitations']
    assert json.loads(integrity.render_json(a))==a and integrity.render_json(a)==integrity.render_json(b)
    assert integrity.render_html(a)==integrity.render_html(b)


def test_immutable_inputs_empty_file_and_no_mutation(tmp_path):
    path,mfile,recording,raw=prepare(tmp_path,b'');saved=deepcopy(raw)
    dataset,manifest=verify_loaded(path,raw);before=asdict(dataset),asdict(manifest)
    result=report(path,dataset,manifest)
    assert result['verification_status']=='verified' and result['entries'][0]['bytes_read']==0
    assert result['entries'][0]['actual_sha256']==hashlib.sha256(b'').hexdigest()
    result['entries'][0]['diagnostic_codes'].append('changed')
    assert raw==saved and (asdict(dataset),asdict(manifest))==before
    with pytest.raises(FrozenInstanceError):manifest.entries[0].expected_size_bytes=1


@pytest.mark.parametrize('changes',[{'schema_version':2},{'schema_version':True},{'schema_version':1.0},
    {'manifest_id':''},{'manifest_id':'x'*129},{'manifest_id':None},{'manifest_id':chr(0xD800)},
    {'entries':{}},{'unknown':0}])
def test_manifest_root_schema(changes):
    raw=declaration();raw.update(changes)
    with pytest.raises(integrity.IntegrityInputError):integrity.manifest_from_document(raw)


@pytest.mark.parametrize('field,value',[('source_id',''),('source_id','x'*129),('source_id',False),
    ('expected_size_bytes',True),('expected_size_bytes',-1),('expected_size_bytes',1.0),
    ('expected_size_bytes',float('nan')),('expected_size_bytes',float('inf')),
    ('expected_size_bytes',integrity.MAX_FILE_BYTES+1),('expected_sha256','a'*63),
    ('expected_sha256','A'*64),('expected_sha256','g'*64),('expected_sha256',None),('unknown',0)])
def test_manifest_entry_schema(field,value):
    raw=declaration();raw['entries'][0][field]=value
    with pytest.raises(integrity.IntegrityInputError):integrity.manifest_from_document(raw)


def test_duplicates_missing_fields_entry_and_aggregate_limits():
    for key in ('schema_version','manifest_id','dataset_reference','entries'):
        raw=declaration();del raw[key]
        with pytest.raises(integrity.IntegrityInputError):integrity.manifest_from_document(raw)
    for key in ('source_id','recording_reference','expected_size_bytes','expected_sha256'):
        raw=declaration();del raw['entries'][0][key]
        with pytest.raises(integrity.IntegrityInputError):integrity.manifest_from_document(raw)
    for duplicate in ('source_id','recording_reference'):
        raw=declaration();other=deepcopy(raw['entries'][0]);other.update(source_id='b',recording_reference='b.bin')
        other[duplicate]=raw['entries'][0][duplicate];raw['entries'].append(other)
        with pytest.raises(integrity.IntegrityInputError,match='duplicate'):integrity.manifest_from_document(raw)
    raw=declaration();raw['entries']*=17
    with pytest.raises(integrity.IntegrityInputError,match='16'):integrity.manifest_from_document(raw)
    raw=declaration();raw['entries']=[{**raw['entries'][0],'source_id':str(i),
        'recording_reference':str(i)+'.bin','expected_size_bytes':integrity.MAX_FILE_BYTES} for i in range(5)]
    with pytest.raises(integrity.IntegrityInputError,match='aggregate'):integrity.manifest_from_document(raw)


@pytest.mark.parametrize('value',['../data.bin','/tmp/data.bin','https://example.com/file','file:///file',
    'C:\\file','sub\\file','./file','sub/../file','sub//file','file/','\x00','', 'x'*257])
@pytest.mark.parametrize('field',['dataset_reference','recording_reference'])
def test_reference_syntax(value,field):
    raw=declaration()
    if field=='dataset_reference':raw[field]=value
    else:raw['entries'][0][field]=value
    with pytest.raises(integrity.IntegrityInputError):integrity.manifest_from_document(raw)


@pytest.mark.parametrize('raw',[b'{',b'[]',b'"\xff"',b'{"a":1,"a":2}',b'{"a":NaN}',
    b'{"a":Infinity}',b'{"a":1e309}',b'['*2000,b' '*(1024*1024+1)])
def test_strict_json_input(tmp_path,raw):
    path=tmp_path/'manifest.json';path.write_bytes(raw)
    with pytest.raises(integrity.IntegrityInputError):integrity.load_manifest(path)


def test_nested_duplicate_and_missing_manifest(tmp_path):
    path=tmp_path/'manifest.json';path.write_text(json.dumps(declaration()).replace('"expected_size_bytes": 0','"expected_size_bytes": 0, "expected_size_bytes": 0'))
    with pytest.raises(integrity.IntegrityInputError,match='duplicate'):integrity.load_manifest(path)
    with pytest.raises(integrity.IntegrityInputError):integrity.load_manifest(tmp_path/'absent')


@pytest.mark.parametrize('case',['missing','extra','wrong_pair','wrong_dataset'])
def test_exact_associations_before_any_recording_reads(tmp_path,monkeypatch,case):
    path,mfile,recording,raw=prepare(tmp_path);dataset=load_dataset(path)
    if case=='missing':raw['entries']=[]
    elif case=='extra':raw['entries'].append({**raw['entries'][0],'source_id':'extra','recording_reference':'other.bin'})
    elif case=='wrong_pair':raw['entries'][0]['recording_reference']='other.bin'
    else:raw['dataset_reference']='other.json'
    monkeypatch.setattr(integrity.os,'read',lambda *args:pytest.fail('unexpected read'))
    with pytest.raises(integrity.IntegrityInputError):report(path,dataset,integrity.manifest_from_document(raw))


def test_missing_after_load_and_missing_initial_input(tmp_path):
    path,mfile,recording,raw=prepare(tmp_path);dataset,manifest=verify_loaded(path,raw);recording.unlink()
    result=report(path,dataset,manifest)
    assert result['verification_status']=='not_evaluated' and result['entries'][0]['diagnostic_codes']==['FILE_UNAVAILABLE']
    assert result['entries'][0]['actual_sha256'] is None
    p=cli(tmp_path,'--dataset',str(path),'--manifest',str(mfile),'--strict')
    assert p.returncode==2 and p.stdout==b'' and p.stderr


def test_permission_error_report(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path);dataset,manifest=verify_loaded(path,raw);original=os.open
    def denied(name,*args,**kwargs):
        if str(name)=='data.bin':raise PermissionError('host-specific text must not enter report')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(integrity.os,'open',denied)
    result=report(path,dataset,manifest)
    assert result['verification_status']=='not_evaluated'
    assert result['entries'][0]['diagnostic_codes']==['PERMISSION_DENIED']
    assert 'host-specific text' not in integrity.render_json(result)


@pytest.mark.parametrize('kind',['short','growth','mutation','truncation'])
def test_observable_changes_during_stream(tmp_path,monkeypatch,kind):
    path,mfile,recording,raw=prepare(tmp_path,b'a'*(integrity.CHUNK_BYTES+13))
    dataset,manifest=verify_loaded(path,raw);original=os.read;first=True
    def changed(fd,count):
        nonlocal first
        if first and kind=='short':first=False;return b''
        chunk=original(fd,count)
        if first:
            first=False
            if kind=='growth':
                with recording.open('ab') as stream:stream.write(b'x')
            elif kind=='truncation':recording.write_bytes(b'')
            elif kind=='mutation':
                info=recording.stat()
                with recording.open('r+b') as stream:stream.write(b'z')
                os.utime(recording,ns=(info.st_atime_ns,info.st_mtime_ns+1000000000))
        return chunk
    monkeypatch.setattr(integrity.os,'read',changed)
    result=report(path,dataset,manifest);row=result['entries'][0]
    expected={'short':'SHORT_READ','growth':'FILE_GROWTH','mutation':'FILE_CHANGED','truncation':'SHORT_READ'}[kind]
    assert row['diagnostic_codes']==[expected] and row['actual_sha256'] is None
    assert row['integrity_status']=='not_evaluated' and row['bytes_read']<=integrity.MAX_FILE_BYTES


def test_reference_replacement_after_hashing(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path);dataset,manifest=verify_loaded(path,raw);original=integrity._stream
    def replace(*args):
        digest=original(*args);recording.unlink();recording.write_bytes(b'replacement');return digest
    monkeypatch.setattr(integrity,'_stream',replace)
    row=report(path,dataset,manifest)['entries'][0]
    assert row['diagnostic_codes']==['FILE_CHANGED'] and row['actual_sha256'] is None


@pytest.mark.parametrize('outside',[False,True])
def test_symlinks_rejected_without_read(tmp_path,monkeypatch,outside):
    path,mfile,recording,raw=prepare(tmp_path);dataset,manifest=verify_loaded(path,raw)
    other=tmp_path/'inside.bin' if not outside else tmp_path.parent/(tmp_path.name+'-outside.bin')
    other.write_bytes(b'test');recording.unlink();recording.symlink_to(other)
    monkeypatch.setattr(integrity.os,'read',lambda *args:pytest.fail('unexpected read'))
    assert report(path,dataset,manifest)['entries'][0]['diagnostic_codes']==['UNSAFE_REFERENCE']


def test_symlink_parent_and_special_files(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path)
    folder=tmp_path/'folder';folder.mkdir();recording.rename(folder/'data.bin')
    data=json.loads(path.read_text());data['sources'][0]['recording_reference']='folder/data.bin';path.write_text(json.dumps(data))
    raw['entries'][0]['recording_reference']='folder/data.bin';dataset,manifest=verify_loaded(path,raw)
    folder.rename(tmp_path/'other');folder.symlink_to(tmp_path/'other',target_is_directory=True)
    assert report(path,dataset,manifest)['entries'][0]['diagnostic_codes']==['UNSAFE_REFERENCE']
    folder.unlink();(tmp_path/'other').rename(folder);(folder/'data.bin').unlink();os.mkfifo(folder/'data.bin')
    monkeypatch.setattr(integrity.os,'read',lambda *args:pytest.fail('unexpected read'))
    assert report(path,dataset,manifest)['entries'][0]['diagnostic_codes']==['UNSUPPORTED_FILE_TYPE']


def test_actual_size_limits_prevent_reads(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path,b'a'*10);dataset,manifest=verify_loaded(path,raw)
    monkeypatch.setattr(integrity,'MAX_FILE_BYTES',9)
    monkeypatch.setattr(integrity.os,'read',lambda *args:pytest.fail('unexpected read'))
    row=report(path,dataset,manifest)['entries'][0]
    assert row['actual_size_bytes']==10 and row['diagnostic_codes']==['FILE_SIZE_LIMIT'] and row['bytes_read']==0


def test_actual_aggregate_limit_and_status_precedence(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path,b'a'*8);data=json.loads(path.read_text())
    data['sources'].append({**data['sources'][0],'source_id':'b','recording_reference':'b.bin'})
    path.write_text(json.dumps(data));(tmp_path/'b.bin').write_bytes(b'b'*8)
    raw['entries'].append({**raw['entries'][0],'source_id':'b','recording_reference':'b.bin'})
    dataset,manifest=verify_loaded(path,raw)
    monkeypatch.setattr(integrity,'MAX_AGGREGATE_BYTES',15)
    result=report(path,dataset,manifest)
    assert result['not_evaluated_count']==2 and all(row['bytes_read']==0 for row in result['entries'])
    assert all(row['diagnostic_codes']==['AGGREGATE_SIZE_LIMIT'] for row in result['entries'])
    monkeypatch.setattr(integrity,'MAX_AGGREGATE_BYTES',16)
    raw['entries'][0]['expected_sha256']='0'*64;manifest=integrity.manifest_from_document(raw)
    (tmp_path/'b.bin').unlink();result=report(path,dataset,manifest)
    assert result['verification_status']=='mismatch' and result['mismatch_count']==result['not_evaluated_count']==1


def test_streaming_memory_and_read_sizes(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path,b'x'*(4*1024*1024));dataset,manifest=verify_loaded(path,raw)
    sizes=[];original=os.read
    def bounded(fd,count):sizes.append(count);return original(fd,count)
    monkeypatch.setattr(integrity.os,'read',bounded)
    tracemalloc.start()
    try:
        result=report(path,dataset,manifest);_,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert result['verification_status']=='verified' and max(sizes)<=integrity.CHUNK_BYTES
    assert len(sizes)>2 and peak<integrity.CHUNK_BYTES*8


def test_empty_manifest_and_unsupported_platform(tmp_path,monkeypatch):
    path,mfile,recording,raw=prepare(tmp_path)
    data=json.loads(path.read_text());data['sources']=[];data['records']=[];path.write_text(json.dumps(data))
    raw['entries']=[];result=report(path,load_dataset(path),integrity.manifest_from_document(raw))
    assert result['verification_status']=='not_evaluated' and result['diagnostics'][-1]['code']=='NO_FILES'
    path,mfile,recording,raw=prepare(tmp_path)
    monkeypatch.setattr(integrity,'_DESCRIPTORS_SUPPORTED',False)
    assert report(path,*verify_loaded(path,raw))['entries'][0]['diagnostic_codes']==['DESCRIPTOR_VERIFICATION_UNAVAILABLE']


class Markup(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','link','img')
        assert not any(key in ('src','href') for key,value in attrs)


def test_html_escaping(tmp_path):
    path,mfile,recording,raw=prepare(tmp_path);raw['manifest_id']='<script>"& Ω</script>'
    result=report(path,*verify_loaded(path,raw));result['entries'][0]['source_id']=raw['manifest_id']
    html=integrity.render_html(result)
    assert raw['manifest_id'] not in html and escape(raw['manifest_id'],quote=True) in html
    assert html.startswith('<!DOCTYPE html>') and html.endswith('</html>\n');Markup().feed(html)


@pytest.mark.parametrize('name,strict,code',[('integrity_match',True,0),('integrity_size_mismatch',True,1),
    ('integrity_digest_mismatch',True,1),('integrity_digest_mismatch',False,0)])
@pytest.mark.parametrize('format',['json','html'])
def test_cli_reports_stable_readonly(tmp_path,name,strict,code,format):
    args=['--dataset',str(DATASET),'--manifest',str(FIXTURES/(name+'.json')),'--format',format,*(['--strict'] if strict else [])]
    a,b=cli(tmp_path,*args),cli(tmp_path,*args)
    assert a.returncode==b.returncode==code and a.stdout==b.stdout and not a.stderr and not b.stderr
    assert not list(tmp_path.iterdir())
    if format=='json':assert json.loads(a.stdout)['verification_status']==('verified' if code==0 and name=='integrity_match' else 'mismatch')
    else:Markup().feed(a.stdout.decode())


def test_cli_unevaluated_and_invalid_no_partial_output(tmp_path,monkeypatch,capsys):
    path,mfile,recording,raw=prepare(tmp_path)
    monkeypatch.setattr(integrity,'_DESCRIPTORS_SUPPORTED',False)
    args=['--dataset',str(path),'--manifest',str(mfile)]
    assert integrity.main(args+['--strict'])==2
    captured=capsys.readouterr();assert not captured.err and json.loads(captured.out)['verification_status']=='not_evaluated'
    assert integrity.main(args)==0;capsys.readouterr()
    for bad in ([],['--dataset',str(path)],args+['--format','csv'],args+['--unknown'],
                ['--dataset',str(path),'--manifest',str(tmp_path/'absent')]):
        p=cli(tmp_path,*bad);assert p.returncode==2 and not p.stdout and p.stderr
    raw['entries'][0]['source_id']='other';mfile.write_text(json.dumps(raw))
    p=cli(tmp_path,*args);assert p.returncode==2 and not p.stdout and b'associations' in p.stderr


def test_no_writes_network_processes_or_media_decoding(tmp_path):
    path,mfile,recording,raw=prepare(tmp_path);before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    code='''
import sys,os
sys.path[:0]=sys.argv[1:3]
from examples.recorded_sensor_integrity import run_verification,render_json,render_html
def audit(event,args):
    if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
        raise AssertionError('write')
    if event.startswith(('socket.','subprocess.')) or event in ('os.remove','os.rename','os.mkdir'):
        raise AssertionError('unexpected operation')
    if event=='import' and args[0].split('.')[0] in ('cv2','numpy','PIL','torch','ultralytics'):
        raise AssertionError('media/inference import')
sys.addaudithook(audit)
result=run_verification(sys.argv[3],sys.argv[4]);render_json(result);render_html(result)
assert result['verification_status']=='verified'
'''
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(path),str(mfile)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stdout and not p.stderr
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before


def test_existing_recorded_cli_compatibility(tmp_path):
    code='import runpy,sys;sys.path[:0]=sys.argv[1:3];sys.argv=["recorded","--dataset",sys.argv[3],"--strict"];runpy.run_module("examples.recorded_sensor_metadata",run_name="__main__")'
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT),str(ROOT/'src'),str(DATASET)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert p.returncode==0 and not p.stderr
    # Exact pre-Phase-59 stdout capture, independent of current rendering code.
    assert hashlib.sha256(p.stdout).hexdigest()=='be27e15513a310d9f16b08add8407a2c04e4ad838f8d3e8145ce1dd812ff155b'
