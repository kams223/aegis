"""SF-2 explicit temporal alignment and a bounded SF-1 admission bridge."""
from dataclasses import dataclass, fields, replace
from fractions import Fraction
from typing import Literal

from aegis.fusion.contracts import MeasurementTime, SensorObservation
from aegis.fusion.clock_mapping import BoundedClockMapping, MappedTimeInterval, map_measurement_time
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.admission import (AdmissionRequest, AdmissionResult, AdmissionLedger,
    EvidenceKey, admit_batch, MAX_REQUESTS, _time, _key)
from aegis.fusion.uncertainty import Diagnostic, _Fault, _require, _text, _number


@dataclass(frozen=True, slots=True)
class TimingRequest:
    evidence_key: EvidenceKey
    acquisition: MeasurementTime
    delivery: MeasurementTime | None
    evaluation: MeasurementTime
    max_age_seconds: int | float | None
    operation_id: str
    revision: str
    acquisition_mapping: BoundedClockMapping | None = None
    delivery_mapping: BoundedClockMapping | None = None


@dataclass(frozen=True, slots=True)
class TimingResult:
    request: TimingRequest
    status: Literal['eligible', 'deferred', 'rejected']
    acquisition_interval: tuple[int | float, int | float] | None
    delivery_interval: tuple[int | float, int | float] | None
    mapped_acquisition: MappedTimeInterval | None
    mapped_delivery: MappedTimeInterval | None
    diagnostics: tuple[Diagnostic, ...]
    restrictions: tuple[str, ...] = ('CLOCK_RELATIONSHIP_IS_CALLER_DECLARED',)


def _mapped(time, mapping, domain, path):
    _time(time, path)
    if mapping is None:
        return ((time.seconds, time.seconds), None) if time.clock_domain == domain else (None, None)
    _require(type(mapping) is BoundedClockMapping, 'CLOCK_MAPPING', path, 'Require explicit BoundedClockMapping')
    for name in ('source_clock_domain', 'target_clock_domain'):
        _text(getattr(mapping, name), path + '.mapping.' + name)
    for name in ('scale', 'offset_seconds', 'valid_from_source_seconds', 'valid_until_source_seconds', 'error_bound_seconds'):
        _number(getattr(mapping, name), path + '.mapping.' + name)
    _require(mapping.target_clock_domain == domain and mapping.source_clock_domain == time.clock_domain,
             'CLOCK_DOMAIN', path, 'Mapping source/target do not match the declared clocks')
    try:
        BoundedClockMapping(**{f.name: getattr(mapping, f.name) for f in fields(mapping)})
        mapped = map_measurement_time(time, mapping)
    except (TypeError, ValueError, OverflowError):
        raise _Fault('CLOCK_MAPPING', path, 'Invalid mapping, validity interval or unrepresentable enclosing bounds') from None
    return (mapped.lower_seconds, mapped.upper_seconds), mapped


def align_time(request: TimingRequest) -> TimingResult:
    """Align explicit acquisition/delivery intervals; never choose a favorable endpoint."""
    acquisition = delivery = mapped_acquisition = mapped_delivery = None
    try:
        _require(type(request) is TimingRequest, 'REQUEST_TYPE', 'request', 'Require TimingRequest')
        _key(request.evidence_key)
        _text(request.operation_id, 'operation_id'); _text(request.revision, 'revision')
        _time(request.evaluation, 'evaluation')
        if request.max_age_seconds is not None:
            _number(request.max_age_seconds, 'max_age_seconds')
            _require(request.max_age_seconds >= 0, 'AGE_POLICY', 'max_age_seconds', 'Require nonnegative age policy or explicit None')
        acquisition, mapped_acquisition = _mapped(request.acquisition, request.acquisition_mapping,
                                                  request.evaluation.clock_domain, 'acquisition')
        if request.delivery is not None:
            delivery, mapped_delivery = _mapped(request.delivery, request.delivery_mapping,
                                                request.evaluation.clock_domain, 'delivery')
        else:
            _require(request.delivery_mapping is None, 'CLOCK_MAPPING', 'delivery_mapping', 'A mapping cannot supply an absent delivery timestamp')
        if request.delivery is not None:
            if request.acquisition.clock_domain == request.delivery.clock_domain:
                _require(Fraction(request.acquisition.seconds) <= Fraction(request.delivery.seconds),
                         'CAUSAL_ORDER', 'delivery', 'Delivery precedes acquisition in the same source clock')
            a, d = request.acquisition_mapping, request.delivery_mapping
            if a is not None and d is not None and a.source_clock_domain == d.source_clock_domain:
                # Two declarations for the same clock pair must be compatible
                # throughout their common validity interval, not just at samples.
                start = max(Fraction(a.valid_from_source_seconds), Fraction(d.valid_from_source_seconds))
                end = min(Fraction(a.valid_until_source_seconds), Fraction(d.valid_until_source_seconds))
                if start <= end:
                    error = Fraction(a.error_bound_seconds) + Fraction(d.error_bound_seconds)
                    for point in (start, end):
                        difference = ((Fraction(a.scale) - Fraction(d.scale)) * point
                                      + Fraction(a.offset_seconds) - Fraction(d.offset_seconds))
                        _require(abs(difference) <= error, 'INCONSISTENT_MAPPING', 'mapping',
                                 'Clock declarations have disjoint bounds within overlapping validity')
        reason = None
        if acquisition is None or (request.delivery is not None and delivery is None):
            reason = ('CLOCK_MAPPING_REQUIRED', 'mapping', 'No relationship to the evaluation clock was declared')
        elif delivery is None:
            reason = ('AVAILABILITY_UNKNOWN', 'delivery', 'No delivery was recorded; acquisition is not substituted')
        else:
            lo, hi = map(Fraction, acquisition); dl, du = map(Fraction, delivery)
            now = Fraction(request.evaluation.seconds)
            _require(lo <= du, 'CAUSAL_ORDER', 'delivery', 'Delivery precedes the entire acquisition interval')
            if hi > dl:
                reason = ('TEMPORAL_AMBIGUITY', 'delivery', 'Acquisition/delivery bounds do not establish causal eligibility')
            elif du > now:
                reason = ('PENDING_DELIVERY' if dl > now else 'TEMPORAL_AMBIGUITY', 'delivery', 'Delivery is not established at or before evaluation')
            elif request.max_age_seconds is not None and now - lo > Fraction(request.max_age_seconds):
                reason = ('STALE_MEASUREMENT', 'max_age_seconds', 'Worst-case acquisition age exceeds the explicit limit')
        return TimingResult(request, 'deferred' if reason else 'eligible', acquisition, delivery,
                            mapped_acquisition, mapped_delivery, (Diagnostic(*reason),) if reason else ())
    except _Fault as error:
        return TimingResult(request, 'rejected', acquisition, delivery, mapped_acquisition, mapped_delivery, (error.diagnostic,))


@dataclass(frozen=True, slots=True)
class AlignmentRequest:
    source: AdmissionRequest
    operation_id: str
    revision: str
    clock_mapping: BoundedClockMapping | None = None


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    request: AlignmentRequest
    status: str
    prepared_request: AdmissionRequest | None
    clock_mapping: BoundedClockMapping | None
    mapped_time: MappedTimeInterval | None
    admission: AdmissionResult | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class AlignmentBatch:
    results: tuple[AlignmentResult, ...]
    ledger: AdmissionLedger
    diagnostics: tuple[Diagnostic, ...] = ()


def align_batch(requests: tuple[AlignmentRequest, ...], ledger: AdmissionLedger) -> AlignmentBatch:
    """Prepare explicit acquisition mappings, then call SF-1 once in input order.

    Delivery remains the original SF-1 timestamp in the evaluation domain; use
    align_time for bounded delivery mappings. No interval is forged into a point.
    """
    try:
        _require(type(ledger) is AdmissionLedger, 'LEDGER', 'ledger', 'Require AdmissionLedger')
        AdmissionLedger(ledger.entries)
        _require(type(requests) is tuple and len(requests) <= MAX_REQUESTS, 'BOUND', 'requests', 'Require at most 1024 alignment requests')
    except _Fault as error:
        return AlignmentBatch((), ledger if type(ledger) is AdmissionLedger else AdmissionLedger.empty(), (error.diagnostic,))
    results, prepared, positions = [], [], []
    text_bytes = 0
    for request in requests:
        mapping = mapped = source = None
        try:
            _require(type(request) is AlignmentRequest, 'REQUEST_TYPE', 'request', 'Require AlignmentRequest')
            for name in ('operation_id', 'revision'):
                _text(getattr(request, name), name)
                text_bytes += len(getattr(request, name).encode('utf-8'))
            if text_bytes > 1024 * 1024:
                return AlignmentBatch((), ledger, (Diagnostic('BOUND', 'requests', 'Alignment identity text exceeds 1 MiB; no admission performed'),))
            source = request.source
            _require(type(source) is AdmissionRequest and type(source.observation) is SensorObservation,
                     'REQUEST_TYPE', 'source', 'Require existing normalized SF-1 request')
            _time(source.evaluation, 'evaluation')
            existing = source.derivation
            if existing is not None:
                _require(type(existing) is DerivedSensorEvidence and existing.source_observation is source.observation,
                         'DERIVATION_SOURCE_MISMATCH', 'source.derivation', 'Derivation must retain the original observation')
            mapping = request.clock_mapping
            if mapping is not None:
                _, mapped = _mapped(source.observation.measurement_time, mapping, source.evaluation.clock_domain, 'acquisition')
                if existing is not None and existing.mapped_time is not None:
                    _require(existing.mapped_time == mapped and existing.mapped_time.source_time is source.observation.measurement_time,
                             'INCONSISTENT_MAPPING', 'source.derivation', 'Explicit mapping contradicts retained timing provenance')
                try:
                    derivation = replace(existing, mapped_time=mapped) if existing is not None else DerivedSensorEvidence(source.observation, mapped_time=mapped)
                except (TypeError, ValueError, OverflowError):
                    raise _Fault('DERIVATION', 'source.derivation', 'Existing evidence checks rejected the mapped declaration') from None
                source = replace(source, derivation=derivation)
            elif existing is not None:
                mapped = existing.mapped_time
                _require(mapped is None or type(mapped) is MappedTimeInterval, 'CLOCK_MAPPING', 'source.derivation', 'Require existing mapped interval')
                mapping = mapped.source_mapping if mapped is not None else None
            positions.append(len(results)); prepared.append(source)
            results.append(AlignmentResult(request, 'deferred', source, mapping, mapped, None, ()))
        except _Fault as error:
            results.append(AlignmentResult(request, 'rejected', source, mapping, mapped, None, (error.diagnostic,)))
    admitted = admit_batch(tuple(prepared), ledger)
    if admitted.diagnostics:
        for i in positions:
            results[i] = replace(results[i], status='rejected', diagnostics=admitted.diagnostics)
    else:
        for i, outcome in zip(positions, admitted.results):
            results[i] = replace(results[i], status=outcome.status, admission=outcome, diagnostics=outcome.diagnostics)
    return AlignmentBatch(tuple(results), admitted.ledger, admitted.diagnostics)
