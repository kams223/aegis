import json

import pytest

from aegis.storage.run_history_store import (
    RunHistoryError,
    RunHistoryStore,
)
from aegis.storage.run_repository import RunRepository


def create_manifest(
    run_id: str,
    finished_at_utc: str,
) -> dict:
    """Create a test pipeline manifest."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "started_at_utc": "2026-08-07T14:20:00+00:00",
        "finished_at_utc": finished_at_utc,
        "duration_seconds": 120.0,
        "input": {
            "path": "data/videos/test.mp4",
            "sha256": "test-sha256",
        },
        "model": {
            "model_path": "yolo11n.pt",
            "tracker_config": "bytetrack.yaml",
            "device": "cpu",
            "confidence_threshold": 0.35,
            "image_size": 640,
        },
        "performance": {
            "processing_metrics_available": True,
            "processing_metrics": {
                "duration_seconds": 100.0,
                "results": {
                    "average_processing_fps": 2.5,
                    "frames_processed": 271,
                    "frame_detections": 462,
                    "tracked_observations": 452,
                    "unique_tracks": 45,
                },
            },
        },
        "stages": [],
    }


def write_json_manifest(
    history_directory,
    manifest,
):
    """Write one archived JSON manifest."""

    history_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        history_directory
        / f"{manifest['run_id']}.json"
    )

    path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    return path


def test_store_uses_json_without_database(
    tmp_path,
):
    history_directory = tmp_path / "runs"

    manifest = create_manifest(
        run_id="json-run",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    write_json_manifest(
        history_directory,
        manifest,
    )

    store = RunHistoryStore(
        database_path=tmp_path / "missing.sqlite3",
        history_directory=history_directory,
    )

    assert store.uses_database is False
    assert store.source_name == "json"
    assert store.count_runs() == 1
    assert store.list_manifests() == [manifest]
    assert store.get_manifest("json-run") == manifest


def test_json_store_returns_newest_first(tmp_path):
    history_directory = tmp_path / "runs"

    older = create_manifest(
        run_id="20260806T100000000000Z-older",
        finished_at_utc="2026-08-06T10:00:00+00:00",
    )

    newer = create_manifest(
        run_id="20260807T100000000000Z-newer",
        finished_at_utc="2026-08-07T10:00:00+00:00",
    )

    write_json_manifest(
        history_directory,
        older,
    )

    write_json_manifest(
        history_directory,
        newer,
    )

    store = RunHistoryStore(
        database_path=tmp_path / "missing.sqlite3",
        history_directory=history_directory,
    )

    manifests = store.list_manifests()

    assert [
        manifest["run_id"]
        for manifest in manifests
    ] == [
        "20260807T100000000000Z-newer",
        "20260806T100000000000Z-older",
    ]


def test_store_prefers_existing_database(tmp_path):
    history_directory = tmp_path / "runs"
    database_path = tmp_path / "world.sqlite3"

    json_manifest = create_manifest(
        run_id="json-run",
        finished_at_utc="2026-08-07T14:10:00+00:00",
    )

    database_manifest = create_manifest(
        run_id="database-run",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    write_json_manifest(
        history_directory,
        json_manifest,
    )

    repository = RunRepository(database_path)
    repository.initialize()
    repository.save_manifest(database_manifest)

    store = RunHistoryStore(
        database_path=database_path,
        history_directory=history_directory,
    )

    assert store.uses_database is True
    assert store.source_name == "sqlite"
    assert store.count_runs() == 1

    assert store.list_manifests() == [
        database_manifest
    ]

    assert store.get_manifest(
        "database-run"
    ) == database_manifest

    assert store.get_manifest("json-run") is None


def test_database_store_returns_newest_first(
    tmp_path,
):
    database_path = tmp_path / "world.sqlite3"
    repository = RunRepository(database_path)
    repository.initialize()

    older = create_manifest(
        run_id="older-run",
        finished_at_utc="2026-08-07T14:20:00+00:00",
    )

    newer = create_manifest(
        run_id="newer-run",
        finished_at_utc="2026-08-07T14:30:00+00:00",
    )

    repository.save_manifest(older)
    repository.save_manifest(newer)

    store = RunHistoryStore(
        database_path=database_path,
        history_directory=tmp_path / "runs",
    )

    manifests = store.list_manifests()

    assert [
        manifest["run_id"]
        for manifest in manifests
    ] == [
        "newer-run",
        "older-run",
    ]


def test_list_manifests_respects_limit(tmp_path):
    database_path = tmp_path / "world.sqlite3"
    repository = RunRepository(database_path)
    repository.initialize()

    repository.save_manifest(
        create_manifest(
            run_id="older-run",
            finished_at_utc=(
                "2026-08-07T14:20:00+00:00"
            ),
        )
    )

    repository.save_manifest(
        create_manifest(
            run_id="newer-run",
            finished_at_utc=(
                "2026-08-07T14:30:00+00:00"
            ),
        )
    )

    store = RunHistoryStore(
        database_path=database_path,
        history_directory=tmp_path / "runs",
    )

    manifests = store.list_manifests(limit=1)

    assert len(manifests) == 1
    assert manifests[0]["run_id"] == "newer-run"


def test_missing_run_returns_none(tmp_path):
    store = RunHistoryStore(
        database_path=tmp_path / "missing.sqlite3",
        history_directory=tmp_path / "missing-runs",
    )

    assert store.count_runs() == 0
    assert store.list_manifests() == []
    assert store.get_manifest("missing-run") is None


def test_store_rejects_unsafe_run_id(tmp_path):
    store = RunHistoryStore(
        database_path=tmp_path / "missing.sqlite3",
        history_directory=tmp_path / "runs",
    )

    with pytest.raises(ValueError):
        store.get_manifest("../unsafe")


def test_json_store_rejects_invalid_manifest(
    tmp_path,
):
    history_directory = tmp_path / "runs"
    history_directory.mkdir()

    invalid_path = history_directory / "invalid.json"

    invalid_path.write_text(
        "{invalid JSON",
        encoding="utf-8",
    )

    store = RunHistoryStore(
        database_path=tmp_path / "missing.sqlite3",
        history_directory=history_directory,
    )

    with pytest.raises(
        RunHistoryError,
        match="Invalid pipeline run manifest",
    ):
        store.list_manifests()
