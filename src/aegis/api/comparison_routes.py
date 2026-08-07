from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from aegis.api.app import load_manifest_file
from aegis.pipeline.run_comparison import compare_runs
from aegis.pipeline.run_manifest import validate_run_id


RUN_HISTORY_PATH = Path(
    "outputs/data/runs"
)


router = APIRouter(
    prefix="/run-comparisons",
    tags=["run comparisons"],
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

    manifest_path = (
        RUN_HISTORY_PATH / f"{validated_run_id}.json"
    )

    return load_manifest_file(
        path=manifest_path,
        missing_status_code=404,
    )


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
