import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from aegis.pipeline.run_manifest import validate_run_id
from aegis.storage.run_history_store import (
    RunHistoryError,
    RunHistoryStore,
)
from aegis.storage.track_repository import TrackRepository


DEFAULT_TRACK_DATA_PATH = Path(
    "outputs/data/aegis_track_quality.csv"
)

RUN_MANIFEST_PATH = Path(
    "outputs/data/aegis_run_manifest.json"
)

DEFAULT_RUN_HISTORY_PATH = Path(
    "outputs/data/runs"
)

DEFAULT_DATABASE_PATH = Path(
    "outputs/data/aegis_world_model.sqlite3"
)

TRACK_DATA_PATH = DEFAULT_TRACK_DATA_PATH
RUN_HISTORY_PATH = DEFAULT_RUN_HISTORY_PATH
DATABASE_PATH = DEFAULT_DATABASE_PATH

QualityLevel = Literal["stable", "tentative", "weak"]


app = FastAPI(
    title="Aegis World Model API",
    description=(
        "Read-only situational-awareness API for tracked objects "
        "and offline pipeline runs."
    ),
    version="0.6.0",
)


def build_run_history_store() -> RunHistoryStore:
    """Create the configured run-history data source."""

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


def database_tracks_enabled() -> bool:
    """Return whether SQLite track lookup is configured."""

    return (
        TRACK_DATA_PATH == DEFAULT_TRACK_DATA_PATH
        or DATABASE_PATH != DEFAULT_DATABASE_PATH
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


def load_csv_tracks() -> list[dict]:
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


def find_database_track_run(
    repository: TrackRepository,
) -> str | None:
    """Find the newest run containing persisted tracks."""

    try:
        manifests = build_run_history_store().list_manifests()

        for manifest in manifests:
            run_id = manifest.get("run_id")

            if not isinstance(run_id, str):
                continue

            if repository.count_tracks(run_id) > 0:
                return run_id

    except (
        RunHistoryError,
        ValueError,
        sqlite3.Error,
    ):
        return None

    return None


def load_database_track_snapshot(
) -> tuple[list[dict], str] | None:
    """Load the newest available SQLite track snapshot."""

    if not database_tracks_enabled():
        return None

    database_path = build_run_history_store().database_path

    if not database_path.is_file():
        return None

    repository = TrackRepository(database_path)

    try:
        run_id = find_database_track_run(repository)

        if run_id is None:
            return None

        track_count = repository.count_tracks(run_id)

        tracks = repository.list_tracks(
            run_id=run_id,
            limit=max(track_count, 1),
        )

    except (ValueError, sqlite3.Error):
        return None

    return tracks, run_id


def load_track_snapshot(
) -> tuple[list[dict], str, str | None]:
    """Load tracks from SQLite or the CSV fallback."""

    database_snapshot = load_database_track_snapshot()

    if database_snapshot is not None:
        tracks, run_id = database_snapshot
        return tracks, "sqlite", run_id

    return load_csv_tracks(), "csv", None


def load_tracks() -> list[dict]:
    """Load tracks from the active world-model source."""

    tracks, _, _ = load_track_snapshot()
    return tracks


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


def load_run_history(
    limit: int | None = None,
) -> list[dict]:
    """Load full run manifests from active storage."""

    try:
        return build_run_history_store().list_manifests(
            limit=limit
        )

    except (RunHistoryError, ValueError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load run history: {error}",
        ) from error


def load_archived_run(run_id: str) -> dict:
    """Load one run from the active history store."""

    try:
        manifest = build_run_history_store().get_manifest(
            run_id
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except RunHistoryError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load pipeline run: {error}",
        ) from error

    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pipeline run {run_id} was not found."
            ),
        )

    return manifest


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

    run_store = build_run_history_store()

    database_available = (
        run_store.database_path.is_file()
    )

    database_snapshot = load_database_track_snapshot()

    database_tracks_available = (
        database_snapshot is not None
    )

    csv_tracks_available = TRACK_DATA_PATH.is_file()

    world_model_available = (
        database_tracks_available
        or csv_tracks_available
    )

    run_manifest_available = RUN_MANIFEST_PATH.is_file()

    json_history_available = (
        RUN_HISTORY_PATH.is_dir()
    )

    run_history_available = (
        database_available
        or json_history_available
    )

    track_run_id = (
        database_snapshot[1]
        if database_snapshot is not None
        else None
    )

    return {
        "status": (
            "healthy"
            if world_model_available
            and run_manifest_available
            else "degraded"
        ),
        "world_model_available": world_model_available,
        "world_model_path": str(TRACK_DATA_PATH),
        "track_storage_source": (
            "sqlite"
            if database_tracks_available
            else "csv"
        ),
        "track_run_id": track_run_id,
        "run_manifest_available": run_manifest_available,
        "run_manifest_path": str(RUN_MANIFEST_PATH),
        "run_history_available": run_history_available,
        "run_history_path": str(RUN_HISTORY_PATH),
        "database_available": database_available,
        "database_path": str(
            run_store.database_path
        ),
        "run_history_source": run_store.source_name,
    }


@app.get("/statistics")
def statistics() -> dict:
    """Return aggregate world-model statistics."""

    tracks, storage_source, run_id = (
        load_track_snapshot()
    )

    quality_counts = Counter(
        track["quality_level"] for track in tracks
    )

    label_counts = Counter(
        track["dominant_label"] for track in tracks
    )

    return {
        "total_tracks": len(tracks),
        "storage_source": storage_source,
        "run_id": run_id,
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

    tracks, storage_source, run_id = (
        load_track_snapshot()
    )

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
        "storage_source": storage_source,
        "run_id": run_id,
        "tracks": filtered_tracks[:limit],
    }


@app.get("/tracks/{track_id}")
def get_track(track_id: int) -> dict:
    """Return one track by its persistent tracking ID."""

    tracks, _, _ = load_track_snapshot()

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
    """Return compact records from active run storage."""

    run_store = build_run_history_store()

    try:
        total_runs = run_store.count_runs()

        manifests = run_store.list_manifests(
            limit=limit
        )

    except (RunHistoryError, ValueError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load run history: {error}",
        ) from error

    return {
        "total_runs": total_runs,
        "returned": len(manifests),
        "storage_source": run_store.source_name,
        "runs": [
            summarize_manifest(manifest)
            for manifest in manifests
        ],
    }


@app.get("/runs/latest")
def latest_run() -> dict:
    """Return the latest offline pipeline run manifest."""

    return load_run_manifest()


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Return one pipeline run from active storage."""

    validated_run_id = validate_run_id_for_api(
        run_id
    )

    return load_archived_run(
        validated_run_id
    )


def validate_run_id_for_api(run_id: str) -> str:
    """Convert run-ID validation failures to HTTP 400."""

    try:
        return validate_run_id(run_id)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
