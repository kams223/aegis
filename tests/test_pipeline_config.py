import json

import pytest

from aegis.core.pipeline_config import PipelineConfig


def valid_config() -> dict:
    """Return a complete valid pipeline configuration."""

    return {
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
            "video_path": "outputs/videos/tracked.mp4",
            "observations_path": "outputs/data/observations.csv",
            "summaries_path": "outputs/data/summaries.csv",
            "quality_path": "outputs/data/quality.csv",
        },
        "quality": {
            "minimum_stable_observations": 5,
            "minimum_stable_duration": 0.2,
            "minimum_stable_confidence": 0.5,
        },
    }


def test_pipeline_config_loads_valid_json(tmp_path):
    config_path = tmp_path / "pipeline.json"

    config_path.write_text(
        json.dumps(valid_config()),
        encoding="utf-8",
    )

    config = PipelineConfig.from_file(config_path)

    assert config.model_path == "yolo11n.pt"
    assert config.confidence_threshold == 0.35
    assert config.image_size == 640
    assert config.device == "cpu"
    assert config.minimum_stable_observations == 5


def test_pipeline_config_rejects_invalid_confidence():
    raw_config = valid_config()
    raw_config["model"]["confidence_threshold"] = 1.5

    with pytest.raises(
        ValueError,
        match="confidence_threshold",
    ):
        PipelineConfig.from_dict(raw_config)


def test_pipeline_config_rejects_missing_section():
    raw_config = valid_config()
    del raw_config["output"]

    with pytest.raises(
        ValueError,
        match="Invalid pipeline configuration",
    ):
        PipelineConfig.from_dict(raw_config)


def test_pipeline_config_rejects_duplicate_outputs():
    raw_config = valid_config()

    raw_config["output"]["quality_path"] = (
        raw_config["output"]["summaries_path"]
    )

    with pytest.raises(
        ValueError,
        match="output paths must be unique",
    ):
        PipelineConfig.from_dict(raw_config)
