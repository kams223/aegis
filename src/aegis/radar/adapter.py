"""Pure conversion from radar-local detections to normalized evidence."""

import json

from aegis.fusion.contracts import ObservationBatch, ReferenceFrame, SensorObservation
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement


def radar_detections_to_observations(
    detections: tuple[RadarDetection, ...],
    *,
    sensor_id: str,
    reference_frame_id: str,
) -> ObservationBatch[RadarPolarDetectionMeasurement]:
    """Preserve ordered evidence with explicit physical/logical sensor context.

    The frame identifies the radar measurement origin/axes, not calibration or
    a transform. Measurement and time objects are retained exactly; no clocks,
    units, or coordinates are converted. sensor_id is never inferred from a
    source session. No source lifecycle or cross-call history is owned here.

    Compact JSON observation IDs encode ["radar-detection", 1, sensor_id,
    source_session_id, evidence_id]. Replay and reorder preserve evidence IDs;
    neither values nor collection ordinals define identity. Duplicate session/
    evidence keys within this call are rejected, not deduplicated. Cross-call
    or global uniqueness remains the producer's responsibility.

    Supplied local detection IDs encode [source_session_id, local_detection_id]
    as source_local_id; absent IDs remain None. Both identities are evidence
    provenance, never track, target, or world-entity identity. Empty input yields
    an empty batch, which carries no scan completion, timing, or heartbeat data.
    """
    if not isinstance(detections, tuple):
        raise TypeError("detections must be a tuple")
    if not sensor_id.strip():
        raise ValueError("sensor_id cannot be empty or whitespace")
    reference_frame = ReferenceFrame(reference_frame_id)

    seen: set[tuple[str, str]] = set()
    observations: list[SensorObservation[RadarPolarDetectionMeasurement]] = []
    for detection in detections:
        key = (detection.source_session_id, detection.evidence_id)
        if key in seen:
            raise ValueError("Duplicate radar evidence key (source_session_id, evidence_id)")
        seen.add(key)
        observations.append(SensorObservation(
            observation_id=json.dumps(
                ["radar-detection", 1, sensor_id, *key], separators=(",", ":"),
            ),
            sensor_id=sensor_id,
            measurement_time=detection.measurement_time,
            reference_frame=reference_frame,
            measurement=detection.measurement,
            source_local_id=(
                None if detection.local_detection_id is None else json.dumps(
                    [detection.source_session_id, detection.local_detection_id],
                    separators=(",", ":"),
                )
            ),
        ))
    return ObservationBatch(tuple(observations))
