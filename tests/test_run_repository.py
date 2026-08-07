import sqlite3

import pytest

from aegis.storage.run_repository import (
    SCHEMA_VERSION,
    RunRepository,
)


def create_manifest(
    run_id: str,
    finished_at_utc: str,
    fps: float = 2.5,
) -> dict:
    """Create a complete test pipeline manifest."""

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
            },
            {
                "name": "Per-track world-model summarization",
                "status": "completed",
                "duration_seconds": 0.02,
                "exit_code": 0,
            },
        ],
    }


def test_initialize_creates_schema(tmp_path):
    database_path = tmp_path / "aegis.sqlite3"
    repository = RunRepository(database_path)

    repository.initialize()

    assert database_path.is_file()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        schema_row = connection.execute(
            """
            SELECT value
            FROM metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

    assert "metadata" in tables
    assert "pipeline_runs" in tables
    assert "pipeline_stages" in tables
    assert schema_row[0] == str(SCHEMA_VERSION)


def test_save_and_load_manifest(tmp_path):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    repository.save_manifest(manifest)

    assert repository.count_runs() == 1
    assert repository.get_manifest("run-001") == manifest
    assert repository.get_manifest("missing-run") is None


def test_save_manifest_persists_stages(tmp_path):
    database_path = tmp_path / "aegis.sqlite3"
    repository = RunRepository(database_path)
    repository.initialize()

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    repository.save_manifest(manifest)

    with sqlite3.connect(database_path) as connection:
        stages = connection.execute(
            """
            SELECT
                stage_index,
                name,
                status,
                exit_code
            FROM pipeline_stages
            WHERE run_id = ?
            ORDER BY stage_index
            """,
            ("run-001",),
        ).fetchall()

    assert stages == [
        (
            0,
            "Video detection and tracking",
            "completed",
            0,
        ),
        (
            1,
            "Per-track world-model summarization",
            "completed",
            0,
        ),
    ]


def test_saving_same_run_updates_existing_record(
    tmp_path,
):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
        fps=2.0,
    )

    repository.save_manifest(manifest)

    manifest["performance"]["processing_metrics"][
        "results"
    ]["average_processing_fps"] = 3.0

    manifest["stages"] = [
        {
            "name": "Replacement stage",
            "status": "completed",
            "duration_seconds": 50.0,
            "exit_code": 0,
        }
    ]

    repository.save_manifest(manifest)

    stored = repository.get_manifest("run-001")
    runs = repository.list_runs()

    assert repository.count_runs() == 1
    assert stored == manifest
    assert runs[0]["average_processing_fps"] == 3.0

    with repository.connect() as connection:
        stage_count = connection.execute(
            """
            SELECT COUNT(*) AS stage_count
            FROM pipeline_stages
            WHERE run_id = ?
            """,
            ("run-001",),
        ).fetchone()["stage_count"]

    assert stage_count == 1


def test_list_runs_returns_newest_first(tmp_path):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    repository.save_manifest(
        create_manifest(
            run_id="older-run",
            finished_at_utc=(
                "2026-08-07T14:20:00+00:00"
            ),
            fps=2.0,
        )
    )

    repository.save_manifest(
        create_manifest(
            run_id="newer-run",
            finished_at_utc=(
                "2026-08-07T14:30:00+00:00"
            ),
            fps=2.5,
        )
    )

    runs = repository.list_runs(limit=1)

    assert len(runs) == 1
    assert runs[0]["run_id"] == "newer-run"
    assert runs[0]["average_processing_fps"] == 2.5
    assert (
        runs[0]["processing_metrics_available"]
        is True
    )


def test_save_manifest_rejects_missing_run_id(
    tmp_path,
):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    with pytest.raises(
        ValueError,
        match="run_id",
    ):
        repository.save_manifest({})


def test_save_manifest_rejects_invalid_stages(
    tmp_path,
):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )
    manifest["stages"] = "invalid"

    with pytest.raises(
        ValueError,
        match="stages",
    ):
        repository.save_manifest(manifest)


def test_list_runs_rejects_invalid_limit(tmp_path):
    repository = RunRepository(
        tmp_path / "aegis.sqlite3"
    )
    repository.initialize()

    with pytest.raises(
        ValueError,
        match="limit",
    ):
        repository.list_runs(limit=0)
