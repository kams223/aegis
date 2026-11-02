"""Bounded codec, local-file and independent prefix hash tests."""
from copy import deepcopy
from dataclasses import replace,fields
from hashlib import sha256
import os
import pytest

from examples.correspondence_research_fixture import fixture,request_for,position_source
from test_correspondence_contracts import rebuild,report,code
from aegis.simulation.correspondence_contracts import ContractError,MAX_BYTES,thaw,SOURCE_TYPES
from aegis.simulation.correspondence_io import (canonical_bytes,parse_artifact,read_artifact,encode_source,decode_source,view_digests,source_facts,digest,time_wire)
from aegis.simulation.correspondence_evaluation import load_research_bundle,report_bytes
from aegis.fusion.contracts import MeasurementTime,ReferenceFrame


@pytest.mark.parametrize('raw,expected',[
 (b'\xff','UTF8'),(b'{"a":1,"a":2}','SCHEMA'),(b'{"a":NaN}','SCHEMA'),
 (b'['*17+b']'*17,'BOUND'),(b'{} trailing','SCHEMA'),(b'null','SCHEMA')])
def test_invalid_bytes(raw,expected):
    with pytest.raises(ContractError) as e: parse_artifact(raw,'observations')
    assert e.value.code==expected


@pytest.mark.parametrize('kind',('observations','truth','hypotheses'))
def test_file_size_bound_before_parse(kind):
    with pytest.raises(ContractError,match='BOUND'): parse_artifact(b' '*(MAX_BYTES[kind]+1),kind)


def test_raw_digest_not_canonical_digest():
    b=fixture(('A',)); raw=canonical_bytes(b.truth.data)
    a=parse_artifact(b' '+raw,'truth')
    assert a.data==b.truth.data and a.sha256!=b.truth.sha256
    assert a.sha256==sha256(b' '+raw).hexdigest()


def test_regular_local_files_readonly(tmp_path):
    b=fixture(('A',)); paths={}
    for kind in ('observations','truth','hypotheses'):
        path=tmp_path/(kind+'.json'); path.write_bytes(canonical_bytes(getattr(b,kind).data)); paths[kind]=path
    before={k:p.read_bytes() for k,p in paths.items()}
    r=load_research_bundle(paths,request_for(b)['expected_digests'],request_for(b)['policy'])
    assert r.bundle is not None
    assert before=={k:p.read_bytes() for k,p in paths.items()}
    link=tmp_path/'link'; link.symlink_to(paths['observations'])
    with pytest.raises(ContractError,match='IO_ERROR'): read_artifact(link,'observations')
    linkdir=tmp_path/'dir'; linkdir.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ContractError,match='IO_ERROR'): read_artifact(linkdir/'truth.json','truth')
    with pytest.raises(ContractError,match='IO_ERROR'): read_artifact(tmp_path,'truth')


def test_fifo_never_blocks(tmp_path):
    fifo=tmp_path/'fifo'; os.mkfifo(fifo)
    with pytest.raises(ContractError,match='IO_ERROR'): read_artifact(fifo,'truth')


def test_prefix_hash_independent_naive_oracle():
    b=fixture(('A','A')); d=b.observations.data
    cutoffs=[time_wire(MeasurementTime(v,'sim')) for v in (2,-1,0,1,0)]
    results=view_digests(b.observations,cutoffs)
    for cutoff in cutoffs:
        stream=[{'profile':'sf4-observation-view-v1','dataset_sha256':b.observations.sha256}]
        for i in range(2):
            if i>int(cutoff['seconds']['value']): continue
            o=d['occurrences'][i]; s=b.observations.sources[i]
            stream.append({'kind':'evidence','evidence_key':dict(sensor_id='camera',source_session_id='authored-session',observation_id='e'+str(i)),'source_sha256':digest(source_facts(o,s))})
            a=d['acquisitions'][i]
            facts={'profile':'sf4-acquisition-facts-v1',**{k:thaw(v) for k,v in a.items() if k!='observation_occurrence_refs'},'logical_evidence_keys':[stream[-1]['evidence_key']]}
            stream.append({'kind':'acquisition','acquisition_ref':'a'+str(i),'envelope_sha256':digest(facts)})
        stream.append({'kind':'cutoff','time':cutoff})
        raw=b''.join(len(canonical_bytes(x)).to_bytes(4,'big')+canonical_bytes(x) for x in stream)
        assert results[canonical_bytes(cutoff)]==sha256(raw).hexdigest()


def test_all_source_tags_roundtrip_and_shared_derived_links():
    from aegis.fusion.derived_evidence import derive_camera_evidence,derive_radar_evidence
    from aegis.fusion.clock_mapping import BoundedClockMapping
    from aegis.fusion.admission import EvidenceKey,CorrelationClaim
    from aegis.spatial.camera import PinholeCameraIntrinsics
    from aegis.spatial.transforms import RigidTransform
    from aegis.radar.contracts import RadarPolarDetectionMeasurement
    from aegis.fusion.camera_adapter import ImageTrackMeasurement
    from aegis.fusion.uncertainty import UnknownUncertainty,MeasurementBasis
    r=position_source(0,0); frame=r.observation.reference_frame; optical=ReferenceFrame('optical'); world=ReferenceFrame('world')
    mapping=BoundedClockMapping('sim','target',1,0,0,20,0)
    rotation=((1,0,0),(0,1,0),(0,0,1))
    intrinsics=PinholeCameraIntrinsics(100,100,320,240,640,480,frame,optical,'calibration')
    rigid=RigidTransform(optical,world,rotation,(0,0,0))
    ray=replace(r,derivation=derive_camera_evidence(r.observation,image_point=r.observation.measurement,intrinsics=intrinsics,spatial_transform=rigid,clock_mapping=mapping))
    # Full radar projection/transformation supplies the remaining point tags.
    radar_obs=replace(r.observation,measurement=RadarPolarDetectionMeasurement(10,0,0),reference_frame=ReferenceFrame('radar'))
    radar_transform=RigidTransform(radar_obs.reference_frame,world,rotation,(1,2,3))
    radar=replace(r,observation=radar_obs,derivation=derive_radar_evidence(radar_obs,spatial_transform=radar_transform))
    box=replace(r,observation=replace(r.observation,measurement=ImageTrackMeasurement(0,'object',0.5,1,2,3,4,640,480)),uncertainty=UnknownUncertainty('unknown'),correlation=CorrelationClaim('independence_asserted',None,'assertion',(EvidenceKey('camera','authored-session','e0'),EvidenceKey('second','s','e'))))
    covered=set()
    for source in (r,ray,radar,box):
        graph=encode_source(source); covered|={n['type'] for n in graph['objects']}
        decoded=decode_source(graph)
        assert decoded==source
        if decoded.derivation: assert decoded.derivation.source_observation is decoded.observation
        if source is ray: assert decoded.derivation.spatial_projection.source_image_point is decoded.observation.measurement
        if source is radar: assert decoded.derivation.spatial_projection.source_measurement is decoded.observation.measurement
    assert covered==set(SOURCE_TYPES)


def test_graph_renaming_cannot_change_source_digest():
    source=position_source(0,0); g=encode_source(source)
    def rename(v):
        if isinstance(v,dict):
            return {k: ('renamed-'+x if k in ('ref','root_ref','object_id') else rename(x)) for k,x in v.items()}
        if isinstance(v,list): return [rename(x) for x in v]
        return v
    decoded=decode_source(rename(g))
    b=fixture(('A',)); o=b.observations.data['occurrences'][0]
    assert source_facts(o,source)==source_facts(o,decoded)


def test_report_parse_and_no_self_hash():
    r=report(fixture()); raw=report_bytes(r)
    assert raw.endswith(b'\n')
    assert parse_artifact(raw,'report').data==r
    assert 'report_sha256' not in r


def test_escaped_strings_do_not_bypass_lexical_depth():
    b=fixture(('A',)); raw=canonical_bytes(b.truth.data)
    # Legal brackets in a quoted reason are content, not structural depth.
    d=thaw(b.truth.data); d['evidence_labels'][0]={'evidence_key':d['evidence_labels'][0]['evidence_key'],'status':'unavailable','reason':'["\\]'*50}
    from aegis.simulation.correspondence_io import artifact_from_data
    assert artifact_from_data(d,'truth').data['evidence_labels'][0]['reason']==d['evidence_labels'][0]['reason']
    with pytest.raises(ContractError): read_artifact('bad\0path','truth')


def test_graph_node_budget_and_wrong_identity_links():
    g=encode_source(position_source(0,0))
    for i in range(128): g['objects'].append({'object_id':'spare'+str(i),'type':'ReferenceFrame','fields':{'frame_id':'unused'}})
    with pytest.raises(ContractError,match='BOUND'): decode_source(g)


def test_view_includes_unconfirmed_status_declaration():
    b=fixture(('?',)); cutoff=time_wire(MeasurementTime(0,'sim'))
    assert view_digests(b.observations,[cutoff])
    altered=rebuild(b,lambda d:d['acquisitions'][0].update(available_at=cutoff))
    assert view_digests(b.observations,[cutoff])!=view_digests(altered.observations,[cutoff])


def test_unknown_delivery_is_never_inferred_from_receipt():
    b=fixture(('A',)); source=b.observations.sources[0]
    def change(d):
        d['occurrences'][0].update(admission_request=encode_source(replace(source,available_at=None)),occurrence_received_at=time_wire(MeasurementTime(0,'sim')))
    r=report(rebuild(b,change))
    assert r['evidence_rows'][0]['temporal_reason']=='DELIVERY_UNKNOWN'
    assert r['lifecycle_rows'][0]['status']=='unknown'


def test_copied_derivation_source_is_not_shared_identity():
    from aegis.fusion.derived_evidence import derive_camera_evidence
    s=position_source(0,0); s=replace(s,derivation=derive_camera_evidence(s.observation))
    g=encode_source(s)
    root=next(n for n in g['objects'] if n['type']=='DerivedSensorEvidence')
    original=next(n for n in g['objects'] if n['object_id']==root['fields']['source_observation']['ref'])
    copied=deepcopy(original); copied['object_id']='copied'; g['objects'].append(copied)
    root['fields']['source_observation']={'ref':'copied'}
    with pytest.raises(ContractError): decode_source(g)


def test_envelope_digest_uses_primary_occurrence_order_not_member_ref_order():
    # Two sources at the same step; reverse only the explicit member references.
    b=rebuild(fixture((('A','B'),)),lambda d:d['acquisitions'][0]['observation_occurrence_refs'].reverse())
    d=b.observations.data; cutoff=time_wire(MeasurementTime(0,'sim'))
    keys=[dict(sensor_id='camera',source_session_id='authored-session',observation_id='e'+str(i)) for i in range(2)]
    events=[{'profile':'sf4-observation-view-v1','dataset_sha256':b.observations.sha256}]
    for i,key in enumerate(keys):
        events.append({'kind':'evidence','evidence_key':key,'source_sha256':digest(source_facts(d['occurrences'][i],b.observations.sources[i]))})
    a=d['acquisitions'][0]
    facts={'profile':'sf4-acquisition-facts-v1',**{k:thaw(v) for k,v in a.items() if k!='observation_occurrence_refs'},'logical_evidence_keys':keys}
    events.extend([{'kind':'acquisition','acquisition_ref':'a0','envelope_sha256':digest(facts)},{'kind':'cutoff','time':cutoff}])
    expected=sha256(b''.join(len(canonical_bytes(x)).to_bytes(4,'big')+canonical_bytes(x) for x in events)).hexdigest()
    assert view_digests(b.observations,[cutoff])[canonical_bytes(cutoff)]==expected


def test_review_unrelated_artifact_bindings_cannot_be_reused():
    from aegis.simulation.correspondence_evaluation import ResearchBundle
    raw=fixture(('A',)); impaired=fixture(('A',),impaired=True)
    assert code(report(ResearchBundle(impaired.observations,raw.truth,raw.hypotheses)))=='DIGEST_MISMATCH'


def test_review_source_facts_fingerprints_independently_reconstructed():
    import json
    from dataclasses import fields,is_dataclass
    from aegis.fusion.admission import EvidenceKey
    source=position_source(0,0); key=EvidenceKey('camera','authored-session','e0')
    def reference(value):
        if value is None or type(value) is str: return value
        if type(value) is int: return ['int',str(value)]
        if type(value) is float: return ['float',value.hex()]
        if type(value) is tuple: return [reference(x) for x in value]
        assert is_dataclass(value)
        return [type(value).__module__+'.'+type(value).__name__,[[f.name,reference(getattr(value,f.name))] for f in fields(value)]]
    def fingerprint(value):
        payload=['sf1-fingerprint-v1',reference(value)]
        return sha256(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
    o=fixture(('A',)).observations.data['occurrences'][0]
    facts=source_facts(o,source)
    assert facts['sf1_evidence_sha256']==fingerprint((key,source.observation,source.available_at))
    assert facts['sf1_assumptions_sha256']==fingerprint((source.entity_kind,source.quantity,source.basis,source.uncertainty,source.correlation,source.derivation,source.evaluation.clock_domain))
    assert set(facts)=={'profile','sf1_evidence_sha256','sf1_assumptions_sha256','source_max_age_seconds','step_ref','acquisition_ref','acquisition_mapping_ref','provenance'}


def test_review_json_value_node_budget_counts_values_once():
    from aegis.simulation.correspondence_io import _preflight
    _preflight('['+','.join('0' for _ in range(99999))+']')
    with pytest.raises(ContractError,match='BOUND'): _preflight('['+','.join('0' for _ in range(100000))+']')
    _preflight('{"key":["brackets[\\\"\\\\]",null,true,false,123]}')
