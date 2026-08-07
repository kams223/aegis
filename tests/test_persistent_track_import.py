import csv
import json
from pathlib import Path

from aegis.core.pipeline_config import PipelineConfig
from aegis.pipeline.persistent_manifest import (
    PersistentRunManifest,
)
from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import TrackRepository


FIELD_NAMES = [
    "track_id",
    "dominant_label",
    "quality_level",
    "quality_reason",
    "observation_count",
    "duration_seconds",
    "average_confidence",
    "displacement_pixels",
    "first_frame",
    "last_frame",
    "first_seen_seconds",
    "last_seen_seconds",
    "start_center_x",
    "start_center_y",
    "end_center_x",
    "end_center_y",
]


def create_config(
    input_path: Path,
    output_directory: Path,
) -> PipelineConfig:
    """Create a test configuration."""

    return PipelineConfig.from_dict(
        {
            "input": {
                "video_path": str(input_path),
            },
            "model": {
                "model_path": "test-model.pt",
                "tracker_config": "test-tracker.yaml",
                "confidence_threshold": 0.4,
                "image_size": 320,
                "device": "cpu",
            },
            "output": {
                "video_path": str(
                    output_directory / "tracked.mp4"
                ),
                "observations_path": str(
                    output_directory / "observations.csv"
                ),
                "summaries_path": str(
                    output_directory / "summaries.csv"
                ),
                "quality_path": str(
                    output_directory / "quality.csv"
                ),
                "processing_metrics_path": str(
                    output_directory / "metrics.json"
                ),
                "database_path": str(
                    output_directory / "world.sqlite3"
                ),
            },
            "quality": {
                "minimum_stable_observations": 5,
                "minimum_stable_duration": 0.2,
                "minimum_stable_confidence": 0.5,
            },
        }
    )


def write_quality_csv(
    path: Path,
) -> None:
    """Write synthetic evaluated tracks."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=FIELD_NAMES,
        )

        writer.writeheader()

        writer.writerows(
            [
                {
                    "track_id": 1,
                    "dominant_label": "person",
                    "quality_level": "stable",
                    "quality_reason": "Persistent track",
                    "observation_count": 20,
                    "duration_seconds": 2.0,
                    "average_confidence": 0.8,
                    "displacement_pixels": 100.0,
                    "first_frame": 1,
                    "last_frame": 61,
                    "first_seen_seconds": 0.0,
                    "last_seen_seconds": 2.0,
                    "start_center_x": 100.0,
                    "start_center_y": 200.0,
                    "end_center_x": 180.0,
                    "end_center_y": 260.0,
                },
                {
                    "track_id": 2,
                    "dominant_label": "car",
                    "quality_level": "weak",
                    "quality_reason": "Too few observations",
                    "observation_count": 1,
                    "duration_seconds": 0.0,
                    "average_confidence": 0.35,
                    "displacement_pixels": 0.0,
                    "first_frame": 10,
                    "last_frame": 10,
                    "first_seen_seconds": 0.3,
                    "last_seen_seconds": 0.3,
                    "start_center_x": 300.0,
                    "start_center_y": 400.0,
                    "end_center_x": 300.0,
                    "end_center_y": 400.0,
                },
            ]
        )


def create_manifest(
    config: PipelineConfig,
    output_directory: Path,
    run_id: str,
) -> PersistentRunManifest:
    """Create one persistent test manifest."""

    return PersistentRunManifest(
        config=config,
        config_path=Path("configs/test.json"),
        output_path=(
            output_directory / "manifest.json"
        ),
        history_directory=(
            output_directory / "runs"
        ),
        run_id=run_id,
    )


def test_completed_run_imports_tracks(tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    write_quality_csv(config.quality_path)

    manifest = create_manifest(
        config=config,
        output_directory=output_directory,
        run_id="completed-track-run",
    )

    manifest.start(monotonic_time=100.0)

    manifest.record_stage(
        name="Track-quality evaluation",
        status="completed",
        duration_seconds=1.0,
        exit_code=0,
    )

    manifest.finish(
        status="completed",
        exit_code=0,
        monotonic_time=102.0,
    )

    track_repository = TrackRepository(
        config.database_path
    )

    assert track_repository.count_tracks(
        "completed-track-run"
    ) == 2

    assert track_repository.quality_counts(
        "completed-track-run"
    ) == {
        "stable": 1,
        "tentative": 0,
        "weak": 1,
    }

    performance = manifest.data["performance"]

    assert performance[
        "database_tracks_available"
    ] is True

    assert performance["database_track_count"] == 2

    assert performance[
        "database_tracks_error"
    ] is None

    run_repository = RunRepository(
        config.database_path
    )

    stored = run_repository.get_manifest(
        "completed-track-run"
    )

    assert stored is not None

    assert stored["performance"][
        "database_tracks_available"
    ] is True

    assert stored["performance"][
        "database_track_count"
    ] == 2

    latest = json.loads(
        manifest.output_path.read_text(
            encoding="utf-8"
        )
    )

    assert latest == stored


def test_missing_quality_csv_records_error(
    tmp_path,
):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    manifest = create_manifest(
        config=config,
        output_directory=output_directory,
        run_id="missing-quality-run",
    )

    manifest.start(monotonic_time=100.0)

    manifest.finish(
        status="completed",
        exit_code=0,
        monotonic_time=101.0,
    )

    performance = manifest.data["performance"]

    assert performance[
        "database_tracks_available"
    ] is False

    assert performance["database_track_count"] == 0

    assert performance[
        "database_tracks_error"
    ] is not None

    assert "not found" in performance[
        "database_tracks_error"
    ]


def test_failed_run_does_not_import_tracks(
    tmp_path,
):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"synthetic-video")

    output_directory = tmp_path / "outputs"

    config = create_config(
        input_path=input_path,
        output_directory=output_directory,
    )

    write_quality_csv(config.quality_path)

    manifest = create_manifest(
        config=config,
        output_directory=output_directory,
        run_id="failed-track-run",
    )

    manifest.start(monotonic_time=100.0)

    manifest.finish(
        status="failed",
        exit_code=7,
        monotonic_time=101.0,
    )

    track_repository = TrackRepository(
        config.database_path
    )
    track_repository.initialize()

    assert track_repository.count_tracks(
        "failed-track-run"
    ) == 0

    performance = manifest.data["performance"]

    assert performance[
        "database_tracks_available"
    ] is False

    assert performance["database_track_count"] == 0
    assert performance["database_tracks_error"] is None
