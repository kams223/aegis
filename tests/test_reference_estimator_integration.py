"""SF-3 accepts only the documented synthetic subset of SF-1/SF-2 evidence."""
from dataclasses import replace
import pytest
from aegis.simulation.reference_estimation import scenario
from aegis.fusion.reference_estimator import adapt_position, correct, initialize, ReferenceModel
from aegis.fusion.admission import AdmissionRequest, AdmissionLedger, CorrelationClaim, admit_batch
from aegis.fusion.uncertainty import CovarianceDeclaration, UnknownUncertainty
from aegis.fusion.geometry import GeometryRequest
from aegis.fusion.contracts import MeasurementTime
from test_fusion_admission import make_request


def readmit(source,**changes):
    a=source.source
    u=a.uncertainty
    request=AdmissionRequest(a.source_observation,a.evidence_key.source_session_id,a.entity_kind,a.quantity,a.basis,
        CovarianceDeclaration(u.matrix,u.measurement_basis,u.uncertainty_provenance),a.correlation,a.evaluation,a.available_at,None,a.derivation)
    result=admit_batch((replace(request,**changes),),AdmissionLedger.empty()).results[0]
    assert result.status=='admitted',result
    return replace(source,source=result.admitted_measurement)


def test_sf1_sf2_xy_principal_submatrix_and_lineage_are_preserved():
    fixture=scenario('constant_velocity'); m=fixture.measurements[0]
    out=correct(initialize(fixture.prior).state,m,ReferenceModel(0,'1'))
    assert out.status=='corrected' and m.frame==fixture.prior.frame
    assert m.covariance==((1,0),(0,1))
    assert out.state.measurements[0].source is m.source
    assert m.source.source.source_observation is fixture.acquisitions[0].observations[0]
    assert 'NO_INDEPENDENT_COMBINATION' in m.restrictions
    assert 'CONDITIONAL_SYNTHETIC_JOINT_MODEL' in m.restrictions
    assert 'JOINT_COMPATIBILITY_NOT_ASSESSED' in m.restrictions


@pytest.mark.parametrize('claim', [CorrelationClaim.unknown(),CorrelationClaim('shared_group','common-error',None,())])
def test_unknown_or_shared_correlation_is_deferred(claim):
    fixture=scenario('constant_velocity'); source=fixture.measurements[0].source
    source=readmit(source,correlation=claim)
    out=adapt_position(source,fixture.assumptions,None)
    assert out.status=='deferred' and out.diagnostics[0].code=='JOINT_MODEL_REQUIRED'


def test_singular_raw_or_projected_covariance_is_never_bypassed():
    fixture=scenario('constant_velocity'); source=fixture.measurements[0].source
    u=source.source.uncertainty
    singular=CovarianceDeclaration(((1,0,0),(0,1,0),(0,0,0)),u.measurement_basis,u.uncertainty_provenance)
    raw=readmit(source,uncertainty=singular)
    assert adapt_position(raw,fixture.assumptions,None).status=='deferred'
    projected=replace(source,projected_uncertainty=replace(source.projected_uncertainty,matrix=((1,0,0),(0,1,0),(0,0,0))))
    # XY submatrix is SPD; the original singular-model restriction must still survive.
    assert adapt_position(projected,fixture.assumptions,None).status=='deferred'


@pytest.mark.parametrize('uncertainty', [None,UnknownUncertainty('not supplied')])
def test_unavailable_projected_uncertainty_is_not_polar_covariance(uncertainty):
    fixture=scenario('constant_velocity')
    out=adapt_position(replace(fixture.measurements[0].source,projected_uncertainty=uncertainty),fixture.assumptions,None)
    assert out.status=='deferred' and out.measurement is None


def test_camera_pixels_and_directions_are_not_cartesian_positions():
    from aegis.fusion.admission import EvidenceKey
    r=make_request()
    a=admit_batch((r,),AdmissionLedger.empty()).results[0].admitted_measurement
    assumptions=scenario('constant_velocity').assumptions
    out=adapt_position(GeometryRequest(a,'identity','1','identity'),assumptions,None)
    assert out.status=='rejected' and out.diagnostics[0].code=='GEOMETRY'
    assert adapt_position(GeometryRequest(a,'camera','1','camera_direction'),assumptions,None).status=='deferred'


def test_ambiguous_mapped_acquisition_is_deferred_even_after_sf1_admission():
    from aegis.fusion.clock_mapping import BoundedClockMapping
    from aegis.fusion.derived_evidence import derive_radar_evidence
    fixture=scenario('constant_velocity'); source=fixture.measurements[0].source
    a=source.source
    mapping=BoundedClockMapping(a.source_observation.measurement_time.clock_domain,'reference.mapped',1,100,0,20,.1)
    derived=derive_radar_evidence(a.source_observation,clock_mapping=mapping)
    mapped=readmit(source,derivation=derived,evaluation=MeasurementTime(110,'reference.mapped'),available_at=MeasurementTime(101,'reference.mapped'))
    assert adapt_position(mapped,fixture.assumptions,None).diagnostics[0].code=='TEMPORAL_AMBIGUITY'


def test_non_synthetic_uncertainty_cannot_enter_reference_integration():
    fixture=scenario('constant_velocity'); source=fixture.measurements[0].source
    u=source.projected_uncertainty
    out=adapt_position(replace(source,projected_uncertainty=replace(u,uncertainty_provenance=replace(u.uncertainty_provenance,method='calibration'))),fixture.assumptions,None)
    assert out.status=='rejected' and out.diagnostics[0].code=='SYNTHETIC_ONLY'


def test_own_platform_telemetry_and_unadmitted_observations_are_rejected():
    fixture=scenario('constant_velocity')
    assert adapt_position(fixture.acquisitions[0].observations[0],fixture.assumptions,None).status=='rejected'
    assert adapt_position({'observation_type':'gnss','position':(1,2)},fixture.assumptions,None).status=='rejected'


def test_geometry_admission_cannot_be_reused_after_its_evaluation_context():
    from aegis.fusion.reference_estimator import replay
    fixture=scenario('constant_velocity')
    # Admit with a short SF-1 age policy. AdmittedMeasurement does not retain it.
    source=readmit(fixture.measurements[-1].source,max_age_seconds=0)
    m=adapt_position(source,fixture.assumptions,None).measurement
    assert m is not None
    later=MeasurementTime(m.evaluation.seconds+1,m.evaluation.clock_domain)
    out=replay(fixture.prior,(m,),later,ReferenceModel(0,'1'))
    assert out.steps[0].status=='deferred'
    assert out.steps[0].diagnostics[0].code=='EVALUATION_CONTEXT'
    assert not out.final.state.measurements
