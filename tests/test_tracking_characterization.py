"""Characterize Aegis processing without heavy dependencies."""

import csv
import importlib.util
import json
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from aegis.core.frames import Frame, FrameMetadata
from aegis.fusion.camera_adapter import ImageTrackMeasurement, tracked_objects_to_observations
from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame, SensorObservation
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
    fake_runtime, tmp_path, source_fps, model_settings, monkeypatch,
):
    adapter = Mock(side_effect=AssertionError("Disabled delivery must not convert"))
    monkeypatch.setattr(fake_runtime.processing, "tracked_objects_to_observations", adapter, raising=False)
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
    adapter.assert_not_called()

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


OBSERVATION_CONTEXT = {
    "sensor_id": "camera-front",
    "clock_domain": "recording:test-origin",
    "reference_frame_id": "front:image-plane",
}


@dataclass(frozen=True)
class RangeMeasurement:
    """Test-only measurement shape, not a production sensor contract."""

    range_m: float
    bearing_rad: float


class RecordingObservationConsumer:
    """Record the small test fixture's batches without modality-specific logic."""

    def __init__(self):
        self.batches: list[ObservationBatch[object]] = []

    def accept(self, batch: ObservationBatch[object]) -> None:
        self.batches.append(batch)


@pytest.fixture
def observation_runtime(fake_runtime, tmp_path, monkeypatch):
    config = PipelineConfig.from_dict({
        "input": {"video_path": str(tmp_path / "input.mp4")},
        "model": {
            "model_path": "yolo11n.pt", "tracker_config": "bytetrack.yaml",
            "confidence_threshold": 0.35, "image_size": 640, "device": "cpu",
        },
        "output": {
            "video_path": str(tmp_path / "out.mp4"),
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
    config.input_video_path.write_bytes(b"fake source")
    frames = [
        Frame(object(), FrameMetadata("opening-a", number, timestamp, 640, 480))
        for number, timestamp in ((7, 0.240123), (8, 0.28), (9, 0.32), (12, 0.440567))
    ]
    outputs = [
        TrackingFrameOutput(make_batch(frame.metadata, index in (0, 3)), count, object())
        for index, (frame, count) in enumerate(zip(frames, (2, 1, 0, 2)))
    ]
    fake_runtime.session.track.side_effect = outputs
    source = Mock(spec=["metadata", "read_frame", "release"])
    source.metadata = SimpleNamespace(width=640, height=480, fps=25.0)
    source.read_frame.side_effect = [*frames, None]
    source_factory = Mock(return_value=source)
    monkeypatch.setattr(fake_runtime.processing, "VideoFileSource", source_factory)

    events = []
    logger = TrackLogger(config.observations_path)
    original_write = logger.write_batch

    def write_batch(batch):
        count = original_write(batch)
        events.append("logged")
        return count

    logger.write_batch = Mock(side_effect=write_batch)
    logger.close = Mock(wraps=logger.close)
    logger_factory = Mock(return_value=logger)
    monkeypatch.setattr(fake_runtime.processing, "TrackLogger", logger_factory)
    writer = fake_runtime.cv2.VideoWriter.return_value
    writer.isOpened.return_value = True
    writer.write.side_effect = lambda image: events.append("video")
    fake_runtime.cv2.putText.side_effect = lambda *args: events.append("overlay")
    return SimpleNamespace(
        runtime=fake_runtime, config=config, frames=frames, outputs=outputs,
        source=source, source_factory=source_factory, logger=logger,
        logger_factory=logger_factory, writer=writer, events=events,
    )


def test_observation_delivery_preserves_context_order_outputs_and_caller_ownership(observation_runtime):
    env = observation_runtime
    received = []

    class Consumer:
        open = Mock()
        close = Mock()

        def __call__(self, batch):
            env.events.append("callback")
            received.append(batch)

    consumer = Consumer()
    assert env.runtime.processing.process_video(
        env.config, on_observations=consumer, **OBSERVATION_CONTEXT,
    ) == 0

    # Real conversion across nonempty, untracked, empty, then gapped source frames.
    assert received == [
        tracked_objects_to_observations(output.tracks, **OBSERVATION_CONTEXT)
        for output in (env.outputs[0], env.outputs[3])
    ]
    assert all(isinstance(batch, ObservationBatch) for batch in received)
    first = received[0].observations[0]
    assert first.sensor_id == "camera-front"
    assert first.measurement_time.seconds == 0.240123
    assert first.measurement_time.clock_domain == "recording:test-origin"
    assert first.reference_frame.frame_id == "front:image-plane"
    assert first.measurement == ImageTrackMeasurement(
        1, "car", 0.876543, 10.126, 20.234, 30.134, 60.242, 640, 480,
    )
    assert first.source_local_id == '["opening-a",9]'
    assert first.observation_id == '["camera-track","camera-front","opening-a",7,9,0]'
    assert received[1].observations[0].measurement_time.seconds == 0.440567
    assert env.events == (
        ["logged", "callback", "overlay", "overlay", "overlay", "video"]
        + ["logged", "overlay", "overlay", "overlay", "video"] * 2
        + ["logged", "callback", "overlay", "overlay", "overlay", "video"]
    )
    assert env.runtime.session.track.call_args_list == [call(frame) for frame in env.frames]
    assert env.writer.write.call_args_list == [call(output.annotated_image) for output in env.outputs]
    env.runtime.cv2.VideoWriter.assert_called_once_with(
        str(env.config.output_video_path), 123, 25.0, (640, 480),
    )
    assert [entry.args[1] for entry in env.runtime.cv2.putText.call_args_list] == [
        text
        for number, active in ((7, 2), (8, 0), (9, 0), (12, 2))
        for text in (f"Aegis | Frame: {number}", f"Active tracks: {active}", "Unique tracks: 2")
    ]
    with env.config.observations_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["frame_number"] for row in rows] == ["7", "7", "12", "12"]
    assert [row["timestamp_seconds"] for row in rows] == ["0.24", "0.24", "0.441", "0.441"]
    metrics = json.loads(env.config.processing_metrics_path.read_text())
    assert metrics["status"] == "completed"
    assert {key: metrics["results"][key] for key in (
        "frames_processed", "frame_detections", "tracked_observations", "unique_tracks",
    )} == dict(frames_processed=4, frame_detections=5, tracked_observations=4, unique_tracks=2)
    consumer.open.assert_not_called()
    consumer.close.assert_not_called()
    env.source.release.assert_called_once_with()
    env.writer.release.assert_called_once_with()
    env.logger.close.assert_called_once_with()
    env.runtime.session.close.assert_called_once_with()


def test_shared_consumer_receives_sequential_heterogeneous_observation_batches(observation_runtime):
    env = observation_runtime
    consumer = RecordingObservationConsumer()
    assert env.runtime.processing.process_video(
        env.config, on_observations=consumer.accept, **OBSERVATION_CONTEXT,
    ) == 0

    # Camera evidence goes through real processing and conversion, not a manual handoff.
    assert len(consumer.batches) == 2
    camera_batches = tuple(consumer.batches)
    for batch, timestamp in zip(camera_batches, (0.240123, 0.440567), strict=True):
        assert isinstance(batch, ObservationBatch)
        assert len(batch.observations) == 2
        for observation, track_id in zip(batch.observations, (9, 3), strict=True):
            assert isinstance(observation.measurement, ImageTrackMeasurement)
            assert observation.sensor_id == "camera-front"
            assert observation.measurement_time == MeasurementTime(timestamp, "recording:test-origin")
            assert observation.reference_frame == ReferenceFrame("front:image-plane")
            assert observation.source_local_id == f'["opening-a",{track_id}]'

    measurement = RangeMeasurement(range_m=42.5, bearing_rad=0.125)
    observation = SensorObservation(
        observation_id="test-range-observation-1",
        sensor_id="test-range-01",
        measurement_time=MeasurementTime(123.75, "test-range-clock"),
        reference_frame=ReferenceFrame("test-range-frame"),
        source_local_id="test-range-session/local-2",
        measurement=measurement,
    )
    second_batch = ObservationBatch((observation,))
    consumer.accept(second_batch)

    # One caller-owned consumer retains exact call order across different payload shapes.
    assert len(consumer.batches) == 3
    assert consumer.batches[0] is camera_batches[0]
    assert consumer.batches[1] is camera_batches[1]
    assert consumer.batches[2] is second_batch
    received, = consumer.batches[2].observations
    assert received is observation
    assert received.observation_id == "test-range-observation-1"
    assert received.sensor_id == "test-range-01"
    assert received.measurement_time == MeasurementTime(123.75, "test-range-clock")
    assert received.reference_frame == ReferenceFrame("test-range-frame")
    assert received.source_local_id == "test-range-session/local-2"
    assert received.measurement is measurement
    assert isinstance(received.measurement, RangeMeasurement)
    assert received.measurement == RangeMeasurement(42.5, 0.125)


INVALID_DELIVERY_OPTIONS = [
    {**({"on_observations": lambda batch: None} if flags[0] else {}), **{
        key: OBSERVATION_CONTEXT[key]
        for key, present in zip(OBSERVATION_CONTEXT, flags[1:]) if present
    }}
    for flags in product((False, True), repeat=4)
    if flags not in ((False,) * 4, (True,) * 4)
] + [
    dict(OBSERVATION_CONTEXT, on_observations=lambda batch: None, **{field: blank})
    for field in OBSERVATION_CONTEXT for blank in ("", " \t")
] + [dict(OBSERVATION_CONTEXT, on_observations=object())]


@pytest.mark.parametrize("options", INVALID_DELIVERY_OPTIONS)
def test_observation_delivery_rejects_invalid_context_before_resources(observation_runtime, options):
    env = observation_runtime
    assert env.runtime.processing.process_video(env.config, **options) == 1
    env.source_factory.assert_not_called()
    env.runtime.session_factory.assert_not_called()
    env.runtime.cv2.VideoWriter.assert_not_called()
    env.logger_factory.assert_not_called()
    metrics = json.loads(env.config.processing_metrics_path.read_text())
    assert metrics["status"] == "failed"
    assert metrics["error"]
    assert metrics["results"]["frames_processed"] == 0


@pytest.mark.parametrize("failure", [
    "callback_runtime", "callback_unexpected", "callback_interrupt",
    "conversion_runtime", "conversion_unexpected",
])
def test_observation_delivery_failure_stops_after_logging_and_closes_session(
    observation_runtime, monkeypatch, failure,
):
    env = observation_runtime
    error = (
        KeyboardInterrupt() if failure.endswith("interrupt") else
        LookupError("delivery failed") if failure.endswith("unexpected") else
        RuntimeError("delivery failed")
    )
    callback = Mock()
    if failure.startswith("conversion"):
        adapter = Mock(side_effect=error)
        monkeypatch.setattr(env.runtime.processing, "tracked_objects_to_observations", adapter, raising=False)
    else:
        callback.side_effect = error

    if failure.endswith("interrupt"):
        with pytest.raises(KeyboardInterrupt):
            env.runtime.processing.process_video(env.config, on_observations=callback, **OBSERVATION_CONTEXT)
    else:
        assert env.runtime.processing.process_video(
            env.config, on_observations=callback, **OBSERVATION_CONTEXT,
        ) == 1

    if failure.startswith("conversion"):
        adapter.assert_called_once_with(env.outputs[0].tracks, **OBSERVATION_CONTEXT)
        callback.assert_not_called()
    else:
        callback.assert_called_once()
    env.runtime.session.track.assert_called_once_with(env.frames[0])
    env.source.read_frame.assert_called_once_with()
    assert env.events == ["logged"]
    env.logger.write_batch.assert_called_once_with(env.outputs[0].tracks)
    env.runtime.cv2.putText.assert_not_called()
    env.writer.write.assert_not_called()
    env.source.release.assert_called_once_with()
    env.writer.release.assert_called_once_with()
    env.logger.close.assert_called_once_with()
    env.runtime.session.close.assert_called_once_with()
    with env.config.observations_path.open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 2
    metrics = json.loads(env.config.processing_metrics_path.read_text())
    assert metrics["status"] == ("interrupted" if failure.endswith("interrupt") else "failed")
    # Existing failure metrics do not publish partial loop counters.
    assert metrics["results"]["frames_processed"] == 0
