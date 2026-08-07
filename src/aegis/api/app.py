import csv
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from aegis.pipeline.run_manifest import validate_run_id


TRACK_DATA_PATH = Path(
    "outputs/data/aegis_track_quality.csv"
)

RUN_MANIFEST_PATH = Path(
    "outputs/data/aegis_run_manifest.json"
)

RUN_HISTORY_PATH = Path(
    "outputs/data/runs"
)

QualityLevel = Literal["stable", "tentative", "weak"]


app = FastAPI(
    title="Aegis World Model API",
    description=(
        "Read-only situational-awareness API for tracked objects "
        "and offline pipeline runs."
    ),
    version="0.4.0",
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

    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read world-model data: {error}",
        ) from error


def load_manifest_file(
    path: Path,
    missing_status_code: int,
) -> dict:
    """Load and validate one pipeline run manifest."""

    if not path.is_file():
        raise HTTPException(
            status_code=missing_status_code,
            detail=f"Pipeline run manifest was not found: {path}",
        )

    try:
        with path.open(
            mode="r",
            encoding="utf-8",
        ) as input_file:
            manifest = json.load(input_file)

    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid pipeline run manifest: {error}",
        ) from error

    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not read pipeline run manifest: {error}"
            ),
        ) from error

    if not isinstance(manifest, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                "Invalid pipeline run manifest: "
                "the root value must be an object."
            ),
        )

    return manifest


def load_run_manifest() -> dict:
    """Load the latest offline pipeline run manifest."""

    if not RUN_MANIFEST_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Pipeline run manifest is unavailable. "
                f"Expected: {RUN_MANIFEST_PATH}"
            ),
        )

    return load_manifest_file(
        path=RUN_MANIFEST_PATH,
        missing_status_code=503,
    )


def get_processing_summary(
    manifest: dict,
) -> dict:
    """Extract compact processing metrics from one manifest."""

    performance = manifest.get("performance", {})

    if not isinstance(performance, dict):
        performance = {}

    processing_metrics = performance.get(
        "processing_metrics",
        {},
    )

    if not isinstance(processing_metrics, dict):
        processing_metrics = {}

    results = processing_metrics.get("results", {})

    if not isinstance(results, dict):
        results = {}

    return {
        "processing_metrics_available": (
            performance.get(
                "processing_metrics_available",
                False,
            )
            is True
        ),
        "average_processing_fps": results.get(
            "average_processing_fps"
        ),
        "frames_processed": results.get(
            "frames_processed"
        ),
        "frame_detections": results.get(
            "frame_detections"
        ),
        "tracked_observations": results.get(
            "tracked_observations"
        ),
        "unique_tracks": results.get(
            "unique_tracks"
        ),
        "processing_duration_seconds": (
            processing_metrics.get("duration_seconds")
        ),
        "initialization_overhead_seconds": (
            performance.get(
                "initialization_overhead_seconds"
            )
        ),
        "pipeline_duration_seconds": (
            performance.get(
                "pipeline_duration_seconds"
            )
        ),
    }


def summarize_manifest(manifest: dict) -> dict:
    """Create a compact representation of one run."""

    model = manifest.get("model", {})
    input_metadata = manifest.get("input", {})
    stages = manifest.get("stages", [])

    if not isinstance(model, dict):
        model = {}

    if not isinstance(input_metadata, dict):
        input_metadata = {}

    summary = {
        "run_id": manifest.get("run_id"),
        "schema_version": manifest.get("schema_version"),
        "status": manifest.get("status"),
        "exit_code": manifest.get("exit_code"),
        "started_at_utc": manifest.get("started_at_utc"),
        "finished_at_utc": manifest.get("finished_at_utc"),
        "duration_seconds": manifest.get(
            "duration_seconds"
        ),
        "model_path": model.get("model_path"),
        "device": model.get("device"),
        "input_path": input_metadata.get("path"),
        "stage_count": (
            len(stages)
            if isinstance(stages, list)
            else 0
        ),
    }

    summary.update(
        get_processing_summary(manifest)
    )

    return summary


def load_run_history() -> list[dict]:
    """Load archived manifests from newest to oldest."""

    if not RUN_HISTORY_PATH.is_dir():
        return []

    manifest_paths = sorted(
        RUN_HISTORY_PATH.glob("*.json"),
        reverse=True,
    )

    return [
        load_manifest_file(
            path=manifest_path,
            missing_status_code=404,
        )
        for manifest_path in manifest_paths
    ]


@app.get("/")
def root() -> dict:
    """Return basic API information."""

    return {
        "service": "Aegis World Model API",
        "version": app.version,
        "documentation": "/docs",
        "latest_run": "/runs/latest",
        "run_history": "/runs",
    }


@app.get("/health")
def health() -> dict:
    """Report service and generated-data availability."""

    world_model_available = TRACK_DATA_PATH.is_file()
    run_manifest_available = RUN_MANIFEST_PATH.is_file()
    run_history_available = RUN_HISTORY_PATH.is_dir()

    return {
        "status": (
            "healthy"
            if world_model_available
            and run_manifest_available
            else "degraded"
        ),
        "world_model_available": world_model_available,
        "world_model_path": str(TRACK_DATA_PATH),
        "run_manifest_available": run_manifest_available,
        "run_manifest_path": str(RUN_MANIFEST_PATH),
        "run_history_available": run_history_available,
        "run_history_path": str(RUN_HISTORY_PATH),
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


@app.get("/runs")
def list_runs(
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
) -> dict:
    """Return compact archived-run records."""

    manifests = load_run_history()
    selected_manifests = manifests[:limit]

    return {
        "total_runs": len(manifests),
        "returned": len(selected_manifests),
        "runs": [
            summarize_manifest(manifest)
            for manifest in selected_manifests
        ],
    }


@app.get("/runs/latest")
def latest_run() -> dict:
    """Return the latest offline pipeline run manifest."""

    return load_run_manifest()


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Return one archived pipeline run manifest."""

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
