"""Deterministic read-only explanations of supplied values, without an LLM."""

from aegis.platform.contracts import (
    DeviceRegistry, EvidenceReference, InvestigationRequest, InvestigationResult,
    Observation, PlatformContractError, ValidationEvidence, MAX_ITEMS, unique,
)


def _records(values, cls, key):
    if type(values) is not tuple or len(values) > MAX_ITEMS or any(type(v) is not cls for v in values):
        raise PlatformContractError("investigation: require bounded immutable " + cls.__name__ + " values")
    unique(values, key, cls.__name__)
    return {getattr(value, key): value for value in values}


def investigate(request, *, registry, observations, evidence, validation_results):
    """Consume provided data only; no file retrieval, report loading, or mutation.

    Retrieve means return an existing reference, never dereference it. Inspect
    and compare require supplied validated-outcome contracts; missing outcomes
    yield not_evaluated. IDs are resolved exactly; no discovery or fallback.
    """
    if type(request) is not InvestigationRequest or type(registry) is not DeviceRegistry:
        raise PlatformContractError("investigation: require request and registry contracts")
    obs = _records(observations, Observation, "observation_id")
    refs = _records(evidence, EvidenceReference, "evidence_id")
    outcomes = _records(validation_results, ValidationEvidence, "evidence_id")
    sources = {s.source_id: s for d in registry.devices for s in d.sources}
    devices = {d.device_id: d for d in registry.devices}
    for item in evidence:
        if item.source_id not in sources:
            raise PlatformContractError("investigation: dangling evidence source")
    for item in validation_results:
        ref = refs.get(item.evidence_id)
        if ref is None or ref.kind not in ("dataset_report", "validation_result") or ref.dataset_id != item.dataset_id:
            raise PlatformContractError("investigation: invalid validation evidence association")
    for item in observations:
        ref = refs.get(item.evidence_id)
        source = sources.get(item.source_id)
        if ref is None or source is None or ref.source_id != item.source_id or source.clock_domain != item.timestamp.clock_domain:
            raise PlatformContractError("investigation: inconsistent observation reference")
    action = request.action
    keys = request.reference_ids
    status = "completed"
    if action == "summarize_device_health":
        device = devices.get(keys[0])
        if device is None:
            raise PlatformContractError("investigation: unknown device reference")
        summary = "Device " + device.device_id + " health=" + device.health.status + "; connection=" + device.connection_status + ". " + device.health.note
        used = tuple(source.evidence_id for source in device.sources)
        if any(key not in refs or refs[key].source_id != source.source_id for key, source in zip(used, device.sources)):
            raise PlatformContractError("investigation: unresolved device evidence")
    elif action == "explain_observation":
        item = obs.get(keys[0])
        if item is None:
            raise PlatformContractError("investigation: unknown observation reference")
        summary = "Observation " + item.observation_id + " category=" + item.category + "; quality=" + item.quality + ". " + item.annotation
        if item.uncertainty_note is not None:
            summary += " Uncertainty: " + item.uncertainty_note
        used = (item.evidence_id,)
    else:
        selected = tuple(refs.get(key) for key in keys)
        if any(ref is None for ref in selected):
            raise PlatformContractError("investigation: unknown evidence reference")
        used = keys
        if action == "retrieve_evidence":
            summary = "Existing local reference: " + selected[0].local_path + ". Content not opened."
        else:
            if any(ref.kind not in ("dataset_report", "validation_result") for ref in selected):
                raise PlatformContractError("investigation: require validation report references")
            values = tuple(outcomes.get(key) for key in keys)
            if any(value is None for value in values):
                status = "not_evaluated"
                summary = "Supplied validation outcomes unavailable; referenced files were not opened."
            elif action == "inspect_dataset_report":
                value = values[0]
                summary = "Dataset " + value.dataset_id + ": metadata=" + value.metadata_status + "; integrity=" + value.integrity_status + ". Declared offline outcomes only."
            else:
                a, b = values
                same = (a.metadata_status, a.integrity_status) == (b.metadata_status, b.integrity_status)
                summary = "Offline validation statuses " + ("unchanged" if same else "changed") + "; " + a.evidence_id + " metadata=" + a.metadata_status + ", integrity=" + a.integrity_status + "; " + b.evidence_id + " metadata=" + b.metadata_status + ", integrity=" + b.integrity_status + ". No physical equivalence inferred."
    # Bound generated text too, without silently truncating supplied evidence.
    return InvestigationResult(result_id=request.request_id + ":result", request_id=request.request_id,
                               status=status, summary=summary, evidence_ids=used)
