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
            },
            "quality": {
                "minimum_stable_observations": 5,
                "minimum_stable_duration": 0.2,
                "minimum_stable_confidence": 0.5,
            },
        }
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
    assert latest["schema_version"] == 2
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
