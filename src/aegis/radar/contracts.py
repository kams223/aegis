"""Immutable radar detection evidence in canonical SI conventions."""

from dataclasses import dataclass
from math import isfinite, pi

from aegis.fusion.contracts import MeasurementTime


def _require_identifier(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty or whitespace")


@dataclass(frozen=True)
class RadarPolarDetectionMeasurement:
    """One radar detection's polar evidence, not a target state.

    The sensor-local frame is right-handed: +x forward along declared
    boresight, +y left, +z up. range_m is finite nonnegative straight-line
    slant range from the declared measurement origin, in metres. Zero is
    valid, not missing data, but does not establish a direction in space.

    azimuth_rad is finite radians in [-pi, pi), zero at +x and positive
    from +x toward +y about +z. elevation_rad, when supplied, is finite
    radians from the local x-y plane toward +z, in [-pi/2, pi/2].

    radial_velocity_mps is finite sensor-relative line-of-sight range rate
    in metres/second: positive receding, negative approaching. It is not
    full target velocity. None means no usable measurement of that optional
    component; zero is a measured value. Missing elevation does not imply
    a point in the x-y plane. Values are never wrapped, clamped, or converted.
    """

    range_m: float
    azimuth_rad: float
    elevation_rad: float | None = None
    radial_velocity_mps: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.range_m) or self.range_m < 0:
            raise ValueError("range_m must be finite and nonnegative")
        if not isfinite(self.azimuth_rad) or not -pi <= self.azimuth_rad < pi:
            raise ValueError("azimuth_rad must be finite and in [-pi, pi)")
        if self.elevation_rad is not None and (
            not isfinite(self.elevation_rad)
            or not -pi / 2 <= self.elevation_rad <= pi / 2
        ):
            raise ValueError("elevation_rad must be finite and in [-pi/2, pi/2]")
        if self.radial_velocity_mps is not None and not isfinite(self.radial_velocity_mps):
            raise ValueError("radial_velocity_mps must be finite")


@dataclass(frozen=True)
class RadarDetection:
    """Producer-owned event provenance with canonical radar detection evidence.

    source_session_id namespaces one source evidence sequence, not a sensor;
    it must change when evidence identifiers reset. evidence_id is a stable
    event identity inside that namespace, never physical target identity.
    measurement_time is producer-supplied measurement/event time, not processing
    time; its explicit clock domain is preserved without synchronization.

    local_detection_id optionally preserves producer-local detection provenance,
    not track or target identity. Producers whose local IDs reset per scan must
    include sufficient scan scope before constructing this value. Identifiers
    are retained unchanged. The immutable measurement is already canonical SI.
    """

    source_session_id: str
    evidence_id: str
    measurement_time: MeasurementTime
    measurement: RadarPolarDetectionMeasurement
    local_detection_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.source_session_id, "source_session_id")
        _require_identifier(self.evidence_id, "evidence_id")
        if self.local_detection_id is not None:
            _require_identifier(self.local_detection_id, "local_detection_id")
        if not isfinite(self.measurement_time.seconds):
            raise ValueError("measurement_time.seconds must be finite")
