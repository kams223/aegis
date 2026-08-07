from fastapi.testclient import TestClient

import aegis.api.app as api_module
from aegis.storage.run_repository import RunRepository


client = TestClient(api_module.app)


def create_manifest(
    run_id: str,
    finished_at_utc: str,
    fps: float,
) -> dict:
    """Create a database-backed API test manifest."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "configuration_path": "configs/pipeline.json",
        "started_at_utc": "2026-08-07T14:20:00+00:00",
        "finished_at_utc": finished_at_utc,
        "duration_seconds": 120.0,
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
            "initialization_overhead_seconds": 20.0,
            "pipeline_duration_seconds": 120.0,
            "processing_metrics": {
                "duration_seconds": 100.0,
                "results": {
                    "average_processing_fps": fps,
                    "frames_processed": 271,
                    "frame_detections": 462,
                    "tracked_observations": 452,
                    "unique_tracks": 45,
                },
            },
        },
        "stages": [
            {
                "name": "Video detection and tracking",
                "status": "completed",
                "duration_seconds": 100.0,
                "exit_code": 0,
            }
        ],
    }


def create_database(tmp_path):
    """Create a populated run-history database."""

    database_path = tmp_path / "world.sqlite3"
    repository = RunRepository(database_path)
    repository.initialize()

    older = create_manifest(
        run_id="database-run-older",
        finished_at_utc="2026-08-07T14:20:00+00:00",
        fps=2.0,
    )

    newer = create_manifest(
        run_id="database-run-newer",
        finished_at_utc="2026-08-07T14:30:00+00:00",
        fps=2.5,
    )

    repository.save_manifest(older)
    repository.save_manifest(newer)

    return database_path


def configure_database(
    tmp_path,
    monkeypatch,
):
    """Configure API run history to use test SQLite."""

    database_path = create_database(tmp_path)
    history_path = tmp_path / "runs"
    history_path.mkdir()

    monkeypatch.setattr(
        api_module,
        "DATABASE_PATH",
        database_path,
    )

    monkeypatch.setattr(
        api_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    return database_path


def test_list_runs_uses_sqlite(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get("/runs?limit=1")
    body = response.json()

    assert response.status_code == 200
    assert body["storage_source"] == "sqlite"
    assert body["total_runs"] == 2
    assert body["returned"] == 1

    assert body["runs"][0]["run_id"] == (
        "database-run-newer"
    )

    assert body["runs"][0][
        "average_processing_fps"
    ] == 2.5


def test_get_run_uses_sqlite(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/database-run-older"
    )

    body = response.json()

    assert response.status_code == 200
    assert body["run_id"] == "database-run-older"

    assert body["performance"][
        "processing_metrics"
    ]["results"]["average_processing_fps"] == 2.0


def test_get_missing_database_run_returns_404(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/missing-database-run"
    )

    assert response.status_code == 404


def test_health_reports_sqlite_source(
    tmp_path,
    monkeypatch,
):
    database_path = configure_database(
        tmp_path,
        monkeypatch,
    )

    track_path = tmp_path / "tracks.csv"
    manifest_path = tmp_path / "latest.json"

    track_path.write_text(
        "track_id\n",
        encoding="utf-8",
    )

    manifest_path.write_text(
        "{}",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        track_path,
    )

    monkeypatch.setattr(
        api_module,
        "RUN_MANIFEST_PATH",
        manifest_path,
    )

    response = client.get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "healthy"
    assert body["database_available"] is True
    assert body["database_path"] == str(
        database_path
    )
    assert body["run_history_source"] == "sqlite"


def test_json_fallback_reports_json_source(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "runs"
    history_path.mkdir()

    monkeypatch.setattr(
        api_module,
        "DATABASE_PATH",
        tmp_path / "missing.sqlite3",
    )

    monkeypatch.setattr(
        api_module,
        "RUN_HISTORY_PATH",
        history_path,
    )

    response = client.get("/runs")
    body = response.json()

    assert response.status_code == 200
    assert body["storage_source"] == "json"
    assert body["total_runs"] == 0
    assert body["runs"] == []
