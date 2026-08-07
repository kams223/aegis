import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat()


class ProcessingMetricsRecorder:
    """Record video-processing performance metrics."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.started_monotonic: float | None = None

        self.data: dict[str, Any] = {}

    def start(self, monotonic_time: float) -> None:
        """Initialize a running metrics record."""

        self.started_monotonic = monotonic_time

        self.data = {
            "schema_version": 1,
            "status": "running",
            "started_at_utc": utc_now(),
            "finished_at_utc": None,
            "duration_seconds": None,
            "error": None,
            "video": {
                "width": None,
                "height": None,
                "source_fps": None,
            },
            "results": {
                "frames_processed": 0,
                "frame_detections": 0,
                "tracked_observations": 0,
                "unique_tracks": 0,
                "average_processing_fps": 0.0,
            },
        }

        self.write()

    def set_video_metadata(
        self,
        width: int,
        height: int,
        source_fps: float,
    ) -> None:
        """Record source-video metadata."""

        self._require_started()

        self.data["video"] = {
            "width": width,
            "height": height,
            "source_fps": round(source_fps, 3),
        }

        self.write()

    def finish_success(
        self,
        monotonic_time: float,
        frames_processed: int,
        frame_detections: int,
        tracked_observations: int,
        unique_tracks: int,
    ) -> None:
        """Finalize a successful processing record."""

        duration_seconds = self._duration(
            monotonic_time
        )

        average_processing_fps = (
            frames_processed / duration_seconds
            if duration_seconds > 0
            else 0.0
        )

        self.data["status"] = "completed"
        self.data["finished_at_utc"] = utc_now()
        self.data["duration_seconds"] = round(
            duration_seconds,
            3,
        )
        self.data["error"] = None
        self.data["results"] = {
            "frames_processed": frames_processed,
            "frame_detections": frame_detections,
            "tracked_observations": tracked_observations,
            "unique_tracks": unique_tracks,
            "average_processing_fps": round(
                average_processing_fps,
                3,
            ),
        }

        self.write()

    def finish_failure(
        self,
        monotonic_time: float,
        error: str,
        status: str = "failed",
    ) -> None:
        """Finalize a failed or interrupted record."""

        duration_seconds = self._duration(
            monotonic_time
        )

        self.data["status"] = status
        self.data["finished_at_utc"] = utc_now()
        self.data["duration_seconds"] = round(
            duration_seconds,
            3,
        )
        self.data["error"] = error

        self.write()

    def _duration(
        self,
        monotonic_time: float,
    ) -> float:
        """Calculate elapsed time from the start."""

        self._require_started()

        return monotonic_time - self.started_monotonic

    def _require_started(self) -> None:
        """Reject updates before recorder initialization."""

        if self.started_monotonic is None:
            raise RuntimeError(
                "Processing metrics recorder must be started"
            )

    def write(self) -> None:
        """Atomically persist the current metrics record."""

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.output_path.with_name(
            f".{self.output_path.name}.tmp"
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
