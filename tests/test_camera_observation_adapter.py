"""Camera boundary conversion using only Aegis values."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.core.frames import FrameMetadata
from aegis.fusion.camera_adapter import ImageTrackMeasurement, tracked_objects_to_observations
from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch


CONTEXT = dict(sensor_id="camera-front", clock_domain="video:opening-a",
               reference_frame_id="camera-front:image")


def batch():
    return TrackedObjectBatch(
        FrameMetadata("opening-a", 7, 0.240123, 1920, 1080),
        (TrackedObject(9, ObjectDetection(
            2, "car", 0.876543, 10.126, 20.234, 300.134, 460.242,
        )),),
    )


def test_single_track_preserves_all_evidence_context_and_deterministic_ids():
    source = batch()
    output = tracked_objects_to_observations(source, **CONTEXT)
    assert output == tracked_objects_to_observations(source, **CONTEXT)
    assert isinstance(output, ObservationBatch)
    assert isinstance(output.observations, tuple)
    observation, = output.observations
    assert observation.sensor_id == "camera-front"
    assert observation.sensor_id != source.frame.stream_id
    assert observation.measurement_time == MeasurementTime(0.240123, "video:opening-a")
    assert observation.reference_frame == ReferenceFrame("camera-front:image")
    assert observation.source_local_id == '["opening-a",9]'
    assert observation.observation_id == '["camera-track","camera-front","opening-a",7,9,0]'
    assert observation.measurement == ImageTrackMeasurement(
        2, "car", 0.876543, 10.126, 20.234, 300.134, 460.242, 1920, 1080,
    )
    with pytest.raises(FrozenInstanceError):
        observation.measurement.x1 = 0.0


def test_multiple_rows_preserve_order_and_duplicate_local_ids_remain_distinct():
    source = batch()
    first = source.objects[0]
    second = TrackedObject(3, replace(first.detection, label="person", class_id=0))
    source = replace(source, objects=(first, second, first))
    observations = tracked_objects_to_observations(source, **CONTEXT).observations
    assert [item.measurement.label for item in observations] == ["car", "person", "car"]
    assert [json.loads(item.source_local_id) for item in observations] == [
        ["opening-a", 9], ["opening-a", 3], ["opening-a", 9],
    ]
    assert len({item.observation_id for item in observations}) == 3


def test_same_track_in_different_openings_has_separate_provenance():
    source = batch()
    other = replace(source, frame=replace(source.frame, stream_id="opening-b"))
    first = tracked_objects_to_observations(source, **CONTEXT).observations[0]
    second = tracked_objects_to_observations(other, **CONTEXT).observations[0]
    assert first.source_local_id != second.source_local_id
    assert first.observation_id != second.observation_id
    assert first.measurement == second.measurement


@pytest.mark.parametrize("change", ["sensor", "frame"])
def test_observation_ids_distinguish_sensor_and_frame(change):
    source = batch()
    context = dict(CONTEXT)
    first = tracked_objects_to_observations(source, **context).observations[0]
    if change == "sensor":
        context["sensor_id"] = "camera-rear"
    else:
        source = replace(source, frame=replace(source.frame, frame_number=10))
    second = tracked_objects_to_observations(source, **context).observations[0]
    assert first.observation_id != second.observation_id
    assert first.source_local_id == second.source_local_id


def test_identity_encoding_handles_delimiters_without_collisions():
    source = batch()
    ids = []
    for sensor, stream in (("a/b", "c"), ("a", "b/c"), ('a"', "b%/c")):
        changed = replace(source, frame=replace(source.frame, stream_id=stream))
        context = dict(CONTEXT, sensor_id=sensor)
        observation = tracked_objects_to_observations(changed, **context).observations[0]
        assert json.loads(observation.source_local_id) == [stream, 9]
        assert json.loads(observation.observation_id)[1:3] == [sensor, stream]
        ids.append(observation.observation_id)
    assert len(set(ids)) == 3


def test_clock_and_reference_context_are_preserved_without_conversion():
    source = batch()
    first = tracked_objects_to_observations(source, **CONTEXT).observations[0]
    second = tracked_objects_to_observations(
        source, **dict(CONTEXT, clock_domain="another-video:origin", reference_frame_id="other:image"),
    ).observations[0]
    assert first.measurement_time.seconds == second.measurement_time.seconds == 0.240123
    assert first.measurement_time != second.measurement_time
    assert second.measurement_time.clock_domain == "another-video:origin"
    assert second.reference_frame.frame_id == "other:image"
    assert first.measurement == second.measurement


def test_empty_input_produces_no_synthetic_observations():
    assert tracked_objects_to_observations(replace(batch(), objects=()), **CONTEXT) == ObservationBatch(())


@pytest.mark.parametrize("field", list(CONTEXT))
def test_context_arguments_are_required(field):
    context = dict(CONTEXT)
    del context[field]
    with pytest.raises(TypeError, match=field):
        tracked_objects_to_observations(batch(), **context)


@pytest.mark.parametrize("field", list(CONTEXT))
@pytest.mark.parametrize("empty", [False, True])
def test_blank_context_is_rejected_even_for_empty_batches(field, empty):
    source = replace(batch(), objects=()) if empty else batch()
    with pytest.raises(ValueError):
        tracked_objects_to_observations(source, **dict(CONTEXT, **{field: " \t"}))


def test_adapter_import_and_conversion_need_no_heavy_dependencies_or_clock():
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins
import sys
import time
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
forbidden = {"cv2", "numpy", "ultralytics", "torch"}
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from aegis.fusion.camera_adapter import tracked_objects_to_observations
from aegis.core.frames import FrameMetadata
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch
def no_clock():
    raise AssertionError("Clock read")
time.time = time.monotonic = time.perf_counter = no_clock
batch = TrackedObjectBatch(FrameMetadata("stream", 1, 0.0, 10, 20),
    (TrackedObject(7, ObjectDetection(0, "person", 0.5, 1.25, 2.5, 3.75, 4.5)),))
output = tracked_objects_to_observations(batch, sensor_id="sensor", clock_domain="video:stream", reference_frame_id="sensor:image")
assert len(output.observations) == 1
assert not forbidden.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
