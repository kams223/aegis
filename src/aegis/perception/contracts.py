"""Aegis detection values and a backend-independent detector interface.

These contracts coexist with the legacy core.detections types.
"""

from dataclasses import dataclass
from typing import Protocol

from aegis.core.frames import Frame, FrameMetadata


@dataclass(frozen=True)
class ObjectDetection:
    """A classification and floating-point xyxy box, without tracking identity.

    Coordinates use original image pixels with a top-left origin. They are
    not normalized or rounded. class_id belongs to the detector's label set.
    """

    class_id: int
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class DetectionBatch:
    """Ordered detections for one frame; an empty tuple is valid."""

    frame: FrameMetadata
    detections: tuple[ObjectDetection, ...]


class Detector(Protocol):
    """Convert one frame into Aegis-owned detections."""

    def detect(self, frame: Frame) -> DetectionBatch:
        """Return detections associated with the input frame's metadata."""
        ...
