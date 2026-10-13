"""Bounded manifests, path confinement, offline reports and strict batch CLI."""
from dataclasses import asdict
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from examples import synthetic_observation_batch as batch
from examples.synthetic_observation_scenarios import load_scenario

ROOT = Path(__file__).resolve().parents[1]


def local(tmp_path, name='baseline', *, with_profile=True):
    scenario = tmp_path/'scenario.json'
    shutil.copyfile(ROOT/'examples/scenarios'/f'{name}.json',scenario)
    shutil.copyfile(ROOT/'examples/profiles'/f'{name}.json',tmp_path/'profile.json')
    data = {'schema_version':1,'batch_id':'local batch','description':'Software-only checks',
            'entries':[{'scenario':'scenario.json', **({'profile':'profile.json'} if with_profile else {})}]}
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(data))
    return path,data


def write(path,data):
    path.write_text(json.dumps(data))


@pytest.mark.parametrize('name,status,count', [('synthetic_validation_batch','passed',2),
    ('synthetic_validation_fault_batch','failed',3)])
def test_every_batch_fixture_order_schema_and_stable_reports(name,status,count):
    path = ROOT/'examples'/f'{name}.json'
    first,second = batch.run_batch(path),batch.run_batch(path)
    assert first == second and first['overall_status'] == status
    assert list(first) == ['schema_version','batch_id','description','scope','entries','overall_status','limitations']
    assert [e['position'] for e in first['entries']] == list(range(count))
    assert first['entries'][0]['scenario_id'] == 'JSON baseline camera/radar fixture'
    assert first['entries'][1]['scenario_id'] == 'Explicit repeated delivery fixture'
    assert batch.render_batch_json(first) == batch.render_batch_json(second)
    assert batch.render_batch_html(first) == batch.render_batch_html(second)
    assert json.loads(batch.render_batch_json(first)) == first
    if count == 3:
        row = first['entries'][2]
        assert row['profile_evaluation_status'] == 'passed'
        assert row['metadata_validation_status'] == row['final_status'] == 'failed'
        assert row['diagnostic_counts']['Invalid'] == 12
        assert row['scenario_validation']['overall_validation']['status'] == 'failed'
    else:
        assert all(e['scenario_validation']['overall_validation']['status'] == 'not_evaluated' for e in first['entries'])


def test_missing_profile_empty_profile_and_empty_batch_are_unevaluated(tmp_path):
    path,data = local(tmp_path,with_profile=False)
    report = batch.run_batch(path)
    row = report['entries'][0]
    assert report['overall_status'] == row['final_status'] == row['profile_evaluation_status'] == 'not_evaluated'
    assert row['profile_loading'] == 'not_evaluated' and row['profile_id'] is None
    assert row['metadata_validation_status'] == 'passed'
    data['entries'] = []
    write(path,data)
    assert batch.run_batch(path)['overall_status'] == 'not_evaluated'


def test_profile_mismatch_is_a_reported_failure_not_load_error(tmp_path):
    path,data = local(tmp_path)
    p = json.loads((tmp_path/'profile.json').read_text())
    p['expectations']['delivery_count'] = 10
    write(tmp_path/'profile.json',p)
    report = batch.run_batch(path)
    row = report['entries'][0]
    assert row['profile_loading'] == 'passed' and row['loading_error'] is None
    assert row['metadata_validation_status'] == 'passed' and row['final_status'] == 'failed'
    assert row['profile_evaluation']['failed_expectations'] == [
        {'id':'delivery_count','status':'failed','expected':10,'actual':2}]


@pytest.mark.parametrize('value', ['../scenario.json','/tmp/file','https://example.com/file',
    'file:///tmp/file','C:\\file','sub\\file','./scenario.json','sub/../scenario.json',
    'sub//file','missing.json','scenario.json/','\x00',''])
def test_entry_paths_reject_traversal_urls_invalid_paths_and_missing_files(tmp_path,value):
    path,data = local(tmp_path)
    data['entries'][0]['scenario'] = value
    write(path,data)
    with pytest.raises(batch.BatchInputError):
        batch.run_batch(path)


def test_symlink_escape_rejected_and_internal_symlink_allowed(tmp_path):
    base = tmp_path/'inside';base.mkdir()
    path,data = local(base)
    outside = tmp_path/'outside.json'
    shutil.copyfile(base/'scenario.json',outside)
    (base/'escape.json').symlink_to(outside)
    data['entries'][0]['scenario'] = 'escape.json';write(path,data)
    with pytest.raises(batch.BatchInputError,match='symlink escapes'):
        batch.run_batch(path)
    (base/'internal.json').symlink_to(base/'scenario.json')
    data['entries'][0]['scenario'] = 'internal.json';write(path,data)
    assert batch.run_batch(path)['overall_status'] == 'passed'
    (base/'profile-escape.json').symlink_to(outside)
    data['entries'][0]['profile'] = 'profile-escape.json';write(path,data)
    with pytest.raises(batch.BatchInputError,match='profile_loading'):
        batch.run_batch(path)


@pytest.mark.parametrize('field,value', [('schema_version',2),('schema_version',True),
    ('batch_id',''),('description',None),('entries',{}),('entries',[{}]),
    ('entries',[{'scenario':'scenario.json','extra':0}]),('entries',[{'scenario':1}]),
    ('entries',[{'scenario':'scenario.json','profile':None}]),
    ('entries',[{'scenario':'scenario.json'}]*33)])
def test_manifest_schema_and_entry_bounds(tmp_path,field,value):
    path,data = local(tmp_path)
    data[field] = value;write(path,data)
    with pytest.raises(batch.BatchInputError):
        batch.run_batch(path)


@pytest.mark.parametrize('raw',[b'{',b'"\xff"',b'{"x":1,"x":2}',b'{"x":NaN}',
    b'{"x":1e309}',b' '*(1024*1024+1)])
def test_manifest_json_error_rules(tmp_path,raw):
    path = tmp_path/'manifest.json';path.write_bytes(raw)
    with pytest.raises(batch.BatchInputError):
        batch.run_batch(path)


def test_failed_later_entry_rejects_entire_batch_and_source_nonmutation(tmp_path,monkeypatch):
    path,data = local(tmp_path)
    scenario = load_scenario(tmp_path/'scenario.json');before = asdict(scenario)
    original = batch.load_scenario
    monkeypatch.setattr(batch,'load_scenario',lambda p: scenario)
    assert batch.run_batch(path)['overall_status'] == 'passed'
    assert asdict(scenario) == before
    monkeypatch.setattr(batch,'load_scenario',original)
    data['entries'].append({'scenario':'absent.json'});write(path,data)
    with pytest.raises(batch.BatchInputError,match='entry 1: scenario_loading'):
        batch.run_batch(path)


def test_id_mismatch_and_loading_error_stage_are_distinct(tmp_path):
    path,data = local(tmp_path)
    p = json.loads((tmp_path/'profile.json').read_text());p['scenario_id']='other'
    write(tmp_path/'profile.json',p)
    with pytest.raises(batch.BatchInputError,match='profile_loading: scenario_id'):
        batch.run_batch(path)
    (tmp_path/'profile.json').write_text('{')
    with pytest.raises(batch.BatchInputError,match='profile_loading: invalid'):
        batch.run_batch(path)
    (tmp_path/'scenario.json').write_text('{')
    with pytest.raises(batch.BatchInputError,match='scenario_loading: invalid'):
        batch.run_batch(path)


class Markup(HTMLParser):
    def __init__(self,text):
        super().__init__();self.tags=[];self.attrs=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag);self.attrs.extend(attrs)


def test_html_escaping_all_dynamic_fields_and_offline_structure(tmp_path):
    path,data = local(tmp_path)
    hostile = '<script>"& Ω</script>'
    data['batch_id']=data['description']=hostile;write(path,data)
    report=batch.run_batch(path)
    report['entries'][0]['scenario_id']=hostile
    report['entries'][0]['profile_evaluation']['checks'][0]['expected']=hostile
    html=batch.render_batch_html(report)
    assert html.startswith('<!DOCTYPE html>') and html.endswith('</html>\n')
    assert hostile not in html and escape(hostile,quote=True) in html
    parsed=Markup(html)
    assert 'script' not in parsed.tags and 'link' not in parsed.tags and 'img' not in parsed.tags
    assert not any(name in ('src','href') for name,value in parsed.attrs)
    assert 'caption' in parsed.tags and 'th' in parsed.tags


def cli(tmp_path,*args,optimized=False):
    script='import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];sys.argv=["batch"]+sys.argv[3:];runpy.run_module("examples.synthetic_observation_batch",run_name="__main__")'
    return subprocess.run([sys.executable,'-I','-S','-B',*(['-O'] if optimized else []),'-c',script,
        str(ROOT),str(ROOT/'src'),*args],cwd=tmp_path,env={},capture_output=True,timeout=30)


@pytest.mark.parametrize('name,with_profile,code',[('baseline',True,0),('metadata_edge_cases',True,1),('baseline',False,2)])
@pytest.mark.parametrize('format',['json','html'])
def test_cli_strict_reports_complete_stable_and_without_stdout_contamination(tmp_path,name,with_profile,code,format):
    path,data=local(tmp_path,name,with_profile=with_profile)
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    args=('--manifest',str(path),'--format',format,'--strict')
    first,second=cli(tmp_path,*args),cli(tmp_path,*args)
    assert first.returncode==second.returncode==code and first.stderr==second.stderr==b''
    assert first.stdout==second.stdout and first.stdout
    if format=='json':
        assert json.loads(first.stdout)['overall_status']=={0:'passed',1:'failed',2:'not_evaluated'}[code]
    else:
        assert first.stdout.startswith(b'<!DOCTYPE html>') and first.stdout.endswith(b'</html>\n')
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before


def test_cli_non_strict_invalid_invocation_and_no_partial_report(tmp_path):
    path,data=local(tmp_path,'metadata_edge_cases')
    assert cli(tmp_path,'--manifest',str(path)).returncode==0
    for args in ([],['--manifest',str(path),'--format','csv'],['--manifest',str(path),'--unknown']):
        r=cli(tmp_path,*args);assert r.returncode==2 and r.stdout==b'' and b'error:' in r.stderr
    data['entries'].append({'scenario':'absent.json'});write(path,data)
    r=cli(tmp_path,'--manifest',str(path),'--strict')
    assert r.returncode==2 and r.stdout==b'' and b'entry 1: scenario_loading' in r.stderr
    r=cli(tmp_path,'--manifest',str(path),optimized=True)
    assert r.returncode!=0 and r.stdout==b'' and b'Run without -O' in r.stderr


def test_readonly_offline_execution_audit(tmp_path):
    path,data=local(tmp_path)
    script='''
import sys
sys.path[:0]=sys.argv[1:3]
from examples.synthetic_observation_batch import run_batch,render_batch_json,render_batch_html
from pathlib import Path
root=Path(sys.argv[3]).parent.resolve()
def audit(event,args):
    if event=='open':
        if args[1]!='r' or not Path(args[0]).resolve().is_relative_to(root):
            raise AssertionError('unexpected I/O')
    if event.startswith(('socket.','subprocess.')) or event in ('os.remove','os.rename','os.mkdir'):
        raise AssertionError('write/network/process operation')
sys.addaudithook(audit)
report=run_batch(sys.argv[3]);render_batch_json(report);render_batch_html(report)
'''
    r=subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(ROOT),str(ROOT/'src'),str(path)],
        cwd=tmp_path,env={},capture_output=True,timeout=30)
    assert r.returncode==0,r.stderr.decode()
    assert r.stdout==b''


def test_maximum_batch_entries_retains_each_explicit_occurrence(tmp_path):
    path,data=local(tmp_path)
    data['entries'] *= batch.MAX_ENTRIES
    write(path,data)
    report=batch.run_batch(path)
    assert len(report['entries']) == 32
    assert [row['position'] for row in report['entries']] == list(range(32))
    assert report['overall_status'] == 'passed'


def test_empty_history_keeps_lineage_unevaluated_even_with_matching_profile(tmp_path):
    path,data=local(tmp_path)
    source=json.loads((tmp_path/'scenario.json').read_text())
    source['observations']=[];source['deliveries']=[]
    write(tmp_path/'scenario.json',source)
    declared=json.loads((tmp_path/'profile.json').read_text())
    declared['expectations']={'source_count':2,'observation_count':0,'delivery_count':0,'metadata_validity':'passed'}
    write(tmp_path/'profile.json',declared)
    row=batch.run_batch(path)['entries'][0]
    assert row['profile_evaluation_status']=='passed'
    assert row['metadata_validation_status']=='passed'
    assert row['inventory_integrity_status']==row['final_status']=='not_evaluated'


def test_cli_mismatch_failure_keeps_report_and_profile_load_failure_has_none(tmp_path):
    path,data=local(tmp_path)
    declared=json.loads((tmp_path/'profile.json').read_text())
    declared['expectations']['delivery_count']=99
    write(tmp_path/'profile.json',declared)
    result=cli(tmp_path,'--manifest',str(path),'--strict')
    assert result.returncode==1 and result.stderr==b''
    assert json.loads(result.stdout)['entries'][0]['profile_evaluation']['failed_expectations'][0]['actual']==2
    declared['scenario_id']='unrelated';write(tmp_path/'profile.json',declared)
    result=cli(tmp_path,'--manifest',str(path),'--strict')
    assert result.returncode==2 and result.stdout==b'' and b'profile_loading' in result.stderr


def test_manifest_unknown_fields_missing_required_fields_and_missing_file(tmp_path):
    path,data=local(tmp_path)
    write(path,{**data,'extra':0})
    with pytest.raises(batch.BatchInputError,match='unsupported'):
        batch.run_batch(path)
    del data['schema_version'];write(path,data)
    with pytest.raises(batch.BatchInputError,match='missing'):
        batch.run_batch(path)
    with pytest.raises(batch.BatchInputError,match='unable to read'):
        batch.run_batch(tmp_path/'absent.json')
