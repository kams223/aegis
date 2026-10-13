"""Synthetic offline platform snapshot; no devices, media, or LLM services."""

import argparse
from html import escape
import json
import sys

from aegis.platform.contracts import (
    AdapterIdentity, Capability, HealthSnapshot, Timestamp, SourceReference,
    Device, build_registry, EvidenceReference, Observation, SensorAvailability,
    SentinelMonitor, Alert, AlertExplanation, InvestigationRequest,
    HumanReviewDecision, AuditEntry, PlatformContractError,
)
from aegis.platform import build_snapshot, snapshot_document, investigate


def demo_snapshot():
    """Fixed illustrative records; all identities and human review are test-only."""
    devices, evidence = [], []
    rows = (("native-aerial", "aegis_native", "aerial", "camera-a", "camera_recording"),
            ("simulated-ground", "simulated", "ground", "metadata-g", "observation_note"),
            ("third-party", "third_party", "other", "display-r", "observation_note"))
    for identity, category, device_type, source_id, kind in rows:
        domain = "demo:" + source_id
        evidence_id = source_id + ":evidence"
        source = SourceReference(source_id=source_id, device_id=identity, clock_domain=domain, evidence_id=evidence_id)
        capabilities = (Capability(name="health_snapshot", support="supported"),
                        Capability(name="observation_display", support="supported"),
                        Capability(name="camera_evidence", support="supported" if kind == "camera_recording" else "unsupported"),
                        Capability(name="recorded_integrity", support="unknown"))
        devices.append(Device(device_id=identity, category=category, device_type=device_type,
            adapter=AdapterIdentity(adapter_id="offline-fixture", version="1.0"),
            capabilities=capabilities, connection_status="offline",
            health=HealthSnapshot(status="unknown", timestamp=Timestamp(value=0, unit="s", clock_domain=domain),
                                  note="Synthetic declaration; no hardware health measurement."), sources=(source,)))
        evidence.append(EvidenceReference(evidence_id=evidence_id, source_id=source_id, kind=kind,
            local_path="examples/recorded_datasets/placeholder.txt", dataset_id=None))
    registry = build_registry(tuple(devices))
    observations = (
        Observation(observation_id="display-normal", source_id="metadata-g",
            timestamp=Timestamp(value=2, unit="s", clock_domain="demo:metadata-g"),
            category="synthetic", quality="declared", uncertainty_note=None,
            annotation="Illustrative metadata event; no position measurement.", review_status="unreviewed", evidence_id="metadata-g:evidence"),
        Observation(observation_id="display-unusual", source_id="display-r",
            timestamp=Timestamp(value=7, unit="ms", clock_domain="demo:display-r"),
            category="synthetic", quality="uncertain", uncertainty_note="Missing measurement context; requires human inspection.",
            annotation="Unusual synthetic metadata annotation, not a threat classification.", review_status="unreviewed", evidence_id="display-r:evidence"),
    )
    sentinels = tuple(SentinelMonitor(device_id=d.device_id, sentinel_category=d.device_type,
        connectivity="offline", sensors=tuple(SensorAvailability(source_id=s.source_id, status="unknown") for s in d.sources),
        battery_percent=None, maintenance_status="unknown",
        camera_evidence_id="camera-a:evidence" if d.device_type == "aerial" else None,
        review_status="unreviewed") for d in devices[:2])
    alert = Alert(alert_id="unusual-annotation", observation_id="display-unusual", status="reviewed",
                  explanation=AlertExplanation(code="unusual_metadata", explanation="Synthetic annotation needs context, not operational assessment.", evidence_ids=("display-r:evidence",)))
    request = InvestigationRequest(request_id="demo-investigation", alert_id=alert.alert_id,
                                   action="explain_observation", reference_ids=("display-unusual",))
    result = investigate(request, registry=registry, observations=observations, evidence=tuple(evidence), validation_results=())
    review_time = Timestamp(value=10, unit="s", clock_domain="demo:review")
    decision = HumanReviewDecision(decision_id="demo-review", subject_kind="alert", subject_id=alert.alert_id,
        reviewer_id="synthetic-reviewer", previous_status="unreviewed", new_status="reviewed", timestamp=review_time,
        note="Illustrative human review only; no real-world authorization.")
    audits = (AuditEntry(audit_id="demo-audit-investigation", actor_id="offline-copilot",
        event="investigation_completed", reference_id=result.result_id, timestamp=review_time,
        note="Read-only deterministic explanation."),
        AuditEntry(audit_id="demo-audit-review", actor_id=decision.reviewer_id, event="human_review",
        reference_id=decision.decision_id, timestamp=review_time, note=decision.note))
    return build_snapshot(snapshot_id="synthetic-platform-v1", description="Offline metadata-only fixture; no real devices or operational targets.",
        registry=registry, evidence=tuple(evidence), observations=observations, sentinels=sentinels,
        alerts=(alert,), investigation_requests=(request,), investigation_results=(result,),
        review_history=(decision,), audit_entries=audits, validation_results=())


def render_json(snapshot):
    return json.dumps(snapshot_document(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def render_html(snapshot):
    doc = snapshot_document(snapshot)
    body = "<h1>AEGIS Offline Platform Snapshot</h1><p>Software-only synthetic data. No device connections or operational assessment.</p>"
    body += "<p>" + escape(doc["description"], quote=True) + "</p>"
    for heading, value in (("Device registry", doc["registry"]), ("Display observations", doc["observations"]),
                           ("Sentinel monitoring", doc["sentinels"]), ("Copilot investigations", doc["investigation_results"]),
                           ("Human review", doc["review_history"]), ("Complete snapshot", doc)):
        body += "<h2>" + heading + "</h2><pre>" + escape(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False), quote=True) + "</pre>"
    return '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AEGIS Offline Platform Snapshot</title></head><body>' + body + '</body></html>\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--format", choices=("json", "html"), default="json")
    args = parser.parse_args(argv)
    try:
        snapshot = demo_snapshot()
        rendered = render_html(snapshot) if args.format == "html" else render_json(snapshot)
    except PlatformContractError as cause:
        parser.error(str(cause))
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
