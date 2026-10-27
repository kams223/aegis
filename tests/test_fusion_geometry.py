"""Independent analytical oracles for passive geometry and J R Jᵀ."""
from dataclasses import replace
from fractions import Fraction
import pytest
from aegis.fusion.geometry import (
    LinearTransform, GeometryRequest, propagate_covariance, transform_measurement,
)
from aegis.fusion.uncertainty import (
    MeasurementBasis, ValidatedCovariance, CovarianceDeclaration, UnknownUncertainty, UncertaintyProvenance,
)
from aegis.fusion.contracts import ReferenceFrame
from aegis.fusion.admission import admit_batch, AdmissionLedger
from aegis.spatial.transforms import RigidTransform
from aegis.spatial.camera import PinholeCameraIntrinsics
from aegis.fusion.derived_evidence import derive_camera_evidence
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from test_fusion_admission import make_request

PROVENANCE = UncertaintyProvenance('analytical','1','synthetic_model')
ROTATION = ((0,-1,0),(1,0,0),(0,0,1))


def admitted(r=None):
    return admit_batch((r or make_request(),), AdmissionLedger.empty()).results[0].admitted_measurement


def pixel_transform(**changes):
    b = make_request().basis
    return replace(LinearTransform('affine','1',b,replace(b,reference_frame=ReferenceFrame('resampled')),
                                   ((0,-2),(3,0)),(10,20),'pixel_affine'), **changes)


def test_pixel_affine_analytical_oracle_and_immutability():
    a = admitted(); before = repr(a)
    t = pixel_transform()
    q = GeometryRequest(a,'affine','1','pixel_affine',linear=t)
    out = transform_measurement(q)
    assert out.status == 'transformed' and out.geometry == (-470,980)
    assert out.propagation.covariance.matrix == ((36,0),(0,36))
    assert out.propagation.covariance.source_uncertainty is a.uncertainty
    assert out.request.source is a and repr(a) == before
    assert out == transform_measurement(q)
    assert set(a.restrictions) <= set(out.restrictions)


def test_identity_exact_zero_and_singular_covariance():
    for matrix, rank in [(((1,1),(1,1)),1),(((0,0),(0,0)),0),(((4,0),(0,9)),2)]:
        r = make_request(); r = replace(r, uncertainty=replace(r.uncertainty,matrix=matrix))
        a = admitted(r)
        out = transform_measurement(GeometryRequest(a,'identity','1','identity'))
        assert out.status == 'transformed' and out.geometry == a.values
        assert out.propagation.covariance.matrix == matrix and out.propagation.covariance.rank == rank
        if rank < 2:
            assert 'REQUIRES_SINGULAR_MODEL' in out.restrictions


@pytest.mark.parametrize('jacobian', [((1,),),((1,0),),((1,0),(0,float('nan'))),((float('inf'),0),(0,1)),((True,0),(0,1)),[[1,0],[0,1]]])
def test_bad_jacobians(jacobian):
    out = propagate_covariance(admitted().uncertainty,pixel_transform(jacobian=jacobian))
    assert out.status == 'rejected' and out.covariance is None


def test_unknown_remains_unknown_and_basis_is_checked():
    u = UnknownUncertainty('not calibrated')
    out = propagate_covariance(u,pixel_transform())
    assert out.status == 'deferred' and out.covariance is u
    t = pixel_transform(source_basis=replace(make_request().basis,reference_frame=ReferenceFrame('wrong')))
    assert propagate_covariance(admitted().uncertainty,t).status == 'rejected'
    t = pixel_transform(destination_basis=replace(make_request().basis,units=('m','m')))
    assert propagate_covariance(admitted().uncertainty,t).status == 'rejected'


def test_independent_gram_oracle():
    # R = B Bᵀ; check (J B)(J B)ᵀ independently of implementation's J R Jᵀ loop.
    b = ((1,2),(3,4)); j = ((0.1,2),(-3,0.5))
    f = Fraction
    r = tuple(tuple(sum(b[i][k]*b[l][k] for k in range(2)) for l in range(2)) for i in range(2))
    jb = tuple(tuple(sum(f(j[i][k])*b[k][l] for k in range(2)) for l in range(2)) for i in range(2))
    oracle = tuple(tuple(sum(jb[i][k]*jb[l][k] for k in range(2)) for l in range(2)) for i in range(2))
    u = ValidatedCovariance(r,make_request().basis,PROVENANCE)
    out = propagate_covariance(u,pixel_transform(jacobian=j))
    assert out.covariance.matrix == oracle and out.covariance.rank == 2
    assert all(type(x) is Fraction for row in out.covariance.matrix for x in row)


def radar_request(elevation=0):
    r = make_request()
    obs = replace(r.observation, sensor_id='radar',reference_frame=ReferenceFrame('radar'),
                  measurement=RadarPolarDetectionMeasurement(10,0,elevation))
    axes = ('range_m','azimuth_rad') + (('elevation_rad',) if elevation is not None else ())
    units = ('m','rad') + (('rad',) if elevation is not None else ())
    b = MeasurementBasis('radar_polar',axes,units,obs.reference_frame)
    matrix = tuple(tuple(int(i==k) for k in range(len(axes))) for i in range(len(axes)))
    return replace(r,observation=obs,quantity='radar_polar',basis=b,uncertainty=CovarianceDeclaration(matrix,b,PROVENANCE))


def cartesian_basis(frame):
    return MeasurementBasis('cartesian_point',('x_m','y_m','z_m'),('m',)*3,frame)


def test_radar_rotation_translation_and_explicit_projected_uncertainty():
    r = radar_request(); a = admitted(r)
    assert a is not None
    rigid = RigidTransform(r.observation.reference_frame,ReferenceFrame('world'),ROTATION,(1,2,3))
    b = cartesian_basis(rigid.source_frame)
    u = CovarianceDeclaration(((4,1,0),(1,9,0),(0,0,0)),b,PROVENANCE)
    q = GeometryRequest(a,'radar-to-world','1','radar_cartesian',rigid=rigid,projected_uncertainty=u)
    out = transform_measurement(q)
    assert out.status == 'transformed'
    assert (out.geometry.x_m,out.geometry.y_m,out.geometry.z_m) == (1,12,3)
    assert out.propagation.covariance.matrix == ((9,-1,0),(-1,4,0),(0,0,0))
    assert out.propagation.covariance.rank == 2
    assert out.propagation.covariance.source_uncertainty.uncertainty_provenance is PROVENANCE
    assert out.request.source.uncertainty is a.uncertainty
    assert transform_measurement(replace(q,projected_uncertainty=None)).status == 'deferred'
    assert transform_measurement(replace(q,projected_uncertainty=r.uncertainty)).status == 'rejected'
    assert transform_measurement(replace(q,rigid=replace(rigid,source_frame=ReferenceFrame('wrong')))).status == 'rejected'


def test_missing_elevation_is_not_zero():
    a = admitted(radar_request(None))
    out = transform_measurement(GeometryRequest(a,'project','1','radar_cartesian'))
    assert out.status == 'deferred' and out.geometry is None
    assert out.diagnostics[0].code == 'MISSING_ELEVATION'


def test_camera_direction_no_depth_or_origin_relocation():
    r = make_request()
    missing = transform_measurement(GeometryRequest(admitted(r),'camera','1','camera_direction'))
    assert missing.status == 'deferred'
    optical = ReferenceFrame('optical')
    intrinsics = PinholeCameraIntrinsics(100,100,320,240,640,480,r.observation.reference_frame,optical,'calibration')
    derived = derive_camera_evidence(r.observation,image_point=r.observation.measurement,intrinsics=intrinsics)
    a = admitted(replace(r,derivation=derived))
    rigid = RigidTransform(optical,ReferenceFrame('world'),ROTATION,(100,200,300))
    basis = MeasurementBasis('direction',('direction_x','direction_y','direction_z'),('1',)*3,optical)
    u = CovarianceDeclaration(((1,0,0),(0,1,0),(0,0,0)),basis,PROVENANCE)
    q = GeometryRequest(a,'camera','1','camera_direction',rigid=rigid,projected_uncertainty=u)
    out = transform_measurement(q)
    assert out.status == 'transformed'
    assert (out.geometry.direction_x,out.geometry.direction_y,out.geometry.direction_z) == (0,0,1)
    assert out.geometry.source_ray is derived.spatial_projection
    assert 'DIRECTION_ONLY_NO_DEPTH_OR_RELOCATED_ORIGIN' in out.restrictions
    unknown = UnknownUncertainty('no direction model')
    out = transform_measurement(replace(q,projected_uncertainty=unknown))
    assert out.status == 'deferred' and out.propagation.covariance is unknown


def test_fake_admission_and_unsupported_operations():
    a = admitted()
    assert transform_measurement(GeometryRequest(replace(a,values=(0,0)),'fake','1','identity')).status == 'rejected'
    assert transform_measurement(GeometryRequest(a,'depth','1','camera_depth')).status == 'rejected'
    assert propagate_covariance(a.uncertainty,pixel_transform(kind='polar_to_cartesian')).status == 'rejected'


def test_extreme_finite_input_remains_exact():
    from sys import float_info
    b = make_request().basis
    u = ValidatedCovariance(((float_info.max,0),(0,5e-324)),b,PROVENANCE)
    out = propagate_covariance(u,pixel_transform(jacobian=((float_info.max,0),(0,5e-324))))
    assert out.status == 'transformed' and out.covariance.rank == 2
    assert out.covariance.matrix[0][0] > Fraction(float_info.max)


def test_rigid_declaration_cannot_disagree_with_jacobian():
    source, dest = ReferenceFrame('a'),ReferenceFrame('b')
    rigid = RigidTransform(source,dest,ROTATION,(1,2,3))
    before, after = cartesian_basis(source),cartesian_basis(dest)
    u = ValidatedCovariance(((1,0,0),(0,1,0),(0,0,1)),before,PROVENANCE)
    t = LinearTransform('rigid','1',before,after,ROTATION,(1,2,3),'cartesian_rigid',rigid)
    assert propagate_covariance(u,t).status == 'transformed'
    assert propagate_covariance(u,replace(t,jacobian=((1,0,0),(0,1,0),(0,0,1)))).status == 'rejected'
    assert propagate_covariance(u,replace(t,offset=(0,0,0))).status == 'rejected'
    assert propagate_covariance(u,t,('x',)*17).status == 'rejected'


def test_negative_zero_and_correlation_restrictions():
    a = admitted()
    t = pixel_transform(jacobian=((1,-0.0),(0,1)),offset=(-0.0,0))
    out = propagate_covariance(a.uncertainty,t,('SAME_CORRELATION_GROUP','NO_INDEPENDENT_COMBINATION'))
    assert out.covariance.matrix == ((4,0),(0,9))
    assert 'SAME_CORRELATION_GROUP' in out.restrictions
    assert out.transform is t


def test_timing_geometry_integration_preserves_mapping_and_evidence():
    from aegis.fusion.timing import AlignmentRequest, align_batch
    from aegis.fusion.contracts import MeasurementTime
    from aegis.fusion.clock_mapping import BoundedClockMapping
    r = make_request(evaluation=MeasurementTime(112,'common'),available_at=MeasurementTime(111,'common'))
    mapping = BoundedClockMapping('video:a','common',1,100,0,20,0)
    aligned = align_batch((AlignmentRequest(r,'timing','1',mapping),),AdmissionLedger.empty())
    a = aligned.results[0].admission.admitted_measurement
    out = transform_measurement(GeometryRequest(a,'identity','1','identity'))
    assert out.status == 'transformed'
    assert out.request.source.derivation.mapped_time.source_mapping is mapping
    assert out.request.source.source_observation is r.observation
    assert out.request.source.available_at is r.available_at


def test_zero_range_radar_origin_does_not_infer_elevation():
    r = radar_request(None)
    obs = replace(r.observation,measurement=RadarPolarDetectionMeasurement(0,0,None))
    a = admitted(replace(r,observation=obs))
    out = transform_measurement(GeometryRequest(a,'origin','1','radar_cartesian'))
    assert out.status == 'deferred'  # known origin, uncertainty still unknown
    assert (out.geometry.x_m,out.geometry.y_m,out.geometry.z_m) == (0,0,0)
    assert out.request.source.source_observation.measurement.elevation_rad is None


@pytest.mark.parametrize('rigid', [False, 0, '', ()])
def test_false_valued_rigid_is_not_an_absent_transform(rigid):
    out = transform_measurement(GeometryRequest(admitted(radar_request()),'rigid','1','radar_cartesian',rigid=rigid))
    assert out.status == 'rejected'


def test_radar_without_projection_is_not_missing_camera_calibration():
    out = transform_measurement(GeometryRequest(admitted(radar_request()),'camera','1','camera_direction'))
    assert out.status == 'rejected' and out.diagnostics[0].code == 'MEASUREMENT'


def test_mixed_unit_identity_never_relabels_radar_uncertainty():
    a = admitted(radar_request())
    out = transform_measurement(GeometryRequest(a,'identity','1','identity'))
    assert out.status == 'transformed'
    assert out.propagation.covariance.measurement_basis.units == ('m','rad','rad')
    assert out.propagation.covariance.matrix == a.uncertainty.matrix
    t = out.propagation.transform
    assert propagate_covariance(a.uncertainty,replace(t,destination_basis=replace(a.basis,units=('m','m','m')))).status == 'rejected'


def test_nontrivial_rotation_exact_float_policy_and_serialization():
    import json
    source,dest = ReferenceFrame('source'),ReferenceFrame('destination')
    c,s = 0.6,0.8
    rotation = ((c,-s,0),(s,c,0),(0,0,1))
    rigid = RigidTransform(source,dest,rotation,(3,-4,5))
    before,after = cartesian_basis(source),cartesian_basis(dest)
    u = ValidatedCovariance(((4,0,0),(0,9,0),(0,0,0)),before,PROVENANCE)
    t = LinearTransform('rotation','1',before,after,rotation,(3,-4,5),'cartesian_rigid',rigid)
    f = Fraction
    oracle = ((4*f(c)**2+9*f(s)**2,-5*f(c)*f(s),f(0)),
              (-5*f(c)*f(s),4*f(s)**2+9*f(c)**2,f(0)),(f(0),f(0),f(0)))
    first = propagate_covariance(u,t,('SAME_CORRELATION_GROUP',))
    second = propagate_covariance(u,t,('SAME_CORRELATION_GROUP',))
    assert first.covariance.matrix == oracle and first.covariance.rank == 2
    assert first == second
    # Canonical caller encoding, not a newly introduced wire format or float cast.
    def encode(covariance):
        return json.dumps([[[x.numerator,x.denominator] for x in row] for row in covariance.matrix],separators=(',',':'))
    assert encode(first.covariance) == encode(second.covariance)
    assert first.covariance.source_uncertainty.uncertainty_provenance is PROVENANCE
    assert 'SAME_CORRELATION_GROUP' in first.restrictions


def test_rank_collapse_has_explicit_singular_restriction():
    out = propagate_covariance(admitted().uncertainty,pixel_transform(jacobian=((1,2),(2,4))))
    assert out.status == 'transformed' and out.covariance.rank == 1
    assert out.covariance.matrix == ((40,80),(80,160))
    assert 'REQUIRES_SINGULAR_MODEL' in out.restrictions


def test_invalid_transform_is_rejected_even_when_geometry_is_unavailable():
    q = GeometryRequest(admitted(radar_request(None)),'rigid','1','radar_cartesian',rigid=False)
    assert transform_measurement(q).status == 'rejected'


def test_missing_elevation_does_not_hide_declared_source_frame_mismatch():
    rigid = RigidTransform(ReferenceFrame('wrong'),ReferenceFrame('destination'),((1,0,0),(0,1,0),(0,0,1)),(0,0,0))
    out = transform_measurement(GeometryRequest(admitted(radar_request(None)),'rigid','1','radar_cartesian',rigid=rigid))
    assert out.status == 'rejected' and out.diagnostics[0].code == 'FRAME_MISMATCH'
