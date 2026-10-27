"""SF-1 pure external-object admission. No association, estimator or actuation."""
from dataclasses import dataclass, fields
from fractions import Fraction
from hashlib import sha256
import json
from math import pi
from typing import Literal

from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.clock_mapping import BoundedClockMapping, MappedTimeInterval
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, CameraRay, PinholeCameraIntrinsics
from aegis.spatial.radar import RadarPoint
from aegis.spatial.transforms import RigidTransform, RotatedDirection, TransformedPoint
from aegis.fusion.uncertainty import (
    CovarianceDeclaration, ValidatedCovariance, UnknownUncertainty, MeasurementBasis,
    UncertaintyProvenance, Diagnostic, validate_covariance, _Fault, _require, _text,
    _number, _frame, _basis,
)

MAX_REQUESTS = 1024
MAX_LEDGER_ENTRIES = 4096
MAX_CORRELATION_SCOPE = 16
MAX_IDENTIFIER_BYTES = 1024 * 1024
MAX_CANONICAL_NODES = 524288


@dataclass(frozen=True, slots=True)
class EvidenceKey:
    sensor_id: str
    source_session_id: str
    observation_id: str


def _key(key):
    _require(type(key) is EvidenceKey, 'EVIDENCE_IDENTITY', 'key', 'Require EvidenceKey')
    for name in ('sensor_id', 'source_session_id', 'observation_id'):
        _text(getattr(key, name), 'key.' + name)


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    key: EvidenceKey
    evidence_sha256: str
    assumptions_sha256: str


@dataclass(frozen=True, slots=True)
class AdmissionLedger:
    entries: tuple[LedgerEntry, ...] = ()

    def __post_init__(self):
        _require(type(self.entries) is tuple and len(self.entries) <= MAX_LEDGER_ENTRIES,
                 'BOUND', 'ledger', 'Require at most 4096 immutable entries')
        seen = set()
        for entry in self.entries:
            _require(type(entry) is LedgerEntry, 'LEDGER', 'ledger', 'Require LedgerEntry')
            _key(entry.key)
            _require(entry.key not in seen, 'LEDGER', 'ledger', 'Ledger keys must be unique')
            seen.add(entry.key)
            for digest in (entry.evidence_sha256, entry.assumptions_sha256):
                _require(type(digest) is str and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest),
                         'LEDGER', 'ledger', 'Require lowercase SHA-256 fingerprints')

    @classmethod
    def empty(cls):
        return cls()


@dataclass(frozen=True, slots=True)
class CorrelationClaim:
    mode: Literal['unknown', 'shared_group', 'independence_asserted'] = 'unknown'
    group_id: str | None = None
    assumption_id: str | None = None
    scope: tuple[EvidenceKey, ...] = ()

    @classmethod
    def unknown(cls):
        return cls()


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    observation: SensorObservation
    source_session_id: str
    entity_kind: str
    quantity: str
    basis: MeasurementBasis
    uncertainty: CovarianceDeclaration | UnknownUncertainty
    correlation: CorrelationClaim
    evaluation: MeasurementTime
    available_at: MeasurementTime | None
    max_age_seconds: int | float | None
    derivation: DerivedSensorEvidence | None = None


@dataclass(frozen=True, slots=True)
class AdmittedMeasurement:
    source_observation: SensorObservation
    derivation: DerivedSensorEvidence | None
    evidence_key: EvidenceKey
    entity_kind: str
    quantity: str
    basis: MeasurementBasis
    values: tuple[int | float, ...]
    uncertainty: ValidatedCovariance
    correlation: CorrelationClaim
    measurement_interval: tuple[int | float, int | float]
    evaluation: MeasurementTime
    available_at: MeasurementTime
    restrictions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    status: Literal['admitted', 'deferred', 'rejected', 'duplicate']
    evidence_key: EvidenceKey | None
    source_observation: SensorObservation | None
    uncertainty: ValidatedCovariance | UnknownUncertainty | None
    admitted_measurement: AdmittedMeasurement | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class BatchAdmissionResult:
    results: tuple[AdmissionResult, ...]
    ledger: AdmissionLedger
    diagnostics: tuple[Diagnostic, ...] = ()


def _time(time, path):
    _require(type(time) is MeasurementTime, 'TIMESTAMP', path, 'Require explicit MeasurementTime in seconds')
    _number(time.seconds, path + '.seconds')
    _text(time.clock_domain, path + '.clock_domain')


def _measurement(obs):
    _require(type(obs) is SensorObservation, 'OBSERVATION_TYPE', 'observation', 'Require normalized SensorObservation, not native telemetry')
    for name in ('sensor_id', 'observation_id'):
        _text(getattr(obs, name), 'observation.' + name)
    if obs.source_local_id is not None:
        _text(obs.source_local_id, 'observation.source_local_id')
    _time(obs.measurement_time, 'observation.measurement_time')
    _frame(obs.reference_frame, 'observation.reference_frame')
    m = obs.measurement
    if type(m) in (ImagePoint, ImageTrackMeasurement):
        for name in ('image_width', 'image_height'):
            value = getattr(m, name)
            _require(type(value) is int and 0 < value <= 2147483647, 'IMAGE_DIMENSIONS', name, 'Require bounded positive integer image dimensions')
        if type(m) is ImagePoint:
            _frame(m.image_frame, 'measurement.image_frame')
            _require(m.image_frame == obs.reference_frame, 'FRAME_MISMATCH', 'measurement.image_frame', 'Image point and observation frames differ')
            kind, quantity, axes = 'image_point', 'image_location', ('u_px', 'v_px')
            values = (m.u_px, m.v_px)
        else:
            _require(type(m.class_id) is int and 0 <= m.class_id <= 2147483647,
                     'CLASS_ID', 'measurement.class_id', 'Require bounded nonnegative class ID')
            _text(m.label, 'measurement.label')
            _number(m.confidence, 'measurement.confidence')  # Backend score is metadata, not a probability or covariance.
            kind, quantity, axes = 'image_bbox', 'image_extent', ('x1', 'y1', 'x2', 'y2')
            values = (m.x1, m.y1, m.x2, m.y2)
        units = ('px',) * len(axes)
    elif type(m) is RadarPolarDetectionMeasurement:
        kind, quantity, axes, units = 'radar_polar', 'radar_polar', ('range_m', 'azimuth_rad'), ('m', 'rad')
        values = (m.range_m, m.azimuth_rad)
        for name, unit in (('elevation_rad', 'rad'), ('radial_velocity_mps', 'm/s')):
            if getattr(m, name) is not None:
                axes += (name,); units += (unit,); values += (getattr(m, name),)
    else:
        raise _Fault('UNSUPPORTED_MEASUREMENT_TYPE', 'observation.measurement', 'Only image point, image box and radar polar measurements are supported')
    for name, value in zip(axes, values):
        _number(value, 'measurement.' + name)
    if type(m) is ImageTrackMeasurement:
        _require(m.x1 < m.x2 and m.y1 < m.y2, 'IMAGE_BOX', 'measurement', 'Require an ordered positive-area box; no repair or clipping')
    if type(m) is RadarPolarDetectionMeasurement:
        _require(m.range_m >= 0 and -pi <= m.azimuth_rad < pi and (m.elevation_rad is None or -pi / 2 <= m.elevation_rad <= pi / 2),
                 'RADAR_DOMAIN', 'measurement', 'Radar range or angles violate canonical SI conventions')
    return MeasurementBasis(kind, axes, units, obs.reference_frame), quantity, values


def _correlation(claim, key):
    _require(type(claim) is CorrelationClaim, 'CORRELATION', 'correlation', 'Require explicit CorrelationClaim')
    _require(type(claim.mode) is str, 'CORRELATION', 'correlation.mode', 'Require a declared mode')
    _require(type(claim.scope) is tuple and len(claim.scope) <= MAX_CORRELATION_SCOPE,
             'BOUND', 'correlation.scope', 'Require at most 16 immutable evidence keys')
    for item in claim.scope:
        _key(item)
    _require(len(set(claim.scope)) == len(claim.scope), 'CORRELATION', 'correlation.scope', 'Scope keys must be unique')
    if claim.mode == 'unknown':
        _require(claim.group_id is None and claim.assumption_id is None and not claim.scope,
                 'CORRELATION', 'correlation', 'Unknown correlation cannot assert groups or independence')
    elif claim.mode == 'shared_group':
        _text(claim.group_id, 'correlation.group_id')
        _require(claim.assumption_id is None and not claim.scope, 'CORRELATION', 'correlation', 'Shared group is not an independence assertion')
    elif claim.mode == 'independence_asserted':
        _text(claim.assumption_id, 'correlation.assumption_id')
        _require(claim.group_id is None and 2 <= len(claim.scope) and key in claim.scope,
                 'CORRELATION', 'correlation.scope', 'Independence requires a named assumption and explicit scope including this evidence')
    else:
        raise _Fault('CORRELATION', 'correlation.mode', 'Unsupported correlation mode')
    return ('JOINT_COMPATIBILITY_NOT_ASSESSED',) + (('INDEPENDENCE_IS_CALLER_ASSERTED',) if claim.mode == 'independence_asserted' else ('NO_INDEPENDENT_COMBINATION',))


_CANONICAL_TYPES = (SensorObservation, MeasurementTime, ReferenceFrame, ImagePoint,
    ImageTrackMeasurement, RadarPolarDetectionMeasurement, MeasurementBasis, UncertaintyProvenance,
    CovarianceDeclaration, UnknownUncertainty, EvidenceKey, CorrelationClaim, DerivedSensorEvidence,
    BoundedClockMapping, MappedTimeInterval, CameraRay, PinholeCameraIntrinsics, RadarPoint,
    RigidTransform, RotatedDirection, TransformedPoint)


class _BatchBound(Exception):
    pass


class _Budget:
    def __init__(self):
        self.text_bytes = 0
        self.nodes = 0

    def canonical(self, value, depth=0):
        self.nodes += 1
        if self.nodes > MAX_CANONICAL_NODES or depth > 16:
            raise _BatchBound()
        if value is None:
            return None
        if type(value) is str:
            _text(value, 'fingerprint.text')
            self.text_bytes += len(value.encode('utf-8'))
            if self.text_bytes > MAX_IDENTIFIER_BYTES:
                raise _BatchBound()
            return value
        if type(value) in (int, float):
            _number(value, 'fingerprint.number')
            return ['int' if type(value) is int else 'float', str(value) if type(value) is int else value.hex()]
        if type(value) is tuple:
            _require(len(value) <= 16, 'BOUND', 'fingerprint.tuple', 'Metadata tuple exceeds bound')
            return [self.canonical(v, depth + 1) for v in value]
        _require(type(value) in _CANONICAL_TYPES, 'PROVENANCE_TYPE', 'fingerprint', 'Unsupported provenance object type')
        return [type(value).__module__ + '.' + type(value).__name__,
                [[f.name, self.canonical(getattr(value, f.name), depth + 1)] for f in fields(value)]]

    def digest(self, value):
        return sha256(json.dumps(['sf1-fingerprint-v1', self.canonical(value)], ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def _interval(request):
    mapped = request.derivation.mapped_time if request.derivation is not None else None
    if mapped is not None:
        _require(mapped.clock_domain == request.evaluation.clock_domain, 'CLOCK_DOMAIN', 'derivation.mapped_time', 'Mapped and evaluation domains differ')
        return mapped.lower_seconds, mapped.upper_seconds
    time = request.observation.measurement_time
    if time.clock_domain != request.evaluation.clock_domain:
        return None
    return time.seconds, time.seconds


def admit_batch(requests: tuple[AdmissionRequest, ...], ledger: AdmissionLedger) -> BatchAdmissionResult:
    """Sequential pure admission with caller-owned replay-stable duplicate protection.

    Only admitted records reserve keys. Batch budget overflow rolls back all
    tentative results; per-record rejection does not discard earlier admissions.
    Fingerprints exclude evaluation time/age policy, not evidence or assumptions.
    """
    try:
        _require(type(ledger) is AdmissionLedger, 'LEDGER', 'ledger', 'Require an immutable AdmissionLedger')
        AdmissionLedger(ledger.entries)  # Recheck public ledger structure, without trusting external fingerprints as authentication.
        _require(type(requests) is tuple and len(requests) <= MAX_REQUESTS, 'BOUND', 'requests', 'Require at most 1024 immutable requests')
    except _Fault as error:
        return BatchAdmissionResult((), ledger if type(ledger) is AdmissionLedger else AdmissionLedger.empty(), (error.diagnostic,))
    entries = list(ledger.entries)
    seen = {e.key: e for e in entries}
    results = []
    budget = _Budget()
    for request in requests:
        key = obs = uncertainty = None
        try:
            _require(type(request) is AdmissionRequest, 'REQUEST_TYPE', 'request', 'Require AdmissionRequest')
            expected, quantity, values = _measurement(request.observation)
            obs = request.observation
            key = EvidenceKey(obs.sensor_id, request.source_session_id, obs.observation_id)
            _key(key)
            _require(type(request.entity_kind) is str and request.entity_kind == 'external_object', 'ENTITY_KIND', 'entity_kind', 'SF-1 supports external-object observations only')
            _require(type(request.quantity) is str and request.quantity == quantity, 'UNSUPPORTED_QUANTITY', 'quantity', 'Requested quantity does not match the measured observable')
            _basis(request.basis, 'basis')
            _require(request.basis.reference_frame == expected.reference_frame, 'FRAME_MISMATCH', 'basis.reference_frame', 'No frame conversion is performed')
            _require(request.basis.units == expected.units, 'UNITS_MISMATCH', 'basis.units', 'Units must match canonical measurement components')
            _require(request.basis == expected, 'BASIS', 'basis', 'Axes and measurement kind must match exact supplied components')
            if type(request.uncertainty) is UnknownUncertainty:
                _text(request.uncertainty.reason, 'uncertainty.reason')
                uncertainty = request.uncertainty
            else:
                check = validate_covariance(request.uncertainty, expected)
                if check.diagnostics:
                    d = check.diagnostics[0]
                    raise _Fault(d.code, d.path, d.explanation)
                uncertainty = check.covariance
            restrictions = _correlation(request.correlation, key)
            _time(request.evaluation, 'evaluation')
            if request.available_at is not None:
                _time(request.available_at, 'available_at')
                _require(request.available_at.clock_domain == request.evaluation.clock_domain,
                         'CLOCK_DOMAIN', 'available_at', 'Availability must be declared in the evaluation domain')
            if request.max_age_seconds is not None:
                _number(request.max_age_seconds, 'max_age_seconds')
                _require(request.max_age_seconds >= 0, 'AGE_POLICY', 'max_age_seconds', 'Require nonnegative age bound or explicit None')
            source_hash = budget.digest((key, obs, request.available_at))
            assumptions_hash = budget.digest((request.entity_kind, request.quantity, request.basis,
                request.uncertainty, request.correlation, request.derivation, request.evaluation.clock_domain))
            if request.derivation is not None:
                _require(type(request.derivation) is DerivedSensorEvidence and request.derivation.source_observation is obs,
                         'DERIVATION_SOURCE_MISMATCH', 'derivation', 'Derivation must retain the exact source observation')
                try:
                    DerivedSensorEvidence(**{f.name: getattr(request.derivation, f.name) for f in fields(request.derivation)})
                except (TypeError, ValueError, OverflowError):
                    raise _Fault('DERIVATION', 'derivation', 'Existing derivation and provenance checks failed') from None
            previous = seen.get(key)
            if previous is not None:
                _require(previous.evidence_sha256 == source_hash, 'EVIDENCE_CONFLICT', 'observation', 'Previously admitted key now has different source content or availability')
                _require(previous.assumptions_sha256 == assumptions_hash, 'ADMISSION_CONTEXT_CONFLICT', 'request', 'Previously admitted key now has different uncertainty or derivation assumptions')
                results.append(AdmissionResult('duplicate', key, obs, uncertainty, None, (Diagnostic('DUPLICATE', 'observation', 'Evidence was already admitted; no second admission'),)))
                continue
            reason = None
            interval = _interval(request)
            if interval is not None and request.available_at is not None:
                _require(Fraction(interval[0]) <= Fraction(request.available_at.seconds), 'CAUSAL_ORDER', 'available_at',
                         'Delivery precedes the entire acquisition interval')
            if type(uncertainty) is UnknownUncertainty:
                reason = ('UNCERTAINTY_UNKNOWN', 'uncertainty', 'Unknown uncertainty remains unknown; no default matrix is supplied')
            elif interval is None:
                reason = ('CLOCK_MAPPING_REQUIRED', 'observation.measurement_time', 'An explicit bounded mapping to evaluation time is required')
            elif request.available_at is None:
                reason = ('AVAILABILITY_UNKNOWN', 'available_at', 'Known delivery is required; acquisition is not substituted')
            else:
                lower, upper = map(Fraction, interval)
                available, now = Fraction(request.available_at.seconds), Fraction(request.evaluation.seconds)
                if upper > available:
                    reason = ('TEMPORAL_AMBIGUITY', 'available_at', 'Acquisition bounds straddle delivery; eligibility is not established')
                elif available > now:
                    reason = ('PENDING_DELIVERY', 'available_at', 'Delivery is after evaluation')
                elif request.max_age_seconds is not None and now - lower > Fraction(request.max_age_seconds):
                    reason = ('STALE_MEASUREMENT', 'max_age_seconds', 'Worst-case acquisition age exceeds the explicit age policy')
            if reason:
                results.append(AdmissionResult('deferred', key, obs, uncertainty, None, (Diagnostic(*reason),)))
                continue
            _require(len(entries) < MAX_LEDGER_ENTRIES, 'BOUND', 'ledger', 'Ledger capacity reached; keys are never silently evicted')
            admitted = AdmittedMeasurement(obs, request.derivation, key, request.entity_kind, quantity, expected, values,
                uncertainty, request.correlation, interval, request.evaluation, request.available_at, restrictions + uncertainty.restrictions)
            entry = LedgerEntry(key, source_hash, assumptions_hash)
            entries.append(entry); seen[key] = entry
            results.append(AdmissionResult('admitted', key, obs, uncertainty, admitted, ()))
        except _Fault as error:
            results.append(AdmissionResult('rejected', key, obs, uncertainty, None, (error.diagnostic,)))
        except _BatchBound:
            return BatchAdmissionResult((), ledger, (Diagnostic('BOUND', 'requests', 'Batch canonical-node, depth or 1 MiB text budget exceeded; no admissions retained'),))
    return BatchAdmissionResult(tuple(results), AdmissionLedger(tuple(entries)))
