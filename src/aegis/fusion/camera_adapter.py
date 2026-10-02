"""Convert Aegis image tracks into normalized evidence without fusion."""

from dataclasses import dataclass
import json

from aegis.fusion.contracts import (
    MeasurementTime,
    ObservationBatch,
    ReferenceFrame,
    SensorObservation,
)
from aegis.tracking.contracts import TrackedObjectBatch


@dataclass(frozen=True)
class ImageTrackMeasurement:
    """Image-space evidence copied from one tracked detection.

    xyxy coordinates are unrounded floating-point original-image pixels with a
    top-left origin, not normalized coordinates. Image dimensions preserve the
    source extent because ObservationBatch does not carry FrameMetadata.
    class_id belongs to the backend label set; label and confidence are copied
    unchanged. Confidence is backend detection confidence, not fused confidence.
    No depth, physical position, velocity, or target identity is implied.
    """

    class_id: int
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    image_width: int
    image_height: int


def tracked_objects_to_observations(
    batch: TrackedObjectBatch,
    *,
    sensor_id: str,
    clock_domain: str,
    reference_frame_id: str,
) -> ObservationBatch[ImageTrackMeasurement]:
    """Convert each input row in order using caller-supplied sensor context.

    The caller must identify the video-relative timebase and image frame; naming
    a clock or frame never converts the values. sensor_id is never inferred from
    the source opening's stream_id.

    IDs are compact JSON arrays (ASCII-escaped strings), avoiding delimiter
    ambiguity. source_local_id encodes [stream_id, track_id]. observation_id
    encodes ["camera-track", sensor_id, stream_id, frame_number, track_id, ordinal],
    where ordinal is the zero-based input row position. Thus duplicate track IDs
    retain separate evidence rows. Identical ordered input/context replays yield
    identical IDs. Reordering rows may change IDs; these are evidence keys, not
    globally associated target identities. No sorting or deduplication occurs.
    """
    # Nonempty batches also receive SensorObservation's identifier validation.
    # Check here so invalid sensor context cannot pass unnoticed on empty input.
    if not sensor_id.strip():
        raise ValueError("sensor_id cannot be empty or whitespace")

    frame = batch.frame
    measurement_time = MeasurementTime(frame.timestamp_seconds, clock_domain)
    reference_frame = ReferenceFrame(reference_frame_id)
    observations: list[SensorObservation[ImageTrackMeasurement]] = []
    for ordinal, tracked in enumerate(batch.objects):
        detection = tracked.detection
        observations.append(SensorObservation(
            observation_id=json.dumps(
                ["camera-track", sensor_id, frame.stream_id, frame.frame_number,
                 tracked.track_id, ordinal], separators=(",", ":"),
            ),
            sensor_id=sensor_id,
            measurement_time=measurement_time,
            reference_frame=reference_frame,
            source_local_id=json.dumps(
                [frame.stream_id, tracked.track_id], separators=(",", ":"),
            ),
            measurement=ImageTrackMeasurement(
                class_id=detection.class_id,
                label=detection.label,
                confidence=detection.confidence,
                x1=detection.x1,
                y1=detection.y1,
                x2=detection.x2,
                y2=detection.y2,
                image_width=frame.width,
                image_height=frame.height,
            ),
        ))
    return ObservationBatch(tuple(observations))
