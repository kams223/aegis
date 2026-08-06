import json
from pathlib import Path

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.run_manifest import (
    RunManifest,
    calculate_sha256,
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


def test_run_manifest_records_successful_run(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"
    manifest_path = output_directory / "manifest.json"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    manifest = RunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=manifest_path,
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

    saved = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    assert saved["schema_version"] == 1
    assert saved["status"] == "completed"
    assert saved["exit_code"] == 0
    assert saved["duration_seconds"] == 3.0

    assert saved["input"]["exists"] is True
    assert saved["input"]["size_bytes"] == 15
    assert len(saved["input"]["sha256"]) == 64

    assert saved["model"]["model_path"] == (
        "test-model.pt"
    )

    assert len(saved["stages"]) == 1
    assert saved["stages"][0]["status"] == "completed"
