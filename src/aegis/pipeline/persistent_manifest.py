import sqlite3
from pathlib import Path

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.run_manifest import RunManifest
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

    def write(self) -> None:
        """Persist the current state to JSON and SQLite."""

        outputs = self.data.get("outputs")

        if isinstance(outputs, dict):
            outputs["database"] = str(
                self.config.database_path
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
