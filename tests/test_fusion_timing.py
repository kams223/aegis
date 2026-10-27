"""SF-2 exact temporal boundaries and the existing admission ledger."""
from dataclasses import replace
import pytest
from aegis.fusion.timing import TimingRequest, align_time, AlignmentRequest, align_batch
from aegis.fusion.admission import EvidenceKey, AdmissionLedger
from aegis.fusion.contracts import MeasurementTime
from aegis.fusion.clock_mapping import BoundedClockMapping
from test_fusion_admission import make_request


def timing(**changes):
    return replace(TimingRequest(EvidenceKey('camera', 'session', 'event'), MeasurementTime(10, 'a'),
        MeasurementTime(11, 'a'), MeasurementTime(12, 'a'), 2, 'timing', '1'), **changes)


@pytest.mark.parametrize('evaluation,status', [(10,'deferred'), (11,'eligible'), (12,'eligible'), (12.0001,'deferred')])
def test_selected_time_boundaries(evaluation, status):
    assert align_time(timing(evaluation=MeasurementTime(evaluation,'a'))).status == status


def test_equal_times_and_missing_delivery():
    assert align_time(timing(delivery=MeasurementTime(10,'a'), evaluation=MeasurementTime(10,'a'))).status == 'eligible'
    out = align_time(timing(delivery=None))
    assert out.status == 'deferred' and out.diagnostics[0].code == 'AVAILABILITY_UNKNOWN'
    assert align_time(timing(delivery=MeasurementTime(9,'a'))).status == 'rejected'


def test_explicit_mapping_and_ambiguous_delivery():
    mapping = BoundedClockMapping('source','a',1,0,0,20,1)
    r = timing(acquisition=MeasurementTime(10,'source'), acquisition_mapping=mapping)
    assert align_time(r).diagnostics[0].code == 'STALE_MEASUREMENT'


@pytest.mark.parametrize('delivery,evaluation,status', [(12,12,'deferred'), (12,13,'eligible'), (12,11,'deferred')])
def test_delivery_bounds(delivery,evaluation,status):
    m = BoundedClockMapping('delivery','a',1,0,0,20,1)
    r = timing(delivery=MeasurementTime(delivery,'delivery'), delivery_mapping=m,
               evaluation=MeasurementTime(evaluation,'a'), max_age_seconds=None)
    assert align_time(r).status == status


def test_missing_or_wrong_clock_relationship():
    assert align_time(timing(acquisition=MeasurementTime(10,'other'))).status == 'deferred'
    m = BoundedClockMapping('wrong','a',1,0,0,20,0)
    assert align_time(timing(acquisition_mapping=m)).status == 'rejected'
    m = BoundedClockMapping('a','b',1,0,0,9,0)
    assert align_time(timing(acquisition_mapping=m,evaluation=MeasurementTime(12,'b'))).status == 'rejected'


def test_bridge_repeatability_identity_and_duplicate_precedence():
    r = make_request(); before = repr(r)
    q = AlignmentRequest(r,'align','1')
    out = align_batch((q,q), AdmissionLedger.empty())
    assert [x.status for x in out.results] == ['admitted','duplicate']
    assert out.results[0].admission.source_observation is r.observation
    assert out == align_batch((q,q), AdmissionLedger.empty()) and repr(r) == before
    assert align_batch((q,) * 1025, AdmissionLedger.empty()).diagnostics


def test_delayed_request_does_not_reserve_evidence():
    r = make_request()
    pending = replace(r,evaluation=MeasurementTime(10,'video:a'))
    out = align_batch((AlignmentRequest(pending,'align','1'),AlignmentRequest(r,'align','1')), AdmissionLedger.empty())
    assert [x.status for x in out.results] == ['deferred','admitted']
    assert len(out.ledger.entries) == 1


def test_bridge_mapping_preserves_original_source_and_rejects_inconsistency():
    from aegis.fusion.derived_evidence import derive_camera_evidence
    r = make_request(evaluation=MeasurementTime(112,'common'), available_at=MeasurementTime(111,'common'))
    m = BoundedClockMapping('video:a','common',1,100,0,20,0)
    q = AlignmentRequest(r,'align','1',m)
    out = align_batch((q,),AdmissionLedger.empty()).results[0]
    assert out.status == 'admitted'
    assert out.admission.admitted_measurement.measurement_interval == (110,110)
    assert out.prepared_request.observation is r.observation and r.derivation is None
    old = derive_camera_evidence(r.observation,clock_mapping=m)
    wrong = replace(m,offset_seconds=99)
    bad = AlignmentRequest(replace(r,derivation=old),'align','1',wrong)
    assert align_batch((bad,),AdmissionLedger.empty()).results[0].diagnostics[0].code == 'INCONSISTENT_MAPPING'


def test_fractional_mapping_encloses_exact_value():
    from fractions import Fraction
    m = BoundedClockMapping('source','a',0.1,0.2,0,20,0)
    r = timing(acquisition=MeasurementTime(3,'source'),acquisition_mapping=m,max_age_seconds=None)
    out = align_time(r)
    exact = Fraction(3)*Fraction(0.1)+Fraction(0.2)
    assert Fraction(out.acquisition_interval[0]) <= exact <= Fraction(out.acquisition_interval[1])
    assert out.mapped_acquisition.source_time is r.acquisition


@pytest.mark.parametrize('value', [float('nan'),float('inf'),True,-1])
def test_invalid_age_policy(value):
    assert align_time(timing(max_age_seconds=value)).status == 'rejected'


def test_acquisition_delivery_overlap_defers_without_using_favorable_endpoint():
    m = BoundedClockMapping('source','a',1,0,0,20,1)
    q = timing(acquisition=MeasurementTime(10,'source'),acquisition_mapping=m,
               delivery=MeasurementTime(10,'a'),max_age_seconds=None)
    out = align_time(q)
    assert out.status == 'deferred' and out.diagnostics[0].code == 'TEMPORAL_AMBIGUITY'


def test_contradictory_overlapping_clock_declarations_reject():
    # The same source instant cannot map both to t and t+100 with zero error.
    acquisition = BoundedClockMapping('source','a',1,0,0,20,0)
    delivery = BoundedClockMapping('source','a',1,100,0,20,0)
    q = timing(acquisition=MeasurementTime(10,'source'),delivery=MeasurementTime(11,'source'),
               acquisition_mapping=acquisition,delivery_mapping=delivery,
               evaluation=MeasurementTime(112,'a'),max_age_seconds=None)
    out = align_time(q)
    assert out.status == 'rejected' and out.diagnostics[0].code == 'INCONSISTENT_MAPPING'


def test_same_source_clock_causal_reversal_is_not_hidden_by_error_bounds():
    m = BoundedClockMapping('source','a',1,0,0,20,2)
    q = timing(acquisition=MeasurementTime(10,'source'),delivery=MeasurementTime(9,'source'),
               acquisition_mapping=m,delivery_mapping=m,max_age_seconds=None)
    assert align_time(q).diagnostics[0].code == 'CAUSAL_ORDER'


@pytest.mark.parametrize('offset,error,status', [(-99,0,'rejected'),(-99,1,'eligible'),(-100,0,'eligible')])
def test_negative_offsets_mapping_consistency_inclusive_error(offset,error,status):
    a = BoundedClockMapping('source','a',1,-100,100,200,0)
    d = BoundedClockMapping('source','a',1,offset,100,200,error)
    q = timing(acquisition=MeasurementTime(110,'source'),delivery=MeasurementTime(115,'source'),
               acquisition_mapping=a,delivery_mapping=d,evaluation=MeasurementTime(20,'a'),max_age_seconds=None)
    assert align_time(q).status == status


def test_inconsistent_rate_detected_at_validity_endpoint():
    a = BoundedClockMapping('source','a',1,0,0,100,0)
    d = BoundedClockMapping('source','a',2,0,0,100,0)
    q = timing(acquisition=MeasurementTime(0,'source'),delivery=MeasurementTime(0,'source'),
               acquisition_mapping=a,delivery_mapping=d,max_age_seconds=None)
    # Both map these actual samples to zero; the declared clock models conflict elsewhere.
    assert align_time(q).diagnostics[0].code == 'INCONSISTENT_MAPPING'


def test_disjoint_mapping_validity_does_not_claim_inconsistency():
    a = BoundedClockMapping('source','a',1,0,0,10,0)
    d = BoundedClockMapping('source','a',1,-1,11,20,0)
    q = timing(acquisition=MeasurementTime(10,'source'),delivery=MeasurementTime(12,'source'),
               acquisition_mapping=a,delivery_mapping=d,max_age_seconds=None)
    assert align_time(q).status == 'eligible'


def test_extreme_mapping_cancellation_and_unrepresentable_bounds():
    from sys import float_info
    limit = float_info.max
    m = BoundedClockMapping('source','a',1,-limit,-limit,limit,0)
    q = timing(acquisition=MeasurementTime(limit,'source'),delivery=MeasurementTime(0,'a'),
               acquisition_mapping=m,evaluation=MeasurementTime(0,'a'),max_age_seconds=0)
    assert align_time(q).status == 'eligible'
    bad = replace(m,scale=2,offset_seconds=limit)
    assert align_time(replace(q,acquisition_mapping=bad)).diagnostics[0].code == 'CLOCK_MAPPING'


def test_conflicting_evidence_does_not_consume_additional_ledger_capacity():
    r = make_request()
    changed = replace(r,observation=replace(r.observation,measurement=replace(r.observation.measurement,u_px=321)))
    out = align_batch(tuple(AlignmentRequest(x,'align','1') for x in (r,changed,r)),AdmissionLedger.empty())
    assert [x.status for x in out.results] == ['admitted','rejected','duplicate']
    assert len(out.ledger.entries) == 1
