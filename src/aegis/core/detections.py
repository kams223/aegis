from dataclasses import dataclass
from typing import List


@dataclass
class Detection:
    object_id: int
    label: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


@dataclass
class DetectionMessage:
    sensor_id: str
    timestamp: float
    detections: List[Detection]
