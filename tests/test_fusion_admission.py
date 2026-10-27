"""Strict admission, temporal eligibility, resource bounds and ledger behavior."""
from dataclasses import FrozenInstanceError, replace
from math import inf, nan
import pytest
from aegis.fusion.contracts import SensorObservation, MeasurementTime, ReferenceFrame
from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.derived_evidence import derive_camera_evidence
from aegis.spatial.camera import ImagePoint
from aegis.fusion.uncertainty import MeasurementBasis, CovarianceDeclaration, UncertaintyProvenance, UnknownUncertainty
from aegis.fusion.admission import (
    AdmissionRequest, AdmissionLedger, EvidenceKey, LedgerEntry, CorrelationClaim,
    admit_batch, MAX_LEDGER_ENTRIES,
)


def make_request(**changes):
    frame = ReferenceFrame('camera:image')
    obs = SensorObservation('event-a', 'camera', MeasurementTime(10., 'video:a'), frame,
                            ImagePoint(320., 240., 640, 480, frame))
    b = MeasurementBasis('image_point', ('u_px', 'v_px'), ('px', 'px'), frame)
    r = AdmissionRequest(obs, 'opening-a', 'external_object', 'image_location', b,
        CovarianceDeclaration(((4., 0.), (0., 9.)), b, UncertaintyProvenance('pixel-model', '1', 'synthetic_model')),
        CorrelationClaim.unknown(), MeasurementTime(12., 'video:a'), MeasurementTime(10.5, 'video:a'), 5.)
    return replace(r, **changes)


def run(request, ledger=None):
    return admit_batch((request,), ledger or AdmissionLedger.empty())


def test_valid_admission_preserves_source_values_and_caller_ownership():
    r = make_request(); before = repr(r)
    batch = run(r); result = batch.results[0]; a = result.admitted_measurement
    assert result.status == 'admitted' and not result.diagnostics
    assert a.source_observation is r.observation and result.source_observation is r.observation
    assert a.uncertainty.matrix is r.uncertainty.matrix
    assert a.values == (320., 240.) and a.measurement_interval == (10., 10.)
    assert a.evaluation is r.evaluation and a.available_at is r.available_at
    assert a.restrictions == ('JOINT_COMPATIBILITY_NOT_ASSESSED', 'NO_INDEPENDENT_COMBINATION')
    assert len(batch.ledger.entries) == 1 and repr(r) == before
    assert batch == run(r)
    with pytest.raises(FrozenInstanceError):
        a.quantity = 'position'
    assert AdmissionLedger.empty().entries == ()


@pytest.mark.parametrize('matrix,rank', [(((1., 1.), (1., 1.)), 1), (((0., 0.), (0., 0.)), 0)])
def test_singular_and_zero_covariance_have_explicit_restrictions(matrix, rank):
    r = make_request(); r = replace(r, uncertainty=replace(r.uncertainty, matrix=matrix))
    result = run(r).results[0]
    assert result.status == 'admitted' and result.uncertainty.rank == rank
    assert 'REQUIRES_SINGULAR_MODEL' in result.admitted_measurement.restrictions


@pytest.mark.parametrize('changes,code', [
    ({'entity_kind': 'own_platform'}, 'ENTITY_KIND'), ({'quantity': 'cartesian_position'}, 'UNSUPPORTED_QUANTITY'),
    ({'basis': None}, 'BASIS'), ({'available_at': MeasurementTime(11., 'other')}, 'CLOCK_DOMAIN'),
    ({'max_age_seconds': -1}, 'AGE_POLICY'), ({'max_age_seconds': nan}, 'NONFINITE_VALUE'),
    ({'max_age_seconds': False}, 'NUMERIC_TYPE'), ({'source_session_id': ''}, 'TEXT'),
    ({'uncertainty': None}, 'UNCERTAINTY_TYPE'), ({'correlation': None}, 'CORRELATION'),
])
def test_invalid_context_is_rejected(changes, code):
    result = run(make_request(**changes))
    assert not result.ledger.entries
    assert result.results[0].status == 'rejected' and result.results[0].diagnostics[0].code == code
    assert result.results[0].admitted_measurement is None


@pytest.mark.parametrize('changes,code', [
    ({'reference_frame': None}, 'FRAME_MISSING'),
    ({'measurement_time': MeasurementTime(nan, 'video:a')}, 'NONFINITE_VALUE'),
    ({'measurement_time': MeasurementTime(inf, 'video:a')}, 'NONFINITE_VALUE'),
    ({'measurement_time': MeasurementTime(True, 'video:a')}, 'NUMERIC_TYPE'),
    ({'measurement': object()}, 'UNSUPPORTED_MEASUREMENT_TYPE'),
])
def test_legacy_envelope_does_not_bypass_admission(changes, code):
    r = make_request(observation=replace(make_request().observation, **changes))
    out = run(r).results[0]
    assert out.status == 'rejected' and out.diagnostics[0].code == code


@pytest.mark.parametrize('seconds,status,code', [
    (10.4, 'deferred', 'PENDING_DELIVERY'), (10.5, 'admitted', None),
    (15., 'admitted', None), (15.00001, 'deferred', 'STALE_MEASUREMENT'),
])
def test_delivery_and_age_equality_boundaries(seconds, status, code):
    out = run(make_request(evaluation=MeasurementTime(seconds, 'video:a'))).results[0]
    assert out.status == status
    if code:
        assert out.diagnostics[0].code == code and out.admitted_measurement is None


def test_unknown_uncertainty_availability_mapping_and_explicit_disabled_age():
    unknown = UnknownUncertainty('no calibrated model')
    result = run(make_request(uncertainty=unknown))
    assert result.results[0].uncertainty is unknown
    assert result.results[0].diagnostics[0].code == 'UNCERTAINTY_UNKNOWN'
    assert not result.ledger.entries
    assert run(make_request(available_at=None)).results[0].diagnostics[0].code == 'AVAILABILITY_UNKNOWN'
    assert run(make_request(evaluation=MeasurementTime(12., 'other'), available_at=None)).results[0].diagnostics[0].code == 'CLOCK_MAPPING_REQUIRED'
    assert run(make_request(evaluation=MeasurementTime(1e100, 'video:a'), max_age_seconds=None)).results[0].status == 'admitted'
    corrected = run(make_request(), result.ledger)
    assert corrected.results[0].status == 'admitted'


def test_causal_error_and_signed_source_offsets():
    r = make_request()
    assert run(replace(r, available_at=MeasurementTime(9., 'video:a'))).results[0].diagnostics[0].code == 'CAUSAL_ORDER'
    negative = replace(r.observation, measurement_time=MeasurementTime(-10., 'video:a'))
    assert run(replace(r, observation=negative, available_at=MeasurementTime(-9., 'video:a'), evaluation=MeasurementTime(-8., 'video:a'))).results[0].status == 'admitted'


def test_mapped_interval_requires_all_bounds_and_exact_lineage():
    r = make_request()
    mapping = BoundedClockMapping('video:a', 'common', 1., 90., 0., 20., 1.)
    d = derive_camera_evidence(r.observation, clock_mapping=mapping)
    r = replace(r, derivation=d, evaluation=MeasurementTime(103., 'common'), available_at=MeasurementTime(101., 'common'))
    a = run(r).results[0]
    assert a.status == 'admitted' and a.admitted_measurement.measurement_interval == (99., 101.)
    assert a.admitted_measurement.derivation is d
    assert run(replace(r, available_at=MeasurementTime(100., 'common'))).results[0].diagnostics[0].code == 'TEMPORAL_AMBIGUITY'
    assert run(replace(r, available_at=MeasurementTime(98., 'common'))).results[0].diagnostics[0].code == 'CAUSAL_ORDER'
    assert run(replace(r, evaluation=MeasurementTime(104., 'common'))).results[0].status == 'admitted'
    assert run(replace(r, evaluation=MeasurementTime(105., 'common'))).results[0].diagnostics[0].code == 'STALE_MEASUREMENT'
    copied = replace(r.observation)
    assert run(replace(r, observation=copied)).results[0].diagnostics[0].code == 'DERIVATION_SOURCE_MISMATCH'


def test_exact_age_comparison_avoids_overflow():
    r = make_request()
    r = replace(r, observation=replace(r.observation, measurement_time=MeasurementTime(-1e308, 'video:a')),
                available_at=MeasurementTime(0., 'video:a'), evaluation=MeasurementTime(1e308, 'video:a'), max_age_seconds=1e308)
    assert run(r).results[0].diagnostics[0].code == 'STALE_MEASUREMENT'
    assert run(replace(r, max_age_seconds=None)).results[0].status == 'admitted'


def test_repeated_and_conflicting_evidence_within_and_across_calls():
    r = make_request(); original = AdmissionLedger.empty()
    batch = admit_batch((r, r), original)
    assert [v.status for v in batch.results] == ['admitted', 'duplicate']
    assert len(batch.ledger.entries) == 1 and original.entries == ()
    repeat = run(replace(r, observation=replace(r.observation), evaluation=MeasurementTime(0., 'video:a')), batch.ledger)
    assert repeat.results[0].status == 'duplicate'  # Evaluation is not immutable evidence identity.
    changed = replace(r, observation=replace(r.observation, measurement=replace(r.observation.measurement, u_px=321.)))
    assert run(changed, batch.ledger).results[0].diagnostics[0].code == 'EVIDENCE_CONFLICT'
    covariance = replace(r, uncertainty=replace(r.uncertainty, matrix=((5., 0.), (0., 9.))))
    assert run(covariance, batch.ledger).results[0].diagnostics[0].code == 'ADMISSION_CONTEXT_CONFLICT'
    assert run(replace(r, source_session_id='different-acquisition-session'), batch.ledger).results[0].status == 'admitted'
    assert not any(v.admitted_measurement for v in repeat.results)


def test_correlation_is_explicit_and_not_inferred_from_sensor_ids():
    r = make_request(); key = EvidenceKey('camera', 'opening-a', 'event-a')
    other = EvidenceKey('radar', 'run-r', 'event-r')
    shared = CorrelationClaim('shared_group', group_id='derived-from-shared-input')
    assert 'NO_INDEPENDENT_COMBINATION' in run(replace(r, correlation=shared)).results[0].admitted_measurement.restrictions
    claim = CorrelationClaim('independence_asserted', assumption_id='model-1', scope=(key, other))
    assert run(replace(r, correlation=claim)).results[0].admitted_measurement.restrictions == ('JOINT_COMPATIBILITY_NOT_ASSESSED', 'INDEPENDENCE_IS_CALLER_ASSERTED')
    for bad in (CorrelationClaim('invalid'), CorrelationClaim('unknown', group_id='x'), CorrelationClaim('independence_asserted', assumption_id='x', scope=(other,)), CorrelationClaim('independence_asserted', assumption_id='x', scope=(key, key))):
        assert run(replace(r, correlation=bad)).results[0].status == 'rejected'


def test_ledger_capacity_and_batch_bounds_are_explicit():
    entries = tuple(LedgerEntry(EvidenceKey('s', 'session', str(i)), 'a'*64, 'b'*64) for i in range(MAX_LEDGER_ENTRIES))
    ledger = AdmissionLedger(entries)
    assert run(make_request(), ledger).results[0].diagnostics[0].code == 'BOUND'
    empty = AdmissionLedger.empty()
    for requests in ([make_request()], (make_request(),)*1025):
        result = admit_batch(requests, empty)
        assert result.results == () and result.ledger is empty and result.diagnostics[0].code == 'BOUND'
    assert admit_batch((), empty).ledger == empty
    assert admit_batch((), None).diagnostics[0].code == 'LEDGER'
    with pytest.raises(ValueError):
        AdmissionLedger(entries + (entries[0],))
    with pytest.raises(ValueError):
        AdmissionLedger((entries[0], entries[0]))


def test_aggregate_budget_rolls_back_all_tentative_admissions():
    r = make_request()
    requests = tuple(replace(r, source_session_id=str(i), observation=replace(r.observation, observation_id=str(i)+'x'*1000, sensor_id='s'*1000)) for i in range(700))
    ledger = AdmissionLedger.empty()
    result = admit_batch(requests, ledger)
    assert result.results == () and result.ledger is ledger
    assert result.diagnostics[0].code == 'BOUND'


def test_each_record_can_fail_without_mutation_or_discarding_valid_neighbors():
    r = make_request(); bad = replace(r, entity_kind='own_platform')
    final = replace(r, observation=replace(r.observation, observation_id='second'))
    before = repr((r, bad, final))
    result = admit_batch((r, bad, final), AdmissionLedger.empty())
    assert [x.status for x in result.results] == ['admitted', 'rejected', 'admitted']
    assert len(result.ledger.entries) == 2 and repr((r, bad, final)) == before


def test_unknown_uncertainty_does_not_hide_invalid_causal_order():
    r = make_request(uncertainty=UnknownUncertainty('not supplied'), available_at=MeasurementTime(9., 'video:a'))
    result = run(r).results[0]
    assert result.status == 'rejected' and result.diagnostics[0].code == 'CAUSAL_ORDER'
    assert result.uncertainty is r.uncertainty


def test_capacity_still_allows_duplicates_and_per_record_progress():
    r = make_request(); admitted = run(r).ledger.entries[0]
    filler = tuple(LedgerEntry(EvidenceKey('s', 'source', str(i)), 'a'*64, 'b'*64) for i in range(MAX_LEDGER_ENTRIES-1))
    ledger = AdmissionLedger((admitted,) + filler)
    assert run(r, ledger).results[0].status == 'duplicate'
    partial = AdmissionLedger(filler)
    second = replace(r, observation=replace(r.observation, observation_id='second'))
    result = admit_batch((r, second, r), partial)
    assert [x.status for x in result.results] == ['admitted', 'rejected', 'duplicate']
    assert result.results[1].diagnostics[0].code == 'BOUND'
    assert len(result.ledger.entries) == MAX_LEDGER_ENTRIES


def test_frame_axes_and_covariance_units_are_never_converted():
    r = make_request()
    cases = [(replace(r.basis, reference_frame=ReferenceFrame('other')), 'FRAME_MISMATCH'),
             (replace(r.basis, axes=('v_px','u_px')), 'BASIS'),
             (replace(r.basis, units=('m','m')), 'UNITS_MISMATCH')]
    for b, code in cases:
        assert run(replace(r, basis=b)).results[0].diagnostics[0].code == code
    for uncertainty in (replace(r.uncertainty, matrix=((1.,),)),
                        replace(r.uncertainty, measurement_basis=replace(r.basis, units=('rad','rad')))):
        out = run(replace(r, uncertainty=uncertainty)).results[0]
        assert out.status == 'rejected' and out.admitted_measurement is None


def test_payload_finite_rules_no_clipping_and_explicit_text_bounds():
    r = make_request()
    assert run(replace(r, observation=replace(r.observation, measurement=replace(r.observation.measurement, u_px=-1000.)))).results[0].status == 'admitted'
    for value in (nan, inf, -inf):
        with pytest.raises(ValueError):
            replace(r.observation.measurement, u_px=value)  # Existing point contract rejects this before admission.
        box = ImageTrackMeasurement(0, 'object', 0.8, value, 0., 10., 10., 640, 480)
        obs = replace(r.observation, measurement=box)
        assert run(replace(r, observation=obs)).results[0].diagnostics[0].code == 'NONFINITE_VALUE'
    obs = replace(r.observation, measurement=replace(r.observation.measurement, u_px=True))
    assert run(replace(r, observation=obs)).results[0].diagnostics[0].code == 'NUMERIC_TYPE'
    for session in ('x'*1025, 'é'*600, 'x\ny'):
        assert run(replace(r, source_session_id=session)).results[0].status == 'rejected'


def test_maximum_valid_batch_is_bounded_and_repeatable():
    r = make_request()
    requests = tuple(replace(r, observation=replace(r.observation, observation_id=f'event-{i}')) for i in range(1024))
    before = repr(requests)
    result = admit_batch(requests, AdmissionLedger.empty())
    assert not result.diagnostics and len(result.results) == 1024
    assert all(x.status == 'admitted' for x in result.results)
    assert len(result.ledger.entries) == 1024 and repr(requests) == before
    replay = admit_batch(requests, result.ledger)
    assert all(x.status == 'duplicate' and x.admitted_measurement is None for x in replay.results)
    assert replay.ledger == result.ledger


def test_only_successful_admissions_reserve_evidence_keys():
    r = make_request()
    unknown = replace(r, uncertainty=UnknownUncertainty('not supplied'))
    malformed = replace(r, uncertainty=replace(r.uncertainty, matrix=((1., 2.), (2., 1.))))
    result = admit_batch((unknown, malformed, r, r), AdmissionLedger.empty())
    assert [x.status for x in result.results] == ['deferred','rejected','admitted','duplicate']
    assert len(result.ledger.entries) == 1


@pytest.mark.parametrize('condition,first_status,first_code', [
    ('pending', 'deferred', 'PENDING_DELIVERY'),
    ('stale', 'deferred', 'STALE_MEASUREMENT'),
    ('unknown_delivery', 'deferred', 'AVAILABILITY_UNKNOWN'),
    ('missing_mapping', 'deferred', 'CLOCK_MAPPING_REQUIRED'),
    ('ambiguous_delivery', 'deferred', 'TEMPORAL_AMBIGUITY'),
    ('invalid_causality', 'rejected', 'CAUSAL_ORDER'),
    ('invalid_derivation', 'rejected', 'DERIVATION_SOURCE_MISMATCH'),
])
def test_post_fingerprint_failures_do_not_reserve_identity(condition, first_status, first_code):
    valid = make_request()
    if condition == 'pending':
        failed = replace(valid, evaluation=MeasurementTime(10., 'video:a'))
    elif condition == 'stale':
        failed = replace(valid, evaluation=MeasurementTime(20., 'video:a'))
    elif condition == 'unknown_delivery':
        failed = replace(valid, available_at=None)
    elif condition == 'invalid_causality':
        failed = replace(valid, available_at=MeasurementTime(9., 'video:a'))
    elif condition == 'invalid_derivation':
        failed = replace(valid, derivation=derive_camera_evidence(replace(valid.observation)))
    else:
        mapping = BoundedClockMapping('video:a', 'common', 1., 90., 0., 20., 1.)
        valid = replace(valid, derivation=derive_camera_evidence(valid.observation, clock_mapping=mapping),
                        evaluation=MeasurementTime(103., 'common'), available_at=MeasurementTime(101., 'common'))
        failed = replace(valid, derivation=None) if condition == 'missing_mapping' else replace(valid, available_at=MeasurementTime(100., 'common'))
    initial = AdmissionLedger.empty()
    batch = admit_batch((failed, valid, valid), initial)
    assert [x.status for x in batch.results] == [first_status, 'admitted', 'duplicate']
    assert batch.results[0].diagnostics[0].code == first_code
    assert len(batch.ledger.entries) == 1 and not initial.entries
    assert batch.results[1].admitted_measurement.source_observation is valid.observation
    failed_alone = run(failed, initial)
    assert failed_alone.ledger == initial
    assert run(valid, failed_alone.ledger).results[0].status == 'admitted'


def test_rejected_conflicts_do_not_poison_a_previously_admitted_key():
    r = make_request()
    prior = run(r).ledger
    changed_source = replace(r, observation=replace(r.observation,
        measurement=replace(r.observation.measurement, u_px=999.)))
    changed_assumption = replace(r, uncertainty=replace(r.uncertainty, matrix=((5.,0.),(0.,9.))))
    batch = admit_batch((changed_source, changed_assumption, r), prior)
    assert [x.status for x in batch.results] == ['rejected','rejected','duplicate']
    assert [x.diagnostics[0].code for x in batch.results[:2]] == ['EVIDENCE_CONFLICT','ADMISSION_CONTEXT_CONFLICT']
    assert batch.ledger == prior
    assert all(x.admitted_measurement is None for x in batch.results)


def test_budget_rollback_preserves_nonempty_ledger_and_allows_subsequent_retry():
    r = make_request()
    prior = run(r).ledger
    large = tuple(replace(r, source_session_id=str(i), observation=replace(r.observation,
        observation_id=f'long-{i}'+'x'*1000, sensor_id='s'*1000)) for i in range(700))
    rolled_back = admit_batch(large, prior)
    assert rolled_back.results == () and rolled_back.ledger is prior
    assert rolled_back.diagnostics[0].code == 'BOUND'
    assert run(large[0], rolled_back.ledger).results[0].status == 'admitted'
    assert run(r, rolled_back.ledger).results[0].status == 'duplicate'


def test_negative_zero_and_numeric_types_have_conservative_replay_fingerprints():
    r = make_request()
    positive = replace(r, observation=replace(r.observation, measurement=replace(r.observation.measurement, u_px=0.)))
    ledger = run(positive).ledger
    negative = replace(positive, observation=replace(positive.observation, measurement=replace(positive.observation.measurement, u_px=-0.)))
    integer = replace(positive, observation=replace(positive.observation, measurement=replace(positive.observation.measurement, u_px=0)))
    for changed in (negative, integer):
        result = run(changed, ledger)
        assert result.results[0].diagnostics[0].code == 'EVIDENCE_CONFLICT'
        assert result.ledger == ledger
    original_covariance = replace(r.uncertainty, matrix=((4., 0.), (0., 9.)))
    negative_covariance = replace(original_covariance, matrix=((4., -0.), (-0., 9.)))
    known = run(replace(r, uncertainty=original_covariance)).ledger
    assert run(replace(r, uncertainty=negative_covariance), known).results[0].diagnostics[0].code == 'ADMISSION_CONTEXT_CONFLICT'


def test_admission_uses_the_exact_integer_magnitude_bound_for_times():
    from sys import float_info
    largest = int(float_info.max)
    r = make_request(max_age_seconds=None, evaluation=MeasurementTime(largest, 'video:a'))
    assert run(r).results[0].status == 'admitted'
    too_late = replace(r, evaluation=MeasurementTime(largest + 1, 'video:a'))
    too_early = replace(r, observation=replace(r.observation, measurement_time=MeasurementTime(-largest - 1, 'video:a')))
    for invalid in (too_late, too_early):
        result = run(invalid)
        assert result.results[0].status == 'rejected'
        assert result.results[0].diagnostics[0].code == 'NUMERIC_RANGE'
        assert not result.ledger.entries
