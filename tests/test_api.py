import csv

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


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == (
        "Aegis World Model API"
    )


def test_health_with_available_world_model(
    tmp_path,
    monkeypatch,
):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(api_module, "TRACK_DATA_PATH", data_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["world_model_available"] is True


def test_statistics(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(api_module, "TRACK_DATA_PATH", data_path)

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
    monkeypatch.setattr(api_module, "TRACK_DATA_PATH", data_path)

    response = client.get("/tracks?quality=stable")
    body = response.json()

    assert response.status_code == 200
    assert body["total_matching"] == 1
    assert body["tracks"][0]["track_id"] == 1


def test_get_existing_track(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(api_module, "TRACK_DATA_PATH", data_path)

    response = client.get("/tracks/1")

    assert response.status_code == 200
    assert response.json()["dominant_label"] == "person"


def test_get_missing_track(tmp_path, monkeypatch):
    data_path = create_test_data(tmp_path)
    monkeypatch.setattr(api_module, "TRACK_DATA_PATH", data_path)

    response = client.get("/tracks/999")

    assert response.status_code == 404
