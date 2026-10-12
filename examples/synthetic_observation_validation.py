"""Schema-v1 reports of explicit synthetic software checks, without pytest runs.

Inputs are constructed contracts, not files or executable scenario definitions.
Only an explicitly requested fixed-fixture profile applies built-in expectations.
"""

from dataclasses import asdict
import json
from math import isfinite

from aegis.fusion.contracts import MeasurementTime, ReferenceFrame

try:
    from synthetic_observation_analysis import SyntheticScenario, compare_scenarios, diagnose_scenario, modality
    from synthetic_observation_inspector import _fields, _text, _workspace_body, _document
except ModuleNotFoundError as error:
    if error.name not in ("synthetic_observation_analysis", "synthetic_observation_inspector"):
        raise
    from examples.synthetic_observation_analysis import SyntheticScenario, compare_scenarios, diagnose_scenario, modality
    from examples.synthetic_observation_inspector import _fields, _text, _workspace_body, _document


SCHEMA_VERSION = 1
_SEVERITIES = ("Informational", "Warning", "Invalid")
_UNEVALUATED = (
    "Detection accuracy, precision, recall and false-positive rates",
    "Latency and real-world sensor performance",
    "Physical accuracy and physical-system validation",
    "Operational readiness",
    "Complete production-contract revalidation",
)


class ValidationInputError(ValueError):
    """Input contains opaque metadata that cannot be reported as JSON scalars.

    Missing time/frame wrappers and malformed scalar metadata are reportable;
    arbitrary objects and mutable containers are intentionally unsupported.
    """


def _scalar(value, field):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise ValidationInputError(f"{field}: expected a JSON scalar, not opaque metadata")


def _observation(source):
    time, frame = source.measurement_time, source.reference_frame
    if not isinstance(time, MeasurementTime):
        _scalar(time, "measurement_time")
    if not isinstance(frame, ReferenceFrame):
        _scalar(frame, "reference_frame")
    seconds = time.seconds if isinstance(time, MeasurementTime) else None
    finite = False
    if type(seconds) in (int, float):
        try:
            finite = isfinite(seconds)
        except OverflowError:
            pass
    return {
        "observation_id": _scalar(source.observation_id, "observation_id"),
        "sensor_id": _scalar(source.sensor_id, "sensor_id"),
        "modality": modality(source.measurement),
        "measurement_type": type(source.measurement).__name__,
        "source_local_id": _scalar(source.source_local_id, "source_local_id"),
        "measurement_seconds": seconds if finite else None,
        "measurement_seconds_status": ("invalid_measurement_time" if not isinstance(time, MeasurementTime)
                                       else "available" if finite else "not_representable_as_finite_json_number"),
        "clock_domain": _scalar(time.clock_domain, "clock_domain") if isinstance(time, MeasurementTime) else None,
        "reference_frame_id": _scalar(frame.frame_id, "reference_frame_id") if isinstance(frame, ReferenceFrame) else None,
    }


def _check(key, description, passed, details=()):
    return {"id": key, "status": "not_evaluated" if passed is None else
            "passed" if passed else "failed", "description": description, "details": list(details)}


def _builtin_checks(scenario, enabled):
    descriptions = (
        ("builtin_delivery", "Fixed fixture: one camera and one radar source; radar then camera at raw times 5 and 2 in separate clocks."),
        ("builtin_geometry", "Fixed fixture stored camera direction (0,0,1), radar point (10,0,0), transformed point (11,2,3)."),
        ("builtin_mapped_intervals", "Fixed fixture supplied mappings: radar [204.75,205.25], camera [101.75,102.25] in fixture:time."),
    )
    if not enabled:
        return [_check(key, description, None, ("Fixed-fixture expectations were not requested.",))
                for key, description in descriptions]
    records = scenario.history.records
    delivery = (scenario.camera_observation_count == scenario.radar_observation_count == 1
                and len(records) == 2
                and [modality(e.source_observation.measurement) for e in records] == ["radar", "camera"]
                and [_observation(e.source_observation)["measurement_seconds"] for e in records] == [5., 2.]
                and [_observation(e.source_observation)["clock_domain"] for e in records] ==
                    ["fixture:radar", "fixture:camera"])
    geometry = intervals = False
    if len(records) == 2:
        radar, camera = records
        point, transformed, ray = radar.spatial_projection, radar.transformed_geometry, camera.spatial_projection
        # Read existing fields only; missing or different geometry fails this explicit profile.
        geometry = (all(getattr(point, name, None) == value for name, value in
                        (("x_m", 10.), ("y_m", 0.), ("z_m", 0.)))
                    and all(getattr(transformed, name, None) == value for name, value in
                            (("x_m", 11.), ("y_m", 2.), ("z_m", 3.)))
                    and all(getattr(ray, name, None) == value for name, value in
                            (("direction_x", 0.), ("direction_y", 0.), ("direction_z", 1.))))
        intervals = all(e.mapped_time is not None and
                        (e.mapped_time.lower_seconds, e.mapped_time.upper_seconds, e.mapped_time.clock_domain) == expected
                        for e, expected in zip(records, ((204.75, 205.25, "fixture:time"),
                                                        (101.75, 102.25, "fixture:time")), strict=True))
    return [_check(key, description, result) for (key, description), result in
            zip(descriptions, (delivery, geometry, intervals), strict=True)]


def build_validation_manifest(scenario: SyntheticScenario, *, reference=None, builtin_expectations=False) -> dict:
    """Read scenario values and run only the named checks in the returned manifest.

    reference is a caller-supplied second construction, not a claimed pytest run.
    Missing inventory/reference/profile produces not_evaluated, never success.
    """
    manifest, _ = _validation_data(scenario, reference=reference, builtin_expectations=builtin_expectations)
    return manifest


def _validation_data(scenario, *, reference=None, builtin_expectations=False):
    """Keep the diagnostic tuple alongside its detached manifest for composition."""
    if not isinstance(scenario, SyntheticScenario):
        raise TypeError("scenario must be SyntheticScenario")
    if reference is not None and not isinstance(reference, SyntheticScenario):
        raise TypeError("reference must be SyntheticScenario or None")
    if type(builtin_expectations) is not bool:
        raise TypeError("builtin_expectations must be a boolean")
    # Preflight the reporting envelope before diagnostics use IDs as dict keys.
    for candidate in (scenario, reference):
        if candidate is None:
            continue
        for evidence in candidate.history.records:
            _observation(evidence.source_observation)
        for batch in candidate.source_batches or ():
            for source in batch.observations:
                _observation(source)
    findings = diagnose_scenario(scenario)
    severity_counts = {severity: sum(f.severity == severity for f in findings) for severity in _SEVERITIES}
    batches = scenario.source_batches
    inventory = None
    actual_counts = {"camera": 0, "radar": 0}
    source_positions = {}
    if batches is not None:
        inventory = []
        for batch_position, batch in enumerate(batches):
            observations = []
            for position, source in enumerate(batch.observations):
                observations.append({"observation_position": position, **_observation(source)})
                actual_counts[modality(source.measurement)] += 1
                source_positions.setdefault(id(source), []).append(
                    {"batch_position": batch_position, "observation_position": position})
            inventory.append({"batch_position": batch_position, "observations": observations})
    occurrences, first_references, raw_domains, mapped_domains = [], {}, {}, {}
    for position, evidence in enumerate(scenario.history.records):
        source = evidence.source_observation
        previous = first_references.get(id(evidence))
        first_references.setdefault(id(evidence), position)
        occurrences.append({"position": position, **_observation(source),
                            "same_evidence_as_position": previous,
                            "source_inventory_references": None if batches is None else
                                source_positions.get(id(source), [])})
        domain = occurrences[-1]["clock_domain"]
        if isinstance(domain, str) and domain.strip():
            raw_domains.setdefault(domain,
                                   {"source_inventory_positions": [], "history_positions": []})["history_positions"].append(position)
        if evidence.mapped_time is not None:
            mapped_domains.setdefault(evidence.mapped_time.clock_domain, []).append(position)
    if inventory is not None:
        for batch in inventory:
            for source in batch["observations"]:
                if not isinstance(source["clock_domain"], str) or not source["clock_domain"].strip():
                    continue
                raw_domains.setdefault(source["clock_domain"],
                    {"source_inventory_positions": [], "history_positions": []})["source_inventory_positions"].append(
                        {"batch_position": batch["batch_position"], "observation_position": source["observation_position"]})
    counts_match = None if batches is None else actual_counts == {
        "camera": scenario.camera_observation_count, "radar": scenario.radar_observation_count}
    unreferenced = [row["position"] for row in occurrences if row["source_inventory_references"] == []]
    lineage = None if batches is None or not occurrences else not unreferenced
    reconstruction = None
    reconstruction_details = []
    if reference is not None:
        differences = compare_scenarios(scenario, reference)
        shared = (scenario is reference or scenario.history is reference.history or
                  bool({id(e) for e in scenario.history.records} & {id(e) for e in reference.history.records}) or
                  bool({id(e.source_observation) for e in scenario.history.records} &
                       {id(e.source_observation) for e in reference.history.records}))
        reconstruction = not differences and not shared
        reconstruction_details = [f"{d.location}: {d.field}" for d in differences]
        if shared:
            reconstruction_details.append("Second construction shares a scenario, history, evidence or source observation reference.")
    checks = [
        _check("source_inventory_counts", "Declared camera/radar counts match supplied source inventory.", counts_match,
               ("Source inventory was not supplied.",) if batches is None else ()),
        _check("history_source_references", "Every occurrence retains an identical normalized source in supplied inventory.", lineage,
               ("Inventory unavailable or no history occurrences to inspect.",) if lineage is None else
               tuple(f"history {position}: no identical source in inventory" for position in unreferenced)),
        _check("checked_metadata_contracts", "Existing diagnostic checks find no Invalid metadata findings; not a complete contract validator.",
               severity_counts["Invalid"] == 0,
               tuple(f"{f.location}: {f.code}" for f in findings if f.severity == "Invalid")),
        _check("reconstruction_matches", "Supplied second construction has equal public inventory/history values and repeated-reference pattern, with distinct scenario, history, evidence and history-source observation objects.",
               reconstruction, reconstruction_details if reference is not None else ("Second construction was not supplied.",)),
    ] + _builtin_checks(scenario, builtin_expectations)
    status_counts = {status: sum(check["status"] == status for check in checks)
                     for status in ("passed", "failed", "not_evaluated")}
    overall = "failed" if status_counts["failed"] else "not_evaluated" if status_counts["not_evaluated"] else "passed"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scenario_label": scenario.label,
        "scope": "Deterministic synthetic software checks only",
        "counts": {"camera_observations": scenario.camera_observation_count,
                   "radar_observations": scenario.radar_observation_count,
                   "source_observations": scenario.camera_observation_count + scenario.radar_observation_count,
                   "history_occurrences": len(occurrences),
                   "repeated_reference_occurrences": sum(row["same_evidence_as_position"] is not None for row in occurrences)},
        "source_inventory": {"availability": "not_supplied" if batches is None else "supplied", "batches": inventory},
        "history_occurrences": occurrences,
        "clock_domains": {"raw": [{"clock_domain": domain, **positions} for domain, positions in raw_domains.items()],
                          "mapped": [{"clock_domain": domain, "history_positions": positions}
                                     for domain, positions in mapped_domains.items()]},
        "diagnostics": {"severity_counts": severity_counts, "findings": [asdict(f) for f in findings]},
        "invariants": checks,
        "overall_validation": {"status": overall, "check_counts": status_counts,
                               "interpretation": "Status applies only to listed software checks; unevaluated checks prevent an overall pass."},
        "unevaluated_capabilities": [{"capability": name, "status": "not_evaluated"} for name in _UNEVALUATED],
    }

    return manifest, findings


def render_validation_json(scenario, *, reference=None, builtin_expectations=False) -> str:
    """Stable insertion-ordered UTF-8-compatible JSON; no environment metadata."""
    return json.dumps(build_validation_manifest(scenario, reference=reference,
                      builtin_expectations=builtin_expectations), indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_validation_html(scenario, *, reference=None, builtin_expectations=False) -> str:
    """Combine the manifest dashboard with the existing offline replay inspector."""
    manifest, findings = _validation_data(scenario, reference=reference, builtin_expectations=builtin_expectations)
    return _render_html(scenario, manifest, findings)


def _render_html(scenario, manifest, findings):
    checks = "".join("<li>" + _fields([(name, check[name]) for name in ("id", "status", "description", "details")])
                     + "</li>" for check in manifest["invariants"])
    summary = ("<h1>Synthetic Software Validation Dashboard</h1>" + _fields([
        ("Schema version", manifest["schema_version"]), ("Scenario", manifest["scenario_label"]),
        ("Validation status", manifest["overall_validation"]["status"]),
        ("Scope", manifest["scope"]), ("Interpretation", manifest["overall_validation"]["interpretation"]),
    ] + list(manifest["counts"].items())) + "<h2>Checked invariants</h2><ul>" + checks + "</ul>"
        + "<h2>Diagnostic severity summary</h2>" + _fields(manifest["diagnostics"]["severity_counts"].items())
        + "<h2>Source inventory</h2>" + _fields([("Availability", manifest["source_inventory"]["availability"])])
        + "<pre>" + _text(json.dumps(manifest["source_inventory"]["batches"], indent=2, ensure_ascii=False, allow_nan=False)) + "</pre>"
        + "<h2>Clock-domain summary</h2><pre>" + _text(json.dumps(manifest["clock_domains"], indent=2, ensure_ascii=False, allow_nan=False)) + "</pre>"
        + "<h2>Limitations and unevaluated capabilities</h2><ul>"
        + "".join("<li>" + _text(item["capability"]) + ": not_evaluated</li>" for item in manifest["unevaluated_capabilities"])
        + "</ul><p>Deterministic software checks do not validate a physical system or demonstrate operational readiness. "
          "No accuracy or latency metrics are calculated, and no pytest suite is executed by this report generator.</p>")
    try:
        if manifest["diagnostics"]["severity_counts"]["Invalid"]:
            raise ValueError("Invalid metadata; see validation findings and source inventory")
        body = _workspace_body(scenario, replay=True, findings=findings)
    except (ValueError, TypeError) as error:
        # A failed manifest remains readable even when the inspector refuses invalid input.
        return _document(summary + '<p>Inspection unavailable: ' + _text(error) + '</p>',
                         title="Synthetic Software Validation Dashboard", minimal=True)
    return _document(summary + body, title="Synthetic Software Validation Dashboard", replay=True)


def render_validation_report(scenario, *, html=False, reference=None, builtin_expectations=False):
    """Return a complete document and its scoped exit code from one manifest."""
    manifest, findings = _validation_data(scenario, reference=reference, builtin_expectations=builtin_expectations)
    document = (_render_html(scenario, manifest, findings) if html else
                json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return document, {"passed": 0, "failed": 1, "not_evaluated": 2}[manifest["overall_validation"]["status"]]
