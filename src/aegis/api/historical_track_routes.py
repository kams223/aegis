import sqlite3
from collections import Counter
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from aegis.api.app import (
    build_run_history_store,
    load_archived_run,
    validate_run_id_for_api,
)
from aegis.storage.track_repository import TrackRepository


QualityLevel = Literal["stable", "tentative", "weak"]


router = APIRouter(
    prefix="/runs/{run_id}",
    tags=["historical tracks"],
)


def build_track_repository(
    run_id: str,
) -> tuple[str, TrackRepository]:
    """Validate one run and open its track repository."""

    validated_run_id = validate_run_id_for_api(run_id)

    load_archived_run(validated_run_id)

    database_path = (
        build_run_history_store().database_path
    )

    if not database_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Historical track storage is unavailable. "
                f"Expected SQLite database: {database_path}"
            ),
        )

    return (
        validated_run_id,
        TrackRepository(database_path),
    )


def load_run_tracks(
    run_id: str,
) -> tuple[str, list[dict]]:
    """Load every evaluated track for one run."""

    validated_run_id, repository = (
        build_track_repository(run_id)
    )

    try:
        track_count = repository.count_tracks(
            validated_run_id
        )

        tracks = repository.list_tracks(
            run_id=validated_run_id,
            limit=max(track_count, 1),
        )

    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Historical track storage could not be read: "
                f"{error}"
            ),
        ) from error

    return validated_run_id, tracks


@router.get("/statistics")
def historical_statistics(
    run_id: str,
) -> dict:
    """Return aggregate track statistics for one run."""

    validated_run_id, tracks = load_run_tracks(
        run_id
    )

    quality_counts = Counter(
        track["quality_level"] for track in tracks
    )

    label_counts = Counter(
        track["dominant_label"] for track in tracks
    )

    return {
        "run_id": validated_run_id,
        "storage_source": "sqlite",
        "total_tracks": len(tracks),
        "quality_counts": {
            "stable": quality_counts.get("stable", 0),
            "tentative": quality_counts.get(
                "tentative",
                0,
            ),
            "weak": quality_counts.get("weak", 0),
        },
        "label_counts": dict(
            sorted(
                label_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    }


@router.get("/tracks")
def historical_tracks(
    run_id: str,
    quality: QualityLevel | None = Query(default=None),
    minimum_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
    ),
    dominant_label: str | None = Query(
        default=None,
        min_length=1,
        max_length=200,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
) -> dict:
    """Return filtered and paginated tracks for one run."""

    validated_run_id, repository = (
        build_track_repository(run_id)
    )

    try:
        total_matching = repository.count_tracks(
            run_id=validated_run_id,
            quality=quality,
            minimum_confidence=minimum_confidence,
            dominant_label=dominant_label,
        )

        tracks = repository.list_tracks(
            run_id=validated_run_id,
            quality=quality,
            minimum_confidence=minimum_confidence,
            dominant_label=dominant_label,
            limit=limit,
            offset=offset,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Historical track storage could not be read: "
                f"{error}"
            ),
        ) from error

    returned = len(tracks)

    return {
        "run_id": validated_run_id,
        "storage_source": "sqlite",
        "total_matching": total_matching,
        "returned": returned,
        "offset": offset,
        "limit": limit,
        "has_previous": offset > 0,
        "has_next": (
            offset + returned < total_matching
        ),
        "tracks": tracks,
    }




@router.get("/tracks/{track_id}")
def historical_track(
    run_id: str,
    track_id: int,
) -> dict:
    """Return one evaluated track from one run."""

    validated_run_id, repository = (
        build_track_repository(run_id)
    )

    try:
        track = repository.get_track(
            run_id=validated_run_id,
            track_id=track_id,
        )

    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Historical track storage could not be read: "
                f"{error}"
            ),
        ) from error

    if track is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Track {track_id} was not found in "
                f"run {validated_run_id}."
            ),
        )

    return track
