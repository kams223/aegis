"""Closed research shape, source compatibility and independent rejection tests."""
from copy import deepcopy
from dataclasses import fields, replace
import json
from pathlib import Path
import pytest

from examples.correspondence_research_fixture import fixture,request_for,position_source
from aegis.simulation.correspondence_contracts import (ContractError,SCHEMAS,SOURCE_TYPES,DEFINITIONS,freeze,thaw,scalar,unscalar,validate_shape)
from aegis.simulation.correspondence_io import (artifact_from_data,encode_source,decode_source,canonical_bytes,parse_artifact,time_wire)
from aegis.simulation.correspondence_evaluation import ResearchBundle,evaluate_supplied_hypotheses
from aegis.fusion.contracts import MeasurementTime


def rebuild(bundle,change=None,truth_change=None,hyp_change=None):
    """Bind independently edited literal inputs; never repair their semantics."""
    d,t,h=map(lambda a:thaw(a.data),(bundle.observations,bundle.truth,bundle.hypotheses))
    if change: change(d)
    if truth_change: truth_change(t)
    if hyp_change: hyp_change(h)
    obs=artifact_from_data(d,'observations'); t['dataset_sha256']=h['dataset_sha256']=obs.sha256
    return ResearchBundle(obs,artifact_from_data(t,'truth'),artifact_from_data(h,'hypotheses'))


def report(bundle,**kwargs):
    return evaluate_supplied_hypotheses(bundle,request_for(bundle,**kwargs))


def code(result):
    assert result['status']=='rejected',thaw(result)
    assert result['metrics'] is None
    assert not result['evidence_rows'] and not result['lifecycle_rows']
    return result['diagnostics'][0]['code']


@pytest.mark.parametrize('kind',SCHEMAS)
def test_schema_parity_and_closed_objects(kind):
    path=Path('configs/simulation/correspondence-'+kind+'-v1.schema.json')
    assert json.loads(path.read_text())==SCHEMAS[kind]
    def closed(value):
        if isinstance(value,dict):
            if value.get('type')=='object':
                assert value['additionalProperties'] is False
                assert set(value['properties'])==set(value['required'])
            for v in value.values(): closed(v)
        elif isinstance(value,list):
            for v in value: closed(v)
    closed(SCHEMAS[kind])


@pytest.mark.parametrize('kind',('observations','truth','hypotheses'))
@pytest.mark.parametrize('mutation',('extra','missing','version','bool_version'))
def test_closed_root(kind,mutation):
    b=fixture(('A',)); a=getattr(b,kind); data=thaw(a.data)
    if mutation=='extra': data['new_field']='ignored?'
    if mutation=='missing': del data['revision']
    if mutation=='version': data['schema_version']=2
    if mutation=='bool_version': data['schema_version']=True
    with pytest.raises(ContractError): artifact_from_data(data,kind)


@pytest.mark.parametrize('value',[0,1,-1,2**100,0.0,-0.0,0.1,1e-300,1e300])
def test_lossless_scalars(value):
    decoded=unscalar(scalar(value))
    assert type(decoded) is type(value)
    assert str(decoded)==str(value)


@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),-float('inf'),10**400])
def test_invalid_scalar(value):
    with pytest.raises(ContractError): scalar(value)


@pytest.mark.parametrize('kind,value',[('int','-0'),('int','01'),('int','+1'),('float','nan'),('float','0x1p+0'),('float','inf')])
def test_noncanonical_scalar(kind,value):
    with pytest.raises(ContractError): unscalar({'kind':kind,'value':value})


def test_immutable_and_source_identity():
    b=fixture(('A',)); source=b.observations.sources[0]
    assert source.observation.reference_frame is source.basis.reference_frame
    assert source.basis is source.uncertainty.measurement_basis
    with pytest.raises(TypeError): b.observations.data['revision']='2'
    with pytest.raises(TypeError): b.observations.data._values['revision']='2'
    with pytest.raises(Exception): source.source_session_id='other'
    before=canonical_bytes(b.observations.data)
    report(b)
    assert canonical_bytes(b.observations.data)==before


@pytest.mark.parametrize('mutation,expected',[
    (lambda g:g['objects'].append(deepcopy(g['objects'][0])),'GRAPH_TYPE'),
    (lambda g:g.update(root_ref='missing'),'UNKNOWN_REFERENCE'),
    (lambda g:g['objects'][0]['fields'].update(observation={'ref':g['root_ref']}),'GRAPH_CYCLE'),
    (lambda g:g['objects'][0]['fields'].update(source_session_id={'ref':'n1'}),'SCHEMA'),
    (lambda g:g['objects'][0]['fields'].update(uncertainty={'ref':'n1'}),'GRAPH_TYPE'),
])
def test_graph_rejects(mutation,expected):
    g=encode_source(position_source(0,0)); mutation(g)
    with pytest.raises(ContractError) as e: decode_source(g)
    assert e.value.code==expected


def test_unused_graph_node():
    g=encode_source(position_source(0,0))
    g['objects'].append({'object_id':'unused','type':'ReferenceFrame','fields':{'frame_id':'unused'}})
    with pytest.raises(ContractError,match='GRAPH_TYPE'): decode_source(g)


@pytest.mark.parametrize('mutation',[
 lambda d:d['steps'][0]['start'].update(clock_domain='other'),
 lambda d:d['steps'][0].update(end=time_wire(MeasurementTime(0,'sim'))),
 lambda d:d['provenance'].update(origin='synthetic_impaired'),
 lambda d:d['occurrences'][0].update(acquisition_ref='unknown'),
 lambda d:d['acquisitions'][0].update(observation_occurrence_refs=[]),
 lambda d:d['acquisitions'][0].update(source_session_id='other'),
])
def test_semantic_context_rejection(mutation):
    assert code(report(rebuild(fixture(('A',)),mutation))) in ('SCHEMA','SOURCE_INVALID','UNKNOWN_REFERENCE','REFERENCE_MEMBERSHIP_CONFLICT')


def test_complete_empty_not_unknown():
    assert report(fixture(('M',)))['lifecycle_rows'][0]['status']=='temporarily_missing'
    assert report(fixture(('?',)))['lifecycle_rows'][0]['status']=='unknown'


def test_every_registered_type_has_exact_closed_fields():
    assert len(SOURCE_TYPES)==22
    for name,cls in SOURCE_TYPES.items():
        assert set(DEFINITIONS['Fields'+name]['required'])=={f.name for f in fields(cls)}


@pytest.mark.parametrize('field,cap',[('occurrences',1024),('acquisitions',1024),('steps',1024),('clock_mappings',64)])
def test_collection_capacity(field,cap):
    b=fixture(('A',)); data=thaw(b.observations.data)
    template=data[field][0] if data[field] else {'mapping_id':'m','revision':'1','mapping':{}}
    data[field]=[deepcopy(template) for _ in range(cap+1)]
    with pytest.raises(ContractError,match='BOUND'): artifact_from_data(data,'observations')


@pytest.mark.parametrize('mutation',[
 lambda r:r['populations'].update(correct_count=999),
 lambda r:r['metrics']['strict_correctness'].update(denominator=99),
 lambda r:r.update(status='rejected'),
 lambda r:r.update(evaluation=None),
 lambda r:r['evidence_rows'][0].update(restrictions=False),
])
def test_report_contract_rejects_inconsistent_counts_and_shapes(mutation):
    r=thaw(report(fixture(('A',)))); mutation(r)
    with pytest.raises(ContractError): artifact_from_data(r,'report')


def test_artifact_cannot_forge_digest_or_source_cache():
    from aegis.simulation.correspondence_io import Artifact
    b=fixture(('A',)); sources=(replace(b.observations.sources[0],max_age_seconds=0),)
    with pytest.raises(TypeError): replace(b.observations,sources=sources)
    with pytest.raises(TypeError): replace(b.observations,sha256='0'*64)
    with pytest.raises(TypeError): Artifact(kind='observations',sha256='0'*64,data=b.observations.data)
    assert Artifact(canonical_bytes(b.observations.data),'observations')==b.observations


def test_reason_text_and_identifier_byte_limits():
    s=position_source(0,0)
    from aegis.fusion.uncertainty import UnknownUncertainty
    long_reason='r'*512
    assert decode_source(encode_source(replace(s,uncertainty=UnknownUncertainty(long_reason)))).uncertainty.reason==long_reason
    with pytest.raises(ContractError): encode_source(replace(s,source_session_id='é'*65))


def test_malformed_public_context_is_structured_rejection():
    from aegis.simulation.correspondence_evaluation import ResearchBundle
    b=fixture(('A',))
    assert code(evaluate_supplied_hypotheses(ResearchBundle(None,b.truth,b.hypotheses),request_for(b)))=='SCHEMA'
    with pytest.raises(ContractError): parse_artifact(b'{}',[])


def test_review_object_key_order_cannot_bypass_unique_scope():
    b=fixture(('A',)); request=request_for(b)
    key=thaw(b.truth.data['evidence_labels'][0]['evidence_key'])
    request['scope']['evidence_keys']=[key,dict(reversed(list(key.items())))]
    assert code(evaluate_supplied_hypotheses(b,request))=='SCHEMA'


def test_review_tuple_and_mapping_proxy_inputs_are_deeply_frozen():
    from types import MappingProxyType
    b=fixture(('A',)); request=request_for(b)
    key=thaw(b.truth.data['evidence_labels'][0]['evidence_key'])
    request['scope']['evidence_keys']=(key,)
    policy=request['policy']; request['policy']=MappingProxyType(policy)
    result=evaluate_supplied_hypotheses(b,request)
    assert result['status']=='complete'
    original=canonical_bytes(result)
    key['observation_id']='changed'; policy['revision']='changed'
    assert canonical_bytes(result)==original
    with pytest.raises(TypeError): result['scope']['evidence_keys'][0]['sensor_id']='changed'


def test_review_cyclic_request_rejects_without_recursion_error():
    b=fixture(('A',)); request=request_for(b); request['scope']=request
    assert code(evaluate_supplied_hypotheses(b,request)) in ('BOUND','SCHEMA')


@pytest.mark.parametrize('change',[
 lambda r:r['evidence_rows'][0].update(comparison_status='incorrect'),
 lambda r:r['evidence_rows'][0].update(truth_status='unavailable'),
 lambda r:r['evidence_rows'][0].update(temporal_reason='STALE_MEASUREMENT'),
 lambda r:r['evidence_rows'][0].update(occurrence_refs=[]),
 lambda r:r['continuity']['entities'][0].update(fragment_count=50),
 lambda r:r['continuity']['entities'][0].update(resolved_step_coverage={'numerator':0,'denominator':1}),
])
def test_review_report_rows_and_summaries_cannot_contradict_totals(change):
    value=thaw(report(fixture(('A',)))); change(value)
    with pytest.raises(ContractError): artifact_from_data(value,'report')


@pytest.mark.parametrize('field',('information_cutoff','input_view_sha256'))
def test_review_cutoff_digest_null_coupling_is_structural(field):
    decision=thaw(fixture(('A',)).hypotheses.data['decisions'][0])
    decision[field]=time_wire(MeasurementTime(0,'sim')) if field=='information_cutoff' else '0'*64
    with pytest.raises(ContractError): validate_shape(decision,DEFINITIONS['Decision'])


@pytest.mark.parametrize('change',[
 lambda a:a.update(acquisition_time=None),
 lambda a:a.update(reason='Cannot be completed and unavailable'),
 lambda a:a.update(status='unconfirmed',reason='Callback missing'),
])
def test_review_acquisition_completeness_is_structural(change):
    acquisition=thaw(fixture(('A',)).observations.data['acquisitions'][0]); change(acquisition)
    with pytest.raises(ContractError): validate_shape(acquisition,DEFINITIONS['AcquisitionEnvelope'])


@pytest.mark.parametrize('identifier',['','   ','a\nb','a\x85b'])
def test_review_identifier_restrictions_are_standard_schema_patterns(identifier):
    import re
    from aegis.simulation.correspondence_contracts import IDENT
    assert re.search(IDENT['pattern'],identifier) is None
    with pytest.raises(ContractError): validate_shape(identifier,IDENT)


@pytest.mark.parametrize('change',[
 lambda r:r['diagnostics'][0].update(stage='source'),
 lambda r:r['diagnostics'].reverse(),
 lambda r:r['diagnostics'][0]['reference'].update(collection='entity_catalog'),
 lambda r:r['continuity']['labels'][0].update(truth_support=[],contaminated=False),
 lambda r:r['continuity']['labels'][0].update(collision_step_count=10),
])
def test_review_diagnostic_and_label_integrity(change):
    value=thaw(report(fixture(('A',)))); change(value)
    with pytest.raises(ContractError): artifact_from_data(value,'report')


def test_review_schema_regexes_do_not_accept_a_final_newline_prefix():
    import re
    from aegis.simulation.correspondence_contracts import IDENT,DIGEST
    cases=[(IDENT,'valid\n'),(DIGEST,'0'*64+'\n'),
           (DEFINITIONS['Scalar']['oneOf'][0]['properties']['value'],'1\n'),
           (DEFINITIONS['Scalar']['oneOf'][1]['properties']['value'],'0x0.0p+0\n')]
    for shape,value in cases:
        assert re.search(shape['pattern'],value) is None
        with pytest.raises(ContractError): validate_shape(value,shape)


def test_review_rejected_report_diagnostics_have_valid_closed_reference_shapes():
    from aegis.simulation.correspondence_evaluation import evaluate_supplied_hypotheses
    b=fixture(('A',)); request=request_for(b); request['schema_version']=99
    rejected=thaw(evaluate_supplied_hypotheses(b,request))
    rejected['diagnostics'][0]['reference']={'artifact':'observations','collection':'occurrences','index':None}
    with pytest.raises(ContractError): artifact_from_data(rejected,'report')


def test_review_in_memory_artifact_factory_rejects_cycles_before_encoding():
    cyclic={}; cyclic['self']=cyclic
    with pytest.raises(ContractError): artifact_from_data(cyclic,'observations')
    with pytest.raises(ContractError): artifact_from_data({},[])


@pytest.mark.parametrize('change',[
 lambda r:r['evidence_rows'][0].update(hypothesis_status='pending'),
 lambda r:r['evidence_rows'][0].update(uncertainty_status='unknown'),
 lambda r:r['evidence_rows'][0].update(reason_codes=[]),
])
def test_review_report_cannot_claim_success_with_pending_hypothesis_or_unknown_admission(change):
    value=thaw(report(fixture(('A',)))); change(value)
    with pytest.raises(ContractError): artifact_from_data(value,'report')


def test_review_composed_frozen_subtrees_cannot_bypass_depth_budget():
    value=freeze({'leaf':1})
    with pytest.raises(ContractError,match='BOUND'):
        for _ in range(17): value=freeze({'nested':value})


def test_review_reused_frozen_subtrees_count_each_serialized_occurrence():
    value=freeze({'leaf':1})
    with pytest.raises(ContractError,match='BOUND'): freeze({'values':[value]*50000})
