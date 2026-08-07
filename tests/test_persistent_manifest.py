import json
from pathlib import Path

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.persistent_manifest import (
    PersistentRunManifest,
)
from aegis.storage.run_repository import RunRepository


def create_config(
    input_path: Path,
    output_directory: Path,
) -> PipelineConfig:
    """Create a test configuration with SQLite storage."""

    return PipelineConfig.from_dict(
        {
            "input": {
                "video_path": str(input_path),
            },
            "model": {
                "model_path": "test-model.pt",
                "tracker_config": "test-tracker.yaml",
                "confidence_threshold": 0.4,
                "image_size": 320,
                "device": "cpu",
            },
            "output": {
                "video_path": str(
                    output_directory / "tracked.mp4"
                ),
                "observations_path": str(
                    output_directory / "observations.csv"
                ),
                "summaries_path": str(
                    output_directory / "summaries.csv"
                ),
                "quality_path": str(
                    output_directory / "quality.csv"
                ),
                "processing_metrics_path": str(
                    output_directory
                    / "processing_metrics.json"
                ),
                "database_path": str(
                    output_directory
                    / "world_model.sqlite3"
                ),
            },
            "quality": {
                "minimum_stable_observations": 5,
                "minimum_stable_duration": 0.2,
                "minimum_stable_confidence": 0.5,
            },
        }
    )


def test_start_persists_running_manifest(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    repository = RunRepository(config.database_path)

    manifest = PersistentRunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=output_directory / "manifest.json",
        history_directory=output_directory / "runs",
        run_id="persistent-run-001",
        repository=repository,
    )

    manifest.start(monotonic_time=100.0)

    stored = repository.get_manifest(
        "persistent-run-001"
    )

    assert config.database_path.is_file()
    assert repository.count_runs() == 1
    assert stored is not None
    assert stored["status"] == "running"
    assert stored["exit_code"] is None

    assert stored["outputs"]["database"] == str(
        config.database_path
    )


def test_stage_updates_existing_database_run(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    repository = RunRepository(config.database_path)

    manifest = PersistentRunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=output_directory / "manifest.json",
        history_directory=output_directory / "runs",
        run_id="persistent-run-002",
        repository=repository,
    )

    manifest.start(monotonic_time=100.0)

    manifest.record_stage(
        name="Synthetic stage",
        status="completed",
        duration_seconds=2.5,
        exit_code=0,
    )

    stored = repository.get_manifest(
        "persistent-run-002"
    )

    assert repository.count_runs() == 1
    assert stored is not None
    assert len(stored["stages"]) == 1

    assert stored["stages"][0]["name"] == (
        "Synthetic stage"
    )

    with repository.connect() as connection:
        stage_row = connection.execute(
            """
            SELECT
                name,
                status,
                duration_seconds,
                exit_code
            FROM pipeline_stages
            WHERE run_id = ?
            """,
            ("persistent-run-002",),
        ).fetchone()

    assert stage_row["name"] == "Synthetic stage"
    assert stage_row["status"] == "completed"
    assert stage_row["duration_seconds"] == 2.5
    assert stage_row["exit_code"] == 0


def test_finish_keeps_json_and_database_identical(
    tmp_path,
):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"
    manifest_path = output_directory / "manifest.json"
    history_directory = output_directory / "runs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    repository = RunRepository(config.database_path)

    manifest = PersistentRunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=manifest_path,
        history_directory=history_directory,
        run_id="persistent-run-003",
        repository=repository,
    )

    manifest.start(monotonic_time=100.0)

    manifest.record_stage(
        name="Synthetic stage",
        status="completed",
        duration_seconds=2.5,
        exit_code=0,
    )

    manifest.finish(
        status="completed",
        exit_code=0,
        monotonic_time=103.0,
    )

    latest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    archived = json.loads(
        (
            history_directory
            / "persistent-run-003.json"
        ).read_text(encoding="utf-8")
    )

    stored = repository.get_manifest(
        "persistent-run-003"
    )

    assert latest == archived
    assert latest == stored

    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["exit_code"] == 0
    assert stored["duration_seconds"] == 3.0

    assert stored["outputs"]["database"] == str(
        config.database_path
    )

    runs = repository.list_runs()

    assert len(runs) == 1
    assert runs[0]["run_id"] == "persistent-run-003"
    assert runs[0]["status"] == "completed"


def test_failed_run_is_persisted(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    repository = RunRepository(config.database_path)

    manifest = PersistentRunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=output_directory / "manifest.json",
        history_directory=output_directory / "runs",
        run_id="persistent-run-004",
        repository=repository,
    )

    manifest.start(monotonic_time=100.0)

    manifest.record_stage(
        name="Failed synthetic stage",
        status="failed",
        duration_seconds=1.0,
        exit_code=7,
    )

    manifest.finish(
        status="failed",
        exit_code=7,
        monotonic_time=101.5,
    )

    stored = repository.get_manifest(
        "persistent-run-004"
    )

    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["exit_code"] == 7
    assert stored["duration_seconds"] == 1.5
    assert repository.count_runs() == 1
