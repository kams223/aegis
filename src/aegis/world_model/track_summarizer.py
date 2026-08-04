import csv
from collections import Counter
from pathlib import Path


class TrackSummarizer:
    """Convert frame-level observations into one summary per track."""

    FIELD_NAMES = [
        "track_id",
        "dominant_label",
        "observation_count",
        "first_frame",
        "last_frame",
        "first_seen_seconds",
        "last_seen_seconds",
        "duration_seconds",
        "average_confidence",
        "start_center_x",
        "start_center_y",
        "end_center_x",
        "end_center_y",
        "displacement_pixels",
    ]

    def __init__(self, observations_path: Path):
        self.observations_path = observations_path

    def read_observations(self) -> dict[int, list[dict]]:
        """Group CSV observations by track ID."""

        if not self.observations_path.is_file():
            raise FileNotFoundError(
                f"Observation file not found: {self.observations_path}"
            )

        tracks: dict[int, list[dict]] = {}

        with self.observations_path.open(
            mode="r",
            newline="",
            encoding="utf-8",
        ) as input_file:
            reader = csv.DictReader(input_file)

            for row in reader:
                track_id = int(row["track_id"])
                tracks.setdefault(track_id, []).append(row)

        return tracks

    def summarize_track(
        self,
        track_id: int,
        observations: list[dict],
    ) -> dict:
        """Create one summary from a track's observations."""

        observations.sort(
            key=lambda row: int(row["frame_number"])
        )

        first = observations[0]
        last = observations[-1]

        labels = Counter(
            row["label"] for row in observations
        )
        dominant_label = labels.most_common(1)[0][0]

        confidences = [
            float(row["confidence"])
            for row in observations
        ]
        average_confidence = sum(confidences) / len(confidences)

        start_x = float(first["center_x"])
        start_y = float(first["center_y"])
        end_x = float(last["center_x"])
        end_y = float(last["center_y"])

        displacement_x = end_x - start_x
        displacement_y = end_y - start_y
        displacement_pixels = (
            displacement_x ** 2 + displacement_y ** 2
        ) ** 0.5

        first_seen = float(first["timestamp_seconds"])
        last_seen = float(last["timestamp_seconds"])

        return {
            "track_id": track_id,
            "dominant_label": dominant_label,
            "observation_count": len(observations),
            "first_frame": int(first["frame_number"]),
            "last_frame": int(last["frame_number"]),
            "first_seen_seconds": round(first_seen, 3),
            "last_seen_seconds": round(last_seen, 3),
            "duration_seconds": round(
                max(0.0, last_seen - first_seen),
                3,
            ),
            "average_confidence": round(
                average_confidence,
                4,
            ),
            "start_center_x": round(start_x, 2),
            "start_center_y": round(start_y, 2),
            "end_center_x": round(end_x, 2),
            "end_center_y": round(end_y, 2),
            "displacement_pixels": round(
                displacement_pixels,
                2,
            ),
        }

    def write_summaries(self, output_path: Path) -> int:
        """Generate and save one summary row per track."""

        tracks = self.read_observations()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        summaries = [
            self.summarize_track(track_id, observations)
            for track_id, observations in sorted(tracks.items())
        ]

        with output_path.open(
            mode="w",
            newline="",
            encoding="utf-8",
        ) as output_file:
            writer = csv.DictWriter(
                output_file,
                fieldnames=self.FIELD_NAMES,
            )

            writer.writeheader()
            writer.writerows(summaries)

        return len(summaries)
