from fastapi.testclient import TestClient

import aegis.api.app as api_module
from aegis.api.server import app
from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import TrackRepository


client = TestClient(app)


def create_manifest(
    run_id: str,
    finished_at_utc: str,
) -> dict:
    """Create one historical-track test manifest."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "configuration_path": "configs/pipeline.json",
        "started_at_utc": "2026-08-07T10:00:00+00:00",
        "finished_at_utc": finished_at_utc,
        "duration_seconds": 100.0,
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
    label: str,
    quality: str,
    confidence: float,
) -> dict:
    """Create one historical evaluated track."""

    return {
        "track_id": track_id,
        "dominant_label": label,
        "quality_level": quality,
        "quality_reason": "Historical API test",
        "observation_count": 10,
        "duration_seconds": 1.0,
        "average_confidence": confidence,
        "displacement_pixels": 10.0,
        "first_frame": 1,
        "last_frame": 31,
        "first_seen_seconds": 0.0,
        "last_seen_seconds": 1.0,
        "start_position": {
            "x": 10.0,
            "y": 20.0,
        },
        "end_position": {
            "x": 20.0,
            "y": 30.0,
        },
    }


def configure_history(
    tmp_path,
    monkeypatch,
):
    """Create two isolated historical track snapshots."""

    database_path = tmp_path / "world.sqlite3"
    history_path = tmp_path / "runs"
    history_path.mkdir()

    run_repository = RunRepository(database_path)
    run_repository.initialize()

    run_repository.save_manifest(
        create_manifest(
            run_id="historical-run-one",
            finished_at_utc=(
                "2026-08-07T11:00:00+00:00"
            ),
        )
    )

    run_repository.save_manifest(
        create_manifest(
            run_id="historical-run-two",
            finished_at_utc=(
                "2026-08-07T12:00:00+00:00"
            ),
        )
    )

    track_repository = TrackRepository(database_path)
    track_repository.initialize()

    track_repository.replace_run_tracks(
        run_id="historical-run-one",
        tracks=[
            create_track(
                track_id=1,
                label="person",
                quality="stable",
                confidence=0.9,
            ),
            create_track(
                track_id=2,
                label="car",
                quality="weak",
                confidence=0.3,
            ),
        ],
    )

    track_repository.replace_run_tracks(
        run_id="historical-run-two",
        tracks=[
            create_track(
                track_id=8,
                label="boat",
                quality="tentative",
                confidence=0.6,
            )
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

    return database_path


def test_historical_statistics(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/statistics"
    )

    body = response.json()

    assert response.status_code == 200
    assert body["run_id"] == "historical-run-one"
    assert body["storage_source"] == "sqlite"
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


def test_historical_tracks_apply_filters(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/tracks",
        params={
            "quality": "stable",
            "minimum_confidence": 0.8,
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["run_id"] == "historical-run-one"
    assert body["total_matching"] == 1
    assert body["returned"] == 1
    assert body["tracks"][0]["track_id"] == 1


def test_historical_runs_are_isolated(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-two/tracks"
    )

    body = response.json()

    assert response.status_code == 200
    assert body["total_matching"] == 1
    assert body["tracks"][0]["track_id"] == 8
    assert body["tracks"][0]["dominant_label"] == "boat"


def test_get_historical_track(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/tracks/2"
    )

    body = response.json()

    assert response.status_code == 200
    assert body["track_id"] == 2
    assert body["dominant_label"] == "car"


def test_missing_historical_track_returns_404(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/tracks/999"
    )

    assert response.status_code == 404


def test_missing_historical_run_returns_404(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/missing-historical-run/tracks"
    )

    assert response.status_code == 404


def test_unsafe_historical_run_id_returns_400():
    response = client.get(
        "/runs/bad$id/tracks"
    )

    assert response.status_code == 400
def test_historical_tracks_filter_by_label(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/tracks",
        params={
            "dominant_label": "car",
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["total_matching"] == 1
    assert body["returned"] == 1
    assert body["offset"] == 0
    assert body["limit"] == 100
    assert body["has_previous"] is False
    assert body["has_next"] is False
    assert body["tracks"][0]["track_id"] == 2
    assert body["tracks"][0]["dominant_label"] == "car"


def test_historical_tracks_apply_pagination(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    first_response = client.get(
        "/runs/historical-run-one/tracks",
        params={
            "limit": 1,
            "offset": 0,
        },
    )

    second_response = client.get(
        "/runs/historical-run-one/tracks",
        params={
            "limit": 1,
            "offset": 1,
        },
    )

    first = first_response.json()
    second = second_response.json()

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    assert first["total_matching"] == 2
    assert first["returned"] == 1
    assert first["offset"] == 0
    assert first["limit"] == 1
    assert first["has_previous"] is False
    assert first["has_next"] is True
    assert first["tracks"][0]["track_id"] == 1

    assert second["total_matching"] == 2
    assert second["returned"] == 1
    assert second["offset"] == 1
    assert second["limit"] == 1
    assert second["has_previous"] is True
    assert second["has_next"] is False
    assert second["tracks"][0]["track_id"] == 2


def test_historical_tracks_reject_empty_label(
    tmp_path,
    monkeypatch,
):
    configure_history(
        tmp_path,
        monkeypatch,
    )

    response = client.get(
        "/runs/historical-run-one/tracks",
        params={
            "dominant_label": "",
        },
    )

    assert response.status_code == 422
