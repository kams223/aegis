from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from aegis.pipeline.run_comparison import compare_runs
from aegis.pipeline.run_manifest import validate_run_id
from aegis.storage.run_history_store import (
    RunHistoryError,
    RunHistoryStore,
)


DEFAULT_RUN_HISTORY_PATH = Path(
    "outputs/data/runs"
)

DEFAULT_DATABASE_PATH = Path(
    "outputs/data/aegis_world_model.sqlite3"
)

RUN_HISTORY_PATH = DEFAULT_RUN_HISTORY_PATH
DATABASE_PATH = DEFAULT_DATABASE_PATH


router = APIRouter(
    prefix="/run-comparisons",
    tags=["run comparisons"],
)


def build_run_history_store() -> RunHistoryStore:
    """Create the configured comparison data source."""

    database_path = DATABASE_PATH

    if (
        RUN_HISTORY_PATH != DEFAULT_RUN_HISTORY_PATH
        and DATABASE_PATH == DEFAULT_DATABASE_PATH
    ):
        database_path = (
            RUN_HISTORY_PATH
            / "aegis_world_model.sqlite3"
        )

    return RunHistoryStore(
        database_path=database_path,
        history_directory=RUN_HISTORY_PATH,
    )


def load_archived_run(run_id: str) -> dict:
    """Validate and load one archived pipeline run."""

    try:
        validated_run_id = validate_run_id(run_id)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    try:
        manifest = build_run_history_store().get_manifest(
            validated_run_id
        )

    except RunHistoryError as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not load pipeline run "
                f"{validated_run_id}: {error}"
            ),
        ) from error

    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pipeline run {validated_run_id} "
                "was not found."
            ),
        )

    return manifest


@router.get("")
def compare_archived_runs(
    baseline: str = Query(
        min_length=1,
        description=(
            "Archived run ID used as the comparison baseline."
        ),
    ),
    candidate: str = Query(
        min_length=1,
        description=(
            "Archived run ID evaluated against the baseline."
        ),
    ),
) -> dict:
    """Compare performance metrics from two archived runs."""

    if baseline == candidate:
        raise HTTPException(
            status_code=400,
            detail=(
                "Baseline and candidate run IDs "
                "must be different."
            ),
        )

    baseline_manifest = load_archived_run(baseline)
    candidate_manifest = load_archived_run(candidate)

    return compare_runs(
        baseline_manifest=baseline_manifest,
        candidate_manifest=candidate_manifest,
    )
