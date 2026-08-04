from pathlib import Path

import numpy as np
from ultralytics import YOLO


class ObjectDetector:
    """Run general-purpose object detection on individual video frames."""

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.35,
        image_size: int = 640,
    ):
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold must be between 0.0 and 1.0"
            )

        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size

        print(f"Loading object detector: {model_path}")

        self.model = YOLO(model_path)

        print("Object detector loaded.")

    def detect(self, frame: np.ndarray):
        """Return the first Ultralytics result for one OpenCV frame."""

        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            device="cpu",
            verbose=False,
        )

        return results[0]
