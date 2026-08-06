import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aegis.core.pipeline_config import PipelineConfig


def utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat()


def calculate_sha256(path: Path) -> str:
    """Calculate a file's SHA-256 fingerprint."""

    digest = hashlib.sha256()

    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


class RunManifest:
    """Create an auditable record of one pipeline execution."""

    def __init__(
        self,
        config: PipelineConfig,
        config_path: Path,
        output_path: Path | None = None,
    ):
        self.config = config
        self.config_path = config_path

        self.output_path = (
            output_path
            if output_path is not None
            else config.quality_path.parent
            / "aegis_run_manifest.json"
        )

        self.started_at: str | None = None
        self.started_monotonic: float | None = None

        self.data: dict[str, Any] = {}

    def start(self, monotonic_time: float) -> None:
        """Initialize and persist a running manifest."""

        self.started_at = utc_now()
        self.started_monotonic = monotonic_time

        input_exists = self.config.input_video_path.is_file()

        input_metadata = {
            "path": str(self.config.input_video_path),
            "exists": input_exists,
            "size_bytes": (
                self.config.input_video_path.stat().st_size
                if input_exists
                else None
            ),
            "sha256": (
                calculate_sha256(
                    self.config.input_video_path
                )
                if input_exists
                else None
            ),
        }

        self.data = {
            "schema_version": 1,
            "status": "running",
            "started_at_utc": self.started_at,
            "finished_at_utc": None,
            "duration_seconds": None,
            "exit_code": None,
            "configuration_path": str(
                self.config_path
            ),
            "input": input_metadata,
            "model": {
                "model_path": self.config.model_path,
                "tracker_config": (
                    self.config.tracker_config
                ),
                "confidence_threshold": (
                    self.config.confidence_threshold
                ),
                "image_size": self.config.image_size,
                "device": self.config.device,
            },
            "quality_thresholds": {
                "minimum_stable_observations": (
                    self.config
                    .minimum_stable_observations
                ),
                "minimum_stable_duration": (
                    self.config.minimum_stable_duration
                ),
                "minimum_stable_confidence": (
                    self.config
                    .minimum_stable_confidence
                ),
            },
            "outputs": {
                "video": str(
                    self.config.output_video_path
                ),
                "observations": str(
                    self.config.observations_path
                ),
                "summaries": str(
                    self.config.summaries_path
                ),
                "quality": str(
                    self.config.quality_path
                ),
            },
            "stages": [],
        }

        self.write()

    def record_stage(
        self,
        name: str,
        status: str,
        duration_seconds: float,
        exit_code: int,
    ) -> None:
        """Append one completed stage result."""

        self.data["stages"].append(
            {
                "name": name,
                "status": status,
                "duration_seconds": round(
                    duration_seconds,
                    3,
                ),
                "exit_code": exit_code,
            }
        )

        self.write()

    def finish(
        self,
        status: str,
        exit_code: int,
        monotonic_time: float,
    ) -> None:
        """Finalize the manifest."""

        if self.started_monotonic is None:
            raise RuntimeError(
                "Manifest must be started before it is finished"
            )

        self.data["status"] = status
        self.data["finished_at_utc"] = utc_now()
        self.data["duration_seconds"] = round(
            monotonic_time - self.started_monotonic,
            3,
        )
        self.data["exit_code"] = exit_code

        self.write()

    def write(self) -> None:
        """Atomically save the current manifest state."""

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.output_path.with_suffix(
            self.output_path.suffix + ".tmp"
        )

        temporary_path.write_text(
            json.dumps(
                self.data,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary_path.replace(self.output_path)
