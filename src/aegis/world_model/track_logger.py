import csv
from pathlib import Path
from typing import TextIO

from aegis.tracking.contracts import TrackedObjectBatch


class TrackLogger:
    """Write confirmed tracking observations to a CSV file."""

    FIELD_NAMES = [
        "frame_number",
        "timestamp_seconds",
        "track_id",
        "label",
        "confidence",
        "x1",
        "y1",
        "x2",
        "y2",
        "center_x",
        "center_y",
        "width",
        "height",
    ]

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.file: TextIO | None = None
        self.writer: csv.DictWriter | None = None
        self.row_count = 0

    def open(self) -> None:
        """Create the output file and write its header."""

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        self.file = self.output_path.open(
            mode="w",
            newline="",
            encoding="utf-8",
        )

        self.writer = csv.DictWriter(
            self.file,
            fieldnames=self.FIELD_NAMES,
        )

        self.writer.writeheader()

    def write_batch(self, batch: TrackedObjectBatch) -> int:
        """Write assigned Aegis tracks in batch order."""

        if self.writer is None:
            raise RuntimeError("TrackLogger must be opened before use.")

        written = 0
        for tracked_object in batch.objects:
            detection = tracked_object.detection
            x1, y1, x2, y2 = detection.x1, detection.y1, detection.x2, detection.y2

            width = x2 - x1
            height = y2 - y1
            center_x = x1 + width / 2
            center_y = y1 + height / 2

            self.writer.writerow(
                {
                    "frame_number": batch.frame.frame_number,
                    "timestamp_seconds": round(batch.frame.timestamp_seconds, 3),
                    "track_id": tracked_object.track_id,
                    "label": detection.label,
                    "confidence": round(float(detection.confidence), 4),
                    "x1": round(float(x1), 2),
                    "y1": round(float(y1), 2),
                    "x2": round(float(x2), 2),
                    "y2": round(float(y2), 2),
                    "center_x": round(float(center_x), 2),
                    "center_y": round(float(center_y), 2),
                    "width": round(float(width), 2),
                    "height": round(float(height), 2),
                }
            )

            written += 1
            self.row_count += 1

        return written

    def close(self) -> None:
        """Flush and close the CSV file."""

        if self.file is not None:
            self.file.close()
            self.file = None
            self.writer = None
