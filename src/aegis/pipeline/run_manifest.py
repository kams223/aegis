import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aegis.core.pipeline_config import PipelineConfig


RUN_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


def utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    """Generate a sortable and collision-resistant run ID."""

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    suffix = uuid.uuid4().hex[:8]

    return f"{timestamp}-{suffix}"


def validate_run_id(run_id: str) -> str:
    """Validate a run ID before using it in a file path."""

    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "Run ID must contain only letters, numbers, "
            "periods, underscores, or hyphens and must be "
            "between 1 and 128 characters."
        )

    return run_id


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
        history_directory: Path | None = None,
        run_id: str | None = None,
    ):
        self.config = config
        self.config_path = config_path

        self.output_path = (
            output_path
            if output_path is not None
            else config.quality_path.parent
            / "aegis_run_manifest.json"
        )

        self.history_directory = (
            history_directory
            if history_directory is not None
            else self.output_path.parent / "runs"
        )

        self.run_id = validate_run_id(
            run_id if run_id is not None else generate_run_id()
        )

        self.archive_path = (
            self.history_directory / f"{self.run_id}.json"
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
            "schema_version": 2,
            "run_id": self.run_id,
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
                "latest_manifest": str(
                    self.output_path
                ),
                "archived_manifest": str(
                    self.archive_path
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
        """Append one pipeline-stage result."""

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
        """Finalize and persist the manifest."""

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
        """Atomically save the latest and archived manifests."""

        serialized_manifest = (
            json.dumps(
                self.data,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        self._atomic_write(
            path=self.archive_path,
            content=serialized_manifest,
        )

        self._atomic_write(
            path=self.output_path,
            content=serialized_manifest,
        )

    def _atomic_write(
        self,
        path: Path,
        content: str,
    ) -> None:
        """Write one file using an atomic replacement."""

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = path.with_name(
            f".{path.name}.{self.run_id}.tmp"
        )

        temporary_path.write_text(
            content,
            encoding="utf-8",
        )

        temporary_path.replace(path)
