"""Deterministic acquisition evidence from an immutable script."""

from collections.abc import Iterator
import json
from math import isfinite

from aegis.fusion.contracts import MeasurementTime
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement, RadarScan


def iter_scripted_radar_scans(
    script: tuple[
        tuple[MeasurementTime, tuple[RadarPolarDetectionMeasurement, ...]],
        ...,
    ],
    *,
    source_session_id: str,
) -> Iterator[RadarScan]:
    """Yield every scripted acquisition in order, including empty acquisitions.

    Validation is lazy: session and outer tuple are checked on first advancement,
    even for an empty script; entries are checked when reached. Invalid entries
    raise without yielding a partial scan. Earlier yielded scans remain valid.

    Each entry supplies one event time shared exactly by its scan and detections.
    Measurements already follow the canonical radar convention. No physical
    objects, motion, or acquisition physics are modeled. Scan IDs are zero-based
    script indices; evidence IDs encode the scan ID and measurement ordinal.
    Replaying the same script/session reproduces the same evidence. A new source
    sequence or changed script reusing IDs requires a new caller session scope.
    Exhaustion uses StopIteration; no resources or lifecycle are owned here.

    The caller owns normalization context and synchronous delivery, for example::

        for scan in iter_scripted_radar_scans(script, source_session_id=session):
            batch = radar_detections_to_observations(
                scan.detections, sensor_id=sensor, reference_frame_id=frame,
            )
            if batch.observations:
                consumer(batch)

    An empty ObservationBatch carries no scan_id, scan_time, source-session scan
    completion, or cadence. The caller can inspect the scan before normalization;
    the example deliberately delivers only nonempty normalized evidence. Consumer
    exceptions propagate naturally and stop that composition without retries.
    """
    if not source_session_id.strip():
        raise ValueError("source_session_id cannot be empty or whitespace")
    if not isinstance(script, tuple):
        raise TypeError("script must be a tuple")

    for index, entry in enumerate(script):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError("Each script entry must be a tuple of exactly two elements")
        scan_time, measurements = entry
        if not isinstance(scan_time, MeasurementTime):
            raise TypeError("Script scan_time must be MeasurementTime")
        if not isfinite(scan_time.seconds):
            raise ValueError("scan_time.seconds must be finite")
        if not isinstance(measurements, tuple):
            raise TypeError("Script measurements must be a tuple")

        scan_id = str(index)
        detections = []
        for ordinal, measurement in enumerate(measurements):
            if not isinstance(measurement, RadarPolarDetectionMeasurement):
                raise TypeError("Script measurements must contain RadarPolarDetectionMeasurement values")
            detections.append(RadarDetection(
                source_session_id=source_session_id,
                evidence_id=json.dumps(
                    ["scripted-radar-detection", 1, scan_id, ordinal],
                    separators=(",", ":"),
                ),
                measurement_time=scan_time,
                measurement=measurement,
                local_detection_id=None,
            ))
        yield RadarScan(source_session_id, scan_id, scan_time, tuple(detections))
