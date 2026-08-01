from dataclasses import dataclass
from typing import Any
import time


@dataclass
class SensorMessage:
    sensor_id: str
    sensor_type: str
    timestamp: float
    data: Any

    @classmethod
    def create(cls, sensor_id, sensor_type, data):
        return cls(
            sensor_id=sensor_id,
            sensor_type=sensor_type,
            timestamp=time.time(),
            data=data
        )
