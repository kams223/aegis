import csv

import pytest

from aegis.world_model.track_quality import TrackQualityEvaluator
from aegis.world_model.track_summarizer import TrackSummarizer


def make_observation(
    frame_number: int,
    timestamp_seconds: float,
    label: str,
    confidence: float,
    center_x: float,
    center_y: float,
) -> dict:
    """Create one synthetic frame-level track observation."""

    return {
        "frame_number": str(frame_number),
        "timestamp_seconds": str(timestamp_seconds),
        "track_id": "7",
        "label": label,
        "confidence": str(confidence),
        "x1": str(center_x - 10),
        "y1": str(center_y - 20),
        "x2": str(center_x + 10),
        "y2": str(center_y + 20),
        "center_x": str(center_x),
        "center_y": str(center_y),
        "width": "20",
        "height": "40",
    }


def make_summary(
    observation_count: int,
    duration_seconds: float,
    average_confidence: float,
) -> dict:
    """Create one synthetic summarized track."""

    return {
        "track_id": "7",
        "dominant_label": "person",
        "observation_count": str(observation_count),
        "first_frame": "1",
        "last_frame": str(observation_count),
        "first_seen_seconds": "0.0",
        "last_seen_seconds": str(duration_seconds),
        "duration_seconds": str(duration_seconds),
        "average_confidence": str(average_confidence),
        "start_center_x": "100.0",
        "start_center_y": "200.0",
        "end_center_x": "130.0",
        "end_center_y": "240.0",
        "displacement_pixels": "50.0",
    }


def test_track_summarizer_calculates_track_metrics():
    summarizer = TrackSummarizer(
        observations_path=None
    )

    observations = [
        make_observation(
            frame_number=1,
            timestamp_seconds=0.0,
            label="person",
            confidence=0.60,
            center_x=100.0,
            center_y=200.0,
        ),
        make_observation(
            frame_number=2,
            timestamp_seconds=0.1,
            label="person",
            confidence=0.80,
            center_x=130.0,
            center_y=240.0,
        ),
        make_observation(
            frame_number=3,
            timestamp_seconds=0.2,
            label="car",
            confidence=0.70,
            center_x=130.0,
            center_y=240.0,
        ),
    ]

    summary = summarizer.summarize_track(
        track_id=7,
        observations=observations,
    )

    assert summary["track_id"] == 7
    assert summary["dominant_label"] == "person"
    assert summary["observation_count"] == 3
    assert summary["first_frame"] == 1
    assert summary["last_frame"] == 3
    assert summary["duration_seconds"] == pytest.approx(0.2)
    assert summary["average_confidence"] == pytest.approx(0.7)
    assert summary["displacement_pixels"] == pytest.approx(50.0)


def test_quality_evaluator_marks_stable_track():
    evaluator = TrackQualityEvaluator()

    quality, reason = evaluator.evaluate(
        make_summary(
            observation_count=20,
            duration_seconds=1.5,
            average_confidence=0.75,
        )
    )

    assert quality == "stable"
    assert "Persistent" in reason


def test_quality_evaluator_marks_tentative_track():
    evaluator = TrackQualityEvaluator()

    quality, reason = evaluator.evaluate(
        make_summary(
            observation_count=4,
            duration_seconds=0.1,
            average_confidence=0.55,
        )
    )

    assert quality == "tentative"
    assert "requires more persistence" in reason


def test_quality_evaluator_marks_weak_track():
    evaluator = TrackQualityEvaluator()

    quality, reason = evaluator.evaluate(
        make_summary(
            observation_count=1,
            duration_seconds=0.0,
            average_confidence=0.30,
        )
    )

    assert quality == "weak"
    assert "too few observations" in reason
    assert "low average confidence" in reason


def test_quality_process_writes_classified_csv(tmp_path):
    input_path = tmp_path / "summaries.csv"
    output_path = tmp_path / "quality.csv"

    summaries = [
        make_summary(20, 1.5, 0.75),
        make_summary(4, 0.1, 0.55),
        make_summary(1, 0.0, 0.30),
    ]

    with input_path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as input_file:
        writer = csv.DictWriter(
            input_file,
            fieldnames=summaries[0].keys(),
        )
        writer.writeheader()
        writer.writerows(summaries)

    evaluator = TrackQualityEvaluator()
    counts = evaluator.process(input_path, output_path)

    assert counts == {
        "stable": 1,
        "tentative": 1,
        "weak": 1,
    }

    assert output_path.is_file()

    with output_path.open(
        mode="r",
        newline="",
        encoding="utf-8",
    ) as output_file:
        rows = list(csv.DictReader(output_file))

    assert len(rows) == 3
    assert rows[0]["quality_level"] == "stable"
    assert rows[1]["quality_level"] == "tentative"
    assert rows[2]["quality_level"] == "weak"
