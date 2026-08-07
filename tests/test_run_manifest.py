import csv
import json
from pathlib import Path

import pytest

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.run_manifest import (
    RunManifest,
    calculate_sha256,
    generate_run_id,
    validate_run_id,
)


def create_config(
    input_path: Path,
    output_directory: Path,
) -> PipelineConfig:
    """Create a synthetic configuration for testing."""

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
            },
            "quality": {
                "minimum_stable_observations": 5,
                "minimum_stable_duration": 0.2,
                "minimum_stable_confidence": 0.5,
            },
        }
    )


def write_processing_metrics(
    config: PipelineConfig,
) -> None:
    """Write a synthetic completed metrics artifact."""

    config.processing_metrics_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    config.processing_metrics_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "duration_seconds": 2.5,
                "video": {
                    "width": 1920,
                    "height": 1080,
                    "source_fps": 30.0,
                },
                "results": {
                    "frames_processed": 75,
                    "frame_detections": 120,
                    "tracked_observations": 100,
                    "unique_tracks": 8,
                    "average_processing_fps": 30.0,
                },
            }
        ),
        encoding="utf-8",
    )


def write_quality_data(
    config: PipelineConfig,
) -> None:
    """Write synthetic quality results."""

    config.quality_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with config.quality_path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=[
                "track_id",
                "quality_level",
            ],
        )

        writer.writeheader()

        writer.writerows(
            [
                {
                    "track_id": 1,
                    "quality_level": "stable",
                },
                {
                    "track_id": 2,
                    "quality_level": "stable",
                },
                {
                    "track_id": 3,
                    "quality_level": "tentative",
                },
                {
                    "track_id": 4,
                    "quality_level": "weak",
                },
            ]
        )


def test_calculate_sha256(tmp_path):
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"aegis-test-data")

    fingerprint = calculate_sha256(input_path)

    assert len(fingerprint) == 64
    assert fingerprint == calculate_sha256(input_path)


def test_generate_run_id_is_valid_and_unique():
    first_run_id = generate_run_id()
    second_run_id = generate_run_id()

    assert first_run_id != second_run_id
    assert validate_run_id(first_run_id) == first_run_id
    assert validate_run_id(second_run_id) == second_run_id


def test_validate_run_id_rejects_unsafe_value():
    with pytest.raises(ValueError):
        validate_run_id("../unsafe-run")


def test_run_manifest_records_successful_run(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"
    manifest_path = output_directory / "manifest.json"
    history_directory = output_directory / "runs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    write_processing_metrics(config)
    write_quality_data(config)

    manifest = RunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=manifest_path,
        history_directory=history_directory,
        run_id="test-run-001",
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

    archived_path = (
        history_directory / "test-run-001.json"
    )

    latest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    archived = json.loads(
        archived_path.read_text(encoding="utf-8")
    )

    assert latest == archived
    assert latest["schema_version"] == 3
    assert latest["run_id"] == "test-run-001"
    assert latest["status"] == "completed"
    assert latest["exit_code"] == 0
    assert latest["duration_seconds"] == 3.0

    assert latest["input"]["exists"] is True
    assert latest["input"]["size_bytes"] == 15
    assert len(latest["input"]["sha256"]) == 64

    assert latest["model"]["model_path"] == (
        "test-model.pt"
    )

    assert len(latest["stages"]) == 1
    assert latest["stages"][0]["status"] == "completed"

    assert latest["outputs"]["latest_manifest"] == (
        str(manifest_path)
    )
    assert latest["outputs"]["archived_manifest"] == (
        str(archived_path)
    )

    performance = latest["performance"]

    assert performance["pipeline_duration_seconds"] == 3.0
    assert performance["stage_duration_seconds"] == 2.5

    assert performance[
        "initialization_overhead_seconds"
    ] == 0.5

    assert performance[
        "processing_metrics_available"
    ] is True

    assert performance["processing_metrics"]["results"][
        "frames_processed"
    ] == 75

    assert performance["quality_counts_available"] is True

    assert performance["quality_counts"] == {
        "stable": 2,
        "tentative": 1,
        "weak": 1,
        "total": 4,
    }


def test_completed_manifest_handles_missing_metrics(
    tmp_path,
):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    manifest = RunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=output_directory / "manifest.json",
        history_directory=output_directory / "runs",
        run_id="missing-metrics-run",
    )

    manifest.start(monotonic_time=10.0)

    manifest.finish(
        status="completed",
        exit_code=0,
        monotonic_time=11.0,
    )

    assert manifest.data["performance"][
        "processing_metrics_available"
    ] is False

    assert manifest.data["performance"][
        "processing_metrics_error"
    ] is not None

    assert manifest.data["performance"][
        "quality_counts_available"
    ] is False


def test_multiple_runs_preserve_history(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"
    manifest_path = output_directory / "manifest.json"
    history_directory = output_directory / "runs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    first_manifest = RunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=manifest_path,
        history_directory=history_directory,
        run_id="run-one",
    )

    first_manifest.start(monotonic_time=10.0)
    first_manifest.finish(
        status="completed",
        exit_code=0,
        monotonic_time=12.0,
    )

    second_manifest = RunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=manifest_path,
        history_directory=history_directory,
        run_id="run-two",
    )

    second_manifest.start(monotonic_time=20.0)
    second_manifest.finish(
        status="failed",
        exit_code=7,
        monotonic_time=23.0,
    )

    first_archive = json.loads(
        (
            history_directory / "run-one.json"
        ).read_text(encoding="utf-8")
    )

    second_archive = json.loads(
        (
            history_directory / "run-two.json"
        ).read_text(encoding="utf-8")
    )

    latest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    assert first_archive["run_id"] == "run-one"
    assert first_archive["status"] == "completed"

    assert second_archive["run_id"] == "run-two"
    assert second_archive["status"] == "failed"

    assert latest == second_archive
    assert latest["run_id"] == "run-two"

    archived_files = sorted(
        history_directory.glob("*.json")
    )

    assert len(archived_files) == 2
