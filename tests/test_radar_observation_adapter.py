"""Radar normalization preserves evidence and provenance without a runtime."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement


CONTEXT = dict(sensor_id="radar-front", reference_frame_id="radar-front:measurement")


def detection():
    return RadarDetection(
        "session-a", "scan-7/return-2", MeasurementTime(0.240123, "device:boot-a"),
        RadarPolarDetectionMeasurement(42.5, -0.125, 0.25, -3.75), "scan-7/2",
    )


def test_single_detection_preserves_exact_evidence_context_and_ids():
    source = detection()
    batch = radar_detections_to_observations((source,), **CONTEXT)
    assert isinstance(batch, ObservationBatch)
    assert isinstance(batch.observations, tuple)
    observation, = batch.observations
    assert observation.sensor_id == "radar-front"
    assert observation.sensor_id != source.source_session_id
    assert observation.measurement_time is source.measurement_time
    assert observation.measurement_time == MeasurementTime(0.240123, "device:boot-a")
    assert observation.measurement_time.clock_domain == "device:boot-a"
    assert observation.reference_frame == ReferenceFrame("radar-front:measurement")
    assert observation.measurement is source.measurement
    assert observation.measurement == RadarPolarDetectionMeasurement(42.5, -0.125, 0.25, -3.75)
    assert observation.observation_id == (
        '["radar-detection",1,"radar-front","session-a","scan-7/return-2"]'
    )
    assert observation.source_local_id == '["session-a","scan-7/2"]'


def test_absent_local_detection_id_remains_none():
    source = replace(detection(), local_detection_id=None)
    observation, = radar_detections_to_observations((source,), **CONTEXT).observations
    assert observation.source_local_id is None


def test_replay_is_deterministic_and_keeps_no_cross_call_history():
    source = (detection(),)
    first = radar_detections_to_observations(source, **CONTEXT)
    second = radar_detections_to_observations(source, **CONTEXT)
    assert first == second
    assert first.observations[0].observation_id == second.observations[0].observation_id


def test_reordering_preserves_ids_and_follows_input_order():
    first = detection()
    second = replace(first, evidence_id="event-b", measurement=RadarPolarDetectionMeasurement(7.0, 0.5))
    third = replace(first, evidence_id="event-c", measurement=RadarPolarDetectionMeasurement(9.0, 0.75))
    forward = radar_detections_to_observations((first, second, third), **CONTEXT).observations
    reordered = radar_detections_to_observations((third, first, second), **CONTEXT).observations
    assert [item.measurement.range_m for item in forward] == [42.5, 7.0, 9.0]
    assert reordered == (forward[2], forward[0], forward[1])
    assert [item.observation_id for item in reordered] == [
        forward[index].observation_id for index in (2, 0, 1)
    ]


def test_identical_values_with_distinct_event_ids_remain_separate_evidence():
    first = detection()
    second = replace(first, evidence_id="different-event")
    observations = radar_detections_to_observations((first, second), **CONTEXT).observations
    assert len(observations) == 2
    assert observations[0].measurement is observations[1].measurement
    assert observations[0].measurement_time is observations[1].measurement_time
    assert observations[0].observation_id != observations[1].observation_id


def test_same_evidence_and_local_keys_in_different_sessions_are_allowed_and_scoped():
    first = detection()
    second = replace(first, source_session_id="session-b")
    observations = radar_detections_to_observations((first, second), **CONTEXT).observations
    assert len(observations) == 2
    assert observations[0].observation_id != observations[1].observation_id
    assert observations[0].source_local_id == '["session-a","scan-7/2"]'
    assert observations[1].source_local_id == '["session-b","scan-7/2"]'


def test_different_sensors_produce_distinct_evidence_ids():
    source = (detection(),)
    first, = radar_detections_to_observations(source, **CONTEXT).observations
    second, = radar_detections_to_observations(
        source, **dict(CONTEXT, sensor_id="radar-rear"),
    ).observations
    assert first.observation_id != second.observation_id
    assert json.loads(second.observation_id)[2] == "radar-rear"


def test_json_identity_encoding_is_unambiguous_and_preserves_identifier_content():
    ids = []
    local_ids = []
    for session, key in (("a/b", "c"), ("a", "b/c"), (' a\"/雪 ', ' b\\c,[] ')):
        source = replace(
            detection(), source_session_id=session, evidence_id=key, local_detection_id=key,
        )
        observation, = radar_detections_to_observations(
            (source,), sensor_id=' radar/\"front\" ', reference_frame_id=" frame/local ",
        ).observations
        assert json.loads(observation.observation_id) == [
            "radar-detection", 1, ' radar/\"front\" ', session, key,
        ]
        assert json.loads(observation.source_local_id) == [session, key]
        assert observation.sensor_id == ' radar/\"front\" '
        assert observation.reference_frame.frame_id == " frame/local "
        ids.append(observation.observation_id)
        local_ids.append(observation.source_local_id)
    assert len(set(ids)) == len(set(local_ids)) == 3


@pytest.mark.parametrize("changed_values", [False, True])
def test_duplicate_evidence_keys_are_rejected_regardless_of_values(changed_values):
    first = detection()
    second = replace(first, measurement=RadarPolarDetectionMeasurement(1.0, 0.0)) if changed_values else first
    with pytest.raises(ValueError, match="Duplicate radar evidence key"):
        radar_detections_to_observations((first, second), **CONTEXT)


def test_empty_input_has_no_synthetic_scan_evidence():
    assert radar_detections_to_observations((), **CONTEXT) == ObservationBatch(())


@pytest.mark.parametrize("field", ["sensor_id", "reference_frame_id"])
@pytest.mark.parametrize("value", ["", " \t\n"])
@pytest.mark.parametrize("empty", [False, True])
def test_blank_context_is_rejected_even_for_empty_input(field, value, empty):
    with pytest.raises(ValueError):
        radar_detections_to_observations(
            () if empty else (detection(),), **dict(CONTEXT, **{field: value}),
        )


@pytest.mark.parametrize("empty", [False, True])
def test_mutable_input_collection_is_rejected(empty):
    with pytest.raises(TypeError, match="tuple"):
        radar_detections_to_observations([] if empty else [detection()], **CONTEXT)


def test_independent_clock_domains_and_input_order_are_preserved_without_alignment():
    first = detection()
    second = replace(
        first, evidence_id="other-event",
        measurement_time=MeasurementTime(-123.75, "recording:origin-b"),
    )
    observations = radar_detections_to_observations((first, second), **CONTEXT).observations
    for source, observation in zip((first, second), observations, strict=True):
        assert observation.measurement_time is source.measurement_time
        assert observation.measurement_time.clock_domain == source.measurement_time.clock_domain
    assert [item.measurement_time.seconds for item in observations] == [0.240123, -123.75]


def test_frame_context_changes_only_the_frame_reference():
    source = (detection(),)
    first, = radar_detections_to_observations(source, **CONTEXT).observations
    second, = radar_detections_to_observations(
        source, **dict(CONTEXT, reference_frame_id="explicit:other-measurement-frame"),
    ).observations
    assert second.reference_frame == ReferenceFrame("explicit:other-measurement-frame")
    assert second.measurement is first.measurement
    assert second.measurement_time is first.measurement_time


@pytest.mark.parametrize("elevation,velocity", [
    (None, None), (None, -3.5), (0.25, None), (0.25, 3.5), (0.0, 0.0),
])
def test_optional_dimensions_survive_conversion(elevation, velocity):
    measurement = RadarPolarDetectionMeasurement(42.5, 0.125, elevation, velocity)
    source = replace(detection(), measurement=measurement)
    observation, = radar_detections_to_observations((source,), **CONTEXT).observations
    assert observation.measurement is measurement
    assert observation.measurement.elevation_rad == elevation
    assert observation.measurement.radial_velocity_mps == velocity


def test_normalized_values_remain_frozen():
    batch = radar_detections_to_observations((detection(),), **CONTEXT)
    observation, = batch.observations
    for value, field, replacement in (
        (batch, "observations", ()),
        (observation, "sensor_id", "other"),
        (observation.measurement, "range_m", 0.0),
        (observation.measurement_time, "seconds", 0.0),
        (observation.reference_frame, "frame_id", "other"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)


def test_import_and_conversion_need_no_heavy_dependencies_legacy_types_or_clocks():
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins
import sys
import time
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
forbidden = {"numpy", "cv2", "ultralytics", "torch", "uuid", "random", "datetime"}
legacy = {"aegis.core.messages", "aegis.core.detections", "aegis.fusion.fusion_engine"}
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden or name in legacy:
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
def no_clock(*args, **kwargs):
    raise AssertionError("Clock read")
time.time = time.monotonic = time.perf_counter = no_clock
time.time_ns = time.monotonic_ns = time.perf_counter_ns = no_clock
from aegis.fusion.contracts import MeasurementTime
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement
from aegis.radar.adapter import radar_detections_to_observations
measurement = RadarPolarDetectionMeasurement(1.25, -0.5)
stamp = MeasurementTime(-1.5, "device:boot-a")
detection = RadarDetection("session", "event", stamp, measurement)
batch = radar_detections_to_observations(
    (detection,), sensor_id="radar", reference_frame_id="radar:measurement",
)
observation, = batch.observations
assert observation.measurement is measurement
assert observation.measurement_time is stamp
assert not forbidden.intersection(sys.modules)
assert not legacy.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
