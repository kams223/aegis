"""Pure, offline presentation of existing synthetic observation history.

Source counts describe caller-supplied input collections, not distinct objects
in history. Repeated occurrences are never collapsed. No derivation is run.
"""

from html import escape
from fractions import Fraction
from dataclasses import dataclass
from types import MappingProxyType

try:
    from synthetic_observation_analysis import (
        SyntheticScenario, compare_scenarios, diagnose_scenario, modality,
    )
except ModuleNotFoundError as error:
    if error.name != "synthetic_observation_analysis":
        raise
    # runpy consumers rooted at the repository can use its examples namespace.
    from examples.synthetic_observation_analysis import (
        SyntheticScenario, compare_scenarios, diagnose_scenario, modality,
    )

try:
    from synthetic_observation_replay import ReplayState
except ModuleNotFoundError as error:
    if error.name != "synthetic_observation_replay":
        raise
    from examples.synthetic_observation_replay import ReplayState

from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import CameraRay, ImagePoint
from aegis.spatial.transforms import RotatedDirection


_UNAVAILABLE = "Unavailable (not supplied)"
_NOT_APPLICABLE = "Not applicable"
_STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #172b3a;
       background: #f4f7fa; }
h1, h2 { color: #123e57; }
.table-view { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: white; }
th, td { padding: .65rem; border: 1px solid #bccbd5; text-align: left;
         vertical-align: top; overflow-wrap: anywhere; }
th { background: #e1edf4; }
tbody tr:nth-child(even) { background: #f0f5f8; }
details { min-width: 22rem; }
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.comparison > section { min-width: 0; border: 1px solid #bccbd5; padding: 1rem; }
.delivery, .clock-lane { padding-left: 2rem; border-left: 3px solid #4181a4; }
.delivery li, .clock-lane li { padding: .5rem; margin: .5rem 0; background: white; }
.clock-lane svg { display: block; width: 320px; max-width: 100%; height: 20px; }
.findings li, .differences li { margin: .75rem 0; overflow-wrap: anywhere; }
@media (max-width: 900px) { .comparison { grid-template-columns: 1fr; } }
summary { cursor: pointer; font-weight: bold; }
dl { margin: .5rem 0; }
dt { font-weight: bold; margin-top: .5rem; }
dd { margin-left: 1rem; white-space: pre-wrap; }
"""


def _text(value):
    return escape(_UNAVAILABLE if value is None else str(value), quote=True)


def _fields(items):
    return "<dl>" + "".join(
        f"<dt>{_text(label)}</dt><dd>{_text(value)}</dd>"
        for label, value in items
    ) + "</dl>"


def _measurement_fields(measurement):
    if type(measurement) is RadarPolarDetectionMeasurement:
        return "radar", [
            ("Range (m)", measurement.range_m),
            ("Azimuth (rad)", measurement.azimuth_rad),
            ("Elevation (rad)", measurement.elevation_rad),
            ("Radial range rate (m/s)", measurement.radial_velocity_mps),
        ]
    if type(measurement) is ImageTrackMeasurement:
        fields = [
            ("Class ID", measurement.class_id), ("Label", measurement.label),
            ("Detection confidence (backend)", measurement.confidence),
            ("Bounding box xyxy (px)",
             (measurement.x1, measurement.y1, measurement.x2, measurement.y2)),
        ]
    elif type(measurement) is ImagePoint:
        fields = [("Image point uv (px)", (measurement.u_px, measurement.v_px)),
                  ("Image point frame", measurement.image_frame.frame_id)]
    else:
        raise TypeError("unsupported observation measurement type")
    return "camera", fields + [
        ("Image dimensions (px)", (measurement.image_width, measurement.image_height)),
    ]


def _geometry(value):
    if value is None:
        return _fields([("Geometry", None), ("Geometry frame", None)])
    if isinstance(value, (CameraRay, RotatedDirection)):
        frame = value.optical_frame if isinstance(value, CameraRay) else value.reference_frame
        fields = [("Direction xyz (dimensionless)",
                   (value.direction_x, value.direction_y, value.direction_z))]
    else:
        frame = value.reference_frame
        fields = [("Point xyz (m)", (value.x_m, value.y_m, value.z_m))]
    return _fields(fields + [("Geometry frame", frame.frame_id)])


def _details(evidence, modality, measurement_fields):
    source = evidence.source_observation
    projection = evidence.spatial_projection
    intrinsics = evidence.camera_intrinsics
    transform = evidence.spatial_transform
    mapped = evidence.mapped_time
    items = [("Source observation ID", source.observation_id),
             ("Source sensor ID", source.sensor_id)]
    if modality == "camera":
        point = None if projection is None else projection.source_image_point
        items += [
            ("Selected image point uv (px)", None if point is None else (point.u_px, point.v_px)),
            ("Selected image point frame", None if point is None else point.image_frame.frame_id),
            ("Calibration ID", None if intrinsics is None else intrinsics.calibration_id),
            ("Intrinsics fx/fy/cx/cy (px)", None if intrinsics is None else
             (intrinsics.fx_px, intrinsics.fy_px, intrinsics.cx_px, intrinsics.cy_px)),
            ("Calibration image dimensions (px)", None if intrinsics is None else
             (intrinsics.image_width, intrinsics.image_height)),
            ("Calibration image frame", None if intrinsics is None else intrinsics.image_frame.frame_id),
            ("Calibration optical frame", None if intrinsics is None else intrinsics.optical_frame.frame_id),
        ]
    else:
        items += [("Camera calibration", _NOT_APPLICABLE),
                  ("Projection source", None if projection is None else
                   "Original radar measurement retained by reference")]
    items += [
        ("Transform source frame", None if transform is None else transform.source_frame.frame_id),
        ("Transform target frame", None if transform is None else transform.target_frame.frame_id),
        ("Rotation target from source", None if transform is None else transform.rotation_target_from_source),
        ("Translation target from source (m)", None if transform is None else
         transform.translation_target_from_source_m),
    ]
    mapping = None if mapped is None else mapped.source_mapping
    items += [
        ("Mapped source timestamp (s)", None if mapped is None else mapped.source_time.seconds),
        ("Mapping source clock", None if mapping is None else mapping.source_clock_domain),
        ("Mapping target clock", None if mapping is None else mapping.target_clock_domain),
        ("Mapping scale (dimensionless)", None if mapping is None else mapping.scale),
        ("Mapping offset (target s)", None if mapping is None else mapping.offset_seconds),
        ("Mapping validity (source s)", None if mapping is None else
         (mapping.valid_from_source_seconds, mapping.valid_until_source_seconds)),
        ("Mapping error bound (target s)", None if mapping is None else mapping.error_bound_seconds),
    ]
    return ("<details><summary>Measurement, provenance and derivation inputs</summary>"
            + _fields(measurement_fields + items) + "</details>")


def render_observation_history_html(
    history: ObservationHistory, *, scenario_label: str,
    camera_observation_count: int, radar_observation_count: int,
    source_batches=None, comparison: SyntheticScenario | None = None,
    replay: bool = False, _replay_scope: str = "left",
) -> str:
    """Return a complete HTML string, preserving caller order and occurrences.

    Counts are explicit source-collection metadata; history can contain subsets
    or repeated occurrences. A represented modality requires a positive source
    count. No uniqueness, acquisition count or missing evidence is inferred.
    Inputs must be existing valid contracts with supported concrete measurements.
    """
    if type(replay) is not bool:
        raise TypeError("replay must be a boolean")
    if not isinstance(history, ObservationHistory):
        raise TypeError("history must be ObservationHistory")
    if not isinstance(scenario_label, str):
        raise TypeError("scenario_label must be a string")
    if not scenario_label.strip():
        raise ValueError("scenario_label must be nonblank")
    counts = {"camera": camera_observation_count, "radar": radar_observation_count}
    for name, count in counts.items():
        if type(count) is not int:
            raise TypeError(f"{name}_observation_count must be an integer")
        if count < 0:
            raise ValueError(f"{name}_observation_count must be nonnegative")
    scenario = SyntheticScenario(scenario_label, history, camera_observation_count,
                                 radar_observation_count, source_batches)
    return _document(_workspace_body(scenario, comparison, replay=replay, scope=_replay_scope), replay=replay)


def _document(body, *, title="Synthetic Software Observation Inspector", replay=False, minimal=False):
    """Wrap trusted, already-escaped fragments with the original document bytes."""
    head = '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
    if not minimal:
        head += '<meta name="viewport" content="width=device-width, initial-scale=1">'
    head += "<title>" + _text(title) + "</title>"
    if not minimal:
        head += "<style>" + _STYLE + (_REPLAY_STYLE if replay else "") + "</style>"
    return head + "</head><body>" + body + "</body></html>\n"


@dataclass(frozen=True)
class _PreparedScenario:
    """Report-local immutable indexes; no cache survives the rendering call."""
    findings: tuple
    findings_by_location: object
    source_references: object


def _prepare_scenario(scenario, findings=None):
    findings = diagnose_scenario(scenario) if findings is None else findings
    locations, references = {}, {}
    for index, finding in enumerate(findings):
        locations.setdefault(finding.location, []).append((index, finding))
    if scenario.source_batches is not None:
        for batch_index, batch in enumerate(scenario.source_batches):
            for source_index, source in enumerate(batch.observations):
                references.setdefault(id(source), []).append(f"batch {batch_index}, observation {source_index}")
    return _PreparedScenario(
        findings, MappingProxyType({key: tuple(value) for key, value in locations.items()}),
        None if scenario.source_batches is None else
        MappingProxyType({key: tuple(value) for key, value in references.items()}),
    )


def _workspace_body(scenario, comparison=None, *, replay=False, scope="left", findings=None):
    if type(replay) is not bool:
        raise TypeError("replay must be a boolean")
    # Preserve the existing renderer's envelope checks, including forged counts.
    SyntheticScenario(scenario.label, scenario.history, scenario.camera_observation_count,
                      scenario.radar_observation_count, scenario.source_batches)
    prepared = _prepare_scenario(scenario, findings)
    if any(f.severity == "Invalid" for f in prepared.findings):
        raise ValueError("history violates a checked public contract; inspect diagnose_scenario findings")
    if comparison is not None and not isinstance(comparison, SyntheticScenario):
        raise TypeError("comparison must be SyntheticScenario or None")
    body = _scenario_body(scenario, prepared, replay=replay, scope=scope)
    if comparison is not None:
        other = (_scenario_body(comparison, prepared, replay=replay, scope="right")
                 if comparison is scenario else
                 _workspace_body(comparison, replay=replay, scope="right"))
        body = (_comparison_html(scenario, comparison)
                + '<div class="comparison"><section><h2>Left scenario</h2>'
                + body + "</section><section><h2>Right scenario</h2>"
                + other + "</section></div>")
    return body


def _scenario_body(scenario, prepared, *, replay, scope):
    history, scenario_label = scenario.history, scenario.label
    camera_observation_count = scenario.camera_observation_count
    radar_observation_count = scenario.radar_observation_count
    counts = {"camera": camera_observation_count, "radar": radar_observation_count}
    rows = []
    for position, evidence in enumerate(history.records):
        source = evidence.source_observation
        modality, measurement_fields = _measurement_fields(source.measurement)
        if counts[modality] == 0:
            raise ValueError(f"{modality} history requires a positive source observation count")
        mapped = evidence.mapped_time
        cells = [
            _text(position), _text(modality), _text(type(source.measurement).__name__),
            _text(source.sensor_id), _text(source.observation_id), _text(source.source_local_id),
            _text(source.measurement_time.seconds), _text(source.measurement_time.clock_domain),
            _text(source.reference_frame.frame_id), _fields(measurement_fields),
            _geometry(evidence.spatial_projection), _geometry(evidence.transformed_geometry),
            _fields([("Interval (target s)", None if mapped is None else
                      (mapped.lower_seconds, mapped.upper_seconds)),
                     ("Target clock domain", None if mapped is None else mapped.clock_domain)]),
            _details(evidence, modality, measurement_fields),
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    headings = ["Position", "Modality", "Measurement type", "Sensor ID", "Observation ID",
                "Source-local ID", "Raw timestamp (s)", "Clock domain", "Reference frame",
                "Measurement", "Projection", "Transformed geometry", "Mapped time", "Details"]
    summary = _fields([
        ("Scenario", scenario_label), ("Camera source observations", camera_observation_count),
        ("Radar source observations", radar_observation_count),
        ("Total source observations", camera_observation_count + radar_observation_count),
        ("Evidence occurrences", len(history.records)), ("History occurrences", len(history.records)),
    ])
    body = ("<h1>Synthetic Software Observation Inspector</h1>"
            + summary + "<p>Caller-selected history order; repeated occurrences remain separate. "
            "Occurrence counts do not establish independent acquisitions. IDs do not associate physical objects.</p>"
            "<p>Raw clock domains are preserved. Mapped intervals are conditional on supplied mappings; "
            "no automatic synchronization occurs. Geometry is displayed as supplied; camera direction has no depth. "
            "This software fixture makes no physical accuracy claim and is not a physical sensor simulation.</p>"
            + (_replay_html(scenario, scope, prepared) if replay else "")
            + _timeline_html(scenario) + _diagnostics_html(prepared.findings)
            + "<h2>Ordered history</h2><div class=\"table-view\"><table>"
            "<caption>One row per history occurrence (zero-based position)</caption><thead><tr>"
            + "".join(f"<th scope=\"col\">{_text(heading)}</th>" for heading in headings)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    return body


def render_synthetic_workspace_html(scenario: SyntheticScenario, comparison=None, *, replay=False) -> str:
    """Inspect explicit scenarios; inputs are values, never loaded Python code."""
    if not isinstance(scenario, SyntheticScenario):
        raise TypeError("scenario must be SyntheticScenario")
    return _document(_workspace_body(scenario, comparison, replay=replay), replay=replay)


def _diagnostics_html(findings):
    items = "".join(
        "<li>" + _fields([
            ("Severity", finding.severity), ("Finding", finding.code),
            ("Location", finding.location), ("Observation ID", finding.observation_id),
            ("Explanation", finding.message),
        ]) + "</li>" for finding in findings
    )
    return ("<h2>Sensor-data quality diagnostics</h2>"
            "<p>Warnings request review, not reliability scoring. Missing optional values and "
            "repeated delivery are not contract violations. Checks are not a complete contract validator.</p>"
            + ('<ul class="findings">' + items + "</ul>" if items else "<p>No findings.</p>"))


def _coordinate(value, minimum, maximum):
    # Scale only the visual mark, retaining exact supplied numeric text separately.
    # Fraction avoids overflow for finite timestamps spanning the float range.
    if minimum == maximum:
        return "160.000"
    ratio = (Fraction(value) - Fraction(minimum)) / (Fraction(maximum) - Fraction(minimum))
    return _text(f"{float(10 + 300 * ratio):.3f}")


def _clock_lanes(groups, kind):
    sections = []
    for domain, entries in groups.items():
        minimum = min(entry[1] for entry in entries)
        maximum = max(entry[2] for entry in entries)
        items = []
        for position, lower, upper, source in entries:
            x1, x2 = _coordinate(lower, minimum, maximum), _coordinate(upper, minimum, maximum)
            graphic = ('<svg viewBox="0 0 320 20" role="img"><title>'
                       + _text(f"{kind}: {lower} to {upper} seconds in {domain}")
                       + '</title><line x1="10" y1="10" x2="310" y2="10" stroke="#bccbd5"/>'
                       + f'<line x1="{x1}" y1="10" x2="{x2}" y2="10" stroke="#123e57" stroke-width="4"/>'
                       + f'<circle cx="{x1}" cy="10" r="3" fill="#123e57"/>'
                       + f'<circle cx="{x2}" cy="10" r="3" fill="#123e57"/></svg>')
            fields = [("History position", position), ("Modality", modality(source.measurement)),
                      ("Observation ID", source.observation_id)]
            if kind == "Raw timestamp":
                fields += [("Raw timestamp (s)", lower), ("Clock domain", domain)]
            else:
                fields += [("Mapped interval (target s)", (lower, upper)), ("Target clock domain", domain)]
            items.append("<li>" + graphic + _fields(fields) + "</li>")
        sections.append("<section><h3>" + _text(kind + " clock: " + domain) + "</h3>"
                        + _fields([("Axis minimum (s)", minimum), ("Axis maximum (s)", maximum)])
                        + '<ol class="clock-lane">' + "".join(items) + "</ol></section>")
    return "".join(sections)


def _timeline_html(scenario):
    delivery, raw, mapped = [], {}, {}
    for position, evidence in enumerate(scenario.history.records):
        source = evidence.source_observation
        time = source.measurement_time
        interval = evidence.mapped_time
        delivery.append("<li>" + _fields([
            ("History position", position), ("Modality", modality(source.measurement)),
            ("Observation ID", source.observation_id), ("Raw timestamp (s)", time.seconds),
            ("Clock domain", time.clock_domain),
            ("Mapped interval (target s)", None if interval is None else
             (interval.lower_seconds, interval.upper_seconds)),
            ("Target clock domain", None if interval is None else interval.clock_domain),
        ]) + "</li>")
        raw.setdefault(time.clock_domain, []).append((position, time.seconds, time.seconds, source))
        if interval is not None:
            mapped.setdefault(interval.clock_domain, []).append(
                (position, interval.lower_seconds, interval.upper_seconds, source))
    return ("<h2>Observation timeline</h2><h3>Delivery order</h3>"
            '<ol class="delivery">' + "".join(delivery) + "</ol>"
            + ("<p>No delivery occurrences.</p>" if not delivery else "")
            + "<h3>Raw measurement clocks</h3><p>Each domain has its own numerical axis. "
            "Lanes and entries retain first appearance and delivery order, not timestamp order. "
            "Coincident marks do not imply association. Timestamp metadata is required by evidence contracts.</p>"
            + _clock_lanes(raw, "Raw timestamp")
            + "<h3>Explicitly mapped intervals</h3><p>Separate target-domain axes display supplied "
            "interval bounds, conditional on caller mappings; no synchronization is inferred.</p>"
            + (_clock_lanes(mapped, "Mapped interval") if mapped else
               "<p>Unavailable (not supplied)</p>"))


def _comparison_html(left, right):
    differences = compare_scenarios(left, right)
    items = "".join("<li>" + _fields([
        ("Location", difference.location), ("Field", difference.field),
        ("Left value", difference.left), ("Right value", difference.right),
    ]) + "</li>" for difference in differences)
    return ("<h1>Synthetic scenario comparison</h1>"
            + _fields([("Left scenario", left.label), ("Right scenario", right.label)])
            + "<p>Comparison is positional in delivery order. Matching IDs do not associate objects. "
            "All repeated occurrences are retained; absent occurrences are explicitly identified.</p>"
            + ('<ul class="differences">' + items + "</ul>" if items else
               "<p>No differences in inspected history values, counts, labels or repeated-reference pattern.</p>"))


_REPLAY_STYLE = """
.replay-state { border: 2px solid #bccbd5; background: white; padding: 1rem;
                margin: 1rem 0; scroll-margin-top: 1rem; }
.replay-state:target { border-color: #123e57; outline: 3px solid #4181a4; }
.replay-controls { display: flex; gap: 1rem; flex-wrap: wrap; }
.replay-controls a { padding: .5rem; border: 1px solid #4181a4; }
.replay-controls a[aria-disabled="true"] { color: #52616b; }
"""


def _replay_id(scope, position):
    # IDs and links use only a closed namespace and internally validated indices.
    if scope not in ("left", "right"):
        raise ValueError("replay scope must be left or right")
    return "replay-" + scope + "-" + ("initial" if position is None else str(position))


def _occurrence_list(history, positions):
    items = []
    for position in positions:
        source = history.records[position].source_observation
        items.append("<li>" + _fields([
            ("Position", position), ("Observation ID", source.observation_id),
            ("Sensor ID", source.sensor_id), ("Modality", modality(source.measurement)),
            ("Raw timestamp (s)", source.measurement_time.seconds),
            ("Clock domain", source.measurement_time.clock_domain),
        ]) + "</li>")
    return "<ol>" + "".join(items) + "</ol>" if items else "<p>None.</p>"


def render_replay_state_html(scenario: SyntheticScenario, state: ReplayState, *, scope="left") -> str:
    """Return an escaped static state card, requiring the exact scenario history."""
    if not isinstance(scenario, SyntheticScenario) or not isinstance(state, ReplayState):
        raise TypeError("scenario and state must be SyntheticScenario and ReplayState")
    if state.history is not scenario.history:
        raise ValueError("replay state must reference the scenario history")
    return _replay_state_html(scenario, state, scope, _prepare_scenario(scenario))


def _replay_state_html(scenario, state, scope, prepared):
    card_id = _replay_id(scope, state.position)
    controls = []
    for label, target in (("Previous", state.step_backward()),
                          ("Next", state.step_forward()), ("Reset", state.reset())):
        disabled = ' aria-disabled="true"' if target.position == state.position else ""
        controls.append(f'<a href="#{_replay_id(scope, target.position)}"{disabled}>{label}</a>')
    jumps = " ".join(
        f'<a href="#{_replay_id(scope, position)}">{position}</a>'
        for position in range(state.total_count)
    )
    summary = _fields([
        ("Position", "Before first occurrence" if state.position is None else state.position),
        ("Total occurrences", state.total_count), ("Visited prefix count", len(state.visited_prefix)),
    ])
    selected = "<p>No selected occurrence.</p>"
    findings = ()
    if state.current is not None:
        evidence = state.current
        source = evidence.source_observation
        sensor_modality, measurement_fields = _measurement_fields(source.measurement)
        mapped = evidence.mapped_time
        references = (None if prepared.source_references is None else
                      prepared.source_references.get(id(source), ()))
        selected = _fields([
            ("Observation ID", source.observation_id), ("Sensor ID", source.sensor_id),
            ("Modality", sensor_modality), ("Measurement type", type(source.measurement).__name__),
            ("Source-local ID", source.source_local_id),
            ("Raw timestamp (s)", source.measurement_time.seconds),
            ("Clock domain", source.measurement_time.clock_domain),
            ("Reference frame", source.reference_frame.frame_id),
            ("Source inventory references by identity", None if references is None else
             references or "No identical source in supplied inventory"),
        ] + measurement_fields)
        selected += "<h4>Projection</h4>" + _geometry(evidence.spatial_projection)
        selected += "<h4>Transformed geometry</h4>" + _geometry(evidence.transformed_geometry)
        selected += "<h4>Mapped time</h4>" + _fields([
            ("Interval (target s)", None if mapped is None else (mapped.lower_seconds, mapped.upper_seconds)),
            ("Target clock domain", None if mapped is None else mapped.clock_domain),
        ]) + _details(evidence, sensor_modality, measurement_fields)
        locations = {f"history {state.position}"}
        if references:
            locations.update(references)
        # Merge relevant location buckets by original finding index, not location order.
        relevant = [entry for location in locations
                    for entry in prepared.findings_by_location.get(location, ())]
        findings = tuple(finding for _, finding in sorted(relevant, key=lambda entry: entry[0]))
    boundary = 0 if state.position is None else state.position
    future_start = 0 if state.position is None else state.position + 1
    return (f'<article class="replay-state" id="{card_id}"><h3>Replay state</h3>'
            + summary + '<nav class="replay-controls" aria-label="Replay controls">'
            + "".join(controls) + "</nav><p>Jump to occurrence: "
            + (jumps or "None (empty history)") + "</p><h4>Selected occurrence</h4>"
            + selected + "<h4>Selected occurrence diagnostics</h4>"
            + _diagnostics_html(findings)
            + "<h4>Previously visited occurrences (before selection)</h4>"
            + _occurrence_list(state.history, range(boundary))
            + "<h4>Future occurrences</h4>"
            + _occurrence_list(state.history, range(future_start, state.total_count)) + "</article>")


def _replay_html(scenario, scope, prepared):
    initial = ReplayState(scenario.history)
    states = (initial,) + tuple(initial.jump(i) for i in range(initial.total_count))
    return ('<section class="replay"><h2>Deterministic replay</h2>'
            '<p>Local links select pre-rendered cursor states, highlighted when their fragment is selected. '
            'All states remain readable without JavaScript. The initial state is before the first occurrence. '
            'Previous at the initial state and Next at the last state are no-ops. '
            'The visited prefix includes the selection; backward and reset shorten it. '
            'Jump selects a cursor frontier, not a log of acquisitions or clicks.</p>'
            f'<p><a href="#{_replay_id(scope, None)}">Start replay</a></p>'
            + "".join(_replay_state_html(scenario, state, scope, prepared) for state in states)
            + "</section>")
