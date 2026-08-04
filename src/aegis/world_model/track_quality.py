import csv
from pathlib import Path


class TrackQualityEvaluator:
    """Evaluate the stability of summarized object tracks."""

    OUTPUT_FIELDS = [
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

    def __init__(
        self,
        minimum_stable_observations: int = 5,
        minimum_stable_duration: float = 0.2,
        minimum_stable_confidence: float = 0.50,
    ):
        self.minimum_stable_observations = (
            minimum_stable_observations
        )
        self.minimum_stable_duration = minimum_stable_duration
        self.minimum_stable_confidence = (
            minimum_stable_confidence
        )

    def evaluate(self, track: dict) -> tuple[str, str]:
        """Assign a stability level and an explanatory reason."""

        observation_count = int(track["observation_count"])
        duration = float(track["duration_seconds"])
        confidence = float(track["average_confidence"])

        if (
            observation_count >= self.minimum_stable_observations
            and duration >= self.minimum_stable_duration
            and confidence >= self.minimum_stable_confidence
        ):
            return (
                "stable",
                "Persistent track with sufficient average confidence",
            )

        if observation_count >= 3 and confidence >= 0.40:
            return (
                "tentative",
                "Track requires more persistence or confidence",
            )

        reasons = []

        if observation_count < 3:
            reasons.append("too few observations")

        if confidence < 0.40:
            reasons.append("low average confidence")

        if not reasons:
            reasons.append("insufficient duration")

        return "weak", "; ".join(reasons)

    def process(
        self,
        input_path: Path,
        output_path: Path,
    ) -> dict[str, int]:
        """Evaluate all summarized tracks and write the results."""

        if not input_path.is_file():
            raise FileNotFoundError(
                f"Track summary file not found: {input_path}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        counts = {
            "stable": 0,
            "tentative": 0,
            "weak": 0,
        }

        with input_path.open(
            mode="r",
            newline="",
            encoding="utf-8",
        ) as input_file:
            reader = csv.DictReader(input_file)

            with output_path.open(
                mode="w",
                newline="",
                encoding="utf-8",
            ) as output_file:
                writer = csv.DictWriter(
                    output_file,
                    fieldnames=self.OUTPUT_FIELDS,
                )
                writer.writeheader()

                for track in reader:
                    quality_level, quality_reason = (
                        self.evaluate(track)
                    )

                    counts[quality_level] += 1

                    writer.writerow(
                        {
                            "track_id": track["track_id"],
                            "dominant_label": track[
                                "dominant_label"
                            ],
                            "quality_level": quality_level,
                            "quality_reason": quality_reason,
                            "observation_count": track[
                                "observation_count"
                            ],
                            "duration_seconds": track[
                                "duration_seconds"
                            ],
                            "average_confidence": track[
                                "average_confidence"
                            ],
                            "displacement_pixels": track[
                                "displacement_pixels"
                            ],
                            "first_frame": track["first_frame"],
                            "last_frame": track["last_frame"],
                            "first_seen_seconds": track[
                                "first_seen_seconds"
                            ],
                            "last_seen_seconds": track[
                                "last_seen_seconds"
                            ],
                            "start_center_x": track[
                                "start_center_x"
                            ],
                            "start_center_y": track[
                                "start_center_y"
                            ],
                            "end_center_x": track["end_center_x"],
                            "end_center_y": track["end_center_y"],
                        }
                    )

        return counts
