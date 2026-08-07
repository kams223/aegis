import sqlite3
from pathlib import Path
from typing import Any


TRACK_SCHEMA_VERSION = 1

QUALITY_LEVELS = {
    "stable",
    "tentative",
    "weak",
}


class TrackRepository:
    """Persist and query evaluated track snapshots."""

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
        """Create evaluated-track storage."""

        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluated_tracks (
                    run_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    dominant_label TEXT NOT NULL,
                    quality_level TEXT NOT NULL,
                    quality_reason TEXT NOT NULL,
                    observation_count INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    average_confidence REAL NOT NULL,
                    displacement_pixels REAL NOT NULL,
                    first_frame INTEGER NOT NULL,
                    last_frame INTEGER NOT NULL,
                    first_seen_seconds REAL NOT NULL,
                    last_seen_seconds REAL NOT NULL,
                    start_center_x REAL NOT NULL,
                    start_center_y REAL NOT NULL,
                    end_center_x REAL NOT NULL,
                    end_center_y REAL NOT NULL,
                    PRIMARY KEY (run_id, track_id),
                    FOREIGN KEY (run_id)
                        REFERENCES pipeline_runs(run_id)
                        ON DELETE CASCADE,
                    CHECK (
                        quality_level IN (
                            'stable',
                            'tentative',
                            'weak'
                        )
                    )
                );

                CREATE INDEX IF NOT EXISTS
                    idx_evaluated_tracks_run_quality
                ON evaluated_tracks(
                    run_id,
                    quality_level
                );

                CREATE INDEX IF NOT EXISTS
                    idx_evaluated_tracks_run_confidence
                ON evaluated_tracks(
                    run_id,
                    average_confidence DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_evaluated_tracks_label
                ON evaluated_tracks(
                    dominant_label
                );
                """
            )

            connection.execute(
                """
                INSERT INTO metadata(key, value)
                VALUES ('track_schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value
                """,
                (str(TRACK_SCHEMA_VERSION),),
            )

    def replace_run_tracks(
        self,
        run_id: str,
        tracks: list[dict[str, Any]],
    ) -> int:
        """Replace all evaluated tracks for one run."""

        if not run_id:
            raise ValueError("run_id cannot be empty")

        normalized_tracks = [
            self._normalize_track(track)
            for track in tracks
        ]

        track_ids = [
            track["track_id"]
            for track in normalized_tracks
        ]

        if len(track_ids) != len(set(track_ids)):
            raise ValueError(
                "Track IDs must be unique within one run"
            )

        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM evaluated_tracks
                WHERE run_id = ?
                """,
                (run_id,),
            )

            for track in normalized_tracks:
                connection.execute(
                    """
                    INSERT INTO evaluated_tracks (
                        run_id,
                        track_id,
                        dominant_label,
                        quality_level,
                        quality_reason,
                        observation_count,
                        duration_seconds,
                        average_confidence,
                        displacement_pixels,
                        first_frame,
                        last_frame,
                        first_seen_seconds,
                        last_seen_seconds,
                        start_center_x,
                        start_center_y,
                        end_center_x,
                        end_center_y
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        run_id,
                        track["track_id"],
                        track["dominant_label"],
                        track["quality_level"],
                        track["quality_reason"],
                        track["observation_count"],
                        track["duration_seconds"],
                        track["average_confidence"],
                        track["displacement_pixels"],
                        track["first_frame"],
                        track["last_frame"],
                        track["first_seen_seconds"],
                        track["last_seen_seconds"],
                        track["start_position"]["x"],
                        track["start_position"]["y"],
                        track["end_position"]["x"],
                        track["end_position"]["y"],
                    ),
                )

        return len(normalized_tracks)

    def count_tracks(
        self,
        run_id: str,
    ) -> int:
        """Return the number of tracks for one run."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS track_count
                FROM evaluated_tracks
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        return int(row["track_count"])

    def list_tracks(
        self,
        run_id: str,
        quality: str | None = None,
        minimum_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return filtered evaluated tracks."""

        if quality is not None:
            self._validate_quality(quality)

        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                "minimum_confidence must be between 0 and 1"
            )

        if limit < 1:
            raise ValueError("limit must be positive")

        query = """
            SELECT *
            FROM evaluated_tracks
            WHERE run_id = ?
              AND average_confidence >= ?
        """

        parameters: list[Any] = [
            run_id,
            minimum_confidence,
        ]

        if quality is not None:
            query += """
              AND quality_level = ?
            """
            parameters.append(quality)

        query += """
            ORDER BY
                average_confidence DESC,
                track_id ASC
            LIMIT ?
        """

        parameters.append(limit)

        with self.connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [
            self._row_to_track(row)
            for row in rows
        ]

    def get_track(
        self,
        run_id: str,
        track_id: int,
    ) -> dict[str, Any] | None:
        """Return one evaluated track."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM evaluated_tracks
                WHERE run_id = ?
                  AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_track(row)

    def quality_counts(
        self,
        run_id: str,
    ) -> dict[str, int]:
        """Return quality-level counts for one run."""

        counts = {
            "stable": 0,
            "tentative": 0,
            "weak": 0,
        }

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    quality_level,
                    COUNT(*) AS quality_count
                FROM evaluated_tracks
                WHERE run_id = ?
                GROUP BY quality_level
                """,
                (run_id,),
            ).fetchall()

        for row in rows:
            counts[row["quality_level"]] = int(
                row["quality_count"]
            )

        return counts

    @staticmethod
    def _validate_quality(quality: str) -> None:
        """Reject unsupported quality levels."""

        if quality not in QUALITY_LEVELS:
            raise ValueError(
                "quality must be stable, tentative, or weak"
            )

    def _normalize_track(
        self,
        track: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and normalize one track dictionary."""

        try:
            quality_level = str(
                track["quality_level"]
            )

            self._validate_quality(quality_level)

            start_position = track["start_position"]
            end_position = track["end_position"]

            normalized = {
                "track_id": int(track["track_id"]),
                "dominant_label": str(
                    track["dominant_label"]
                ),
                "quality_level": quality_level,
                "quality_reason": str(
                    track["quality_reason"]
                ),
                "observation_count": int(
                    track["observation_count"]
                ),
                "duration_seconds": float(
                    track["duration_seconds"]
                ),
                "average_confidence": float(
                    track["average_confidence"]
                ),
                "displacement_pixels": float(
                    track["displacement_pixels"]
                ),
                "first_frame": int(
                    track["first_frame"]
                ),
                "last_frame": int(
                    track["last_frame"]
                ),
                "first_seen_seconds": float(
                    track["first_seen_seconds"]
                ),
                "last_seen_seconds": float(
                    track["last_seen_seconds"]
                ),
                "start_position": {
                    "x": float(start_position["x"]),
                    "y": float(start_position["y"]),
                },
                "end_position": {
                    "x": float(end_position["x"]),
                    "y": float(end_position["y"]),
                },
            }

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"Invalid evaluated track: {error}"
            ) from error

        if normalized["track_id"] < 0:
            raise ValueError(
                "track_id cannot be negative"
            )

        if normalized["observation_count"] < 0:
            raise ValueError(
                "observation_count cannot be negative"
            )

        if not (
            0.0
            <= normalized["average_confidence"]
            <= 1.0
        ):
            raise ValueError(
                "average_confidence must be between 0 and 1"
            )

        return normalized

    @staticmethod
    def _row_to_track(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """Convert one SQLite row to API track data."""

        return {
            "track_id": int(row["track_id"]),
            "dominant_label": row["dominant_label"],
            "quality_level": row["quality_level"],
            "quality_reason": row["quality_reason"],
            "observation_count": int(
                row["observation_count"]
            ),
            "duration_seconds": float(
                row["duration_seconds"]
            ),
            "average_confidence": float(
                row["average_confidence"]
            ),
            "displacement_pixels": float(
                row["displacement_pixels"]
            ),
            "first_frame": int(row["first_frame"]),
            "last_frame": int(row["last_frame"]),
            "first_seen_seconds": float(
                row["first_seen_seconds"]
            ),
            "last_seen_seconds": float(
                row["last_seen_seconds"]
            ),
            "start_position": {
                "x": float(row["start_center_x"]),
                "y": float(row["start_center_y"]),
            },
            "end_position": {
                "x": float(row["end_center_x"]),
                "y": float(row["end_center_y"]),
            },
        }
