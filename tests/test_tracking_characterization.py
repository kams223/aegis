"""Freeze current vendor-boundary behavior without inference dependencies."""

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from aegis.core.pipeline_config import PipelineConfig
from aegis.world_model.track_logger import TrackLogger


CSV_FIELDS = [
    "frame_number", "timestamp_seconds", "track_id", "label", "confidence",
    "x1", "y1", "x2", "y2", "center_x", "center_y", "width", "height",
]


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class FakeBoxes:
    def __init__(self, coordinates, confidences, classes, ids):
        self.xyxy = FakeTensor(coordinates)
        self.conf = FakeTensor(confidences)
        self.cls = FakeTensor(classes)
        self.id = None if ids is None else FakeTensor(ids)
        self.count = len(coordinates)

    def __len__(self):
        return self.count


def make_result(kind):
    if kind == "tracked":
        boxes = FakeBoxes(
            [[10.126, 20.234, 30.134, 60.242], [0, 2, 6, 10]],
            [0.876543, 0.5], [1.0, 0.0], [9.0, 3.0],
        )
    elif kind == "untracked":
        boxes = FakeBoxes([[1, 2, 3, 4]], [0.7], [0.0], None)
    elif kind == "empty":
        boxes = FakeBoxes([], [], [], [])
    elif kind == "no_boxes":
        boxes = None
    else:
        raise ValueError(kind)

    return SimpleNamespace(
        boxes=boxes,
        names={0: "person", 1: "car"},
        plot=Mock(return_value=object()),
    )


@pytest.fixture
def fake_runtime(monkeypatch):
    """Load real source against scoped fakes, restoring module entries after use.

    Do not import optional packages or leave production modules cached with fake
    dependencies: CI intentionally installs only requirements-dev.txt.
    """
    numpy = ModuleType("numpy")
    numpy.ndarray = object
    ultralytics = ModuleType("ultralytics")
    ultralytics.YOLO = Mock()
    cv2 = ModuleType("cv2")
    cv2.CAP_PROP_FRAME_WIDTH = 1
    cv2.CAP_PROP_FRAME_HEIGHT = 2
    cv2.CAP_PROP_FPS = 3
    cv2.FONT_HERSHEY_SIMPLEX = 0
    cv2.LINE_AA = 16
    cv2.error = type("FakeOpenCVError", (Exception,), {})
    cv2.VideoCapture = Mock()
    cv2.VideoWriter = Mock()
    cv2.VideoWriter_fourcc = Mock(return_value=123)
    cv2.putText = Mock()

    for module in (numpy, ultralytics, cv2):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    def load_module(name):
        path = Path(__file__).resolve().parents[1] / "src"
        path = path.joinpath(*name.split(".")).with_suffix(".py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    load_module("aegis.sensors.frame_source")
    load_module("aegis.sensors.video_file")
    detector = load_module("aegis.perception.object_detector")
    processing = load_module("aegis.perception.process_video")
    return SimpleNamespace(
        cv2=cv2, yolo=ultralytics.YOLO,
        detector=detector, processing=processing,
    )


@pytest.mark.parametrize(
    "settings, expected",
    [
        ({}, ("yolo11n.pt", "bytetrack.yaml", 0.35, 640, "cpu")),
        (
            dict(model_path="custom.pt", tracker_config="custom-tracker.yaml",
                 confidence_threshold=0.62, image_size=320, device="cuda:1"),
            ("custom.pt", "custom-tracker.yaml", 0.62, 320, "cuda:1"),
        ),
    ],
)
def test_track_calls_model_once_without_predict(fake_runtime, settings, expected):
    frame = object()
    result = make_result("tracked")
    model = Mock(spec=["track", "predict"])
    model.track.return_value = [result, object()]
    fake_runtime.yolo.return_value = model

    detector = fake_runtime.detector.ObjectDetector(**settings)
    assert detector.track(frame) is result

    model_path, tracker, confidence, size, device = expected
    fake_runtime.yolo.assert_called_once_with(model_path)
    assert model.mock_calls == [call.track(
        source=frame, persist=True, tracker=tracker,
        conf=confidence, imgsz=size, device=device, verbose=False,
    )]
    model.predict.assert_not_called()


def test_logger_preserves_csv_order_geometry_and_rounding(tmp_path):
    path = tmp_path / "observations.csv"
    logger = TrackLogger(path)
    logger.open()
    try:
        assert logger.write_result(make_result("tracked"), 7, 1.23456) == 2
        assert logger.row_count == 2
    finally:
        logger.close()

    with path.open(newline="", encoding="utf-8") as output:
        rows = list(csv.reader(output))

    # Literal expectations also catch geometry calculated from rounded corners.
    assert rows == [
        CSV_FIELDS,
        ["7", "1.235", "9", "car", "0.8765", "10.13", "20.23",
         "30.13", "60.24", "20.13", "40.24", "20.01", "40.01"],
        ["7", "1.235", "3", "person", "0.5", "0.0", "2.0",
         "6.0", "10.0", "3.0", "6.0", "6.0", "8.0"],
    ]


@pytest.mark.parametrize("kind", ["untracked", "empty", "no_boxes"])
def test_logger_writes_no_rows_without_assigned_tracks(tmp_path, kind):
    path = tmp_path / "observations.csv"
    logger = TrackLogger(path)
    logger.open()
    try:
        assert logger.write_result(make_result(kind), 1, 0.0) == 0
        assert logger.row_count == 0
    finally:
        logger.close()

    with path.open(newline="", encoding="utf-8") as output:
        assert list(csv.reader(output)) == [CSV_FIELDS]


@pytest.mark.parametrize("source_fps", [25.0, 0.0, -1.0])
def test_processing_counts_returned_boxes_and_plots_every_frame(
    fake_runtime, tmp_path, source_fps,
):
    config = PipelineConfig.from_dict({
        "input": {"video_path": str(tmp_path / "input.mp4")},
        "model": {
            "model_path": "yolo11n.pt", "tracker_config": "bytetrack.yaml",
            "confidence_threshold": 0.35, "image_size": 640, "device": "cpu",
        },
        "output": {
            "video_path": str(tmp_path / "output.mp4"),
            "observations_path": str(tmp_path / "observations.csv"),
            "summaries_path": str(tmp_path / "summaries.csv"),
            "quality_path": str(tmp_path / "quality.csv"),
            "processing_metrics_path": str(tmp_path / "metrics.json"),
        },
        "quality": {
            "minimum_stable_observations": 5,
            "minimum_stable_duration": 0.2,
            "minimum_stable_confidence": 0.5,
        },
    })
    config.input_video_path.write_bytes(b"fake capture supplies the frames")
    kinds = ["tracked", "untracked", "empty", "no_boxes", "tracked"]
    results = [make_result(kind) for kind in kinds]
    frames = [object() for _ in results]
    model = Mock(spec=["track", "predict"])
    model.track.side_effect = [[result] for result in results]
    fake_runtime.yolo.return_value = model

    capture = Mock(spec=["isOpened", "get", "read", "release"])
    capture.isOpened.return_value = True
    cv2 = fake_runtime.cv2
    capture.get.side_effect = {
        cv2.CAP_PROP_FRAME_WIDTH: 640,
        cv2.CAP_PROP_FRAME_HEIGHT: 480,
        cv2.CAP_PROP_FPS: source_fps,
    }.__getitem__
    capture.read.side_effect = [(True, frame) for frame in frames] + [(False, None)]
    cv2.VideoCapture.return_value = capture
    writer = Mock(spec=["isOpened", "write", "release"])
    writer.isOpened.return_value = True
    cv2.VideoWriter.return_value = writer

    assert fake_runtime.processing.process_video(config) == 0

    assert model.mock_calls == [call.track(
        source=frame, persist=True, tracker="bytetrack.yaml",
        conf=0.35, imgsz=640, device="cpu", verbose=False,
    ) for frame in frames]
    model.predict.assert_not_called()

    metrics = json.loads(config.processing_metrics_path.read_text(encoding="utf-8"))
    assert metrics["status"] == "completed"
    effective_fps = source_fps if source_fps > 0 else 30.0
    assert metrics["video"] == {
        "width": 640, "height": 480, "source_fps": effective_fps,
    }
    assert metrics["results"]["frames_processed"] == 5
    # 2 tracked + 1 untracked + 0 empty + 0 absent + 2 tracked boxes.
    assert metrics["results"]["frame_detections"] == 5
    assert metrics["results"]["tracked_observations"] == 4
    assert metrics["results"]["unique_tracks"] == 2

    with config.observations_path.open(newline="", encoding="utf-8") as output:
        rows = list(csv.DictReader(output))
    assert [row["track_id"] for row in rows] == ["9", "3", "9", "3"]
    assert [row["frame_number"] for row in rows] == ["1", "1", "5", "5"]
    last_timestamp = "0.16" if source_fps > 0 else "0.133"
    assert [row["timestamp_seconds"] for row in rows] == [
        "0.0", "0.0", last_timestamp, last_timestamp,
    ]

    for result in results:
        result.plot.assert_called_once_with()
    assert writer.write.call_args_list == [
        call(result.plot.return_value) for result in results
    ]
    assert [(args.args[0], args.args[1]) for args in cv2.putText.call_args_list] == [
        (result.plot.return_value, text)
        for number, (result, active) in enumerate(zip(results, [2, 0, 0, 0, 2]), 1)
        for text in (
            f"Aegis | Frame: {number}", f"Active tracks: {active}", "Unique tracks: 2",
        )
    ]
    cv2.VideoWriter_fourcc.assert_called_once_with(*"mp4v")
    cv2.VideoWriter.assert_called_once_with(
        str(config.output_video_path), 123, effective_fps, (640, 480),
    )
    capture.release.assert_called_once_with()
    writer.release.assert_called_once_with()
