import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class RunRepository:
    """Persist and query Aegis pipeline run manifests."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection."""

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    def initialize(self) -> None:
        """Create the database schema when it does not exist."""

        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    schema_version INTEGER,
                    status TEXT,
                    exit_code INTEGER,
                    configuration_path TEXT,
                    started_at_utc TEXT,
                    finished_at_utc TEXT,
                    duration_seconds REAL,
                    input_path TEXT,
                    input_sha256 TEXT,
                    model_path TEXT,
                    tracker_config TEXT,
                    device TEXT,
                    confidence_threshold REAL,
                    image_size INTEGER,
                    processing_metrics_available INTEGER NOT NULL,
                    average_processing_fps REAL,
                    frames_processed INTEGER,
                    frame_detections INTEGER,
                    tracked_observations INTEGER,
                    unique_tracks INTEGER,
                    processing_duration_seconds REAL,
                    initialization_overhead_seconds REAL,
                    pipeline_duration_seconds REAL,
                    manifest_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pipeline_stages (
                    run_id TEXT NOT NULL,
                    stage_index INTEGER NOT NULL,
                    name TEXT,
                    status TEXT,
                    duration_seconds REAL,
                    exit_code INTEGER,
                    PRIMARY KEY (run_id, stage_index),
                    FOREIGN KEY (run_id)
                        REFERENCES pipeline_runs(run_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_pipeline_runs_finished
                ON pipeline_runs(finished_at_utc DESC);

                CREATE INDEX IF NOT EXISTS
                    idx_pipeline_runs_status
                ON pipeline_runs(status);
                """
            )

            connection.execute(
                """
                INSERT INTO metadata(key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def save_manifest(
        self,
        manifest: dict[str, Any],
    ) -> None:
        """Insert or replace one complete pipeline run."""

        run_id = manifest.get("run_id")

        if not isinstance(run_id, str) or not run_id:
            raise ValueError(
                "Pipeline manifest must contain a run_id"
            )

        model = self._object_value(
            manifest.get("model")
        )
        input_metadata = self._object_value(
            manifest.get("input")
        )
        performance = self._object_value(
            manifest.get("performance")
        )
        processing_metrics = self._object_value(
            performance.get("processing_metrics")
        )
        processing_results = self._object_value(
            processing_metrics.get("results")
        )

        stages = manifest.get("stages", [])

        if not isinstance(stages, list):
            raise ValueError(
                "Pipeline manifest stages must be a list"
            )

        manifest_json = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id,
                    schema_version,
                    status,
                    exit_code,
                    configuration_path,
                    started_at_utc,
                    finished_at_utc,
                    duration_seconds,
                    input_path,
                    input_sha256,
                    model_path,
                    tracker_config,
                    device,
                    confidence_threshold,
                    image_size,
                    processing_metrics_available,
                    average_processing_fps,
                    frames_processed,
                    frame_detections,
                    tracked_observations,
                    unique_tracks,
                    processing_duration_seconds,
                    initialization_overhead_seconds,
                    pipeline_duration_seconds,
                    manifest_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    status = excluded.status,
                    exit_code = excluded.exit_code,
                    configuration_path = (
                        excluded.configuration_path
                    ),
                    started_at_utc = excluded.started_at_utc,
                    finished_at_utc = excluded.finished_at_utc,
                    duration_seconds = excluded.duration_seconds,
                    input_path = excluded.input_path,
                    input_sha256 = excluded.input_sha256,
                    model_path = excluded.model_path,
                    tracker_config = excluded.tracker_config,
                    device = excluded.device,
                    confidence_threshold = (
                        excluded.confidence_threshold
                    ),
                    image_size = excluded.image_size,
                    processing_metrics_available = (
                        excluded.processing_metrics_available
                    ),
                    average_processing_fps = (
                        excluded.average_processing_fps
                    ),
                    frames_processed = excluded.frames_processed,
                    frame_detections = excluded.frame_detections,
                    tracked_observations = (
                        excluded.tracked_observations
                    ),
                    unique_tracks = excluded.unique_tracks,
                    processing_duration_seconds = (
                        excluded.processing_duration_seconds
                    ),
                    initialization_overhead_seconds = (
                        excluded.initialization_overhead_seconds
                    ),
                    pipeline_duration_seconds = (
                        excluded.pipeline_duration_seconds
                    ),
                    manifest_json = excluded.manifest_json
                """,
                (
                    run_id,
                    manifest.get("schema_version"),
                    manifest.get("status"),
                    manifest.get("exit_code"),
                    manifest.get("configuration_path"),
                    manifest.get("started_at_utc"),
                    manifest.get("finished_at_utc"),
                    manifest.get("duration_seconds"),
                    input_metadata.get("path"),
                    input_metadata.get("sha256"),
                    model.get("model_path"),
                    model.get("tracker_config"),
                    model.get("device"),
                    model.get("confidence_threshold"),
                    model.get("image_size"),
                    int(
                        bool(
                            performance.get(
                                "processing_metrics_available",
                                False,
                            )
                        )
                    ),
                    processing_results.get(
                        "average_processing_fps"
                    ),
                    processing_results.get(
                        "frames_processed"
                    ),
                    processing_results.get(
                        "frame_detections"
                    ),
                    processing_results.get(
                        "tracked_observations"
                    ),
                    processing_results.get("unique_tracks"),
                    processing_metrics.get(
                        "duration_seconds"
                    ),
                    performance.get(
                        "initialization_overhead_seconds"
                    ),
                    performance.get(
                        "pipeline_duration_seconds"
                    ),
                    manifest_json,
                ),
            )

            connection.execute(
                """
                DELETE FROM pipeline_stages
                WHERE run_id = ?
                """,
                (run_id,),
            )

            for stage_index, stage_value in enumerate(stages):
                stage = self._object_value(stage_value)

                connection.execute(
                    """
                    INSERT INTO pipeline_stages (
                        run_id,
                        stage_index,
                        name,
                        status,
                        duration_seconds,
                        exit_code
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        stage_index,
                        stage.get("name"),
                        stage.get("status"),
                        stage.get("duration_seconds"),
                        stage.get("exit_code"),
                    ),
                )

    def get_manifest(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Return one stored manifest or None."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT manifest_json
                FROM pipeline_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        manifest = json.loads(row["manifest_json"])

        if not isinstance(manifest, dict):
            raise ValueError(
                "Stored pipeline manifest is not an object"
            )

        return manifest

    def list_runs(
        self,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return compact run records newest first."""

        if limit < 1:
            raise ValueError("limit must be positive")

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    run_id,
                    schema_version,
                    status,
                    exit_code,
                    started_at_utc,
                    finished_at_utc,
                    duration_seconds,
                    model_path,
                    device,
                    processing_metrics_available,
                    average_processing_fps,
                    frames_processed,
                    unique_tracks,
                    processing_duration_seconds,
                    initialization_overhead_seconds,
                    pipeline_duration_seconds
                FROM pipeline_runs
                ORDER BY
                    finished_at_utc DESC,
                    run_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                **dict(row),
                "processing_metrics_available": bool(
                    row["processing_metrics_available"]
                ),
            }
            for row in rows
        ]

    def count_runs(self) -> int:
        """Return the number of stored pipeline runs."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS run_count
                FROM pipeline_runs
                """
            ).fetchone()

        return int(row["run_count"])

    @staticmethod
    def _object_value(value: Any) -> dict[str, Any]:
        """Return a dictionary for an object-like value."""

        if isinstance(value, dict):
            return value

        return {}
