import sqlite3
from pathlib import Path

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.run_manifest import RunManifest
from aegis.storage.import_evaluated_tracks import (
    import_evaluated_tracks,
)
from aegis.storage.run_repository import RunRepository


class PersistentRunManifest(RunManifest):
    """Persist each manifest state to JSON and SQLite."""

    def __init__(
        self,
        config: PipelineConfig,
        config_path: Path,
        output_path: Path | None = None,
        history_directory: Path | None = None,
        run_id: str | None = None,
        repository: RunRepository | None = None,
    ):
        super().__init__(
            config=config,
            config_path=config_path,
            output_path=output_path,
            history_directory=history_directory,
            run_id=run_id,
        )

        self.repository = (
            repository
            if repository is not None
            else RunRepository(config.database_path)
        )

    def finish(
        self,
        status: str,
        exit_code: int,
        monotonic_time: float,
    ) -> None:
        """Finalize the run and persist evaluated tracks."""

        super().finish(
            status=status,
            exit_code=exit_code,
            monotonic_time=monotonic_time,
        )

        performance = self.data.get("performance")

        if not isinstance(performance, dict):
            return

        if status != "completed":
            self.write()
            return

        try:
            summary = import_evaluated_tracks(
                database_path=self.config.database_path,
                quality_path=self.config.quality_path,
                run_id=self.run_id,
            )

        except (
            FileNotFoundError,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as error:
            performance[
                "database_tracks_available"
            ] = False

            performance[
                "database_track_count"
            ] = 0

            performance[
                "database_tracks_error"
            ] = str(error)

        else:
            performance[
                "database_tracks_available"
            ] = True

            performance[
                "database_track_count"
            ] = summary[
                "database_track_count"
            ]

            performance[
                "database_tracks_error"
            ] = None

        self.write()

    def write(self) -> None:
        """Persist the current state to JSON and SQLite."""

        outputs = self.data.get("outputs")

        if isinstance(outputs, dict):
            outputs["database"] = str(
                self.config.database_path
            )

        performance = self.data.get("performance")

        if isinstance(performance, dict):
            performance.setdefault(
                "database_tracks_available",
                False,
            )

            performance.setdefault(
                "database_track_count",
                0,
            )

            performance.setdefault(
                "database_tracks_error",
                None,
            )

        super().write()

        try:
            self.repository.initialize()
            self.repository.save_manifest(self.data)

        except sqlite3.Error as error:
            raise OSError(
                "Could not persist the pipeline run "
                f"to SQLite: {error}"
            ) from error
