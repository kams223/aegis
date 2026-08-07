from typing import Any


METRIC_DEFINITIONS = {
    "average_processing_fps": {
        "label": "Average processing FPS",
        "unit": "fps",
        "higher_is_better": True,
    },
    "processing_duration_seconds": {
        "label": "Processing duration",
        "unit": "seconds",
        "higher_is_better": False,
    },
    "pipeline_duration_seconds": {
        "label": "Pipeline duration",
        "unit": "seconds",
        "higher_is_better": False,
    },
    "initialization_overhead_seconds": {
        "label": "Initialization overhead",
        "unit": "seconds",
        "higher_is_better": False,
    },
    "frames_processed": {
        "label": "Frames processed",
        "unit": "frames",
        "higher_is_better": None,
    },
    "frame_detections": {
        "label": "Frame detections",
        "unit": "detections",
        "higher_is_better": None,
    },
    "tracked_observations": {
        "label": "Tracked observations",
        "unit": "observations",
        "higher_is_better": None,
    },
    "unique_tracks": {
        "label": "Unique tracks",
        "unit": "tracks",
        "higher_is_better": None,
    },
}


def as_number(value: Any) -> float | int | None:
    """Return a finite numeric value or None."""

    if isinstance(value, bool):
        return None

    if not isinstance(value, (int, float)):
        return None

    if value != value:
        return None

    if value in (float("inf"), float("-inf")):
        return None

    return value


def extract_run_metrics(manifest: dict) -> dict:
    """Extract comparable metrics from one run manifest."""

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
        "average_processing_fps": as_number(
            results.get("average_processing_fps")
        ),
        "processing_duration_seconds": as_number(
            processing_metrics.get("duration_seconds")
        ),
        "pipeline_duration_seconds": as_number(
            performance.get("pipeline_duration_seconds")
        ),
        "initialization_overhead_seconds": as_number(
            performance.get(
                "initialization_overhead_seconds"
            )
        ),
        "frames_processed": as_number(
            results.get("frames_processed")
        ),
        "frame_detections": as_number(
            results.get("frame_detections")
        ),
        "tracked_observations": as_number(
            results.get("tracked_observations")
        ),
        "unique_tracks": as_number(
            results.get("unique_tracks")
        ),
    }


def classify_change(
    difference: float,
    higher_is_better: bool | None,
) -> str:
    """Describe whether a metric change is favorable."""

    if difference == 0:
        return "unchanged"

    if higher_is_better is None:
        return "changed"

    improved = (
        difference > 0
        if higher_is_better
        else difference < 0
    )

    return "improved" if improved else "regressed"


def compare_metric(
    name: str,
    baseline_value: float | int | None,
    candidate_value: float | int | None,
) -> dict:
    """Compare one metric between two runs."""

    definition = METRIC_DEFINITIONS[name]

    available = (
        baseline_value is not None
        and candidate_value is not None
    )

    if not available:
        return {
            "name": name,
            "label": definition["label"],
            "unit": definition["unit"],
            "higher_is_better": (
                definition["higher_is_better"]
            ),
            "available": False,
            "baseline": baseline_value,
            "candidate": candidate_value,
            "absolute_change": None,
            "percentage_change": None,
            "assessment": "unavailable",
        }

    absolute_change = (
        candidate_value - baseline_value
    )

    percentage_change = (
        None
        if baseline_value == 0
        else absolute_change / abs(baseline_value) * 100
    )

    return {
        "name": name,
        "label": definition["label"],
        "unit": definition["unit"],
        "higher_is_better": (
            definition["higher_is_better"]
        ),
        "available": True,
        "baseline": baseline_value,
        "candidate": candidate_value,
        "absolute_change": round(
            absolute_change,
            6,
        ),
        "percentage_change": (
            None
            if percentage_change is None
            else round(percentage_change, 3)
        ),
        "assessment": classify_change(
            difference=absolute_change,
            higher_is_better=(
                definition["higher_is_better"]
            ),
        ),
    }


def compare_runs(
    baseline_manifest: dict,
    candidate_manifest: dict,
) -> dict:
    """Compare candidate-run performance with a baseline run."""

    baseline_metrics = extract_run_metrics(
        baseline_manifest
    )
    candidate_metrics = extract_run_metrics(
        candidate_manifest
    )

    comparisons = {
        name: compare_metric(
            name=name,
            baseline_value=baseline_metrics[name],
            candidate_value=candidate_metrics[name],
        )
        for name in METRIC_DEFINITIONS
    }

    available_count = sum(
        comparison["available"]
        for comparison in comparisons.values()
    )

    improved_count = sum(
        comparison["assessment"] == "improved"
        for comparison in comparisons.values()
    )

    regressed_count = sum(
        comparison["assessment"] == "regressed"
        for comparison in comparisons.values()
    )

    unchanged_count = sum(
        comparison["assessment"] == "unchanged"
        for comparison in comparisons.values()
    )

    return {
        "baseline_run_id": baseline_manifest.get(
            "run_id"
        ),
        "candidate_run_id": candidate_manifest.get(
            "run_id"
        ),
        "available_metric_count": available_count,
        "total_metric_count": len(METRIC_DEFINITIONS),
        "improved_metric_count": improved_count,
        "regressed_metric_count": regressed_count,
        "unchanged_metric_count": unchanged_count,
        "metrics": comparisons,
    }
