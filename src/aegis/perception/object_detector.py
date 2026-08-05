from pathlib import Path

import numpy as np
from ultralytics import YOLO


class ObjectDetector:
    """Detect and track general-purpose objects in video frames."""

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.35,
        image_size: int = 640,
        tracker_config: str = "bytetrack.yaml",
        device: str = "cpu",
    ):
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold must be between 0.0 and 1.0"
            )

        if image_size <= 0:
            raise ValueError("image_size must be positive")

        if not device.strip():
            raise ValueError("device cannot be empty")

        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size
        self.tracker_config = tracker_config
        self.device = device

        print(f"Loading object detector: {model_path}")
        print(f"Inference device: {device}")

        self.model = YOLO(model_path)

        print("Object detector loaded.")

    def detect(self, frame: np.ndarray):
        """Detect objects independently in one frame."""

        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )

        return results[0]

    def track(self, frame: np.ndarray):
        """Detect objects and preserve identities between frames."""

        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.tracker_config,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )

        return results[0]
