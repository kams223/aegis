import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("configs/pipeline.json")


@dataclass(frozen=True)
class PipelineConfig:
    """Validated configuration for the offline Aegis pipeline."""

    input_video_path: Path

    model_path: str
    tracker_config: str
    confidence_threshold: float
    image_size: int
    device: str

    output_video_path: Path
    observations_path: Path
    summaries_path: Path
    quality_path: Path

    minimum_stable_observations: int
    minimum_stable_duration: float
    minimum_stable_confidence: float

    @classmethod
    def from_file(
        cls,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> "PipelineConfig":
        """Load and validate a JSON pipeline configuration."""

        if not config_path.is_file():
            raise FileNotFoundError(
                f"Pipeline configuration not found: {config_path}"
            )

        try:
            with config_path.open(
                mode="r",
                encoding="utf-8",
            ) as config_file:
                raw_config = json.load(config_file)

        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSON configuration: {error}"
            ) from error

        return cls.from_dict(raw_config)

    @classmethod
    def from_dict(
        cls,
        raw_config: dict[str, Any],
    ) -> "PipelineConfig":
        """Construct and validate configuration data."""

        try:
            input_config = raw_config["input"]
            model_config = raw_config["model"]
            output_config = raw_config["output"]
            quality_config = raw_config["quality"]

            config = cls(
                input_video_path=Path(
                    input_config["video_path"]
                ),
                model_path=str(
                    model_config["model_path"]
                ),
                tracker_config=str(
                    model_config["tracker_config"]
                ),
                confidence_threshold=float(
                    model_config["confidence_threshold"]
                ),
                image_size=int(
                    model_config["image_size"]
                ),
                device=str(
                    model_config["device"]
                ),
                output_video_path=Path(
                    output_config["video_path"]
                ),
                observations_path=Path(
                    output_config["observations_path"]
                ),
                summaries_path=Path(
                    output_config["summaries_path"]
                ),
                quality_path=Path(
                    output_config["quality_path"]
                ),
                minimum_stable_observations=int(
                    quality_config[
                        "minimum_stable_observations"
                    ]
                ),
                minimum_stable_duration=float(
                    quality_config[
                        "minimum_stable_duration"
                    ]
                ),
                minimum_stable_confidence=float(
                    quality_config[
                        "minimum_stable_confidence"
                    ]
                ),
            )

        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid pipeline configuration: {error}"
            ) from error

        config.validate()
        return config

    def validate(self) -> None:
        """Reject unsafe or nonsensical configuration values."""

        if not self.model_path.strip():
            raise ValueError("model_path cannot be empty")

        if not self.tracker_config.strip():
            raise ValueError("tracker_config cannot be empty")

        if not self.device.strip():
            raise ValueError("device cannot be empty")

        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold must be between 0 and 1"
            )

        if self.image_size <= 0:
            raise ValueError("image_size must be positive")

        if self.minimum_stable_observations <= 0:
            raise ValueError(
                "minimum_stable_observations must be positive"
            )

        if self.minimum_stable_duration < 0:
            raise ValueError(
                "minimum_stable_duration cannot be negative"
            )

        if not 0.0 <= self.minimum_stable_confidence <= 1.0:
            raise ValueError(
                "minimum_stable_confidence must be "
                "between 0 and 1"
            )

        output_paths = [
            self.output_video_path,
            self.observations_path,
            self.summaries_path,
            self.quality_path,
        ]

        if len(set(output_paths)) != len(output_paths):
            raise ValueError(
                "Pipeline output paths must be unique"
            )
