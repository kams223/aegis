"""Authored SF-4 fixtures; labels/truth are supplied literals, never inferred.

Run: PYTHONPATH=src python3 -B examples/correspondence_research_fixture.py
Prints deterministic report hashes only; no input/output file is modified.
"""
from dataclasses import replace
from hashlib import sha256
import json

from aegis.fusion.admission import AdmissionRequest, CorrelationClaim, EvidenceKey
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.uncertainty import MeasurementBasis, CovarianceDeclaration, UncertaintyProvenance
from aegis.spatial.camera import ImagePoint
from aegis.simulation.correspondence_io import (artifact_from_data,encode_source,key_wire,time_wire,scalar)
from aegis.simulation.correspondence_evaluation import (ResearchBundle,evaluate_supplied_hypotheses,report_bytes)


def position_source(index,step,*,available=None,age=None):
    """An image-location source, explicitly NOT a Cartesian estimator input."""
    frame=ReferenceFrame('camera-image')
    basis=MeasurementBasis('image_point',('u_px','v_px'),('px','px'),frame)
    obs=SensorObservation('e'+str(index),'camera',MeasurementTime(step,'sim'),frame,ImagePoint(10+index,20,640,480,frame))
    return AdmissionRequest(obs,'authored-session','external_object','image_location',basis,
        CovarianceDeclaration(((1,0),(0,1)),basis,UncertaintyProvenance('synthetic','1','synthetic_model')),
        CorrelationClaim.unknown(),MeasurementTime(20,'sim'),MeasurementTime(step if available is None else available,'sim'),age)


def fixture(sequence=('A','U','M','B','?','wrong','omitted','end'),*,impaired=False):
    """A tiny authored notation, not an identity generator or hypothesis algorithm.

    A/B map to g, wrong maps to other; U is a fixed candidate pair. A tuple lists
    explicit simultaneous singleton claims for g. M/? are declared empty/unknown
    acquisition assertions. All source IDs are independent of the truth labels.
    """
    generator={'generator_id':'authored-fixture','revision':'1','configuration_sha256':'1'*64}
    provenance={'generator':generator,'origin':'synthetic_impaired' if impaired else 'synthetic_raw',
       'upstream_source_sha256':'2'*64 if impaired else None,'derived_from':None,
       'lineage':[{'operation_id':'authored-impairment','revision':'1','configuration_sha256':'3'*64,'input_sha256':'2'*64}] if impaired else []}
    d=dict(schema_version=1,artifact_kind='offline_correspondence_observations',dataset_id='authored-example',revision='1',observation_view_id='impaired' if impaired else 'raw',generator=generator,scenario_clock_domain='sim',steps=[],clock_mappings=[],occurrences=[],acquisitions=[],provenance=provenance)
    truth=dict(schema_version=1,artifact_kind='offline_correspondence_truth',dataset_sha256='0'*64,truth_id='authored-oracle',revision='1',entity_catalog=[{'truth_entity_id':'g','episode_id':'episode-1'},{'truth_entity_id':'other','episode_id':'episode-2'}],evidence_labels=[],opportunities=[],terminal_annotations=[])
    h=dict(schema_version=1,artifact_kind='offline_correspondence_hypotheses',dataset_sha256='0'*64,hypothesis_id='authored-decisions',revision='1',producer_provenance={'producer_id':'literal-author','revision':'1','alignment_protocol_id':'fixed-before-scoring'},external_label_catalog=['A','B','wrong'],label_alignment=[{'external_label':label,'truth_entity_id':'other' if label=='wrong' else 'g'} for label in ('A','B','wrong')],decisions=[])
    index=0
    for step,token in enumerate(sequence):
        step_ref='s'+str(step); acquisition='a'+str(step)
        d['steps'].append({'step_id':step_ref,'start':time_wire(MeasurementTime(step,'sim')),'end':time_wire(MeasurementTime(step+1,'sim'))})
        if token=='end':
            truth['terminal_annotations'].append({'truth_entity_id':'g','step_ref':step_ref,'visible_at':time_wire(MeasurementTime(step,'sim')),'provenance':{'assertion_id':'explicit-end','revision':'1'}})
            continue
        refs=[]
        tokens=token if type(token) is tuple else (token,)
        if token not in ('M','?'):
            for claim in tokens:
                source=position_source(index,step); key=key_wire(EvidenceKey('camera','authored-session','e'+str(index)))
                occurrence='o'+str(index); refs.append(occurrence)
                p={**provenance,'derived_from':{'dataset_sha256':'2'*64,'evidence_key':key} if impaired else None}
                d['occurrences'].append(dict(occurrence_id=occurrence,step_ref=step_ref,acquisition_ref=acquisition,admission_request=encode_source(source),acquisition_mapping_ref=None,occurrence_received_at=None,provenance=p))
                truth['evidence_labels'].append(dict(evidence_key=key,status='known',truth_entity_id='g'))
                common=dict(evidence_key=key,decision_available_at=time_wire(MeasurementTime(step,'sim')),information_cutoff=None,input_view_sha256=None)
                if claim=='U': h['decisions'].append(dict(**common,status='ambiguous',candidates=['A','B']))
                elif claim=='unresolved': h['decisions'].append(dict(**common,status='unresolved',reason='Explicit author uncertainty'))
                elif claim!='omitted': h['decisions'].append(dict(**common,status='assigned',external_label=claim))
                index+=1
        d['acquisitions'].append(dict(acquisition_ref=acquisition,step_ref=step_ref,sensor_id='camera',source_session_id='authored-session',acquisition_id=acquisition,acquisition_time=time_wire(MeasurementTime(step,'sim')),status='unconfirmed' if token=='?' else 'completed',observation_occurrence_refs=refs,reason='Callback not confirmed' if token=='?' else None,acquisition_mapping_ref=None,available_at=None if token=='?' else time_wire(MeasurementTime(step,'sim')),completeness_provenance={'assertion_id':'inventory-'+str(step),'revision':'1'}))
        truth['opportunities'].append(dict(truth_entity_id='g',step_ref=step_ref,expectation='expected',required_acquisition_refs=[acquisition]))
    observations=artifact_from_data(d,'observations')
    truth['dataset_sha256']=h['dataset_sha256']=observations.sha256
    return ResearchBundle(observations,artifact_from_data(truth,'truth'),artifact_from_data(h,'hypotheses'))


def request_for(bundle,evaluation=20,age=None):
    return dict(schema_version=1,evaluation=time_wire(MeasurementTime(evaluation,'sim')),
        expected_digests=dict(dataset_sha256=bundle.observations.sha256,truth_sha256=bundle.truth.sha256,hypotheses_sha256=bundle.hypotheses.sha256),
        policy={'policy_id':'explicit-age','revision':'1','additional_max_age_seconds':None if age is None else scalar(age)},scope={'evidence_keys':None,'opportunity_keys':None})


def authored_reports():
    return {name:evaluate_supplied_hypotheses(bundle,request_for(bundle)) for name,bundle in
        [('acceptance',fixture()),('split',fixture((('A','B'),))),('empty',fixture(())),('impaired',fixture(impaired=True))]}


if __name__=='__main__':
    print(json.dumps({k:sha256(report_bytes(v)).hexdigest() for k,v in authored_reports().items()},sort_keys=True))
