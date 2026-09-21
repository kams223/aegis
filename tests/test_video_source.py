"""Source-boundary tests using captured images as opaque sentinels."""

import csv
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from aegis.core.frames import Frame, FrameMetadata
from aegis.core.pipeline_config import PipelineConfig
from test_tracking_characterization import fake_runtime, make_result


def open_source(runtime, fps=25.0, images=()):
    cv2 = runtime.cv2
    capture = Mock(spec=["isOpened", "get", "read", "release"])
    capture.isOpened.return_value = True
    capture.get.side_effect = {
        cv2.CAP_PROP_FRAME_WIDTH: 640,
        cv2.CAP_PROP_FRAME_HEIGHT: 480,
        cv2.CAP_PROP_FPS: fps,
    }.__getitem__
    capture.read.side_effect = [(True, image) for image in images] + [(False, None)]
    cv2.VideoCapture.return_value = capture
    source_class = sys.modules["aegis.sensors.video_file"].VideoFileSource
    return source_class("same-video.mp4"), capture


def test_legacy_image_read_eof_and_release(fake_runtime):
    image = object()
    source, capture = open_source(fake_runtime, images=[image])
    try:
        assert source.get_frame() is image
        assert source.get_frame() is None
    finally:
        source.release()
    capture.release.assert_called_once_with()


@pytest.mark.parametrize("fps", [25.0, 29.97])
def test_source_metadata_and_frame_sequence(fake_runtime, fps):
    images = [object(), object(), object()]
    source, capture = open_source(fake_runtime, fps, images)
    try:
        metadata = source.metadata
        assert (metadata.width, metadata.height, metadata.fps) == (640, 480, fps)
        assert isinstance(metadata.stream_id, str) and metadata.stream_id
        for number, image in enumerate(images, 1):
            frame = source.read_frame()
            assert isinstance(frame, Frame)
            assert frame.image is image
            assert frame.metadata == FrameMetadata(
                stream_id=metadata.stream_id,
                frame_number=number,
                timestamp_seconds=(number - 1) / fps,
                width=640,
                height=480,
            )
        assert source.read_frame() is None
    finally:
        source.release()
    capture.release.assert_called_once_with()


@pytest.mark.parametrize("fps", [0.0, -1.0, float("nan"), float("inf")])
def test_unusable_fps_uses_30_fps(fake_runtime, capsys, fps):
    source, _ = open_source(fake_runtime, fps, [object(), object()])
    try:
        assert source.metadata.fps == 30.0
        assert source.read_frame().metadata.timestamp_seconds == 0.0
        assert source.read_frame().metadata.timestamp_seconds == 1 / 30.0
        assert "WARNING: Source FPS unavailable; using 30 FPS." in capsys.readouterr().out
    finally:
        source.release()


def test_reopening_same_video_has_distinct_stream_identity(fake_runtime):
    first, _ = open_source(fake_runtime, images=[object()])
    second, _ = open_source(fake_runtime, images=[object()])
    try:
        a = first.read_frame().metadata
        b = second.read_frame().metadata
        assert a.stream_id != b.stream_id
        assert a.frame_number == b.frame_number == 1
        assert a.timestamp_seconds == b.timestamp_seconds == 0.0
    finally:
        first.release()
        second.release()


def test_legacy_and_typed_reads_share_one_sequence(fake_runtime):
    images = [object(), object()]
    source, _ = open_source(fake_runtime, images=images)
    try:
        assert source.get_frame() is images[0]
        second = source.read_frame()
        assert second.image is images[1]
        assert second.metadata.frame_number == 2
        assert second.metadata.timestamp_seconds == 1 / 25.0
        assert source.get_frame() is None
    finally:
        source.release()


def test_capture_released_if_metadata_read_fails(fake_runtime):
    capture = Mock(spec=["isOpened", "get", "release"])
    capture.isOpened.return_value = True
    capture.get.side_effect = RuntimeError("metadata read failed")
    fake_runtime.cv2.VideoCapture.return_value = capture
    source_class = sys.modules["aegis.sensors.video_file"].VideoFileSource

    with pytest.raises(RuntimeError, match="metadata read failed"):
        source_class("video.mp4")
    capture.release.assert_called_once_with()


@pytest.fixture
def processing_config(tmp_path):
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
    return config


@pytest.mark.parametrize("frame_numbers", [(7,), (7, 10)])
def test_processing_uses_public_source_without_capture(
    fake_runtime, processing_config, monkeypatch, frame_numbers,
):
    config = processing_config
    # Later/gapped frames prove source position and processed count are distinct.
    frames = [
        Frame(object(), FrameMetadata("test-stream", number, (number - 1) / 25, 640, 480))
        for number in frame_numbers
    ]
    source = Mock(spec=["metadata", "read_frame", "release"])
    source.metadata = SimpleNamespace(width=640, height=480, fps=25.0)
    source.read_frame.side_effect = [*frames, None]
    monkeypatch.setattr(fake_runtime.processing, "VideoFileSource", lambda path: source)
    result = make_result("tracked")
    model = fake_runtime.yolo.return_value
    model.track.return_value = [result]
    writer = fake_runtime.cv2.VideoWriter.return_value
    writer.isOpened.return_value = True

    assert fake_runtime.processing.process_video(config) == 0

    assert [entry.kwargs["source"] for entry in model.track.call_args_list] == [
        frame.image for frame in frames
    ]
    assert model.track.call_count == len(frames)
    with config.observations_path.open(newline="", encoding="utf-8") as output:
        rows = list(csv.DictReader(output))
    assert [row["frame_number"] for row in rows] == [
        str(number) for number in frame_numbers for _ in range(2)
    ]
    assert [row["timestamp_seconds"] for row in rows] == [
        str(round(frame.metadata.timestamp_seconds, 3))
        for frame in frames for _ in range(2)
    ]
    metrics = json.loads(config.processing_metrics_path.read_text(encoding="utf-8"))
    assert metrics["results"]["frames_processed"] == len(frames)
    assert [entry.args[1] for entry in fake_runtime.cv2.putText.call_args_list[::3]] == [
        f"Aegis | Frame: {number}" for number in frame_numbers
    ]
    fake_runtime.cv2.VideoWriter.assert_called_once_with(
        str(config.output_video_path), 123, 25.0, (640, 480),
    )
    source.release.assert_called_once_with()
    writer.release.assert_called_once_with()


def failed_capture(runtime):
    capture = Mock(spec=["isOpened", "get", "read", "release"])
    capture.isOpened.return_value = False
    capture.get.return_value = 0.0
    capture.read.return_value = (False, None)
    runtime.cv2.VideoCapture.return_value = capture
    return capture


def test_failed_open_continues_construction_until_caller_releases(fake_runtime, capsys):
    capture = failed_capture(fake_runtime)
    source_class = sys.modules["aegis.sensors.video_file"].VideoFileSource
    source = source_class("unreadable.mp4")
    try:
        assert "ERROR: Could not open video: unreadable.mp4" in capsys.readouterr().out
        assert capture.get.call_args_list == [
            call(fake_runtime.cv2.CAP_PROP_FRAME_WIDTH),
            call(fake_runtime.cv2.CAP_PROP_FRAME_HEIGHT),
            call(fake_runtime.cv2.CAP_PROP_FPS),
        ]
        assert (source.metadata.width, source.metadata.height) == (0, 0)
        assert source.metadata.fps == 30.0
        capture.release.assert_not_called()
        assert source.get_frame() is None
    finally:
        source.release()
    capture.release.assert_called_once_with()


def test_processing_failed_open_records_failure_and_releases(
    fake_runtime, processing_config, capsys,
):
    capture = failed_capture(fake_runtime)
    config = processing_config

    assert fake_runtime.processing.process_video(config) == 1

    output = capsys.readouterr().out
    assert f"ERROR: Could not open video: {config.input_video_path}" in output
    assert "Invalid video dimensions: 0 x 0" in output
    metrics = json.loads(config.processing_metrics_path.read_text(encoding="utf-8"))
    assert metrics["status"] == "failed"
    assert metrics["error"] == "Invalid video dimensions: 0 x 0"
    assert metrics["results"]["frames_processed"] == 0
    fake_runtime.yolo.assert_not_called()
    fake_runtime.cv2.VideoWriter.assert_not_called()
    capture.read.assert_not_called()
    capture.release.assert_called_once_with()
