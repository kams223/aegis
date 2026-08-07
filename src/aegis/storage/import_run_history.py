import argparse
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


def load_archived_manifest(path: Path) -> dict[str, Any]:
    """Load and validate one archived run manifest."""

    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8")
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON: {error}"
        ) from error

    except OSError as error:
        raise OSError(
            f"Could not read manifest: {error}"
        ) from error

    if not isinstance(manifest, dict):
        raise ValueError(
            "Manifest root value must be an object"
        )

    run_id = manifest.get("run_id")

    if not isinstance(run_id, str):
        raise ValueError(
            "Manifest must contain a string run_id"
        )

    validated_run_id = validate_run_id(run_id)

    if validated_run_id != path.stem:
        raise ValueError(
            "Manifest run_id does not match its filename"
        )

    return manifest


def import_run_history(
    history_directory: Path,
    database_path: Path,
) -> dict[str, Any]:
    """Import archived JSON manifests into SQLite."""

    repository = RunRepository(database_path)
    repository.initialize()

    manifest_paths = sorted(
        history_directory.glob("*.json")
    )

    imported_run_ids: list[str] = []
    errors: list[dict[str, str]] = []

    for manifest_path in manifest_paths:
        try:
            manifest = load_archived_manifest(
                manifest_path
            )

            repository.save_manifest(manifest)

            imported_run_ids.append(
                str(manifest["run_id"])
            )

        except (
            OSError,
            ValueError,
            sqlite3.Error,
        ) as error:
            errors.append(
                {
                    "path": str(manifest_path),
                    "error": str(error),
                }
            )

    return {
        "history_directory": str(history_directory),
        "database_path": str(database_path),
        "discovered": len(manifest_paths),
        "imported": len(imported_run_ids),
        "failed": len(errors),
        "database_run_count": repository.count_runs(),
        "imported_run_ids": imported_run_ids,
        "errors": errors,
    }


def parse_arguments(
    arguments: list[str] | None = None,
) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        prog="aegis-import-run-history",
        description=(
            "Import archived Aegis pipeline run manifests "
            "into SQLite."
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
        "--history-directory",
        type=Path,
        default=None,
        help=(
            "Archived manifest directory. By default, "
            "the runs directory beside the quality output "
            "is used."
        ),
    )

    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "SQLite database path. By default, the path "
            "from the pipeline configuration is used."
        ),
    )

    return parser.parse_args(arguments)


def main(
    arguments: list[str] | None = None,
) -> int:
    """Load configuration and import archived manifests."""

    parsed_arguments = parse_arguments(arguments)

    try:
        config = PipelineConfig.from_file(
            parsed_arguments.config
        )

    except (FileNotFoundError, ValueError) as error:
        print(
            f"CONFIGURATION ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    history_directory = (
        parsed_arguments.history_directory
        if parsed_arguments.history_directory is not None
        else config.quality_path.parent / "runs"
    )

    database_path = (
        parsed_arguments.database
        if parsed_arguments.database is not None
        else config.database_path
    )

    try:
        summary = import_run_history(
            history_directory=history_directory,
            database_path=database_path,
        )

    except (OSError, sqlite3.Error) as error:
        print(
            f"DATABASE IMPORT ERROR: {error}",
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

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
