"""Independent hand sequences from the reviewed architecture."""
from copy import deepcopy
import pytest
from examples.correspondence_research_fixture import fixture,request_for
from test_correspondence_contracts import rebuild,report,code
from aegis.fusion.contracts import MeasurementTime
from aegis.simulation.correspondence_io import time_wire
from aegis.simulation.correspondence_evaluation import evaluate_supplied_hypotheses


@pytest.mark.parametrize('sequence,segments,fragments,same,changed,resolved,assessed,splits',[
 (('A','A'),[1],0,1,0,2,2,0),
 (('A','B','A'),[3],2,0,2,3,3,0),
 (('A','M','A'),[2],1,1,0,2,3,0),
 (('A','unresolved','A'),[2],1,1,0,2,3,0),
 (('A','?','A'),[1,1],0,0,0,2,2,0),
 (('A',('A','B'),'A'),[2],1,1,0,2,3,1),
 ((('A','B'),),[0],0,0,0,0,1,1),
 (('M','A'),[1],0,0,0,1,2,0),
])
def test_independent_continuity_oracles(sequence,segments,fragments,same,changed,resolved,assessed,splits):
    r=report(fixture(sequence)); assert r['status']!='rejected'
    e=r['continuity']['entities'][0]
    assert list(e['block_segment_counts'])==segments
    assert e['fragment_count']==fragments
    assert (e['same_label_links'],e['changed_label_links'])==(same,changed)
    assert (e['resolved_steps'],e['assessed_steps'],e['split_steps'])==(resolved,assessed,splits)
    assert e['resolved_step_coverage']=={'numerator':resolved,'denominator':assessed}


@pytest.mark.parametrize('sequence,statuses',[
 (('M','A'),['temporarily_missing','observed']),
 (('A','M','A'),['observed','temporarily_missing','resumed']),
 (('A','?','A'),['observed','unknown','observed']),
 (('A','unresolved','A'),['observed','observed','observed']),
 (('A','end'),['observed','ended']),
])
def test_lifecycle_precedence(sequence,statuses):
    assert [r['status'] for r in report(fixture(sequence))['lifecycle_rows']]==statuses


def test_terminal_visibility_and_conflicting_observation():
    b=fixture(('A','end'))
    assert len(report(b,evaluation=0)['lifecycle_rows'])==1
    b=fixture(('A','A'))
    def change(t):
        t['terminal_annotations'].append(dict(truth_entity_id='g',step_ref='s1',visible_at=time_wire(MeasurementTime(1,'sim')),provenance={'assertion_id':'end','revision':'1'}))
    assert code(report(rebuild(b,truth_change=change)))=='TERMINAL_CONFLICT'


def test_incomplete_acquisitions_observed_but_not_assessed():
    b=fixture(('A',))
    def change(d):
        d['acquisitions'].append(dict(acquisition_ref='other',step_ref='s0',sensor_id='second',source_session_id='s',acquisition_id='none',acquisition_time=None,status='unconfirmed',observation_occurrence_refs=[],reason='Unknown callback',acquisition_mapping_ref=None,available_at=None,completeness_provenance={'assertion_id':'unknown','revision':'1'}))
    b=rebuild(b,change,truth_change=lambda t:t['opportunities'][0]['required_acquisition_refs'].append('other'))
    r=report(b)
    assert r['lifecycle_rows'][0]['status']=='observed'
    assert r['continuity']['entities'][0]['assessed_steps']==0


def test_scope_does_not_create_absence():
    b=fixture(('A',)); request=request_for(b); request['scope']['evidence_keys']=[]
    r=evaluate_supplied_hypotheses(b,request)
    assert r['lifecycle_rows'][0]['status']=='observed'
    assert r['populations']['excluded_scope_count']==1
    assert r['continuity']['entities'][0]['assessed_steps']==0


def test_missing_schedule_breaks_continuity():
    b=fixture(('A','M','A'))
    b=rebuild(b,truth_change=lambda t:t['opportunities'].pop(1))
    r=report(b)
    assert [x['status'] for x in r['lifecycle_rows']]==['observed','observed']
    assert r['continuity']['entities'][0]['same_label_links']==0
    assert r['continuity']['entities'][0]['fragment_count']==0


def contamination_bundle(simultaneous=False):
    b=fixture((('A','A'),) if simultaneous else ('A','A'))
    def change(t):
        t['evidence_labels'][1]['truth_entity_id']='other'
        o=deepcopy(t['opportunities'][-1]); o['truth_entity_id']='other'; t['opportunities'].append(o)
    return rebuild(b,truth_change=change)


@pytest.mark.parametrize('simultaneous', [False,True])
def test_contamination_without_optimized_alignment(simultaneous):
    r=report(contamination_bundle(simultaneous)); p=r['populations']; label=r['continuity']['labels'][0]
    assert p['correct_count']==p['incorrect_count']==1
    assert label['truth_support']==('g','other') and label['contaminated'] is True
    assert label['collision_step_count']==int(simultaneous)
    assert label['adjacent_step_identity_changes']==int(not simultaneous)


def test_not_observable_and_empty_unknown_closure():
    b=fixture(('M',))
    b=rebuild(b,truth_change=lambda t:t['opportunities'][0].update(expectation='not_observable',required_acquisition_refs=[]))
    assert report(b)['lifecycle_rows'][0]['status']=='not_observable'
    b=rebuild(fixture(('M',)),lambda d:d['acquisitions'][0].update(available_at=None))
    assert report(b)['lifecycle_rows'][0]['status']=='unknown'


def test_review_mixed_assignments_preserve_errors_and_conditioned_continuity():
    r=report(fixture((('A','wrong'),)))
    assert r['populations']['correct_count']==r['populations']['incorrect_count']==1
    assert r['metrics']['strict_correctness']=={'numerator':1,'denominator':2}
    entity=r['continuity']['entities'][0]
    assert entity['resolved_steps']==entity['mixed_steps']==1
    assert entity['split_steps']==0
    assert 'MIXED_STEP' in r['lifecycle_rows'][0]['reason_codes']


def test_review_same_label_same_step_is_one_resolved_step_not_a_link():
    r=report(fixture((('A','A'),)))
    assert r['populations']['correct_count']==2
    entity=r['continuity']['entities'][0]
    assert entity['resolved_steps']==1 and entity['same_label_links']==entity['changed_label_links']==0
    assert entity['split_steps']==0


def test_review_terminal_visible_with_selected_not_observable_opportunity():
    b=fixture(('A','end'))
    def add(t):
        t['opportunities'].append(dict(truth_entity_id='g',step_ref='s1',expectation='not_observable',required_acquisition_refs=[]))
    r=report(rebuild(b,truth_change=add))
    assert [x['status'] for x in r['lifecycle_rows']]==['observed','ended']
    assert r['lifecycle_rows'][1]['opportunity_ref']==1
