from aegis.pipeline.run_comparison import (
    compare_runs,
    extract_run_metrics,
)


def create_manifest(
    run_id,
    fps,
    processing_duration,
    pipeline_duration,
    overhead,
    frames=271,
    detections=462,
    observations=452,
    unique_tracks=45,
):
    """Create a synthetic manifest with performance data."""

    return {
        "schema_version": 3,
        "run_id": run_id,
        "performance": {
            "processing_metrics_available": True,
            "pipeline_duration_seconds": pipeline_duration,
            "initialization_overhead_seconds": overhead,
            "processing_metrics": {
                "duration_seconds": processing_duration,
                "results": {
                    "average_processing_fps": fps,
                    "frames_processed": frames,
                    "frame_detections": detections,
                    "tracked_observations": observations,
                    "unique_tracks": unique_tracks,
                },
            },
        },
    }


def test_extract_run_metrics():
    manifest = create_manifest(
        run_id="run-one",
        fps=2.0,
        processing_duration=120.0,
        pipeline_duration=140.0,
        overhead=20.0,
    )

    metrics = extract_run_metrics(manifest)

    assert metrics["average_processing_fps"] == 2.0
    assert metrics["processing_duration_seconds"] == 120.0
    assert metrics["pipeline_duration_seconds"] == 140.0
    assert metrics["initialization_overhead_seconds"] == 20.0
    assert metrics["frames_processed"] == 271
    assert metrics["frame_detections"] == 462


def test_compare_runs_detects_improvement():
    baseline = create_manifest(
        run_id="baseline",
        fps=2.0,
        processing_duration=120.0,
        pipeline_duration=145.0,
        overhead=25.0,
    )

    candidate = create_manifest(
        run_id="candidate",
        fps=2.5,
        processing_duration=100.0,
        pipeline_duration=120.0,
        overhead=20.0,
    )

    comparison = compare_runs(
        baseline_manifest=baseline,
        candidate_manifest=candidate,
    )

    fps = comparison["metrics"][
        "average_processing_fps"
    ]
    processing_time = comparison["metrics"][
        "processing_duration_seconds"
    ]

    assert comparison["baseline_run_id"] == "baseline"
    assert comparison["candidate_run_id"] == "candidate"

    assert fps["available"] is True
    assert fps["absolute_change"] == 0.5
    assert fps["percentage_change"] == 25.0
    assert fps["assessment"] == "improved"

    assert processing_time["absolute_change"] == -20.0
    assert processing_time["assessment"] == "improved"

    assert comparison["improved_metric_count"] == 4
    assert comparison["regressed_metric_count"] == 0


def test_compare_runs_detects_regression():
    baseline = create_manifest(
        run_id="baseline",
        fps=2.5,
        processing_duration=100.0,
        pipeline_duration=120.0,
        overhead=20.0,
    )

    candidate = create_manifest(
        run_id="candidate",
        fps=2.0,
        processing_duration=125.0,
        pipeline_duration=150.0,
        overhead=25.0,
    )

    comparison = compare_runs(
        baseline_manifest=baseline,
        candidate_manifest=candidate,
    )

    assert comparison["metrics"][
        "average_processing_fps"
    ]["assessment"] == "regressed"

    assert comparison["metrics"][
        "processing_duration_seconds"
    ]["assessment"] == "regressed"

    assert comparison["regressed_metric_count"] == 4
    assert comparison["improved_metric_count"] == 0


def test_compare_runs_handles_missing_metrics():
    baseline = {
        "schema_version": 2,
        "run_id": "legacy-run",
    }

    candidate = create_manifest(
        run_id="candidate",
        fps=2.5,
        processing_duration=100.0,
        pipeline_duration=120.0,
        overhead=20.0,
    )

    comparison = compare_runs(
        baseline_manifest=baseline,
        candidate_manifest=candidate,
    )

    assert comparison["available_metric_count"] == 0

    assert comparison["metrics"][
        "average_processing_fps"
    ]["assessment"] == "unavailable"

    assert comparison["metrics"][
        "frames_processed"
    ]["assessment"] == "unavailable"


def test_zero_baseline_has_no_percentage_change():
    baseline = create_manifest(
        run_id="baseline",
        fps=0.0,
        processing_duration=0.0,
        pipeline_duration=0.0,
        overhead=0.0,
    )

    candidate = create_manifest(
        run_id="candidate",
        fps=2.0,
        processing_duration=100.0,
        pipeline_duration=120.0,
        overhead=20.0,
    )

    comparison = compare_runs(
        baseline_manifest=baseline,
        candidate_manifest=candidate,
    )

    assert comparison["metrics"][
        "average_processing_fps"
    ]["percentage_change"] is None
