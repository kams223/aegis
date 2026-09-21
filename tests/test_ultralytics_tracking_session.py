"""Adapter tests using only lightweight model, result, and tensor fakes."""

from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from aegis.core.frames import Frame, FrameMetadata
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import TrackedObject, TrackingSession
from aegis.tracking.ultralytics_session import UltralyticsTrackingSession


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class FakeBoxes:
    def __init__(self, empty=False, assigned=True):
        self.xyxy = FakeTensor([] if empty else [
            [10.126, 20.234, 30.134, 60.242], [0.125, 2.25, 6.5, 10.75],
        ])
        self.conf = FakeTensor([] if empty else [0.876543, 0.543219])
        self.cls = FakeTensor([] if empty else [2.0, 0.0])
        self.id = FakeTensor([] if empty else [9.0, 3.0]) if assigned else None

    def __len__(self):
        return len(self.xyxy.values)


def result(kind="tracked"):
    boxes = None if kind == "none" else FakeBoxes(
        empty=kind in ("empty", "empty_untracked"),
        assigned=kind not in ("untracked", "empty_untracked"),
    )
    return SimpleNamespace(
        boxes=boxes, names={2: "car", 0: "person"},
        plot=Mock(return_value=object()),
    )


def frame(number=1, stream="video-a"):
    return Frame(object(), FrameMetadata(stream, number, (number - 1) / 25, 640, 480))


def make_session(output=None, **settings):
    model = Mock(spec=["track", "predict"])
    model.track.return_value = [result() if output is None else output]
    factory = Mock(return_value=model)
    session = UltralyticsTrackingSession(model_factory=factory, **settings)
    return session, model, factory


@pytest.mark.parametrize("settings, expected", [
    ({}, ("yolo11n.pt", "bytetrack.yaml", 0.35, 640, "cpu")),
    ({"model_path": "custom.pt", "tracker_config": "custom.yaml",
      "confidence_threshold": 0.62, "image_size": 320, "device": "cuda:1"},
     ("custom.pt", "custom.yaml", 0.62, 320, "cuda:1")),
    ({"confidence_threshold": 0.0}, ("yolo11n.pt", "bytetrack.yaml", 0.0, 640, "cpu")),
])
def test_constructs_once_and_tracks_once_per_frame(settings, expected):
    session, model, factory = make_session(**settings)
    frames = [frame(7), frame(8), frame(12)]
    for item in frames:
        session.track(item)
    model_path, tracker, confidence, size, device = expected
    factory.assert_called_once_with(model_path)
    assert model.mock_calls == [call.track(
        source=item.image, persist=True, tracker=tracker,
        conf=confidence, imgsz=size, device=device, verbose=False,
    ) for item in frames]
    model.predict.assert_not_called()
    session.close()


@pytest.mark.parametrize("settings, message", [
    ({"confidence_threshold": -0.1}, "confidence_threshold"),
    ({"confidence_threshold": 1.1}, "confidence_threshold"),
    ({"confidence_threshold": float("nan")}, "confidence_threshold"),
    ({"image_size": 0}, "image_size"),
    ({"image_size": -1}, "image_size"),
    ({"device": "  "}, "device"),
])
def test_invalid_configuration_does_not_construct_model(settings, message):
    factory = Mock()
    with pytest.raises(ValueError, match=message):
        UltralyticsTrackingSession(model_factory=factory, **settings)
    factory.assert_not_called()


def test_conversion_preserves_values_order_metadata_and_annotation():
    vendor = result()
    session, _, _ = make_session(vendor)
    item = frame()
    output = session.track(item)

    assert output.tracks.frame is item.metadata
    assert output.tracks.objects == (
        TrackedObject(9, ObjectDetection(2, "car", 0.876543, 10.126, 20.234, 30.134, 60.242)),
        TrackedObject(3, ObjectDetection(0, "person", 0.543219, 0.125, 2.25, 6.5, 10.75)),
    )
    assert isinstance(output.tracks.objects, tuple)
    assert output.returned_box_count == 2
    vendor.plot.assert_called_once_with()
    assert output.annotated_image is vendor.plot.return_value
    # A returned value must not retain tensor-backed coordinate storage.
    vendor.boxes.xyxy.values[0][0] = 999
    assert output.tracks.objects[0].detection.x1 == 10.126
    session.close()


@pytest.mark.parametrize("kind, count", [
    ("none", 0), ("empty", 0), ("empty_untracked", 0), ("untracked", 2),
])
def test_empty_and_untracked_results_still_plot(kind, count):
    vendor = result(kind)
    session, _, _ = make_session(vendor)
    item = frame()
    output = session.track(item)
    assert output.tracks.objects == ()
    assert output.tracks.frame is item.metadata
    assert output.returned_box_count == count
    assert output.annotated_image is vendor.plot.return_value
    vendor.plot.assert_called_once_with()
    session.close()


def test_multiple_results_use_only_first():
    first, second = result(), result()
    session, model, _ = make_session()
    model.track.return_value = [first, second]
    assert session.track(frame()).annotated_image is first.plot.return_value
    first.plot.assert_called_once_with()
    second.plot.assert_not_called()
    session.close()


@pytest.mark.parametrize("number, stream", [(7, "video-a"), (6, "video-a"), (8, "video-b")])
def test_sequence_rejection_precedes_inference_and_does_not_poison(number, stream):
    session, model, _ = make_session()
    session.track(frame(7))
    with pytest.raises(ValueError):
        session.track(frame(number, stream))
    assert model.track.call_count == 1
    session.track(frame(9))
    assert model.track.call_count == 2
    session.close()


def test_close_is_idempotent_and_tracking_after_close_fails():
    concrete, model, factory = make_session()
    session: TrackingSession = concrete
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.track(frame())
    model.track.assert_not_called()
    factory.assert_called_once()


@pytest.mark.parametrize("failure", [
    "backend", "selection", "empty_results", "labels", "lengths",
    "coordinates", "fractional_id", "nonfinite_id", "plot", "interrupt",
])
def test_failure_after_inference_begins_poison_session(failure):
    vendor = result()
    session, model, factory = make_session(vendor)
    error_type = RuntimeError
    message = "failure"
    if failure == "backend":
        model.track.side_effect = RuntimeError("backend failure")
    elif failure == "selection":
        model.track.return_value = Mock()
        model.track.return_value.__getitem__ = Mock(side_effect=RuntimeError("selection failure"))
    elif failure == "empty_results":
        model.track.return_value = []
        message = "no results"
    elif failure == "labels":
        vendor.names = {}
        error_type, message = ValueError, "label"
    elif failure == "lengths":
        vendor.boxes.conf.values.pop()
        error_type, message = ValueError, "length"
    elif failure == "coordinates":
        vendor.boxes.xyxy.values[0] = [1, 2, 3]
        error_type, message = ValueError, "tracking"
    elif failure == "fractional_id":
        vendor.boxes.id.values[0] = 9.5
        error_type, message = ValueError, "ID"
    elif failure == "nonfinite_id":
        vendor.boxes.cls.values[0] = float("inf")
        error_type, message = ValueError, "ID"
    elif failure == "plot":
        vendor.plot.side_effect = RuntimeError("plot failure")
    elif failure == "interrupt":
        model.track.side_effect = KeyboardInterrupt("backend failure")
        error_type = KeyboardInterrupt

    with pytest.raises(error_type, match=message):
        session.track(frame(7))
    for number in (7, 8):
        with pytest.raises(RuntimeError, match="failed"):
            session.track(frame(number))
    assert model.track.call_count == 1
    factory.assert_called_once()
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.track(frame(9))


def test_sequential_sessions_have_distinct_models_and_histories():
    class StatefulModel:
        def __init__(self):
            self.images = []

        def track(self, **kwargs):
            self.images.append(kwargs["source"])
            return [result()]

    factory = Mock(side_effect=lambda path: StatefulModel())
    created = []

    def create(path):
        model = factory(path)
        created.append(model)
        return model

    a = UltralyticsTrackingSession(model_factory=create)
    first = frame(1, "a")
    a.track(first)
    a.track(frame(2, "a"))
    a.close()
    first_model = created[0]
    b = UltralyticsTrackingSession(model_factory=create)
    assert created[1] is not first_model
    assert created[1].images == []
    second = frame(1, "b")
    b.track(second)
    assert created[1].images == [second.image]
    assert len(first_model.images) == 2
    assert factory.call_args_list == [call("yolo11n.pt"), call("yolo11n.pt")]
    b.close()


def test_default_factory_lazily_constructs_yolo(monkeypatch):
    vendor = ModuleType("ultralytics")
    vendor.YOLO = Mock()
    monkeypatch.setitem(sys.modules, "ultralytics", vendor)
    session = UltralyticsTrackingSession(model_path="local.pt")
    vendor.YOLO.assert_called_once_with("local.pt")
    session.close()


def test_adapter_import_and_injection_need_no_optional_dependencies():
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins
import sys
sys.path.insert(0, sys.argv[1])
forbidden = {"ultralytics", "torch", "cv2", "numpy"}
attempts = []
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        attempts.append(name)
        raise ImportError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from aegis.tracking.ultralytics_session import UltralyticsTrackingSession
session = UltralyticsTrackingSession(model_factory=lambda path: object())
session.close()
assert not attempts, attempts
assert not forbidden.intersection(sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
