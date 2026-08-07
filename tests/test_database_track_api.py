from fastapi.testclient import TestClient

import aegis.api.app as api_module
from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import TrackRepository


client = TestClient(api_module.app)


def create_manifest(
    run_id: str,
    finished_at_utc: str,
) -> dict:
    """Create one database-backed run manifest."""

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
            "database_tracks_available": True,
            "database_track_count": 2,
        },
        "stages": [],
    }


def create_track(
    track_id: int,
    dominant_label: str,
    quality_level: str,
    confidence: float,
) -> dict:
    """Create one evaluated track."""

    return {
        "track_id": track_id,
        "dominant_label": dominant_label,
        "quality_level": quality_level,
        "quality_reason": "Database test track",
        "observation_count": 10,
        "duration_seconds": 1.0,
        "average_confidence": confidence,
        "displacement_pixels": 20.0,
        "first_frame": 1,
        "last_frame": 31,
        "first_seen_seconds": 0.0,
        "last_seen_seconds": 1.0,
        "start_position": {
            "x": 100.0,
            "y": 200.0,
        },
        "end_position": {
            "x": 120.0,
            "y": 220.0,
        },
    }


def configure_database(
    tmp_path,
    monkeypatch,
):
    """Configure a database containing one track snapshot."""

    database_path = tmp_path / "world.sqlite3"
    history_path = tmp_path / "runs"
    history_path.mkdir()

    run_id = "database-track-run"

    run_repository = RunRepository(database_path)
    run_repository.initialize()

    run_repository.save_manifest(
        create_manifest(
            run_id=run_id,
            finished_at_utc=(
                "2026-08-07T14:30:00+00:00"
            ),
        )
    )

    track_repository = TrackRepository(database_path)
    track_repository.initialize()

    track_repository.replace_run_tracks(
        run_id=run_id,
        tracks=[
            create_track(
                track_id=1,
                dominant_label="person",
                quality_level="stable",
                confidence=0.85,
            ),
            create_track(
                track_id=2,
                dominant_label="car",
                quality_level="weak",
                confidence=0.35,
            ),
        ],
    )

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

    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        tmp_path / "missing.csv",
    )

    return database_path, run_id


def test_statistics_uses_sqlite_tracks(
    tmp_path,
    monkeypatch,
):
    _, run_id = configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get("/statistics")
    body = response.json()

    assert response.status_code == 200
    assert body["storage_source"] == "sqlite"
    assert body["run_id"] == run_id
    assert body["total_tracks"] == 2

    assert body["quality_counts"] == {
        "stable": 1,
        "tentative": 0,
        "weak": 1,
    }

    assert body["label_counts"] == {
        "car": 1,
        "person": 1,
    }


def test_list_tracks_uses_sqlite_filters(
    tmp_path,
    monkeypatch,
):
    _, run_id = configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/tracks",
        params={
            "quality": "stable",
            "minimum_confidence": 0.8,
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["storage_source"] == "sqlite"
    assert body["run_id"] == run_id
    assert body["total_matching"] == 1
    assert body["returned"] == 1
    assert body["tracks"][0]["track_id"] == 1


def test_get_track_uses_sqlite(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get("/tracks/2")
    body = response.json()

    assert response.status_code == 200
    assert body["track_id"] == 2
    assert body["dominant_label"] == "car"
    assert body["quality_level"] == "weak"


def test_missing_sqlite_track_returns_404(
    tmp_path,
    monkeypatch,
):
    configure_database(
        tmp_path,
        monkeypatch,
    )

    response = client.get("/tracks/999")

    assert response.status_code == 404


def test_health_reports_sqlite_track_source(
    tmp_path,
    monkeypatch,
):
    database_path, run_id = configure_database(
        tmp_path,
        monkeypatch,
    )

    manifest_path = tmp_path / "latest.json"
    manifest_path.write_text(
        "{}",
        encoding="utf-8",
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
    assert body["world_model_available"] is True
    assert body["track_storage_source"] == "sqlite"
    assert body["track_run_id"] == run_id
    assert body["database_path"] == str(database_path)


def test_newest_run_without_tracks_is_skipped(
    tmp_path,
    monkeypatch,
):
    database_path, track_run_id = configure_database(
        tmp_path,
        monkeypatch,
    )

    repository = RunRepository(database_path)

    repository.save_manifest(
        create_manifest(
            run_id="newer-run-without-tracks",
            finished_at_utc=(
                "2026-08-07T15:00:00+00:00"
            ),
        )
    )

    response = client.get("/tracks")
    body = response.json()

    assert response.status_code == 200
    assert body["storage_source"] == "sqlite"
    assert body["run_id"] == track_run_id
    assert body["total_matching"] == 2
