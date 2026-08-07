import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from aegis.core.pipeline_config import (
    DEFAULT_CONFIG_PATH,
    PipelineConfig,
)
from aegis.pipeline.run_manifest import validate_run_id
from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import TrackRepository


def convert_track_row(
    row: dict[str, str],
) -> dict[str, Any]:
    """Convert one quality CSV row to typed track data."""

    try:
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

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"Invalid evaluated-track row: {error}"
        ) from error


def load_evaluated_tracks(
    quality_path: Path,
) -> list[dict[str, Any]]:
    """Load typed evaluated tracks from CSV."""

    if not quality_path.is_file():
        raise FileNotFoundError(
            f"Track-quality file not found: {quality_path}"
        )

    try:
        with quality_path.open(
            mode="r",
            newline="",
            encoding="utf-8",
        ) as input_file:
            reader = csv.DictReader(input_file)

            if reader.fieldnames is None:
                raise ValueError(
                    "Track-quality CSV has no header"
                )

            return [
                convert_track_row(row)
                for row in reader
            ]

    except OSError as error:
        raise OSError(
            f"Could not read track-quality CSV: {error}"
        ) from error


def load_latest_run_id(
    manifest_path: Path,
) -> str:
    """Load and validate the latest manifest run ID."""

    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Latest run manifest not found: {manifest_path}"
        )

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid latest run manifest: {error}"
        ) from error

    except OSError as error:
        raise OSError(
            f"Could not read latest run manifest: {error}"
        ) from error

    if not isinstance(manifest, dict):
        raise ValueError(
            "Latest run manifest root must be an object"
        )

    run_id = manifest.get("run_id")

    if not isinstance(run_id, str):
        raise ValueError(
            "Latest run manifest must contain a run_id"
        )

    return validate_run_id(run_id)


def import_evaluated_tracks(
    database_path: Path,
    quality_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Replace one run's evaluated tracks from CSV."""

    validated_run_id = validate_run_id(run_id)

    run_repository = RunRepository(database_path)

    if run_repository.get_manifest(
        validated_run_id
    ) is None:
        raise ValueError(
            "Cannot import tracks for an unknown run: "
            f"{validated_run_id}"
        )

    tracks = load_evaluated_tracks(
        quality_path
    )

    track_repository = TrackRepository(
        database_path
    )
    track_repository.initialize()

    imported = track_repository.replace_run_tracks(
        run_id=validated_run_id,
        tracks=tracks,
    )

    return {
        "database_path": str(database_path),
        "quality_path": str(quality_path),
        "run_id": validated_run_id,
        "imported": imported,
        "database_track_count": (
            track_repository.count_tracks(
                validated_run_id
            )
        ),
        "quality_counts": (
            track_repository.quality_counts(
                validated_run_id
            )
        ),
    }


def parse_arguments(
    arguments: list[str] | None = None,
) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        prog="aegis-import-evaluated-tracks",
        description=(
            "Import Aegis evaluated tracks into SQLite."
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "Path to the pipeline JSON configuration "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )

    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Run that produced the quality CSV. "
            "By default, the latest manifest run ID is used."
        ),
    )

    parser.add_argument(
        "--quality-path",
        type=Path,
        default=None,
        help=(
            "Track-quality CSV path. By default, the "
            "configured quality output path is used."
        ),
    )

    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "SQLite database path. By default, the "
            "configured database path is used."
        ),
    )

    return parser.parse_args(arguments)


def main(
    arguments: list[str] | None = None,
) -> int:
    """Load configuration and import evaluated tracks."""

    parsed_arguments = parse_arguments(arguments)

    try:
        config = PipelineConfig.from_file(
            parsed_arguments.config
        )

        database_path = (
            parsed_arguments.database
            if parsed_arguments.database is not None
            else config.database_path
        )

        quality_path = (
            parsed_arguments.quality_path
            if parsed_arguments.quality_path is not None
            else config.quality_path
        )

        latest_manifest_path = (
            config.quality_path.parent
            / "aegis_run_manifest.json"
        )

        run_id = (
            validate_run_id(parsed_arguments.run_id)
            if parsed_arguments.run_id is not None
            else load_latest_run_id(
                latest_manifest_path
            )
        )

        summary = import_evaluated_tracks(
            database_path=database_path,
            quality_path=quality_path,
            run_id=run_id,
        )

    except (
        FileNotFoundError,
        OSError,
        ValueError,
        sqlite3.Error,
    ) as error:
        print(
            f"TRACK IMPORT ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
