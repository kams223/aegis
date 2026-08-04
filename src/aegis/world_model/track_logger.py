import csv
from pathlib import Path
from typing import TextIO


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

    def write_result(
        self,
        result,
        frame_number: int,
        timestamp_seconds: float,
    ) -> int:
        """Write confirmed tracks from one inference result."""

        if self.writer is None:
            raise RuntimeError("TrackLogger must be opened before use.")

        boxes = result.boxes

        if boxes is None or boxes.id is None:
            return 0

        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        class_ids = boxes.cls.cpu().tolist()
        track_ids = boxes.id.cpu().tolist()

        written = 0

        for coordinates_row, confidence, class_id, track_id in zip(
            coordinates,
            confidences,
            class_ids,
            track_ids,
        ):
            x1, y1, x2, y2 = coordinates_row

            width = x2 - x1
            height = y2 - y1
            center_x = x1 + width / 2
            center_y = y1 + height / 2

            class_number = int(class_id)
            label = str(result.names[class_number])

            self.writer.writerow(
                {
                    "frame_number": frame_number,
                    "timestamp_seconds": round(timestamp_seconds, 3),
                    "track_id": int(track_id),
                    "label": label,
                    "confidence": round(float(confidence), 4),
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
