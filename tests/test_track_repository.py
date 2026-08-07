import sqlite3

import pytest

from aegis.storage.run_repository import RunRepository
from aegis.storage.track_repository import (
    TRACK_SCHEMA_VERSION,
    TrackRepository,
)


def create_manifest(run_id: str) -> dict:
    """Create the parent run required by track storage."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "started_at_utc": "2026-08-07T14:20:00+00:00",
        "finished_at_utc": "2026-08-07T14:30:00+00:00",
        "duration_seconds": 120.0,
        "input": {},
        "model": {},
        "performance": {},
        "stages": [],
    }


def create_track(
    track_id: int,
    quality_level: str = "stable",
    confidence: float = 0.8,
) -> dict:
    """Create one evaluated test track."""

    return {
        "track_id": track_id,
        "dominant_label": "person",
        "quality_level": quality_level,
        "quality_reason": "Test quality reason",
        "observation_count": 20,
        "duration_seconds": 2.0,
        "average_confidence": confidence,
        "displacement_pixels": 100.0,
        "first_frame": 1,
        "last_frame": 61,
        "first_seen_seconds": 0.0,
        "last_seen_seconds": 2.0,
        "start_position": {
            "x": 100.0,
            "y": 200.0,
        },
        "end_position": {
            "x": 180.0,
            "y": 260.0,
        },
    }


def create_repositories(tmp_path):
    """Create initialized run and track repositories."""

    database_path = tmp_path / "world.sqlite3"

    run_repository = RunRepository(database_path)
    run_repository.initialize()

    track_repository = TrackRepository(database_path)
    track_repository.initialize()

    return (
        database_path,
        run_repository,
        track_repository,
    )


def test_initialize_creates_track_schema(tmp_path):
    (
        database_path,
        _,
        track_repository,
    ) = create_repositories(tmp_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        schema_row = connection.execute(
            """
            SELECT value
            FROM metadata
            WHERE key = 'track_schema_version'
            """
        ).fetchone()

    assert "evaluated_tracks" in tables
    assert schema_row[0] == str(TRACK_SCHEMA_VERSION)
    assert track_repository.database_path == database_path


def test_replace_and_load_run_tracks(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    tracks = [
        create_track(
            track_id=1,
            quality_level="stable",
            confidence=0.9,
        ),
        create_track(
            track_id=2,
            quality_level="weak",
            confidence=0.3,
        ),
    ]

    written = track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=tracks,
    )

    assert written == 2
    assert track_repository.count_tracks("run-001") == 2

    stored_tracks = track_repository.list_tracks(
        run_id="run-001",
    )

    assert stored_tracks == tracks


def test_replace_removes_previous_tracks(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=[
            create_track(1),
            create_track(2),
        ],
    )

    replacement = create_track(
        track_id=3,
        quality_level="tentative",
        confidence=0.6,
    )

    track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=[replacement],
    )

    assert track_repository.count_tracks("run-001") == 1

    assert track_repository.list_tracks(
        run_id="run-001"
    ) == [replacement]


def test_tracks_are_isolated_by_run(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    run_repository.save_manifest(
        create_manifest("run-002")
    )

    first_track = create_track(
        track_id=1,
        confidence=0.8,
    )

    second_track = create_track(
        track_id=1,
        confidence=0.6,
    )

    track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=[first_track],
    )

    track_repository.replace_run_tracks(
        run_id="run-002",
        tracks=[second_track],
    )

    assert track_repository.get_track(
        "run-001",
        1,
    ) == first_track

    assert track_repository.get_track(
        "run-002",
        1,
    ) == second_track


def test_list_tracks_applies_filters(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=[
            create_track(
                track_id=1,
                quality_level="stable",
                confidence=0.9,
            ),
            create_track(
                track_id=2,
                quality_level="stable",
                confidence=0.7,
            ),
            create_track(
                track_id=3,
                quality_level="weak",
                confidence=0.4,
            ),
        ],
    )

    tracks = track_repository.list_tracks(
        run_id="run-001",
        quality="stable",
        minimum_confidence=0.8,
        limit=10,
    )

    assert len(tracks) == 1
    assert tracks[0]["track_id"] == 1


def test_get_missing_track_returns_none(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    assert track_repository.get_track(
        "run-001",
        999,
    ) is None


def test_quality_counts(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    track_repository.replace_run_tracks(
        run_id="run-001",
        tracks=[
            create_track(1, "stable", 0.9),
            create_track(2, "stable", 0.8),
            create_track(3, "tentative", 0.6),
            create_track(4, "weak", 0.3),
        ],
    )

    assert track_repository.quality_counts(
        "run-001"
    ) == {
        "stable": 2,
        "tentative": 1,
        "weak": 1,
    }


def test_foreign_key_rejects_unknown_run(tmp_path):
    (
        _,
        _,
        track_repository,
    ) = create_repositories(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        track_repository.replace_run_tracks(
            run_id="missing-run",
            tracks=[create_track(1)],
        )


def test_rejects_duplicate_track_ids(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    with pytest.raises(
        ValueError,
        match="unique",
    ):
        track_repository.replace_run_tracks(
            run_id="run-001",
            tracks=[
                create_track(1),
                create_track(1),
            ],
        )


def test_rejects_invalid_quality(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    with pytest.raises(
        ValueError,
        match="quality",
    ):
        track_repository.replace_run_tracks(
            run_id="run-001",
            tracks=[
                create_track(
                    track_id=1,
                    quality_level="unknown",
                )
            ],
        )


def test_rejects_invalid_filter_values(tmp_path):
    (
        _,
        run_repository,
        track_repository,
    ) = create_repositories(tmp_path)

    run_repository.save_manifest(
        create_manifest("run-001")
    )

    with pytest.raises(ValueError):
        track_repository.list_tracks(
            run_id="run-001",
            quality="unknown",
        )

    with pytest.raises(ValueError):
        track_repository.list_tracks(
            run_id="run-001",
            minimum_confidence=2.0,
        )

    with pytest.raises(ValueError):
        track_repository.list_tracks(
            run_id="run-001",
            limit=0,
        )
