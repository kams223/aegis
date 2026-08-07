import json

from fastapi.testclient import TestClient

import aegis.api.app as api_module


client = TestClient(api_module.app)


def write_manifest(
    history_path,
    run_id,
    performance=None,
):
    """Write one archived test manifest."""

    history_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "started_at_utc": "2026-08-07T02:09:33+00:00",
        "finished_at_utc": "2026-08-07T02:11:58+00:00",
        "duration_seconds": 141.447,
        "input": {
            "path": "data/videos/test.mp4",
        },
        "model": {
            "model_path": "yolo11n.pt",
            "device": "cpu",
        },
        "stages": [
            {
                "name": "Video detection and tracking",
                "status": "completed",
                "duration_seconds": 115.76,
                "exit_code": 0,
            }
        ],
    }

    if performance is not None:
        manifest["performance"] = performance

    manifest_path = history_path / f"{run_id}.json"

    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    return manifest_path


def test_run_history_includes_performance_metrics(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "runs"

    write_manifest(
        history_path=history_path,
        run_id="performance-run",
        performance={
            "processing_metrics_available": True,
            "pipeline_duration_seconds": 141.447,
            "initialization_overhead_seconds": 25.664,
            "processing_metrics": {
                "duration_seconds": 115.721,
                "results": {
                    "average_processing_fps": 2.342,
                    "frames_processed": 271,
                    "frame_detections": 462,
                    "tracked_observations": 452,
                    "unique_tracks": 45,
                },
            },
        },
    )

    monkeypatch.setattr(
        api_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    response = client.get("/runs")
    body = response.json()

    assert response.status_code == 200
    assert body["total_runs"] == 1

    run = body["runs"][0]

    assert run["processing_metrics_available"] is True
    assert run["average_processing_fps"] == 2.342
    assert run["frames_processed"] == 271
    assert run["frame_detections"] == 462
    assert run["tracked_observations"] == 452
    assert run["unique_tracks"] == 45
    assert run["processing_duration_seconds"] == 115.721
    assert run["initialization_overhead_seconds"] == 25.664
    assert run["pipeline_duration_seconds"] == 141.447


def test_legacy_run_history_uses_unavailable_metrics(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "runs"

    write_manifest(
        history_path=history_path,
        run_id="legacy-run",
    )

    monkeypatch.setattr(
        api_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    response = client.get("/runs")
    body = response.json()

    assert response.status_code == 200

    run = body["runs"][0]

    assert run["processing_metrics_available"] is False
    assert run["average_processing_fps"] is None
    assert run["frames_processed"] is None
    assert run["frame_detections"] is None
    assert run["tracked_observations"] is None
    assert run["unique_tracks"] is None
    assert run["processing_duration_seconds"] is None
    assert run["initialization_overhead_seconds"] is None
    assert run["pipeline_duration_seconds"] is None
