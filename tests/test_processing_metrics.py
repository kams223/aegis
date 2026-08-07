import json

from aegis.perception.processing_metrics import (
    ProcessingMetricsRecorder,
)


def test_processing_metrics_records_success(tmp_path):
    output_path = tmp_path / "metrics.json"

    recorder = ProcessingMetricsRecorder(output_path)

    recorder.start(monotonic_time=100.0)

    recorder.set_video_metadata(
        width=1920,
        height=1080,
        source_fps=30.0,
    )

    recorder.finish_success(
        monotonic_time=110.0,
        frames_processed=300,
        frame_detections=500,
        tracked_observations=450,
        unique_tracks=25,
    )

    saved = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert saved["schema_version"] == 1
    assert saved["status"] == "completed"
    assert saved["duration_seconds"] == 10.0
    assert saved["video"]["width"] == 1920
    assert saved["video"]["height"] == 1080
    assert saved["video"]["source_fps"] == 30.0

    assert saved["results"]["frames_processed"] == 300
    assert saved["results"]["frame_detections"] == 500

    assert saved["results"]["tracked_observations"] == (
        450
    )
    assert saved["results"]["unique_tracks"] == 25

    assert saved["results"]["average_processing_fps"] == (
        30.0
    )


def test_processing_metrics_records_failure(tmp_path):
    output_path = tmp_path / "metrics.json"

    recorder = ProcessingMetricsRecorder(output_path)

    recorder.start(monotonic_time=20.0)

    recorder.finish_failure(
        monotonic_time=22.5,
        error="Synthetic processing failure",
    )

    saved = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert saved["status"] == "failed"
    assert saved["duration_seconds"] == 2.5
    assert saved["error"] == (
        "Synthetic processing failure"
    )
    assert saved["results"]["frames_processed"] == 0
