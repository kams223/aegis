"""Repeatability, bounded diagnostics and SF-3/IO isolation."""
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import pytest
from examples.correspondence_research_fixture import authored_reports,fixture,request_for
from test_correspondence_contracts import report,rebuild,code
from aegis.simulation.correspondence_contracts import thaw
from aegis.simulation.correspondence_io import canonical_bytes
from aegis.simulation.correspondence_evaluation import report_bytes


def test_three_replays_identical_and_raw_impaired_separate():
    runs=[{k:report_bytes(v) for k,v in authored_reports().items()} for _ in range(3)]
    assert runs[0]==runs[1]==runs[2]
    assert runs[0]['acceptance']!=runs[0]['impaired']


def test_three_hash_seeds():
    outputs=[]
    for seed in ('0','1','1729'):
        env={**os.environ,'PYTHONHASHSEED':seed,'PYTHONPATH':'src:.'}
        p=subprocess.run([sys.executable,'-B','examples/correspondence_research_fixture.py'],env=env,capture_output=True,text=True,timeout=30)
        assert p.returncode==0,p.stderr
        outputs.append(p.stdout)
    assert outputs[0]==outputs[1]==outputs[2]


def test_pure_evaluation_no_clock_io_or_sf3_calls(monkeypatch):
    import time
    from aegis.fusion import reference_estimator
    b=fixture(('A',)); before=repr(b)
    def forbidden(*args,**kwargs): raise AssertionError('Forbidden runtime access')
    for name in ('initialize','predict','correct','adapt_position','replay'):
        if hasattr(reference_estimator,name): monkeypatch.setattr(reference_estimator,name,forbidden)
    with monkeypatch.context() as m:
        m.setattr(time,'time',forbidden); m.setattr(time,'monotonic',forbidden)
        m.setattr('builtins.open',forbidden)
        r=report(b)
    assert r['populations']['correct_count']==1 and repr(b)==before
    for name in ('contracts','io','evaluation'):
        text=Path('src/aegis/simulation/correspondence_'+name+'.py').read_text()
        assert 'import reference_estimator' not in text
        assert 'from aegis.fusion.reference_estimator' not in text


def test_diagnostic_cap_does_not_stop_validation():
    b=fixture(('unresolved',)*140)
    r=report(b,evaluation=200)
    assert r['status']=='complete'
    assert len(r['diagnostics'])==256 and r['diagnostics_dropped']>0
    assert r['populations']['unresolved_count']==140
    bad=rebuild(b,truth_change=lambda t:t['evidence_labels'][-1].update(truth_entity_id='absent'))
    assert code(report(bad))=='UNKNOWN_REFERENCE'


def test_opportunity_edge_bound():
    b=fixture(('M',))
    # Closed schema count rejection is atomic before the evaluator can score.
    d=thaw(b.truth.data); d['opportunities']*=4097
    from aegis.simulation.correspondence_io import artifact_from_data
    from aegis.simulation.correspondence_contracts import ContractError
    with pytest.raises(ContractError,match='BOUND'): artifact_from_data(d,'truth')


def test_output_overflow_has_minimal_atomic_rejection(monkeypatch):
    from aegis.simulation.correspondence_contracts import MAX_BYTES
    b=fixture(('A',)); monkeypatch.setitem(MAX_BYTES,'report',100)
    r=report(b)
    assert code(r)=='OUTPUT_BOUND'
    assert len(canonical_bytes(r))<=4096 and r['metrics'] is None
    assert r['bindings']['dataset_sha256']==b.observations.sha256


def test_review_large_bounded_population_and_independent_node_count():
    b=fixture(('A',)*256)
    def value_nodes(value):
        if isinstance(value,dict): return 1+sum(value_nodes(x) for x in value.values())
        if isinstance(value,list): return 1+sum(value_nodes(x) for x in value)
        return 1
    assert value_nodes(thaw(b.observations.data))==47640
    assert b.observations.byte_count<1024**2
    r=report(b,evaluation=300)
    assert r['status']=='complete'
    assert r['populations']['correct_count']==r['populations']['known_truth_count']==256
    assert r['metrics']['strict_correctness']=={'numerator':256,'denominator':256}
