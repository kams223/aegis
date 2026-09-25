"""Normalized evidence contracts without sensor backends or fusion algorithms."""

from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import (
    MeasurementTime,
    ObservationBatch,
    ReferenceFrame,
    SensorObservation,
)


@dataclass(frozen=True)
class ImagePoint:
    x_pixels: float
    y_pixels: float


@dataclass(frozen=True)
class RangeBearing:
    range_metres: float
    bearing_radians: float


def image_observation() -> SensorObservation[ImagePoint]:
    return SensorObservation(
        observation_id="observation-a",
        sensor_id="camera-a",
        measurement_time=MeasurementTime(-0.25, "video:opening-a"),
        reference_frame=ReferenceFrame("camera-a:image"),
        measurement=ImagePoint(12.125, 30.75),
    )


def test_observation_preserves_typed_evidence_and_provenance():
    observation = image_observation()
    assert observation.observation_id == "observation-a"
    assert observation.sensor_id == "camera-a"
    assert observation.source_local_id is None
    assert observation.measurement.x_pixels == 12.125
    assert observation.measurement.y_pixels == 30.75
    assert observation.reference_frame.frame_id == "camera-a:image"
    assert observation.measurement_time == MeasurementTime(-0.25, "video:opening-a")


def test_different_measurement_shapes_frames_and_clocks_coexist_without_conversion():
    image = image_observation()
    measurement = RangeBearing(42.5, 0.125)
    time = MeasurementTime(1700000000.125, "utc:unix-epoch")
    frame = ReferenceFrame("radar-b:local")
    radar: SensorObservation[RangeBearing] = SensorObservation(
        "observation-b", "radar-b", time, frame, measurement,
    )
    batch: ObservationBatch[ImagePoint | RangeBearing] = ObservationBatch((radar, image))

    assert batch.observations == (radar, image)
    assert radar.measurement is measurement
    assert radar.measurement.range_metres == 42.5
    assert radar.measurement.bearing_radians == 0.125
    assert radar.reference_frame is frame
    assert radar.measurement_time is time
    assert image.reference_frame != radar.reference_frame
    assert image.measurement_time.clock_domain != radar.measurement_time.clock_domain


def test_equal_local_ids_across_sensors_do_not_merge_observations():
    first = replace(image_observation(), source_local_id="session-1/7")
    second = replace(
        first, observation_id="observation-b", sensor_id="camera-b",
        reference_frame=ReferenceFrame("camera-b:image"),
    )
    batch = ObservationBatch((first, second))

    assert first.source_local_id == second.source_local_id == "session-1/7"
    assert first.sensor_id != second.sensor_id
    assert first.observation_id != second.observation_id
    assert len(batch.observations) == 2
    assert batch.observations[0] is first
    assert batch.observations[1] is second


def test_time_domain_is_preserved_even_for_equal_numeric_timestamps():
    first = MeasurementTime(0.0, "video:opening-a")
    second = MeasurementTime(0.0, "device:radar-b:boot-2")
    assert first.seconds == second.seconds == 0.0
    assert first != second


def test_envelope_metadata_payload_and_batch_are_frozen_values():
    observation = image_observation()
    batch = ObservationBatch((observation,))
    for value, field, replacement in (
        (observation, "sensor_id", "other"),
        (observation.measurement_time, "seconds", 99.0),
        (observation.reference_frame, "frame_id", "other"),
        (observation.measurement, "x_pixels", 0.0),
        (batch, "observations", ()),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
    assert isinstance(batch.observations, tuple)


def test_empty_batch_is_valid_and_mutable_collection_is_rejected():
    assert ObservationBatch[ImagePoint](()).observations == ()
    with pytest.raises(TypeError, match="tuple"):
        ObservationBatch([])  # type: ignore[arg-type]


@pytest.mark.parametrize("identifier", ["", " \t"])
@pytest.mark.parametrize("field", ["observation_id", "sensor_id", "source_local_id"])
def test_observation_rejects_blank_identifiers(field, identifier):
    with pytest.raises(ValueError, match=field):
        replace(image_observation(), **{field: identifier})


@pytest.mark.parametrize("identifier", ["", " \t"])
def test_clock_and_frame_identifiers_cannot_be_blank(identifier):
    with pytest.raises(ValueError, match="clock_domain"):
        MeasurementTime(0.0, identifier)
    with pytest.raises(ValueError, match="frame_id"):
        ReferenceFrame(identifier)


def test_contract_imports_are_lightweight_and_construction_reads_no_clock():
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins
import sys
import time
sys.path.insert(0, sys.argv[1])
forbidden = {"cv2", "numpy", "ultralytics", "torch", "sqlite3", "sqlalchemy", "fastapi"}
attempts = []
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        attempts.append(name)
        raise ImportError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
def no_clock():
    raise AssertionError("Contract must not generate measurement time")
time.time = time.monotonic = time.perf_counter = no_clock
observation = SensorObservation("obs", "sensor", MeasurementTime(-1.5, "clock"), ReferenceFrame("frame"), 2.5)
assert observation.measurement_time.seconds == -1.5
assert not attempts, attempts
assert not forbidden.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
