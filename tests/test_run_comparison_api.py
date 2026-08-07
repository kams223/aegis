import json

from fastapi.testclient import TestClient

import aegis.api.comparison_routes as comparison_module
from aegis.api.server import app


client = TestClient(app)


def write_manifest(
    history_path,
    run_id,
    fps,
    processing_duration,
    pipeline_duration,
    overhead,
):
    """Write a test run manifest containing performance data."""

    history_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "performance": {
            "processing_metrics_available": True,
            "pipeline_duration_seconds": pipeline_duration,
            "initialization_overhead_seconds": overhead,
            "processing_metrics": {
                "duration_seconds": processing_duration,
                "results": {
                    "average_processing_fps": fps,
                    "frames_processed": 271,
                    "frame_detections": 462,
                    "tracked_observations": 452,
                    "unique_tracks": 45,
                },
            },
        },
    }

    manifest_path = history_path / f"{run_id}.json"

    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    return manifest_path


def test_compare_archived_runs(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "runs"

    write_manifest(
        history_path=history_path,
        run_id="baseline-run",
        fps=2.0,
        processing_duration=120.0,
        pipeline_duration=145.0,
        overhead=25.0,
    )

    write_manifest(
        history_path=history_path,
        run_id="candidate-run",
        fps=2.5,
        processing_duration=100.0,
        pipeline_duration=120.0,
        overhead=20.0,
    )

    monkeypatch.setattr(
        comparison_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "baseline-run",
            "candidate": "candidate-run",
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["baseline_run_id"] == "baseline-run"
    assert body["candidate_run_id"] == "candidate-run"
    assert body["available_metric_count"] == 8
    assert body["improved_metric_count"] == 4
    assert body["regressed_metric_count"] == 0

    assert body["metrics"][
        "average_processing_fps"
    ]["assessment"] == "improved"


def test_compare_rejects_same_run():
    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "same-run",
            "candidate": "same-run",
        },
    )

    assert response.status_code == 400
    assert "must be different" in (
        response.json()["detail"]
    )


def test_compare_rejects_unsafe_run_id():
    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "bad$id",
            "candidate": "candidate-run",
        },
    )

    assert response.status_code == 400


def test_compare_returns_not_found(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "runs"
    history_path.mkdir()

    monkeypatch.setattr(
        comparison_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "missing-baseline",
            "candidate": "missing-candidate",
        },
    )

    assert response.status_code == 404
