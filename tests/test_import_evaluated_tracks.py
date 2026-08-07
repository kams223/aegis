import csv
import json

import pytest

from aegis.storage.import_evaluated_tracks import (
    convert_track_row,
    import_evaluated_tracks,
    load_evaluated_tracks,
    load_latest_run_id,
    main,
)
from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import TrackRepository


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


def create_manifest(run_id: str) -> dict:
    """Create a parent pipeline run."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "started_at_utc": "2026-08-07T14:20:00+00:00",
        "finished_at_utc": "2026-08-07T14:30:00+00:00",
        "duration_seconds": 120.0,
        "input": {},
        "model": {},
        "performance": {},
        "stages": [],
    }


def create_csv_row(
    track_id: int,
    quality_level: str,
    confidence: float,
) -> dict:
    """Create one evaluated-track CSV row."""

    return {
        "track_id": track_id,
        "dominant_label": "person",
        "quality_level": quality_level,
        "quality_reason": "Test reason",
        "observation_count": 20,
        "duration_seconds": 2.0,
        "average_confidence": confidence,
        "displacement_pixels": 100.0,
        "first_frame": 1,
        "last_frame": 61,
        "first_seen_seconds": 0.0,
        "last_seen_seconds": 2.0,
        "start_center_x": 100.0,
        "start_center_y": 200.0,
        "end_center_x": 180.0,
        "end_center_y": 260.0,
    }


def write_quality_csv(path, rows):
    """Write evaluated-track CSV test data."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
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


def write_config(
    path,
    database_path,
    quality_path,
):
    """Write a complete pipeline test configuration."""

    path.write_text(
        json.dumps(
            {
                "input": {
                    "video_path": "data/videos/test.mp4",
                },
                "model": {
                    "model_path": "yolo11n.pt",
                    "tracker_config": "bytetrack.yaml",
                    "confidence_threshold": 0.35,
                    "image_size": 640,
                    "device": "cpu",
                },
                "output": {
                    "video_path": (
                        "outputs/videos/tracked.mp4"
                    ),
                    "observations_path": (
                        "outputs/data/observations.csv"
                    ),
                    "summaries_path": (
                        "outputs/data/summaries.csv"
                    ),
                    "quality_path": str(quality_path),
                    "processing_metrics_path": (
                        "outputs/data/metrics.json"
                    ),
                    "database_path": str(database_path),
                },
                "quality": {
                    "minimum_stable_observations": 5,
                    "minimum_stable_duration": 0.2,
                    "minimum_stable_confidence": 0.5,
                },
            }
        ),
        encoding="utf-8",
    )


def test_convert_track_row():
    row = {
        key: str(value)
        for key, value in create_csv_row(
            track_id=1,
            quality_level="stable",
            confidence=0.8,
        ).items()
    }

    track = convert_track_row(row)

    assert track["track_id"] == 1
    assert track["quality_level"] == "stable"
    assert track["average_confidence"] == 0.8

    assert track["start_position"] == {
        "x": 100.0,
        "y": 200.0,
    }


def test_load_evaluated_tracks(tmp_path):
    quality_path = tmp_path / "quality.csv"

    write_quality_csv(
        quality_path,
        [
            create_csv_row(1, "stable", 0.8),
            create_csv_row(2, "weak", 0.3),
        ],
    )

    tracks = load_evaluated_tracks(
        quality_path
    )

    assert len(tracks) == 2
    assert tracks[0]["track_id"] == 1
    assert tracks[1]["track_id"] == 2


def test_load_latest_run_id(tmp_path):
    manifest_path = tmp_path / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "latest-run-001",
            }
        ),
        encoding="utf-8",
    )

    assert load_latest_run_id(
        manifest_path
    ) == "latest-run-001"


def test_import_evaluated_tracks(tmp_path):
    database_path = tmp_path / "world.sqlite3"
    quality_path = tmp_path / "quality.csv"

    run_repository = RunRepository(database_path)
    run_repository.initialize()
    run_repository.save_manifest(
        create_manifest("run-001")
    )

    write_quality_csv(
        quality_path,
        [
            create_csv_row(1, "stable", 0.8),
            create_csv_row(2, "tentative", 0.6),
            create_csv_row(3, "weak", 0.3),
        ],
    )

    summary = import_evaluated_tracks(
        database_path=database_path,
        quality_path=quality_path,
        run_id="run-001",
    )

    track_repository = TrackRepository(
        database_path
    )

    assert summary["imported"] == 3
    assert summary["database_track_count"] == 3

    assert summary["quality_counts"] == {
        "stable": 1,
        "tentative": 1,
        "weak": 1,
    }

    assert track_repository.count_tracks(
        "run-001"
    ) == 3


def test_import_is_idempotent(tmp_path):
    database_path = tmp_path / "world.sqlite3"
    quality_path = tmp_path / "quality.csv"

    run_repository = RunRepository(database_path)
    run_repository.initialize()
    run_repository.save_manifest(
        create_manifest("run-001")
    )

    write_quality_csv(
        quality_path,
        [
            create_csv_row(1, "stable", 0.8),
            create_csv_row(2, "weak", 0.3),
        ],
    )

    first_summary = import_evaluated_tracks(
        database_path=database_path,
        quality_path=quality_path,
        run_id="run-001",
    )

    second_summary = import_evaluated_tracks(
        database_path=database_path,
        quality_path=quality_path,
        run_id="run-001",
    )

    assert first_summary[
        "database_track_count"
    ] == 2

    assert second_summary[
        "database_track_count"
    ] == 2


def test_import_rejects_unknown_run(tmp_path):
    database_path = tmp_path / "world.sqlite3"
    quality_path = tmp_path / "quality.csv"

    run_repository = RunRepository(database_path)
    run_repository.initialize()

    write_quality_csv(
        quality_path,
        [
            create_csv_row(1, "stable", 0.8),
        ],
    )

    with pytest.raises(
        ValueError,
        match="unknown run",
    ):
        import_evaluated_tracks(
            database_path=database_path,
            quality_path=quality_path,
            run_id="missing-run",
        )


def test_main_imports_latest_run_tracks(
    tmp_path,
    capsys,
):
    database_path = tmp_path / "world.sqlite3"
    quality_path = tmp_path / "quality.csv"
    config_path = tmp_path / "pipeline.json"

    latest_manifest_path = (
        quality_path.parent
        / "aegis_run_manifest.json"
    )

    run_repository = RunRepository(database_path)
    run_repository.initialize()
    run_repository.save_manifest(
        create_manifest("latest-run")
    )

    write_quality_csv(
        quality_path,
        [
            create_csv_row(1, "stable", 0.8),
        ],
    )

    latest_manifest_path.write_text(
        json.dumps(
            {
                "run_id": "latest-run",
            }
        ),
        encoding="utf-8",
    )

    write_config(
        path=config_path,
        database_path=database_path,
        quality_path=quality_path,
    )

    result = main(
        [
            "--config",
            str(config_path),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert result == 0
    assert summary["run_id"] == "latest-run"
    assert summary["imported"] == 1
