import json
import sqlite3
from pathlib import Path
from typing import Any

from aegis.pipeline.run_manifest import validate_run_id
from aegis.storage.run_repository import RunRepository


class RunHistoryError(RuntimeError):
    """Report invalid or unreadable run-history data."""


class RunHistoryStore:
    """Read run history from SQLite or archived JSON."""

    def __init__(
        self,
        database_path: Path,
        history_directory: Path,
    ):
        self.database_path = Path(database_path)
        self.history_directory = Path(
            history_directory
        )

    @property
    def uses_database(self) -> bool:
        """Return whether SQLite is the active data source."""

        return self.database_path.is_file()

    @property
    def source_name(self) -> str:
        """Return the active storage source name."""

        return (
            "sqlite"
            if self.uses_database
            else "json"
        )

    def count_runs(self) -> int:
        """Return the number of available archived runs."""

        if self.uses_database:
            repository = RunRepository(
                self.database_path
            )

            try:
                return repository.count_runs()

            except sqlite3.Error as error:
                raise RunHistoryError(
                    "Could not count SQLite pipeline runs: "
                    f"{error}"
                ) from error

        if not self.history_directory.is_dir():
            return 0

        return len(
            list(
                self.history_directory.glob("*.json")
            )
        )

    def list_manifests(
        self,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return full manifests newest first."""

        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")

        if self.uses_database:
            return self._list_database_manifests(
                limit=limit
            )

        return self._list_json_manifests(
            limit=limit
        )

    def get_manifest(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Return one full manifest by run ID."""

        validated_run_id = validate_run_id(run_id)

        if self.uses_database:
            repository = RunRepository(
                self.database_path
            )

            try:
                return repository.get_manifest(
                    validated_run_id
                )

            except (
                json.JSONDecodeError,
                sqlite3.Error,
                ValueError,
            ) as error:
                raise RunHistoryError(
                    "Could not load SQLite pipeline run "
                    f"{validated_run_id}: {error}"
                ) from error

        manifest_path = (
            self.history_directory
            / f"{validated_run_id}.json"
        )

        if not manifest_path.is_file():
            return None

        return self._load_json_manifest(
            manifest_path
        )

    def _list_database_manifests(
        self,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Return full manifests stored in SQLite."""

        repository = RunRepository(
            self.database_path
        )

        try:
            run_count = repository.count_runs()

            if run_count == 0:
                return []

            selected_limit = (
                min(limit, run_count)
                if limit is not None
                else run_count
            )

            run_summaries = repository.list_runs(
                limit=selected_limit
            )

            manifests: list[dict[str, Any]] = []

            for run_summary in run_summaries:
                run_id = run_summary.get("run_id")

                if not isinstance(run_id, str):
                    raise RunHistoryError(
                        "SQLite run record has no valid "
                        "run_id"
                    )

                manifest = repository.get_manifest(
                    run_id
                )

                if manifest is None:
                    raise RunHistoryError(
                        "SQLite run record has no stored "
                        f"manifest: {run_id}"
                    )

                manifests.append(manifest)

            return manifests

        except RunHistoryError:
            raise

        except (
            json.JSONDecodeError,
            sqlite3.Error,
            ValueError,
        ) as error:
            raise RunHistoryError(
                "Could not list SQLite pipeline runs: "
                f"{error}"
            ) from error

    def _list_json_manifests(
        self,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Return full manifests from archived JSON."""

        if not self.history_directory.is_dir():
            return []

        manifest_paths = sorted(
            self.history_directory.glob("*.json"),
            reverse=True,
        )

        if limit is not None:
            manifest_paths = manifest_paths[:limit]

        return [
            self._load_json_manifest(path)
            for path in manifest_paths
        ]

    def _load_json_manifest(
        self,
        path: Path,
    ) -> dict[str, Any]:
        """Load and validate one JSON manifest."""

        try:
            manifest = json.loads(
                path.read_text(encoding="utf-8")
            )

        except json.JSONDecodeError as error:
            raise RunHistoryError(
                f"Invalid pipeline run manifest "
                f"{path}: {error}"
            ) from error

        except OSError as error:
            raise RunHistoryError(
                f"Could not read pipeline run manifest "
                f"{path}: {error}"
            ) from error

        if not isinstance(manifest, dict):
            raise RunHistoryError(
                "Invalid pipeline run manifest "
                f"{path}: root value must be an object"
            )

        run_id = manifest.get("run_id")

        if not isinstance(run_id, str):
            raise RunHistoryError(
                "Invalid pipeline run manifest "
                f"{path}: run_id must be a string"
            )

        try:
            validated_run_id = validate_run_id(
                run_id
            )

        except ValueError as error:
            raise RunHistoryError(
                f"Invalid pipeline run manifest "
                f"{path}: {error}"
            ) from error

        if validated_run_id != path.stem:
            raise RunHistoryError(
                "Invalid pipeline run manifest "
                f"{path}: run_id does not match filename"
            )

        return manifest
