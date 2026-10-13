"""Closed immutable platform snapshot and pure relationship validation."""

from aegis.platform.contracts import (
    Contract, contract, DeviceRegistry, EvidenceReference, Observation,
    SentinelMonitor, Alert, InvestigationRequest, InvestigationResult,
    HumanReviewDecision, AuditEntry, ValidationEvidence, PlatformContractError,
    to_document, from_document, unique,
)


def _require(condition, explanation):
    if not condition:
        raise PlatformContractError("snapshot: " + explanation)


@contract
class PlatformSnapshot(Contract):
    snapshot_id: str
    description: str
    registry: DeviceRegistry
    evidence: tuple[EvidenceReference, ...]
    observations: tuple[Observation, ...]
    sentinels: tuple[SentinelMonitor, ...]
    alerts: tuple[Alert, ...]
    investigation_requests: tuple[InvestigationRequest, ...]
    investigation_results: tuple[InvestigationResult, ...]
    review_history: tuple[HumanReviewDecision, ...]
    audit_entries: tuple[AuditEntry, ...]
    validation_results: tuple[ValidationEvidence, ...]

    def validate(self):
        groups = ((self.evidence, "evidence_id"), (self.observations, "observation_id"),
                  (self.sentinels, "device_id"), (self.alerts, "alert_id"),
                  (self.investigation_requests, "request_id"), (self.investigation_results, "result_id"),
                  (self.review_history, "decision_id"), (self.audit_entries, "audit_id"),
                  (self.validation_results, "evidence_id"))
        for values, key in groups:
            unique(values, key, key)
        unique(self.investigation_results, "request_id", "investigation results")
        devices = {d.device_id: d for d in self.registry.devices}
        sources = {s.source_id: s for d in self.registry.devices for s in d.sources}
        refs = {e.evidence_id: e for e in self.evidence}
        obs = {o.observation_id: o for o in self.observations}
        monitors = {s.device_id: s for s in self.sentinels}
        alerts = {a.alert_id: a for a in self.alerts}
        requests = {r.request_id: r for r in self.investigation_requests}
        results = {r.result_id: r for r in self.investigation_results}
        decisions = {r.decision_id: r for r in self.review_history}
        for ref in self.evidence:
            _require(ref.source_id in sources, "dangling evidence source")
        for source in sources.values():
            _require(source.evidence_id in refs and refs[source.evidence_id].source_id == source.source_id,
                     "dangling or inconsistent source evidence")
        for item in self.observations:
            source = sources.get(item.source_id)
            _require(source is not None and item.evidence_id in refs, "dangling observation source or evidence")
            _require(refs[item.evidence_id].source_id == item.source_id, "observation evidence source differs")
            _require(item.timestamp.clock_domain == source.clock_domain, "observation clock domain differs")
            device = devices[source.device_id]
            _require(any(c.name == "observation_display" and c.support == "supported" for c in device.capabilities),
                     "observation display capability not supported")
        for item in self.sentinels:
            device = devices.get(item.device_id)
            _require(device is not None, "dangling Sentinel device")
            _require(device.device_type == item.sentinel_category, "Sentinel device category differs")
            _require(device.connection_status == item.connectivity, "Sentinel connectivity differs")
            own = {s.source_id for s in device.sources}
            _require({s.source_id for s in item.sensors} == own, "Sentinel sensor inventory differs")
            if item.camera_evidence_id is not None:
                ref = refs.get(item.camera_evidence_id)
                _require(ref is not None and ref.kind == "camera_recording" and ref.source_id in own,
                         "invalid Sentinel camera evidence")
                _require(any(c.name == "camera_evidence" and c.support == "supported" for c in device.capabilities),
                         "camera evidence capability not supported")
        for item in self.alerts:
            _require(item.observation_id in obs, "dangling alert observation")
            _require(all(key in refs for key in item.explanation.evidence_ids), "dangling alert evidence")
            _require(obs[item.observation_id].evidence_id in item.explanation.evidence_ids,
                     "alert lacks observation evidence")
        # Calling the pure investigation function also validates action-specific
        # reference kinds. A stored result must match its deterministic request.
        from aegis.platform.investigation import investigate
        generated = {}
        for request in self.investigation_requests:
            _require(request.alert_id in alerts, "dangling investigation alert")
            if request.action == "explain_observation":
                _require(request.reference_ids == (alerts[request.alert_id].observation_id,),
                         "investigation observation differs from alert")
            generated[request.request_id] = investigate(request, registry=self.registry,
                observations=self.observations, evidence=self.evidence, validation_results=self.validation_results)
        # Validate supplied outcome relationships even in a snapshot without requests.
        for value in self.validation_results:
            ref = refs.get(value.evidence_id)
            _require(ref is not None and ref.kind in ("dataset_report", "validation_result")
                     and ref.dataset_id == value.dataset_id, "inconsistent validation evidence")
        for result in self.investigation_results:
            _require(result.request_id in requests, "dangling investigation result")
            _require(result == generated[result.request_id], "result differs from deterministic investigation")
        # Review history is caller-ordered. It describes an explicit progression
        # from unreviewed to the final supplied state; timestamps are not sorted.
        subjects = {"observation": obs, "sentinel": monitors, "alert": alerts}
        states = {}
        for decision in self.review_history:
            subject = subjects[decision.subject_kind].get(decision.subject_id)
            _require(subject is not None, "dangling review subject")
            key = (decision.subject_kind, decision.subject_id)
            previous = states.get(key, "unreviewed")
            _require(decision.previous_status == previous, "review history transition differs")
            states[key] = decision.new_status
        for kind, values in subjects.items():
            for identity, subject in values.items():
                current = subject.status if kind == "alert" else subject.review_status
                _require(current == states.get((kind, identity), "unreviewed"), "review history does not explain final status")
        for audit in self.audit_entries:
            if audit.event == "human_review":
                decision = decisions.get(audit.reference_id)
                _require(decision is not None and audit.actor_id == decision.reviewer_id
                         and audit.timestamp == decision.timestamp, "inconsistent review audit")
            else:
                result = results.get(audit.reference_id)
                expected = "investigation_completed" if result is not None and result.status == "completed" else "investigation_not_evaluated"
                _require(result is not None and audit.event == expected, "inconsistent investigation audit")


def build_snapshot(**supplied):
    """Combine supplied records with no allocation of time or external resources."""
    return PlatformSnapshot(**supplied)


def snapshot_from_document(document):
    return from_document(PlatformSnapshot, document)


def snapshot_document(snapshot):
    if type(snapshot) is not PlatformSnapshot:
        raise PlatformContractError("snapshot: require PlatformSnapshot")
    return to_document(snapshot)
