"""Characterize Aegis processing without heavy dependencies."""

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from aegis.core.frames import Frame, FrameMetadata
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch, TrackingFrameOutput
from aegis.core.pipeline_config import PipelineConfig
from aegis.world_model.track_logger import TrackLogger


CSV_FIELDS = [
    "frame_number", "timestamp_seconds", "track_id", "label", "confidence",
    "x1", "y1", "x2", "y2", "center_x", "center_y", "width", "height",
]


def make_batch(metadata, tracked=True):
    objects = (
        TrackedObject(9, ObjectDetection(1, "car", 0.876543, 10.126, 20.234, 30.134, 60.242)),
        TrackedObject(3, ObjectDetection(0, "person", 0.5, 0.0, 2.0, 6.0, 10.0)),
    ) if tracked else ()
    return TrackedObjectBatch(metadata, objects)


@pytest.fixture
def fake_runtime(monkeypatch):
    """Load real source against scoped fakes, restoring module entries after use.

    Do not import optional packages or leave production modules cached with fake
    dependencies: CI intentionally installs only requirements-dev.txt.
    """
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

    monkeypatch.setitem(sys.modules, "cv2", cv2)

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
    processing = load_module("aegis.perception.process_video")
    session = Mock(spec=["track", "close"])
    session.track.side_effect = lambda frame: TrackingFrameOutput(
        make_batch(frame.metadata), 2, object(),
    )
    session_factory = Mock(return_value=session)
    # raising=False lets tests expose the old consumer before migration.
    monkeypatch.setattr(processing, "UltralyticsTrackingSession", session_factory, raising=False)
    return SimpleNamespace(
        session=session, session_factory=session_factory,
        cv2=cv2, processing=processing,
    )


def test_logger_preserves_csv_order_geometry_and_rounding(tmp_path):
    path = tmp_path / "observations.csv"
    logger = TrackLogger(path)
    logger.open()
    try:
        assert logger.write_batch(make_batch(FrameMetadata("test", 7, 1.23456, 640, 480))) == 2
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


def test_logger_writes_no_rows_without_assigned_tracks(tmp_path):
    path = tmp_path / "observations.csv"
    logger = TrackLogger(path)
    logger.open()
    try:
        assert logger.write_batch(make_batch(FrameMetadata("test", 1, 0.0, 640, 480), False)) == 0
        assert logger.row_count == 0
    finally:
        logger.close()

    with path.open(newline="", encoding="utf-8") as output:
        assert list(csv.reader(output)) == [CSV_FIELDS]


@pytest.mark.parametrize("model_settings", [
    dict(model_path="yolo11n.pt", tracker_config="bytetrack.yaml",
         confidence_threshold=0.35, image_size=640, device="cpu"),
    dict(model_path="custom.pt", tracker_config="custom.yaml",
         confidence_threshold=0.62, image_size=320, device="cuda:1"),
])
@pytest.mark.parametrize("source_fps", [25.0, 0.0, -1.0])
def test_processing_counts_backend_boxes_and_uses_annotated_images(
    fake_runtime, tmp_path, source_fps, model_settings,
):
    config = PipelineConfig.from_dict({
        "input": {"video_path": str(tmp_path / "input.mp4")},
        "model": model_settings,
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
    counts = [2, 1, 0, 0, 2]
    frames = [object() for _ in counts]
    outputs = []

    def track(frame):
        assert isinstance(frame, Frame)
        index = len(outputs)
        assert frame.image is frames[index]
        output = TrackingFrameOutput(
            make_batch(frame.metadata, index in (0, 4)), counts[index], object(),
        )
        outputs.append(output)
        return output

    fake_runtime.session.track.side_effect = track

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

    fake_runtime.session_factory.assert_called_once_with(
        model_path=config.model_path, confidence_threshold=config.confidence_threshold,
        image_size=config.image_size, tracker_config=config.tracker_config, device=config.device,
    )
    assert fake_runtime.session.track.call_count == len(frames)
    fake_runtime.session.close.assert_called_once_with()

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

    assert writer.write.call_args_list == [
        call(output.annotated_image) for output in outputs
    ]
    assert cv2.putText.call_args_list == [
        call(output.annotated_image, text, position, cv2.FONT_HERSHEY_SIMPLEX,
             1.0, color, 2, cv2.LINE_AA)
        for number, (output, active) in enumerate(zip(outputs, [2, 0, 0, 0, 2]), 1)
        for text, position, color in (
            (f"Aegis | Frame: {number}", (20, 40), (0, 255, 0)),
            (f"Active tracks: {active}", (20, 80), (0, 255, 255)),
            ("Unique tracks: 2", (20, 120), (255, 200, 0)),
        )
    ]
    cv2.VideoWriter_fourcc.assert_called_once_with(*"mp4v")
    cv2.VideoWriter.assert_called_once_with(
        str(config.output_video_path), 123, effective_fps, (640, 480),
    )
    capture.release.assert_called_once_with()
    writer.release.assert_called_once_with()


def test_logger_counts_each_call_and_requires_open(tmp_path):
    logger = TrackLogger(tmp_path / "rows.csv")
    batch = make_batch(FrameMetadata("test", 7, 0.24, 640, 480))
    with pytest.raises(RuntimeError, match="opened"):
        logger.write_batch(batch)
    logger.open()
    try:
        assert logger.write_batch(batch) == 2
        assert logger.write_batch(batch) == 2
        assert logger.write_batch(TrackedObjectBatch(batch.frame, ())) == 0
        assert logger.row_count == 4
    finally:
        logger.close()
