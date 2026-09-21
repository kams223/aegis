"""Contract tests that need no image-processing or inference dependencies."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.core.frames import Frame, FrameMetadata
from aegis.perception.contracts import DetectionBatch, Detector, ObjectDetection
from aegis.tracking.contracts import (
    TrackedObject,
    TrackedObjectBatch,
    TrackingFrameOutput,
    TrackingSession,
)


@pytest.fixture
def metadata():
    return FrameMetadata(
        stream_id="video-a", frame_number=7, timestamp_seconds=0.24,
        width=640, height=480,
    )


@pytest.fixture
def detection():
    return ObjectDetection(
        class_id=2, label="car", confidence=0.876543,
        x1=10.126, y1=20.234, x2=300.134, y2=460.242,
    )


def test_frame_preserves_metadata_and_image_reference(metadata):
    # An opaque image sentinel checks ownership without requiring NumPy in CI.
    image = object()
    frame = Frame(image=image, metadata=metadata)

    assert frame.image is image
    assert frame.metadata is metadata
    assert (
        metadata.stream_id, metadata.frame_number, metadata.timestamp_seconds,
        metadata.width, metadata.height,
    ) == ("video-a", 7, 0.24, 640, 480)


def test_detection_preserves_unrounded_pixel_coordinates(detection):
    assert (detection.class_id, detection.label, detection.confidence) == (
        2, "car", 0.876543,
    )
    assert (detection.x1, detection.y1, detection.x2, detection.y2) == (
        10.126, 20.234, 300.134, 460.242,
    )


@pytest.mark.parametrize("empty", [False, True])
def test_detection_batch_preserves_metadata_and_tuple(metadata, detection, empty):
    detections = () if empty else (detection,)
    batch = DetectionBatch(frame=metadata, detections=detections)

    assert batch.frame is metadata
    assert isinstance(batch.detections, tuple)
    assert batch.detections == detections
    with pytest.raises(FrozenInstanceError):
        batch.detections = ()


@pytest.mark.parametrize("empty", [False, True])
def test_tracked_batch_composes_ids_and_detections(metadata, detection, empty):
    tracked = TrackedObject(track_id=9, detection=detection)
    objects = () if empty else (tracked,)
    batch = TrackedObjectBatch(frame=metadata, objects=objects)

    assert tracked.track_id == 9
    assert tracked.detection is detection
    assert batch.frame is metadata
    assert isinstance(batch.objects, tuple)
    assert batch.objects == objects
    with pytest.raises(FrozenInstanceError):
        batch.objects = ()
    with pytest.raises(FrozenInstanceError):
        tracked.detection.confidence = 0.0


def test_tracking_output_keeps_box_count_separate_from_assigned_tracks(metadata):
    batch = TrackedObjectBatch(frame=metadata, objects=())
    annotated_image = object()
    output = TrackingFrameOutput(
        tracks=batch, returned_box_count=3, annotated_image=annotated_image,
    )

    assert output.tracks is batch
    assert output.returned_box_count == 3
    assert output.annotated_image is annotated_image
    assert len(output.tracks.objects) == 0


def test_interfaces_accept_lightweight_structural_implementations(metadata):
    class FakeDetector:
        def detect(self, frame: Frame) -> DetectionBatch:
            return DetectionBatch(frame=frame.metadata, detections=())

    class FakeSession:
        def __init__(self):
            self.closed = False

        def track(self, frame: Frame) -> TrackingFrameOutput:
            return TrackingFrameOutput(
                tracks=TrackedObjectBatch(frame=frame.metadata, objects=()),
                returned_box_count=0,
                annotated_image=frame.image,
            )

        def close(self) -> None:
            self.closed = True

    # No inheritance, registration, models, or factories are required.
    detector: Detector = FakeDetector()
    fake_session = FakeSession()
    session: TrackingSession = fake_session
    frame = Frame(image=object(), metadata=metadata)

    assert detector.detect(frame).frame is metadata
    assert session.track(frame).tracks.frame is metadata
    session.close()
    assert fake_session.closed is True


def test_contract_imports_do_not_attempt_optional_dependencies():
    # A fresh interpreter prevents cached modules or other tests hiding imports.
    source_path = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins
import sys

sys.path.insert(0, sys.argv[1])
forbidden = {"numpy", "cv2", "torch", "ultralytics"}
attempts = []
original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        attempts.append(name)
        raise ImportError("Optional dependency requested: " + name)
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import aegis.core.frames
import aegis.perception.contracts
import aegis.tracking.contracts
assert not attempts, attempts
assert not forbidden.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
