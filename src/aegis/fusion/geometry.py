"""SF-2 passive geometry and exact linear marginal covariance propagation.

Projection is deliberately separate from linear covariance propagation. A polar
or pixel covariance is never relabeled as Cartesian/directional covariance.
"""
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

from aegis.fusion.contracts import ReferenceFrame
from aegis.fusion.admission import AdmittedMeasurement, AdmissionRequest, AdmissionLedger, admit_batch
from aegis.fusion.uncertainty import (
    MeasurementBasis, ValidatedCovariance, CovarianceDeclaration, UnknownUncertainty,
    Diagnostic, validate_covariance, _Fault, _require, _basis, _text, _number,
    _frame, _determinant,
)
from aegis.spatial.transforms import (RigidTransform, TransformedPoint, RotatedDirection,
                                      transform_radar_point, rotate_camera_direction)
from aegis.spatial.radar import RadarPoint, radar_measurement_to_point
from aegis.spatial.camera import CameraRay
from aegis.spatial.camera import ImagePoint
from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.radar.contracts import RadarPolarDetectionMeasurement

MAX_EXACT_BITS = 8192
IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


@dataclass(frozen=True, slots=True)
class LinearTransform:
    operation_id: str
    revision: str
    source_basis: MeasurementBasis
    destination_basis: MeasurementBasis
    jacobian: tuple[tuple[int | float, ...], ...]
    offset: tuple[int | float, ...]
    kind: str = 'identity'
    rigid: RigidTransform | None = None


def _rigid(r):
    _require(type(r) is RigidTransform, 'TRANSFORM', 'rigid', 'Require explicit static rigid transform')
    _frame(r.source_frame, 'rigid.source_frame'); _frame(r.target_frame, 'rigid.target_frame')
    RigidTransform(r.source_frame, r.target_frame, r.rotation_target_from_source, r.translation_target_from_source_m)


def _linear(t):
    _require(type(t) is LinearTransform, 'TRANSFORM', 'transform', 'Require LinearTransform')
    _text(t.operation_id, 'operation_id'); _text(t.revision, 'revision')
    _text(t.kind, 'kind')
    _basis(t.source_basis, 'source_basis'); _basis(t.destination_basis, 'destination_basis')
    n, m = len(t.source_basis.axes), len(t.destination_basis.axes)
    _require(type(t.jacobian) is tuple and len(t.jacobian) == m, 'JACOBIAN', 'jacobian', 'Incorrect row count')
    for row in t.jacobian:
        _require(type(row) is tuple and len(row) == n, 'JACOBIAN', 'jacobian', 'Incorrect column count')
        for x in row:
            _number(x, 'jacobian')
    _require(type(t.offset) is tuple and len(t.offset) == m, 'OFFSET', 'offset', 'Incorrect affine offset')
    for x in t.offset:
        _number(x, 'offset')
    a, b = t.source_basis, t.destination_basis
    if t.kind == 'identity':
        _require(a == b and t.rigid is None and t.jacobian == tuple(tuple(int(i == j) for j in range(n)) for i in range(n)) and all(x == 0 for x in t.offset),
                 'TRANSFORM', 'identity', 'Identity must preserve the entire basis')
    elif t.kind == 'pixel_affine':
        _require(t.rigid is None and all(x.measurement_kind == 'image_point' and x.axes == ('u_px', 'v_px') and x.units == ('px', 'px') for x in (a, b)),
                 'TRANSFORM', 'pixel_affine', 'Only explicitly declared two-dimensional pixel transforms are supported')
    elif t.kind in ('cartesian_rigid', 'direction_rotation'):
        r = t.rigid
        # Recheck the existing proper-rotation policy without repairing parameters.
        _rigid(r)
        direction = t.kind == 'direction_rotation'
        kind, axes, units = (('direction', ('direction_x', 'direction_y', 'direction_z'), ('1',) * 3) if direction
                             else ('cartesian_point', ('x_m', 'y_m', 'z_m'), ('m',) * 3))
        _require(all(x.measurement_kind == kind and x.axes == axes and x.units == units for x in (a, b)) and
                 a.reference_frame == r.source_frame and b.reference_frame == r.target_frame and
                 t.jacobian == r.rotation_target_from_source and
                 t.offset == ((0, 0, 0) if direction else r.translation_target_from_source_m),
                 'TRANSFORM', 'rigid', 'Frames, axes, units, Jacobian and offset must match the declared operation')
    else:
        raise _Fault('UNSUPPORTED_TRANSFORM', 'kind', 'No nonlinear or inferred frame conversion is supported')


def _bounded(x):
    _require(x.numerator.bit_length() <= MAX_EXACT_BITS and x.denominator.bit_length() <= MAX_EXACT_BITS,
             'EXACT_BOUND', 'matrix', 'Exact arithmetic exceeds 8192-bit component bound')
    return x


@dataclass(frozen=True, slots=True)
class ExactCovariance:
    """Exact rational result; not an SF-1 declaration or an implicit float cast."""
    matrix: tuple[tuple[Fraction, ...], ...]
    measurement_basis: MeasurementBasis
    source_uncertainty: ValidatedCovariance
    transform: LinearTransform
    rank: int
    restrictions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PropagationResult:
    transform: LinearTransform
    source_uncertainty: ValidatedCovariance | UnknownUncertainty
    status: str
    covariance: ExactCovariance | UnknownUncertainty | None
    diagnostics: tuple[Diagnostic, ...]
    restrictions: tuple[str, ...]


def propagate_covariance(uncertainty: ValidatedCovariance | UnknownUncertainty, transform: LinearTransform,
                         restrictions: tuple[str, ...] = ()) -> PropagationResult:
    """One bounded J R Jᵀ operation on SF-1 covariance; no independence inference.

    Exact output is intentionally not accepted as a new SF-1 input or recursively
    propagated. Callers must retain explicit transformation/provenance boundaries.
    """
    flags = ()
    try:
        _linear(transform)
        _require(type(restrictions) is tuple and len(restrictions) <= 16, 'BOUND', 'restrictions', 'At most 16 restrictions')
        for flag in restrictions:
            _text(flag, 'restrictions')
        flags = tuple(dict.fromkeys(restrictions + ('JOINT_COMPATIBILITY_NOT_ASSESSED', 'NO_INDEPENDENT_COMBINATION')))
        if type(uncertainty) is UnknownUncertainty:
            _text(uncertainty.reason, 'uncertainty.reason')
            return PropagationResult(transform, uncertainty, 'deferred', uncertainty,
                                     (Diagnostic('UNCERTAINTY_UNKNOWN', 'uncertainty', 'No covariance is substituted'),), flags)
        _require(type(uncertainty) is ValidatedCovariance, 'UNCERTAINTY_TYPE', 'uncertainty', 'Require SF-1 validated marginal covariance')
        check = validate_covariance(CovarianceDeclaration(uncertainty.matrix, uncertainty.measurement_basis, uncertainty.uncertainty_provenance), transform.source_basis)
        if check.diagnostics:
            return PropagationResult(transform, uncertainty, 'rejected', None, check.diagnostics, flags)
        j, r = transform.jacobian, uncertainty.matrix
        n, m = len(r), len(j)
        # Every product/sum is bounded; dimensions <=4 and supplied scalar bits <=1075.
        matrix = tuple(tuple(_bounded(sum((_bounded(Fraction(j[a][i]) * Fraction(r[i][k]) * Fraction(j[b][k]))
                                          for i in range(n) for k in range(n)), Fraction(0))) for b in range(m)) for a in range(m))
        rank = 0
        for size in range(1, m + 1):
            for indices in combinations(range(m), size):
                minor = _determinant(tuple(tuple(matrix[i][k] for k in indices) for i in indices))
                _require(minor >= 0, 'COVARIANCE_NOT_PSD', 'matrix', 'Exact transformed covariance is not PSD')
                if minor > 0:
                    rank = size
        flags = tuple(dict.fromkeys(flags + uncertainty.restrictions + (('REQUIRES_SINGULAR_MODEL',) if rank < m else ())))
        out = ExactCovariance(matrix, transform.destination_basis, uncertainty, transform, rank, flags)
        return PropagationResult(transform, uncertainty, 'transformed', out, (), flags)
    except (_Fault, TypeError, ValueError, OverflowError) as error:
        diagnostic = error.diagnostic if isinstance(error, _Fault) else Diagnostic('TRANSFORM', 'transform', 'Invalid or unrepresentable transform')
        return PropagationResult(transform, uncertainty, 'rejected', None, (diagnostic,), flags)


@dataclass(frozen=True, slots=True)
class GeometryRequest:
    source: AdmittedMeasurement
    operation_id: str
    revision: str
    operation: str
    rigid: RigidTransform | None = None
    linear: LinearTransform | None = None
    projected_uncertainty: CovarianceDeclaration | UnknownUncertainty | None = None


@dataclass(frozen=True, slots=True)
class GeometryResult:
    request: GeometryRequest
    status: str
    source_frame: ReferenceFrame | None
    destination_frame: ReferenceFrame | None
    geometry: tuple[Fraction, ...] | RadarPoint | TransformedPoint | RotatedDirection | CameraRay | None
    propagation: PropagationResult | None
    diagnostics: tuple[Diagnostic, ...]
    restrictions: tuple[str, ...]


def _admitted(a):
    _require(type(a) is AdmittedMeasurement and type(a.uncertainty) is ValidatedCovariance,
             'ADMISSION', 'source', 'Require a validated SF-1 admission')
    u = a.uncertainty
    req = AdmissionRequest(a.source_observation, a.evidence_key.source_session_id, a.entity_kind, a.quantity,
                           a.basis, CovarianceDeclaration(u.matrix, u.measurement_basis, u.uncertainty_provenance),
                           a.correlation, a.evaluation, a.available_at, None, a.derivation)
    batch = admit_batch((req,), AdmissionLedger.empty())
    _require(not batch.diagnostics and len(batch.results) == 1, 'ADMISSION', 'source', 'Admission resource checks failed')
    outcome = batch.results[0]
    _require(outcome.admitted_measurement == a, 'ADMISSION', 'source', 'Admission values or provenance are inconsistent')


def transform_measurement(request: GeometryRequest) -> GeometryResult:
    """Passive geometry only. Returned request retains evidence, timing and lineage."""
    source_frame = destination_frame = geometry = propagation = None
    flags = ()
    try:
        _require(type(request) is GeometryRequest, 'REQUEST_TYPE', 'request', 'Require GeometryRequest')
        _text(request.operation_id, 'operation_id'); _text(request.revision, 'revision')
        _text(request.operation, 'operation')
        a = request.source
        _admitted(a)
        source_frame = a.basis.reference_frame
        flags = a.restrictions
        if request.rigid is not None:
            _rigid(request.rigid)
        if request.operation in ('identity', 'pixel_affine'):
            _require(request.rigid is None and request.projected_uncertainty is None, 'TRANSFORM', 'request', 'Unexpected projection inputs')
            t = request.linear
            if request.operation == 'identity' and t is None:
                n = len(a.values)
                t = LinearTransform(request.operation_id, request.revision, a.basis, a.basis,
                                    tuple(tuple(int(i == k) for k in range(n)) for i in range(n)), (0,) * n)
            _linear(t)
            _require(t.kind == request.operation and t.operation_id == request.operation_id and t.revision == request.revision and t.source_basis == a.basis,
                     'TRANSFORM', 'linear', 'Operation identity or source basis mismatch')
            destination_frame = t.destination_basis.reference_frame
            geometry = tuple(_bounded(sum((Fraction(x) * Fraction(y) for x, y in zip(row, a.values)), Fraction(offset)))
                             for row, offset in zip(t.jacobian, t.offset))
            propagation = propagate_covariance(a.uncertainty, t, flags)
        else:
            _require(request.linear is None, 'TRANSFORM', 'linear', 'Projection cannot use an arbitrary linear Jacobian')
            if request.operation == 'radar_cartesian':
                _require(type(a.source_observation.measurement) is RadarPolarDetectionMeasurement, 'MEASUREMENT', 'source', 'Require radar polar evidence')
                _require(request.rigid is None or request.rigid.source_frame == source_frame,
                         'FRAME_MISMATCH', 'rigid', 'Explicit source frame must match radar evidence')
                geometry = radar_measurement_to_point(a.source_observation.measurement, reference_frame=source_frame)
                if geometry is None:
                    return GeometryResult(request, 'deferred', source_frame, None, None, None,
                                          (Diagnostic('MISSING_ELEVATION', 'source', 'No Cartesian point is fabricated'),), flags)
                kind, axes, units = 'cartesian_point', ('x_m', 'y_m', 'z_m'), ('m',) * 3
                operation = 'cartesian_rigid'
            elif request.operation == 'camera_direction':
                _require(type(a.source_observation.measurement) in (ImagePoint, ImageTrackMeasurement),
                         'MEASUREMENT', 'source', 'Require camera evidence')
                projection = a.derivation.spatial_projection if a.derivation is not None else None
                _require(projection is None or type(projection) is CameraRay, 'MEASUREMENT', 'source', 'Require camera ray')
                if projection is None:
                    return GeometryResult(request, 'deferred', source_frame, None, None, None,
                                          (Diagnostic('CALIBRATION_OR_POINT_REQUIRED', 'source', 'No selected point or calibration is inferred'),), flags)
                geometry = projection
                source_frame = projection.optical_frame
                kind, axes, units = 'direction', ('direction_x', 'direction_y', 'direction_z'), ('1',) * 3
                operation = 'direction_rotation'
                flags += ('DIRECTION_ONLY_NO_DEPTH_OR_RELOCATED_ORIGIN',)
            else:
                raise _Fault('UNSUPPORTED_TRANSFORM', 'operation', 'Unsupported geometry operation')
            rigid = (RigidTransform(source_frame, source_frame, IDENTITY, (0, 0, 0))
                     if request.rigid is None else request.rigid)
            _require(type(rigid) is RigidTransform and rigid.source_frame == source_frame, 'FRAME_MISMATCH', 'rigid', 'Explicit source frame must match geometry')
            destination_frame = rigid.target_frame
            before = MeasurementBasis(kind, axes, units, source_frame)
            after = MeasurementBasis(kind, axes, units, destination_frame)
            t = LinearTransform(request.operation_id, request.revision, before, after, rigid.rotation_target_from_source,
                                (0, 0, 0) if operation == 'direction_rotation' else rigid.translation_target_from_source_m, operation, rigid)
            _linear(t)
            geometry = (rotate_camera_direction(geometry, rigid) if operation == 'direction_rotation' else transform_radar_point(geometry, rigid))
            flags += ('NONLINEAR_PROJECTION_NOT_PROPAGATED', 'PROJECTED_UNCERTAINTY_IS_CALLER_DECLARED')
            u = request.projected_uncertainty
            if u is None:
                u = UnknownUncertainty('No uncertainty declared in projected coordinates')
            if type(u) is CovarianceDeclaration:
                check = validate_covariance(u, before)
                if check.diagnostics:
                    return GeometryResult(request, 'rejected', source_frame, destination_frame, geometry, None, check.diagnostics, flags)
                u = check.covariance
            propagation = propagate_covariance(u, t, flags)
        return GeometryResult(request, propagation.status, source_frame, destination_frame, geometry, propagation, propagation.diagnostics, propagation.restrictions)
    except (_Fault, TypeError, ValueError, OverflowError, AttributeError) as error:
        diagnostic = error.diagnostic if isinstance(error, _Fault) else Diagnostic('TRANSFORM', 'request', 'Invalid geometry or numeric overflow')
        return GeometryResult(request, 'rejected', source_frame, destination_frame, geometry, propagation, (diagnostic,), flags)
