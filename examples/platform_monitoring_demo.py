"""Deterministic synthetic monitoring replay without I/O or device control."""

import argparse
from dataclasses import replace
from html import escape
import json
import sys

from aegis.platform import contracts as c
from aegis.platform.snapshot import snapshot_document, snapshot_from_document
from aegis.platform.simulated_adapters import aerial_sentinel_from_fixture, ground_sentinel_from_fixture, third_party_from_fixture
from aegis.platform.monitoring import (
    ConnectivityEvent, ConnectivityPayload, HealthEvent, HealthPayload,
    AvailabilityEvent, AvailabilityPayload, EvidenceEvent, ObservationEvent,
    ObservationPayload, ReviewEvent, ReviewPayload, reduce_session,
)
from examples.platform_snapshot_demo import demo_snapshot


def demo_inputs():
    initial = demo_snapshot()
    doc = snapshot_document(initial)
    aerial, amonitor = aerial_sentinel_from_fixture(doc['registry']['devices'][0], doc['sentinels'][0])
    ground, gmonitor = ground_sentinel_from_fixture(doc['registry']['devices'][1], doc['sentinels'][1])
    third = third_party_from_fixture(doc['registry']['devices'][2])
    initial = replace(initial, registry=c.build_registry((aerial,ground,third)), sentinels=(amonitor,gmonitor))
    def stamp(value, domain):
        return c.Timestamp(value=value, unit='s', clock_domain=domain)
    atime = stamp(1,'demo:camera-a')
    gtime = stamp(3,'demo:metadata-g')
    otime = stamp(4,'demo:display-r')
    reference = c.EvidenceReference(evidence_id='camera-a:recorded', source_id='camera-a', kind='camera_recording',
                                  local_path='examples/recorded_datasets/placeholder.txt', dataset_id=None)
    observation = c.Observation(observation_id='monitor-unusual', source_id='display-r', timestamp=otime,
        category='synthetic', quality='uncertain', uncertainty_note='Illustrative missing context.',
        annotation='Unusual declared metadata; human interpretation required.', review_status='unreviewed', evidence_id='display-r:evidence')
    alert = c.Alert(alert_id='monitor-alert', observation_id=observation.observation_id, status='unreviewed',
        explanation=c.AlertExplanation(code='unusual_metadata', explanation='Descriptive fixture annotation only.', evidence_ids=(observation.evidence_id,)))
    request = c.InvestigationRequest(request_id='monitor-explanation', alert_id=alert.alert_id,
                                    action='explain_observation', reference_ids=(observation.observation_id,))
    review_time = stamp(5,'demo:display-r')
    decision = c.HumanReviewDecision(decision_id='monitor-review', subject_kind='observation', subject_id=observation.observation_id,
        reviewer_id='synthetic-operator', previous_status='unreviewed', new_status='reviewed', timestamp=review_time,
        note='Illustrative interpretation review; no device-control authorization.')
    events = (
        ConnectivityEvent(event_id='connectivity-1', event_type='device_connectivity', device_id=aerial.device_id, source_id=None,
            timestamp=atime, payload=ConnectivityPayload(previous_status='offline', current_status='recorded')),
        HealthEvent(event_id='health-1', event_type='device_health', device_id=aerial.device_id, source_id=None, timestamp=stamp(2,'demo:camera-a'),
            payload=HealthPayload(previous_health=aerial.health, current_health=replace(aerial.health,status='degraded',timestamp=stamp(2,'demo:camera-a'),note='Synthetic maintenance declaration.'))),
        AvailabilityEvent(event_id='availability-1', event_type='sensor_availability', device_id=ground.device_id, source_id='metadata-g',
            timestamp=gtime, payload=AvailabilityPayload(previous_status='unknown', availability=c.SensorAvailability(source_id='metadata-g',status='unavailable'))),
        EvidenceEvent(event_id='recording-1', event_type='evidence_announcement', device_id=aerial.device_id, source_id='camera-a',
            timestamp=stamp(3,'demo:camera-a'), payload=reference),
        ObservationEvent(event_id='observation-1', event_type='observation_announcement', device_id=third.device_id, source_id='display-r',
            timestamp=otime, payload=ObservationPayload(observation=observation, alerts=(alert,), investigations=(request,),
                copilot_actor_id='offline-copilot', investigation_audit_id='monitor-investigation-audit')),
        ReviewEvent(event_id='review-1', event_type='human_review', device_id=third.device_id, source_id='display-r', timestamp=review_time,
            payload=ReviewPayload(decision=decision,audit_id='monitor-review-audit')),
        # Explicit contradictory predecessor: rejected without modifying state.
        ConnectivityEvent(event_id='conflict-1', event_type='device_connectivity', device_id=aerial.device_id, source_id=None,
            timestamp=stamp(6,'demo:camera-a'), payload=ConnectivityPayload(previous_status='offline',current_status='unknown')),
    )
    return initial, events


def demo_session():
    return reduce_session(*demo_inputs())


def render_json(session):
    return json.dumps(c.to_document(session),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n'


def render_html(session):
    doc = c.to_document(session)
    body = '<h1>Offline Synthetic Monitoring Replay</h1><p>Descriptive software fixture; no hardware, media access or operational commands.</p>'
    for heading, value in (('Initial snapshot identifier',doc['initial_snapshot_id']),('Ordered event results',doc['event_results']),
                           ('Session summary',doc['summary']),('Final validated snapshot',doc['final_snapshot'])):
        body += '<h2>'+heading+'</h2><pre>'+escape(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False),quote=True)+'</pre>'
    return '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>Offline Synthetic Monitoring Replay</title></head><body>'+body+'</body></html>\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--format',choices=('json','html'),default='json')
    args = parser.parse_args(argv)
    try:
        result = demo_session()
        output = render_html(result) if args.format=='html' else render_json(result)
    except c.PlatformContractError as cause:
        parser.error(str(cause))
    print(output,end='')
    return 0


if __name__=='__main__':
    sys.exit(main())
