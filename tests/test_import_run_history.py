import json
from pathlib import Path

from aegis.storage.import_run_history import (
    import_run_history,
    load_archived_manifest,
    main,
)
from aegis.storage.run_repository import RunRepository


def create_manifest(
    run_id: str,
    finished_at_utc: str,
) -> dict:
    """Create a test archived manifest."""

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
                    "average_processing_fps": 2.5,
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


def write_manifest(
    history_directory: Path,
    manifest: dict,
) -> Path:
    """Write one archived test manifest."""

    history_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        history_directory
        / f"{manifest['run_id']}.json"
    )

    path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    return path


def create_config_file(
    path: Path,
    database_path: Path,
) -> None:
    """Write a complete test pipeline configuration."""

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
                    "quality_path": (
                        "outputs/data/quality.csv"
                    ),
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


def test_load_archived_manifest(tmp_path):
    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    path = write_manifest(
        history_directory=tmp_path,
        manifest=manifest,
    )

    assert load_archived_manifest(path) == manifest


def test_import_run_history_imports_all_runs(
    tmp_path,
):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"

    first_manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:20:00+00:00",
    )

    second_manifest = create_manifest(
        run_id="run-002",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    write_manifest(
        history_directory,
        first_manifest,
    )

    write_manifest(
        history_directory,
        second_manifest,
    )

    summary = import_run_history(
        history_directory=history_directory,
        database_path=database_path,
    )

    repository = RunRepository(database_path)

    assert summary["discovered"] == 2
    assert summary["imported"] == 2
    assert summary["failed"] == 0
    assert summary["database_run_count"] == 2

    assert repository.get_manifest(
        "run-001"
    ) == first_manifest

    assert repository.get_manifest(
        "run-002"
    ) == second_manifest


def test_import_run_history_is_idempotent(tmp_path):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    write_manifest(
        history_directory,
        manifest,
    )

    first_summary = import_run_history(
        history_directory=history_directory,
        database_path=database_path,
    )

    second_summary = import_run_history(
        history_directory=history_directory,
        database_path=database_path,
    )

    repository = RunRepository(database_path)

    assert first_summary["database_run_count"] == 1
    assert second_summary["database_run_count"] == 1
    assert repository.count_runs() == 1


def test_import_reports_invalid_json(tmp_path):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"

    history_directory.mkdir()

    invalid_path = (
        history_directory / "invalid-run.json"
    )

    invalid_path.write_text(
        "{invalid JSON",
        encoding="utf-8",
    )

    summary = import_run_history(
        history_directory=history_directory,
        database_path=database_path,
    )

    assert summary["discovered"] == 1
    assert summary["imported"] == 0
    assert summary["failed"] == 1
    assert summary["database_run_count"] == 0

    assert summary["errors"][0]["path"] == str(
        invalid_path
    )

    assert "Invalid JSON" in (
        summary["errors"][0]["error"]
    )


def test_import_rejects_filename_mismatch(tmp_path):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"

    history_directory.mkdir()

    manifest = create_manifest(
        run_id="actual-run",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    mismatched_path = (
        history_directory / "different-run.json"
    )

    mismatched_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    summary = import_run_history(
        history_directory=history_directory,
        database_path=database_path,
    )

    assert summary["imported"] == 0
    assert summary["failed"] == 1

    assert "does not match" in (
        summary["errors"][0]["error"]
    )


def test_main_imports_configured_history(
    tmp_path,
    capsys,
):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"
    config_path = tmp_path / "pipeline.json"

    manifest = create_manifest(
        run_id="run-001",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    write_manifest(
        history_directory,
        manifest,
    )

    create_config_file(
        path=config_path,
        database_path=database_path,
    )

    result = main(
        [
            "--config",
            str(config_path),
            "--history-directory",
            str(history_directory),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert result == 0
    assert summary["imported"] == 1
    assert summary["failed"] == 0

    repository = RunRepository(database_path)

    assert repository.count_runs() == 1
