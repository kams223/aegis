"""Bounded acquisition completeness, separate from aircraft telemetry/replay."""
from dataclasses import dataclass
from hashlib import sha256

from aegis.fusion.contracts import MeasurementTime, SensorObservation
from aegis.fusion.admission import _measurement, _time, _Budget, _BatchBound
from aegis.fusion.uncertainty import Diagnostic, _Fault, _require, _text

MAX_ACQUISITIONS = 1024
MAX_OBSERVATIONS = 1024


@dataclass(frozen=True, slots=True)
class Acquisition:
    sensor_id: str
    source_session_id: str
    acquisition_id: str
    acquisition_time: MeasurementTime | None
    status: str
    observations: tuple[SensorObservation, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    source: Acquisition
    status: str
    completeness: str | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionBatch:
    results: tuple[AcquisitionResult, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


def inspect_acquisitions(events: tuple[Acquisition, ...]) -> AcquisitionBatch:
    """Preserve input order and duplicates; an absent callback is never empty.

    Repetition/conflict detection is local to this explicit batch, not a hidden
    acquisition ledger. Only valid events reserve a key. No observations inferred.
    """
    try:
        _require(type(events) is tuple and len(events) <= MAX_ACQUISITIONS, 'BOUND', 'events', 'At most 1024 immutable acquisitions')
        total = 0
        for event in events:
            if type(event) is Acquisition and type(event.observations) is tuple:
                total += len(event.observations)
            _require(total <= MAX_OBSERVATIONS, 'BOUND', 'observations', 'At most 1024 total observations')
    except _Fault as error:
        return AcquisitionBatch((), (error.diagnostic,))
    results, seen, budget = [], {}, _Budget()
    for event in events:
        try:
            _require(type(event) is Acquisition and type(event.observations) is tuple,
                     'ACQUISITION', 'event', 'Require immutable acquisition and observations')
            for name in ('sensor_id', 'source_session_id', 'acquisition_id'):
                _text(getattr(event, name), name)
            _require(type(event.status) is str and event.status in ('completed', 'unavailable', 'unconfirmed'), 'COMPLETENESS', 'status', 'Require explicit completeness')
            if event.acquisition_time is not None:
                _time(event.acquisition_time, 'acquisition_time')
            if event.status == 'completed':
                _require(event.acquisition_time is not None and event.reason is None, 'COMPLETENESS', 'event', 'Completed acquisition requires time, without unavailability reason')
                completeness = 'completed_with_observations' if event.observations else 'completed_empty'
            else:
                _require(not event.observations, 'COMPLETENESS', 'observations', 'Unconfirmed/unavailable acquisitions cannot assert observations')
                _text(event.reason, 'reason')
                completeness = event.status
            key = (event.sensor_id, event.source_session_id, event.acquisition_id)
            digest = sha256(b'sf2-acquisition-v1')
            digest.update(budget.digest((key, event.acquisition_time, event.status, event.reason, len(event.observations))).encode('ascii'))
            for obs in event.observations:
                _require(type(obs) is SensorObservation and obs.sensor_id == event.sensor_id, 'SOURCE', 'observation', 'Observation sensor must match acquisition')
                _measurement(obs); _time(obs.measurement_time, 'observation.measurement_time')
                _require(obs.measurement_time.clock_domain == event.acquisition_time.clock_domain, 'CLOCK_DOMAIN', 'observation', 'Acquisition clock must match observations; no conversion inferred')
                digest.update(budget.digest(obs).encode('ascii'))
            fingerprint = digest.hexdigest()
            if key in seen:
                duplicate = seen[key] == fingerprint
                results.append(AcquisitionResult(event, 'duplicate' if duplicate else 'rejected', completeness,
                    (Diagnostic('DUPLICATE_ACQUISITION' if duplicate else 'ACQUISITION_CONFLICT', 'acquisition_id', 'Repeated acquisition identity in this batch'),)))
            else:
                seen[key] = fingerprint
                results.append(AcquisitionResult(event, 'accepted', completeness, ()))
        except _BatchBound:
            return AcquisitionBatch((), (Diagnostic('BOUND', 'events', 'Canonical resource budget exceeded; no batch accepted'),))
        except _Fault as error:
            results.append(AcquisitionResult(event, 'rejected', None, (error.diagnostic,)))
    return AcquisitionBatch(tuple(results))
