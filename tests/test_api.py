import csv
import json

from fastapi.testclient import TestClient

import aegis.api.app as api_module


client = TestClient(api_module.app)


FIELD_NAMES = [
    "track_id",
    "dominant_label",
    "quality_level",
    "quality_reason",
    "observation_count",
    "duration_seconds",
    "average_confidence",
    "displacement_pixels",
    "first_frame",
    "last_frame",
    "first_seen_seconds",
    "last_seen_seconds",
    "start_center_x",
    "start_center_y",
    "end_center_x",
    "end_center_y",
]


def create_test_data(tmp_path):
    data_path = tmp_path / "track_quality.csv"

    rows = [
        {
            "track_id": 1,
            "dominant_label": "person",
            "quality_level": "stable",
            "quality_reason": "Persistent track",
            "observation_count": 20,
            "duration_seconds": 2.0,
            "average_confidence": 0.80,
            "displacement_pixels": 100.0,
            "first_frame": 1,
            "last_frame": 61,
            "first_seen_seconds": 0.0,
            "last_seen_seconds": 2.0,
            "start_center_x": 100.0,
            "start_center_y": 200.0,
            "end_center_x": 180.0,
            "end_center_y": 260.0,
        },
        {
            "track_id": 2,
            "dominant_label": "car",
            "quality_level": "weak",
            "quality_reason": "Too few observations",
            "observation_count": 1,
            "duration_seconds": 0.0,
            "average_confidence": 0.35,
            "displacement_pixels": 0.0,
            "first_frame": 10,
            "last_frame": 10,
            "first_seen_seconds": 0.3,
            "last_seen_seconds": 0.3,
            "start_center_x": 300.0,
            "start_center_y": 400.0,
            "end_center_x": 300.0,
            "end_center_y": 400.0,
        },
    ]

    with data_path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=FIELD_NAMES,
        )
        writer.writeheader()
        writer.writerows(rows)

    return data_path


def create_test_manifest(tmp_path):
    manifest_path = tmp_path / "aegis_run_manifest.json"

    manifest = {
        "schema_version": 1,
        "status": "completed",
        "exit_code": 0,
        "configuration_path": "configs/pipeline.json",
        "started_at_utc": "2026-08-06T20:10:47+00:00",
        "finished_at_utc": "2026-08-06T20:13:37+00:00",
        "duration_seconds": 170.0,
        "input": {
            "path": "data/videos/test.mp4",
            "exists": True,
            "size_bytes": 3313134,
            "sha256": "test-sha256",
        },
        "model": {
            "model_path": "yolo11n.pt",
            "tracker_config": "bytetrack.yaml",
            "device": "cpu",
            "confidence_threshold": 0.35,
            "image_size": 640,
        },
        "stages": [
            {
                "name": "Video detection and tracking",
                "status": "completed",
                "duration_seconds": 127.9,
                "exit_code": 0,
            }
        ],
    }

    with manifest_path.open(
        mode="w",
        encoding="utf-8",
    ) as output_file:
        json.dump(manifest, output_file)

    return manifest_path


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == (
        "Aegis World Model API"
    )
    assert response.json()["latest_run"] == "/runs/latest"


def test_health_with_all_data_available(
    tmp_path,
    monkeypatch,
):
    data_path = create_test_data(tmp_path)
    manifest_path = create_test_manifest(tmp_path)

    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
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
    assert body["run_manifest_available"] is True


def test_health_is_degraded_without_manifest(
    tmp_path,
    monkeypatch,
):
    data_path = create_test_data(tmp_path)
    missing_manifest = tmp_path / "missing.json"

    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
    )
    monkeypatch.setattr(
        api_module,
        "RUN_MANIFEST_PATH",
        missing_manifest,
    )

    response = client.get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "degraded"
    assert body["world_model_available"] is True
    assert body["run_manifest_available"] is False


def test_statistics(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
    )

    response = client.get("/statistics")
    body = response.json()

    assert response.status_code == 200
    assert body["total_tracks"] == 2
    assert body["quality_counts"]["stable"] == 1
    assert body["quality_counts"]["weak"] == 1


def test_list_tracks_filters_quality(
    tmp_path,
    monkeypatch,
):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
    )

    response = client.get("/tracks?quality=stable")
    body = response.json()

    assert response.status_code == 200
    assert body["total_matching"] == 1
    assert body["tracks"][0]["track_id"] == 1


def test_get_existing_track(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
    )

    response = client.get("/tracks/1")

    assert response.status_code == 200
    assert response.json()["dominant_label"] == "person"


def test_get_missing_track(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(
        api_module,
        "TRACK_DATA_PATH",
        data_path,
    )

    response = client.get("/tracks/999")

    assert response.status_code == 404


def test_latest_run_returns_manifest(
    tmp_path,
    monkeypatch,
):
    manifest_path = create_test_manifest(tmp_path)

    monkeypatch.setattr(
        api_module,
        "RUN_MANIFEST_PATH",
        manifest_path,
    )

    response = client.get("/runs/latest")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["exit_code"] == 0
    assert body["schema_version"] == 1
    assert body["model"]["model_path"] == "yolo11n.pt"


def test_latest_run_is_unavailable(
    tmp_path,
    monkeypatch,
):
    missing_manifest = tmp_path / "missing.json"

    monkeypatch.setattr(
        api_module,
        "RUN_MANIFEST_PATH",
        missing_manifest,
    )

    response = client.get("/runs/latest")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_latest_run_rejects_invalid_json(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text(
        "{this is not valid JSON",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        api_module,
        "RUN_MANIFEST_PATH",
        manifest_path,
    )

    response = client.get("/runs/latest")

    assert response.status_code == 500
    assert "Invalid pipeline run manifest" in (
        response.json()["detail"]
    )
