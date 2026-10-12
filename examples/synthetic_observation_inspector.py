"""Pure, offline presentation of existing synthetic observation history.

Source counts describe caller-supplied input collections, not distinct objects
in history. Repeated occurrences are never collapsed. No derivation is run.
"""

from html import escape

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
) -> str:
    """Return a complete HTML string, preserving caller order and occurrences.

    Counts are explicit source-collection metadata; history can contain subsets
    or repeated occurrences. A represented modality requires a positive source
    count. No uniqueness, acquisition count or missing evidence is inferred.
    Inputs must be existing valid contracts with supported concrete measurements.
    """
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
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Synthetic Software Observation Inspector</title><style>" + _STYLE
            + "</style></head><body><h1>Synthetic Software Observation Inspector</h1>"
            + summary + "<p>Caller-selected history order; repeated occurrences remain separate. "
            "Occurrence counts do not establish independent acquisitions. IDs do not associate physical objects.</p>"
            "<p>Raw clock domains are preserved. Mapped intervals are conditional on supplied mappings; "
            "no automatic synchronization occurs. Geometry is displayed as supplied; camera direction has no depth. "
            "This software fixture makes no physical accuracy claim and is not a physical sensor simulation.</p>"
            "<h2>Ordered history</h2><div class=\"table-view\"><table>"
            "<caption>One row per history occurrence (zero-based position)</caption><thead><tr>"
            + "".join(f"<th scope=\"col\">{_text(heading)}</th>" for heading in headings)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></body></html>\n")
