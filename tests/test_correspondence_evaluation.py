"""Hand-calculated metrics and adversarial temporal/context populations."""
from copy import deepcopy
from dataclasses import replace
import pytest
from examples.correspondence_research_fixture import fixture,request_for
from test_correspondence_contracts import rebuild,report,code
from aegis.simulation.correspondence_io import encode_source,time_wire,key_wire,view_digests,canonical_bytes
from aegis.simulation.correspondence_contracts import thaw,scalar
from aegis.simulation.correspondence_evaluation import evaluate_supplied_hypotheses,validate_research_bundle
from aegis.fusion.contracts import MeasurementTime
from aegis.fusion.uncertainty import UnknownUncertainty


def test_authored_population_oracle():
    r=report(fixture()); p=r['populations']; m=r['metrics']
    assert [p[k+'_count'] for k in ('correct','incorrect','ambiguous','unresolved')]==[2,1,1,1]
    expected={'conditional_resolved_accuracy':(2,3),'resolved_coverage':(3,5),'strict_correctness':(2,5),'unresolved_fraction':(1,5),'ambiguous_fraction':(1,5),'eligible_data_coverage':(5,5),'known_truth_coverage':(5,5)}
    assert {k:(v['numerator'],v['denominator']) for k,v in m.items()}==expected


@pytest.mark.parametrize('claim,field',[('unresolved','unresolved'),('omitted','unresolved'),('U','ambiguous')])
def test_all_unresolved_or_ambiguous(claim,field):
    r=report(fixture((claim,)*3)); p=r['populations']
    assert r['status']=='complete'
    assert p[field+'_count']==3 and p['known_truth_count']==3
    assert r['metrics']['conditional_resolved_accuracy'] is None
    assert r['metrics']['strict_correctness']=={'numerator':0,'denominator':3}
    assert r['continuity']['entities'][0]['resolved_step_coverage']=={'numerator':0,'denominator':3}


def test_empty_null_not_perfect():
    r=report(fixture(()))
    assert r['status']=='complete' and all(x is None for x in r['metrics'].values())
    assert not r['evidence_rows'] and not r['lifecycle_rows']


def test_duplicate_is_one_logical_item():
    def duplicate(d):
        o=deepcopy(d['occurrences'][0]); o['occurrence_id']='retransmission'; o['occurrence_received_at']=time_wire(MeasurementTime(9,'sim'))
        d['occurrences'].append(o); d['acquisitions'][0]['observation_occurrence_refs'].append('retransmission')
    b=fixture(('A',)); a=report(b); r=report(rebuild(b,duplicate))
    assert r['metrics']==a['metrics'] and r['continuity']==a['continuity']
    assert r['populations']['duplicate_occurrence_count']==1
    assert r['evidence_rows'][0]['occurrence_refs']==('o0','retransmission')


def test_conflicting_duplicate_evidence():
    b=fixture(('A',)); s=b.observations.sources[0]
    def conflict(d):
        o=deepcopy(d['occurrences'][0]); o['occurrence_id']='again'
        o['admission_request']=encode_source(replace(s,max_age_seconds=5))
        d['occurrences'].append(o); d['acquisitions'][0]['observation_occurrence_refs'].append('again')
    assert code(report(rebuild(b,conflict)))=='CONTEXT_POLICY_CONFLICT'


@pytest.mark.parametrize('part',('truth','hypothesis'))
def test_contradictory_declarations(part):
    b=fixture(('A',))
    if part=='truth':
        b=rebuild(b,truth_change=lambda t:t['evidence_labels'].append(deepcopy(t['evidence_labels'][0])))
        assert code(report(b))=='TRUTH_CONFLICT'
    else:
        def change(h):
            d=deepcopy(h['decisions'][0]); d['external_label']='B'; h['decisions'].append(d)
        assert code(report(rebuild(b,hyp_change=change)))=='HYPOTHESIS_CONFLICT'


def test_missing_inventory_rejects_not_empty():
    assert code(report(rebuild(fixture(('A',)),truth_change=lambda t:t['opportunities'][0].update(required_acquisition_refs=['absent']))))=='UNKNOWN_REFERENCE'


def test_delayed_delivery_inclusive_boundary():
    b=fixture(('A',)); s=b.observations.sources[0]
    def delay(d):
        d['occurrences'][0]['admission_request']=encode_source(replace(s,available_at=MeasurementTime(5,'sim')))
        d['acquisitions'][0]['available_at']=time_wire(MeasurementTime(5,'sim'))
    b=rebuild(b,delay,hyp_change=lambda h:h['decisions'][0].update(decision_available_at=time_wire(MeasurementTime(5,'sim'))))
    before=report(b,evaluation=4); at=report(b,evaluation=5)
    assert before['populations']['known_truth_count']==0
    assert before['evidence_rows'][0]['temporal_reason']=='PENDING_DELIVERY'
    assert before['lifecycle_rows'][0]['status']=='unknown'
    assert at['populations']['correct_count']==1
    assert at['evidence_rows'][0]['step_ref']=='s0'


def test_stale_is_observed_never_missing():
    b=fixture(('A',)); r=report(b,evaluation=5,age=4)
    assert r['evidence_rows'][0]['temporal_reason']=='STALE_MEASUREMENT'
    assert r['lifecycle_rows'][0]['status']=='observed'
    assert 'STALE_AT_EVALUATION' in r['lifecycle_rows'][0]['reason_codes']
    assert r['continuity']['entities'][0]['assessed_steps']==0
    assert report(b,evaluation=4,age=4)['populations']['correct_count']==1


@pytest.mark.parametrize('clock',('acquisition','delivery'))
def test_cross_clock_no_implicit_conversion(clock):
    b=fixture(('A',)); source=b.observations.sources[0]
    def change(d):
        s=replace(source,observation=replace(source.observation,measurement_time=MeasurementTime(0,'device'))) if clock=='acquisition' else replace(source,available_at=MeasurementTime(0,'device'))
        d['occurrences'][0]['admission_request']=encode_source(s)
        if clock=='acquisition': d['acquisitions'][0]['acquisition_time']=time_wire(MeasurementTime(0,'device'))
    r=report(rebuild(b,change))
    assert r['status']=='incomplete',thaw(r)
    assert r['populations']['eligible_count']==0 and r['populations']['in_scope_count']==1
    assert r['metrics']['eligible_data_coverage']=={'numerator':0,'denominator':1}
    assert r['lifecycle_rows'][0]['status']=='unknown'


def test_unknown_uncertainty_is_scorable_not_admitted():
    b=fixture(('A',)); source=b.observations.sources[0]
    b=rebuild(b,lambda d:d['occurrences'][0].update(admission_request=encode_source(replace(source,uncertainty=UnknownUncertainty('not calibrated')))))
    r=report(b); row=r['evidence_rows'][0]
    assert row['comparison_status']=='correct'
    assert row['uncertainty_status']=='unknown' and row['admission_status']=='deferred'
    assert row['restrictions'] is None


@pytest.mark.parametrize('status',('ambiguous','unavailable'))
def test_partial_truth_outside_primary_population(status):
    def change(t):
        row=t['evidence_labels'][0]; key=row['evidence_key']; row.clear(); row.update(evidence_key=key,status=status)
        if status=='unavailable': row['reason']='Oracle unavailable'
        else:
            row['candidates']=['g','other']
            t['opportunities'].append({**t['opportunities'][0],'truth_entity_id':'other'})
    r=report(rebuild(fixture(('A',)),truth_change=change))
    assert r['populations']['known_truth_count']==0 and r['populations']['eligible_count']==1
    assert r['evidence_rows'][0]['comparison_status']=='unscored'
    assert r['lifecycle_rows'][0]['status']=='unknown'


@pytest.mark.parametrize('time,expected',[(None,'HYPOTHESIS_AVAILABILITY_UNKNOWN'),(30,'HYPOTHESIS_PENDING'),(-1,'HYPOTHESIS_CAUSAL_CONFLICT')])
def test_hypothesis_ineligibility_never_shrinks_truth(time,expected):
    b=rebuild(fixture(('A',)),hyp_change=lambda h:h['decisions'][0].update(decision_available_at=None if time is None else time_wire(MeasurementTime(time,'sim'))))
    r=report(b)
    assert r['populations']['known_truth_count']==r['populations']['unresolved_count']==1
    assert expected in r['evidence_rows'][0]['reason_codes']


def test_unaligned_does_not_guess():
    b=rebuild(fixture(('A',)),hyp_change=lambda h:h.update(label_alignment=[]))
    assert report(b)['evidence_rows'][0]['hypothesis_status']=='unaligned'


def test_cutoff_exact_binding_and_wrong_digest():
    b=fixture(('A',)); cutoff=time_wire(MeasurementTime(0,'sim'))
    view=view_digests(b.observations,[cutoff])[canonical_bytes(cutoff)]
    b=rebuild(b,hyp_change=lambda h:h['decisions'][0].update(information_cutoff=cutoff,input_view_sha256=view))
    assert report(b)['populations']['correct_count']==1
    assert code(report(rebuild(b,hyp_change=lambda h:h['decisions'][0].update(input_view_sha256='0'*64))))=='INPUT_VIEW_MISMATCH'


def test_source_and_bundle_validation():
    b=fixture(('A',)); policy=request_for(b)['policy']
    result=validate_research_bundle(b.observations,b.truth,b.hypotheses,policy)
    assert result.bundle is not None and not result.diagnostics
    broken=rebuild(b,lambda d:d['acquisitions'][0].update(available_at=time_wire(MeasurementTime(-1,'sim'))))
    result=validate_research_bundle(broken.observations,broken.truth,broken.hypotheses,policy)
    assert result.bundle is None


def mapped_bundle(error=0,offset=-100):
    from dataclasses import fields
    from aegis.fusion.clock_mapping import BoundedClockMapping
    b=fixture(('A',)); source=b.observations.sources[0]
    mapping=BoundedClockMapping('device','sim',1,offset,100,200,error)
    def change(d):
        s=replace(source,observation=replace(source.observation,measurement_time=MeasurementTime(100,'device')),available_at=MeasurementTime(1,'sim'))
        d['occurrences'][0].update(admission_request=encode_source(s),acquisition_mapping_ref='explicit')
        d['acquisitions'][0].update(acquisition_time=time_wire(MeasurementTime(100,'device')),acquisition_mapping_ref='explicit',available_at=time_wire(MeasurementTime(1,'sim')))
        d['clock_mappings']=[{'mapping_id':'explicit','revision':'1','mapping':{f.name:getattr(mapping,f.name) if f.type is str else scalar(getattr(mapping,f.name)) for f in fields(mapping)}}]
    return rebuild(b,change,hyp_change=lambda h:h['decisions'][0].update(decision_available_at=time_wire(MeasurementTime(1,'sim'))))


def test_explicit_negative_offset_and_ambiguous_step_interval():
    assert report(mapped_bundle())['populations']['correct_count']==1
    r=report(mapped_bundle(error=0.1))
    assert r['evidence_rows'][0]['temporal_reason']=='TEMPORAL_ORDER_AMBIGUOUS'
    assert r['lifecycle_rows'][0]['status']=='unknown'


def test_conflicting_overlapping_mappings_rejected():
    b=mapped_bundle()
    def conflict(d):
        m=deepcopy(d['clock_mappings'][0]); m['mapping_id']='contradiction'; m['mapping']['offset_seconds']=scalar(-99); d['clock_mappings'].append(m)
    assert code(report(rebuild(b,conflict)))=='CLOCK_MAPPING_INVALID'


def test_duplicate_hypotheses_do_not_count_twice():
    b=fixture(('A',))
    b=rebuild(b,hyp_change=lambda h:h['decisions'].append(deepcopy(h['decisions'][0])))
    r=report(b)
    assert r['populations']['correct_count']==1
    assert r['evidence_rows'][0]['hypothesis_refs']==(0,1)


def test_wrong_clock_hypothesis_is_unresolved():
    b=rebuild(fixture(('A',)),hyp_change=lambda h:h['decisions'][0]['decision_available_at'].update(clock_domain='unrelated'))
    r=report(b)
    assert r['populations']['unresolved_count']==1
    assert 'HYPOTHESIS_CLOCK_UNSUPPORTED' in r['evidence_rows'][0]['reason_codes']


@pytest.mark.parametrize('matrix',[((0,0),(0,0)),((1,1),(1,1))])
def test_singular_covariance_retains_restriction(matrix):
    b=fixture(('A',)); s=b.observations.sources[0]
    b=rebuild(b,lambda d:d['occurrences'][0].update(admission_request=encode_source(replace(s,uncertainty=replace(s.uncertainty,matrix=matrix)))))
    r=report(b)
    assert r['evidence_rows'][0]['comparison_status']=='correct'
    assert 'REQUIRES_SINGULAR_MODEL' in r['evidence_rows'][0]['restrictions']
    assert 'NO_INDEPENDENT_COMBINATION' in r['evidence_rows'][0]['restrictions']


@pytest.mark.parametrize('field',('units','frame','covariance','entity'))
def test_invalid_source_is_not_hidden_by_empty_scope(field):
    from aegis.fusion.contracts import ReferenceFrame
    b=fixture(('A',)); s=b.observations.sources[0]
    if field=='units': s=replace(s,basis=replace(s.basis,units=('m','m')))
    elif field=='frame': s=replace(s,basis=replace(s.basis,reference_frame=ReferenceFrame('other')))
    elif field=='covariance': s=replace(s,uncertainty=replace(s.uncertainty,matrix=((1,2),(2,1))))
    else: s=replace(s,entity_kind='own_aircraft')
    b=rebuild(b,lambda d:d['occurrences'][0].update(admission_request=encode_source(s)))
    req=request_for(b); req['scope']['evidence_keys']=[]
    assert code(evaluate_supplied_hypotheses(b,req))=='SOURCE_INVALID'


def test_completion_before_delivery_rejects():
    b=fixture(('A',)); s=b.observations.sources[0]
    b=rebuild(b,lambda d:d['occurrences'][0].update(admission_request=encode_source(replace(s,available_at=MeasurementTime(5,'sim')))))
    assert code(report(b))=='COMPLETION_CONFLICT'


def test_selection_and_zero_denominators():
    b=fixture(('A','wrong')); req=request_for(b); req['scope']['evidence_keys']=[thaw(b.truth.data['evidence_labels'][1]['evidence_key'])]
    r=evaluate_supplied_hypotheses(b,req)
    assert r['metrics']['strict_correctness']=={'numerator':0,'denominator':1}
    assert r['populations']['logical_evidence_count']==2 and r['populations']['excluded_scope_count']==1
    req['scope']['evidence_keys']=[]
    r=evaluate_supplied_hypotheses(b,req)
    assert all(value is None for value in r['metrics'].values())


def test_invalid_view_rejected_during_bundle_validation():
    b=fixture(('A',)); cutoff=time_wire(MeasurementTime(0,'sim'))
    b=rebuild(b,hyp_change=lambda h:h['decisions'][0].update(information_cutoff=cutoff,input_view_sha256='0'*64))
    validation=validate_research_bundle(b.observations,b.truth,b.hypotheses,request_for(b)['policy'])
    assert validation.bundle is None
    assert validation.diagnostics[0]['code']=='INPUT_VIEW_MISMATCH'


def test_primary_exclusion_keeps_additional_reasons():
    b=fixture(('A',)); s=b.observations.sources[0]
    def change(d):
        d['occurrences'][0]['admission_request']=encode_source(replace(s,available_at=MeasurementTime(10,'sim')))
        d['acquisitions'][0]['available_at']=time_wire(MeasurementTime(10,'sim'))
    r=report(rebuild(b,change),evaluation=5,age=1)
    row=r['evidence_rows'][0]
    assert row['temporal_reason']=='PENDING_DELIVERY'
    assert 'STALE_MEASUREMENT' in row['reason_codes']
    assert r['populations']['excluded_by_reason'][0]=={'reason_code':'PENDING_DELIVERY','count':1}


@pytest.mark.parametrize('sequence,counts,ratios',[
 (('A','A','A'),(3,0,0,0),((3,3),(3,3),(3,3),(0,3),(0,3))),
 (('wrong','wrong','wrong'),(0,3,0,0),((0,3),(3,3),(0,3),(0,3),(0,3))),
 (('A','wrong','unresolved','U','A','wrong','omitted'),(2,2,1,2),((2,4),(4,7),(2,7),(2,7),(1,7))),
])
def test_review_independent_population_and_unreduced_metric_oracles(sequence,counts,ratios):
    result=report(fixture(sequence)); population=result['populations']
    assert population['in_scope_count']==population['eligible_count']==population['known_truth_count']==len(sequence)
    assert tuple(population[name+'_count'] for name in ('correct','incorrect','ambiguous','unresolved'))==counts
    names=('conditional_resolved_accuracy','resolved_coverage','strict_correctness','unresolved_fraction','ambiguous_fraction')
    assert [(result['metrics'][name]['numerator'],result['metrics'][name]['denominator']) for name in names]==list(ratios)


def test_review_future_decision_stays_unresolved_until_selected_availability():
    b=rebuild(fixture(('A',)),hyp_change=lambda h:h['decisions'][0].update(decision_available_at=time_wire(MeasurementTime(10,'sim'))))
    before=report(b,evaluation=9); at=report(b,evaluation=10)
    assert before['populations']['known_truth_count']==at['populations']['known_truth_count']==1
    assert before['populations']['unresolved_count']==1
    assert at['populations']['correct_count']==1


def test_review_duplicate_payload_change_is_conflict_not_a_second_vote():
    b=fixture(('A',)); source=b.observations.sources[0]
    def duplicate(d):
        row=deepcopy(d['occurrences'][0]); row['occurrence_id']='duplicate'
        changed=replace(source,observation=replace(source.observation,measurement=replace(source.observation.measurement,u_px=99)))
        row['admission_request']=encode_source(changed)
        d['occurrences'].append(row); d['acquisitions'][0]['observation_occurrence_refs'].append('duplicate')
    assert code(report(rebuild(b,duplicate)))=='EVIDENCE_CONFLICT'
