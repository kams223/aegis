from fastapi.testclient import TestClient

import aegis.api.comparison_routes as comparison_module
from aegis.api.server import app
from aegis.storage.run_repository import RunRepository


client = TestClient(app)


def create_manifest(
    run_id: str,
    fps: float,
    processing_duration: float,
    pipeline_duration: float,
    overhead: float,
) -> dict:
    """Create a comparison test manifest."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "started_at_utc": "2026-08-07T14:20:00+00:00",
        "finished_at_utc": "2026-08-07T14:30:00+00:00",
        "duration_seconds": pipeline_duration,
        "input": {
            "path": "data/videos/test.mp4",
            "sha256": "test-sha256",
        },
        "model": {
            "model_path": "yolo11n.pt",
            "tracker_config": "bytetrack.yaml",
            "device": "cpu",
            "confidence_threshold": 0.35,
            "image_size": 640,
        },
        "performance": {
            "processing_metrics_available": True,
            "initialization_overhead_seconds": overhead,
            "pipeline_duration_seconds": (
                pipeline_duration
            ),
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
        "stages": [],
    }


def configure_database(
    tmp_path,
    monkeypatch,
):
    """Create and configure comparison SQLite storage."""

    database_path = tmp_path / "world.sqlite3"
    history_path = tmp_path / "runs"
    history_path.mkdir()

    repository = RunRepository(database_path)
    repository.initialize()

    repository.save_manifest(
        create_manifest(
            run_id="baseline-database-run",
            fps=2.0,
            processing_duration=120.0,
            pipeline_duration=145.0,
            overhead=25.0,
        )
    )

    repository.save_manifest(
        create_manifest(
            run_id="candidate-database-run",
            fps=2.5,
            processing_duration=100.0,
            pipeline_duration=120.0,
            overhead=20.0,
        )
    )

    monkeypatch.setattr(
        comparison_module,
        "DATABASE_PATH",
        database_path,
    )

    monkeypatch.setattr(
        comparison_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    return repository


def test_compare_runs_uses_sqlite(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "baseline-database-run",
            "candidate": "candidate-database-run",
        },
    )

    body = response.json()

    assert response.status_code == 200

    assert body["baseline_run_id"] == (
        "baseline-database-run"
    )

    assert body["candidate_run_id"] == (
        "candidate-database-run"
    )

    fps_metric = body["metrics"][
        "average_processing_fps"
    ]

    assert fps_metric["baseline"] == 2.0
    assert fps_metric["candidate"] == 2.5
    assert fps_metric["assessment"] == "improved"

    duration_metric = body["metrics"][
        "processing_duration_seconds"
    ]

    assert duration_metric["baseline"] == 120.0
    assert duration_metric["candidate"] == 100.0
    assert duration_metric["assessment"] == "improved"


def test_compare_missing_sqlite_run_returns_404(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "missing-database-run",
            "candidate": "candidate-database-run",
        },
    )

    assert response.status_code == 404


def test_comparison_sqlite_is_authoritative(
    tmp_path,
    monkeypatch,
):
    repository = configure_database(
        tmp_path,
        monkeypatch,
    )

    assert repository.count_runs() == 2

    response = client.get(
        "/run-comparisons",
        params={
            "baseline": "baseline-database-run",
            "candidate": "candidate-database-run",
        },
    )

    assert response.status_code == 200

    assert response.json()[
        "available_metric_count"
    ] == 8
