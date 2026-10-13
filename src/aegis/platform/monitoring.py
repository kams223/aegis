"""Bounded pure replay of declared monitoring events; no acquisition or control."""

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

from aegis.platform import contracts as c
from aegis.platform.snapshot import PlatformSnapshot, snapshot_from_document, snapshot_document
from aegis.platform.investigation import investigate


@c.contract
class ConnectivityPayload(c.Contract):
    previous_status: Literal["offline", "recorded", "unknown"]
    current_status: Literal["offline", "recorded", "unknown"]

    def validate(self):
        if self.previous_status == self.current_status:
            raise c.PlatformContractError("connectivity payload: require explicit status change")


@c.contract
class HealthPayload(c.Contract):
    previous_health: c.HealthSnapshot
    current_health: c.HealthSnapshot


@c.contract
class AvailabilityPayload(c.Contract):
    previous_status: Literal["available", "unavailable", "unknown"]
    availability: c.SensorAvailability


@c.contract
class ObservationPayload(c.Contract):
    observation: c.Observation
    alerts: tuple[c.Alert, ...]
    investigations: tuple[c.InvestigationRequest, ...]
    copilot_actor_id: str | None
    investigation_audit_id: str | None

    def validate(self):
        if len(self.alerts) > 1 or len(self.investigations) > 1:
            raise c.PlatformContractError("observation payload: at most one predefined alert and investigation")
        if bool(self.investigations) != (self.copilot_actor_id is not None and self.investigation_audit_id is not None):
            raise c.PlatformContractError("observation payload: investigation requires explicit actor and audit ID")
        if not self.investigations and (self.copilot_actor_id is not None or self.investigation_audit_id is not None):
            raise c.PlatformContractError("observation payload: unused investigation audit metadata")


@c.contract
class ReviewPayload(c.Contract):
    decision: c.HumanReviewDecision
    audit_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _Event(c.Contract):
    event_id: str
    device_id: str
    source_id: str | None
    timestamp: c.Timestamp


@c.contract
class ConnectivityEvent(_Event):
    event_type: Literal["device_connectivity"]
    payload: ConnectivityPayload


@c.contract
class HealthEvent(_Event):
    event_type: Literal["device_health"]
    payload: HealthPayload

    def validate(self):
        if self.payload.current_health.timestamp != self.timestamp:
            raise c.PlatformContractError("health event: payload timestamp differs")


@c.contract
class AvailabilityEvent(_Event):
    event_type: Literal["sensor_availability"]
    payload: AvailabilityPayload

    def validate(self):
        if self.source_id != self.payload.availability.source_id:
            raise c.PlatformContractError("availability event: source differs")


@c.contract
class EvidenceEvent(_Event):
    event_type: Literal["evidence_announcement"]
    payload: c.EvidenceReference

    def validate(self):
        if self.source_id != self.payload.source_id:
            raise c.PlatformContractError("evidence event: source differs")


@c.contract
class ObservationEvent(_Event):
    event_type: Literal["observation_announcement"]
    payload: ObservationPayload

    def validate(self):
        if self.source_id != self.payload.observation.source_id or self.timestamp != self.payload.observation.timestamp:
            raise c.PlatformContractError("observation event: source or timestamp differs")


@c.contract
class ReviewEvent(_Event):
    event_type: Literal["human_review"]
    payload: ReviewPayload

    def validate(self):
        if self.payload.decision.timestamp != self.timestamp:
            raise c.PlatformContractError("review event: payload timestamp differs")


EVENT_TYPES = {"device_connectivity": ConnectivityEvent, "device_health": HealthEvent,
    "sensor_availability": AvailabilityEvent, "evidence_announcement": EvidenceEvent,
    "observation_announcement": ObservationEvent, "human_review": ReviewEvent}


def event_from_document(document):
    if type(document) is not dict or type(document.get("event_type")) is not str or document["event_type"] not in EVENT_TYPES:
        raise c.PlatformContractError("event: unknown or missing event_type")
    return c.from_document(EVENT_TYPES[document["event_type"]], document)


@c.contract
class RejectionDiagnostic(c.Contract):
    event_id: str
    event_index: int
    device_id: str
    source_id: str | None
    code: Literal["DUPLICATE_EVENT_ID", "UNKNOWN_DEVICE", "SOURCE_ASSOCIATION", "CLOCK_DOMAIN_MISMATCH",
        "TIMESTAMP_REGRESSION", "CONFLICTING_UPDATE", "MONITOR_UNAVAILABLE", "DUPLICATE_EVIDENCE_ID",
        "DUPLICATE_OBSERVATION_ID", "REVIEW_ASSOCIATION", "UNAVAILABLE_MEASUREMENT", "SNAPSHOT_REJECTED"]
    severity: Literal["Rejected"]
    explanation: str

    def validate(self):
        if self.event_index < 0 or self.event_index >= c.MAX_ITEMS:
            raise c.PlatformContractError("event_index: outside session bounds")


@c.contract
class EventResult(c.Contract):
    event_id: str
    event_index: int
    event_type: Literal["device_connectivity", "device_health", "sensor_availability", "evidence_announcement", "observation_announcement", "human_review"]
    device_id: str
    source_id: str | None
    timestamp: c.Timestamp
    status: Literal["applied", "rejected"]
    diagnostics: tuple[RejectionDiagnostic, ...]

    def validate(self):
        if self.event_index < 0 or self.event_index >= c.MAX_ITEMS:
            raise c.PlatformContractError("event_index: outside session bounds")
        if (self.status == "applied" and self.diagnostics) or (self.status == "rejected" and len(self.diagnostics) != 1):
            raise c.PlatformContractError("event result: inconsistent rejection diagnostics")
        if any(d.event_id != self.event_id or d.event_index != self.event_index or d.device_id != self.device_id or d.source_id != self.source_id for d in self.diagnostics):
            raise c.PlatformContractError("event result: diagnostic reference differs")


@c.contract
class SessionSummary(c.Contract):
    event_count: int
    applied_count: int
    rejected_count: int
    status: Literal["completed", "completed_with_rejections"]

    def validate(self):
        if any(not 0 <= n <= c.MAX_ITEMS for n in (self.event_count, self.applied_count, self.rejected_count)):
            raise c.PlatformContractError("session summary: count outside bounds")
        if self.event_count != self.applied_count + self.rejected_count or self.status != ("completed_with_rejections" if self.rejected_count else "completed"):
            raise c.PlatformContractError("session summary: inconsistent totals")


@c.contract
class MonitoringSession(c.Contract):
    initial_snapshot_id: str
    event_results: tuple[EventResult, ...]
    final_snapshot: PlatformSnapshot
    summary: SessionSummary

    def validate(self):
        if tuple(r.event_index for r in self.event_results) != tuple(range(len(self.event_results))):
            raise c.PlatformContractError("session: event indices out of order")
        count = sum(r.status == "applied" for r in self.event_results)
        if self.summary.event_count != len(self.event_results) or self.summary.applied_count != count:
            raise c.PlatformContractError("session: summary differs from event results")


class _Rejected(Exception):
    def __init__(self, code, explanation):
        self.code, self.explanation = code, explanation


def _reject(condition, code, explanation):
    if not condition:
        raise _Rejected(code, explanation)


def _seconds(timestamp):
    return Fraction(str(timestamp.value)) * {"s": 1, "ms": Fraction(1,1000), "us": Fraction(1,10**6), "ns": Fraction(1,10**9)}[timestamp.unit]


def _apply(snapshot, event):
    devices = {d.device_id: d for d in snapshot.registry.devices}
    device = devices.get(event.device_id)
    _reject(device is not None, "UNKNOWN_DEVICE", "Event device is not present in the supplied registry.")
    sources = {s.source_id: s for s in device.sources}
    if event.source_id is None:
        _reject(type(event) in (ConnectivityEvent, HealthEvent, ReviewEvent), "SOURCE_ASSOCIATION", "This event requires a declared source reference.")
        domain = device.health.timestamp.clock_domain
    else:
        _reject(event.source_id in sources, "SOURCE_ASSOCIATION", "Event source is not owned by the declared device.")
        domain = sources[event.source_id].clock_domain
    _reject(event.timestamp.clock_domain == domain, "CLOCK_DOMAIN_MISMATCH", "Event clock domain differs from its explicit reference.")
    if type(event) in (ConnectivityEvent, HealthEvent):
        _reject(event.source_id is None, "SOURCE_ASSOCIATION", "Device updates require a device reference without a source reference.")
    monitor = next((s for s in snapshot.sentinels if s.device_id == event.device_id), None)
    candidate = snapshot
    if type(event) is ConnectivityEvent:
        _reject(device.connection_status == event.payload.previous_status, "CONFLICTING_UPDATE", "Expected previous connectivity does not match current state.")
        changed = replace(device, connection_status=event.payload.current_status)
        registry = c.build_registry(tuple(changed if d.device_id == device.device_id else d for d in snapshot.registry.devices))
        monitors = tuple(replace(s, connectivity=changed.connection_status) if s.device_id == device.device_id else s for s in snapshot.sentinels)
        candidate = replace(snapshot, registry=registry, sentinels=monitors)
    elif type(event) is HealthEvent:
        _reject(device.health == event.payload.previous_health, "CONFLICTING_UPDATE", "Expected previous health snapshot does not match current state.")
        _reject(event.payload.current_health.timestamp.clock_domain == device.health.timestamp.clock_domain, "CLOCK_DOMAIN_MISMATCH", "Health clock domain cannot be silently changed.")
        changed = replace(device, health=event.payload.current_health)
        candidate = replace(snapshot, registry=c.build_registry(tuple(changed if d.device_id == device.device_id else d for d in snapshot.registry.devices)))
    elif type(event) is AvailabilityEvent:
        _reject(monitor is not None, "MONITOR_UNAVAILABLE", "Device has no supplied Sentinel sensor-availability monitor.")
        prior = next(s for s in monitor.sensors if s.source_id == event.source_id)
        _reject(prior.status == event.payload.previous_status, "CONFLICTING_UPDATE", "Expected previous sensor availability does not match current state.")
        updated = replace(monitor, sensors=tuple(event.payload.availability if s.source_id == event.source_id else s for s in monitor.sensors))
        candidate = replace(snapshot, sentinels=tuple(updated if s.device_id == updated.device_id else s for s in snapshot.sentinels))
    elif type(event) is EvidenceEvent:
        _reject(all(e.evidence_id != event.payload.evidence_id for e in snapshot.evidence), "DUPLICATE_EVIDENCE_ID", "Evidence identity already exists; replacement is unsupported.")
        candidate = replace(snapshot, evidence=snapshot.evidence + (event.payload,))
    elif type(event) is ObservationEvent:
        item = event.payload.observation
        _reject(all(o.observation_id != item.observation_id for o in snapshot.observations), "DUPLICATE_OBSERVATION_ID", "Observation identity already exists; replacement is unsupported.")
        availability = None if monitor is None else next(s for s in monitor.sensors if s.source_id == item.source_id)
        _reject(availability is None or availability.status == "available" or item.quality in ("uncertain", "missing"),
                "UNAVAILABLE_MEASUREMENT", "Unavailable or unknown sensor data requires explicit uncertainty or missing quality.")
        results, audits = (), ()
        for request in event.payload.investigations:
            result = investigate(request, registry=snapshot.registry, observations=snapshot.observations + (item,),
                                 evidence=snapshot.evidence, validation_results=snapshot.validation_results)
            results += (result,)
            audits += (c.AuditEntry(audit_id=event.payload.investigation_audit_id, actor_id=event.payload.copilot_actor_id,
                event="investigation_completed" if result.status == "completed" else "investigation_not_evaluated",
                reference_id=result.result_id, timestamp=event.timestamp, note="Read-only explanation of supplied offline records."),)
        candidate = replace(snapshot, observations=snapshot.observations + (item,), alerts=snapshot.alerts + event.payload.alerts,
            investigation_requests=snapshot.investigation_requests + event.payload.investigations,
            investigation_results=snapshot.investigation_results + results, audit_entries=snapshot.audit_entries + audits)
    else:
        decision = event.payload.decision
        if decision.subject_kind == "sentinel":
            _reject(event.source_id is None and decision.subject_id == event.device_id and monitor is not None,
                    "REVIEW_ASSOCIATION", "Review event does not match its Sentinel reference.")
            subjects = snapshot.sentinels
            subject = monitor
            identity_field, status_field = "device_id", "review_status"
            group = "sentinels"
        else:
            subjects = snapshot.observations if decision.subject_kind == "observation" else snapshot.alerts
            identity_field = "observation_id" if decision.subject_kind == "observation" else "alert_id"
            status_field = "review_status" if decision.subject_kind == "observation" else "status"
            group = "observations" if decision.subject_kind == "observation" else "alerts"
            subject = next((s for s in subjects if getattr(s, identity_field) == decision.subject_id), None)
            obs = subject if decision.subject_kind == "observation" else next((o for o in snapshot.observations if subject is not None and o.observation_id == subject.observation_id), None)
            _reject(obs is not None and obs.source_id == event.source_id, "REVIEW_ASSOCIATION", "Review event does not match its observation source.")
        _reject(getattr(subject, status_field) == decision.previous_status, "CONFLICTING_UPDATE", "Expected previous review status does not match current state.")
        updated = tuple(replace(s, **{status_field:decision.new_status}) if getattr(s, identity_field) == decision.subject_id else s for s in subjects)
        audit = c.AuditEntry(audit_id=event.payload.audit_id, actor_id=decision.reviewer_id, event="human_review",
                            reference_id=decision.decision_id, timestamp=decision.timestamp, note=decision.note)
        candidate = replace(snapshot, **{group:updated}, review_history=snapshot.review_history + (decision,), audit_entries=snapshot.audit_entries + (audit,))
    return candidate


def reduce_session(initial_snapshot, events):
    """Ordered, atomic replay. Invalid schemas fail the whole invocation; valid
    events with state/relationship conflicts are rejected individually. IDs are
    consumed on first occurrence even when rejected; rejected events never advance
    state or clock watermarks. Units compare exactly within device/domain only.
    Snapshot identity stays the caller's identity; results carry event positions.
    """
    if type(initial_snapshot) is not PlatformSnapshot:
        raise c.PlatformContractError("session: require validated PlatformSnapshot")
    current = snapshot_from_document(snapshot_document(initial_snapshot))
    if type(events) is not tuple or len(events) > c.MAX_ITEMS or any(type(e) not in EVENT_TYPES.values() for e in events):
        raise c.PlatformContractError("session: require tuple of at most 256 typed events")
    # Revalidate the entire script before applying any event. No partial output
    # for malformed input, even if a malformed value follows valid events.
    for event in events:
        event_from_document(c.to_document(event))
    watermarks = {}
    sources = {s.source_id:s for d in current.registry.devices for s in d.sources}
    for device in current.registry.devices:
        key = (device.device_id, device.health.timestamp.clock_domain)
        watermarks[key] = _seconds(device.health.timestamp)
    for observation in current.observations:
        key = (sources[observation.source_id].device_id, observation.timestamp.clock_domain)
        watermarks[key] = max(watermarks.get(key, _seconds(observation.timestamp)), _seconds(observation.timestamp))
    observations = {o.observation_id:o for o in current.observations}
    alerts = {a.alert_id:a for a in current.alerts}
    for decision in current.review_history:
        if decision.subject_kind == "sentinel":
            device_id = decision.subject_id
        else:
            observation_id = decision.subject_id if decision.subject_kind == "observation" else alerts[decision.subject_id].observation_id
            device_id = sources[observations[observation_id].source_id].device_id
        key = (device_id, decision.timestamp.clock_domain)
        watermarks[key] = max(watermarks.get(key, _seconds(decision.timestamp)), _seconds(decision.timestamp))
    seen, results = set(), []
    for index, event in enumerate(events):
        diagnostics = ()
        try:
            _reject(event.event_id not in seen, "DUPLICATE_EVENT_ID", "Event ID already occurred in this session.")
            seen.add(event.event_id)
            key = (event.device_id, event.timestamp.clock_domain)
            _reject(key not in watermarks or _seconds(event.timestamp) >= watermarks[key], "TIMESTAMP_REGRESSION", "Event timestamp precedes known state within this device clock domain.")
            candidate = _apply(current, event)
            current = candidate
            watermarks[key] = _seconds(event.timestamp)
            status = "applied"
        except (_Rejected, c.PlatformContractError) as cause:
            code = cause.code if isinstance(cause, _Rejected) else "SNAPSHOT_REJECTED"
            explanation = cause.explanation if isinstance(cause, _Rejected) else str(cause)
            diagnostics = (RejectionDiagnostic(event_id=event.event_id, event_index=index, device_id=event.device_id,
                source_id=event.source_id, code=code, severity="Rejected", explanation=explanation),)
            status = "rejected"
        results.append(EventResult(event_id=event.event_id, event_index=index, event_type=event.event_type,
            device_id=event.device_id, source_id=event.source_id, timestamp=event.timestamp, status=status, diagnostics=diagnostics))
    applied = sum(result.status == "applied" for result in results)
    summary = SessionSummary(event_count=len(events), applied_count=applied, rejected_count=len(events)-applied,
        status="completed_with_rejections" if applied < len(events) else "completed")
    return MonitoringSession(initial_snapshot_id=initial_snapshot.snapshot_id, event_results=tuple(results), final_snapshot=current, summary=summary)
