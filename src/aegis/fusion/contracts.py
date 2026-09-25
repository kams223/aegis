"""Normalized evidence at the future association/fusion boundary.

These values do not replace raw sensor packets, image contracts, or the scalar
SensorMessage prototype. No synchronization, transforms, or association occur.
"""

from dataclasses import dataclass
from typing import Generic, TypeVar


TMeasurement = TypeVar("TMeasurement", covariant=True)


def _require_identifier(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty or whitespace")


@dataclass(frozen=True)
class MeasurementTime:
    """Producer-supplied measurement time in seconds within an explicit clock.

    clock_domain identifies a particular origin/timebase, not just a category:
    for example 'video:<opening-id>' or 'device:<id>:<boot-id>'. Producers must
    document that timebase. Equal numbers in different domains are not aligned.
    Values are preserved, including negative offsets; no clock is read and no
    conversion or synchronization is performed.
    """

    seconds: float
    clock_domain: str

    def __post_init__(self) -> None:
        _require_identifier(self.clock_domain, "clock_domain")


@dataclass(frozen=True)
class ReferenceFrame:
    """Identity of the frame in which a measurement is expressed.

    frame_id names a specific frame, e.g. 'camera-a:image' or 'radar-b:local',
    rather than only a category such as 'pixels'. Producers define its origin,
    axes, and convention; concrete measurement types define component units and
    representation (e.g. pixels versus metres/radians). This reference supplies
    no transform, calibration, or guarantee that two measurements are comparable.
    """

    frame_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.frame_id, "frame_id")


@dataclass(frozen=True)
class SensorObservation(Generic[TMeasurement]):
    """One item of normalized sensor evidence, not a fused target.

    sensor_id identifies the physical/logical sensor, not a stream opening or
    pipeline run. The producer supplies observation_id, unique within the
    collection being exchanged; this module neither allocates nor checks global
    uniqueness. IDs and time/frame references are preserved without rewriting.

    source_local_id optionally preserves a producer-local detection/track key.
    It is opaque and is not a target ID. Producers must include a session scope
    in this key if their local IDs reset (e.g. '<opening-id>/7'). Equal local
    keys from different sensors do not establish shared target identity.

    measurement retains its concrete static type and is held by reference.
    Producers should supply immutable typed values, such as frozen dataclasses;
    this envelope does not recursively freeze or validate arbitrary payloads.
    Payload geometry and units belong to the concrete measurement contract.
    """

    observation_id: str
    sensor_id: str
    measurement_time: MeasurementTime
    reference_frame: ReferenceFrame
    measurement: TMeasurement
    source_local_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.observation_id, "observation_id")
        _require_identifier(self.sensor_id, "sensor_id")
        if self.source_local_id is not None:
            _require_identifier(self.source_local_id, "source_local_id")


@dataclass(frozen=True)
class ObservationBatch(Generic[TMeasurement]):
    """Ordered evidence for processing; empty batches are valid.

    A batch implies neither a common target nor a common sensor, clock, or
    reference frame. Use a concrete measurement type or a consumer-specific union
    as the type parameter. No sorting, deduplication, or association is performed.
    """

    observations: tuple[SensorObservation[TMeasurement], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple):
            raise TypeError("observations must be a tuple")
