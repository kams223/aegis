import csv
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query


TRACK_DATA_PATH = Path(
    "outputs/data/aegis_track_quality.csv"
)

QualityLevel = Literal["stable", "tentative", "weak"]


app = FastAPI(
    title="Aegis World Model API",
    description=(
        "Read-only situational-awareness API for tracked objects."
    ),
    version="0.1.0",
)


def convert_track(row: dict[str, str]) -> dict:
    """Convert one CSV row into JSON-compatible typed data."""

    return {
        "track_id": int(row["track_id"]),
        "dominant_label": row["dominant_label"],
        "quality_level": row["quality_level"],
        "quality_reason": row["quality_reason"],
        "observation_count": int(row["observation_count"]),
        "duration_seconds": float(row["duration_seconds"]),
        "average_confidence": float(row["average_confidence"]),
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


def load_tracks() -> list[dict]:
    """Load all evaluated tracks from the world-model CSV."""

    if not TRACK_DATA_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "World-model data is unavailable. "
                f"Expected: {TRACK_DATA_PATH}"
            ),
        )

    try:
        with TRACK_DATA_PATH.open(
            mode="r",
            newline="",
            encoding="utf-8",
        ) as input_file:
            reader = csv.DictReader(input_file)
            return [convert_track(row) for row in reader]

    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid world-model data: {error}",
        ) from error


@app.get("/")
def root() -> dict:
    """Return basic API information."""

    return {
        "service": "Aegis World Model API",
        "version": app.version,
        "documentation": "/docs",
    }


@app.get("/health")
def health() -> dict:
    """Report service and world-model availability."""

    return {
        "status": (
            "healthy"
            if TRACK_DATA_PATH.is_file()
            else "degraded"
        ),
        "world_model_available": TRACK_DATA_PATH.is_file(),
        "data_path": str(TRACK_DATA_PATH),
    }


@app.get("/statistics")
def statistics() -> dict:
    """Return aggregate world-model statistics."""

    tracks = load_tracks()

    quality_counts = Counter(
        track["quality_level"] for track in tracks
    )
    label_counts = Counter(
        track["dominant_label"] for track in tracks
    )

    return {
        "total_tracks": len(tracks),
        "quality_counts": {
            "stable": quality_counts.get("stable", 0),
            "tentative": quality_counts.get("tentative", 0),
            "weak": quality_counts.get("weak", 0),
        },
        "label_counts": dict(
            sorted(
                label_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    }


@app.get("/tracks")
def list_tracks(
    quality: QualityLevel | None = Query(default=None),
    minimum_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
) -> dict:
    """Return tracks with optional quality and confidence filters."""

    tracks = load_tracks()

    filtered_tracks = [
        track
        for track in tracks
        if (
            quality is None
            or track["quality_level"] == quality
        )
        and track["average_confidence"] >= minimum_confidence
    ]

    filtered_tracks.sort(
        key=lambda track: (
            -track["average_confidence"],
            track["track_id"],
        )
    )

    return {
        "total_matching": len(filtered_tracks),
        "returned": min(len(filtered_tracks), limit),
        "tracks": filtered_tracks[:limit],
    }


@app.get("/tracks/{track_id}")
def get_track(track_id: int) -> dict:
    """Return one track by its persistent tracking ID."""

    tracks = load_tracks()

    for track in tracks:
        if track["track_id"] == track_id:
            return track

    raise HTTPException(
        status_code=404,
        detail=f"Track {track_id} was not found.",
    )
