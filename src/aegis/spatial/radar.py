"""Pure Cartesian projection of canonical radar-local polar evidence."""

from dataclasses import dataclass
from math import cos, isfinite, sin

from aegis.fusion.contracts import ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement


@dataclass(frozen=True)
class RadarPoint:
    """Position in metres in the explicitly supplied radar-local frame.

    Axes are right-handed: +x forward, +y left, +z up. The original polar
    measurement and frame are retained by identity. No direction or full
    velocity is established, including at the origin. Radial range rate remains
    available only as original evidence: positive receding, negative approaching.
    """

    x_m: float
    y_m: float
    z_m: float
    reference_frame: ReferenceFrame
    source_measurement: RadarPolarDetectionMeasurement

    def __post_init__(self) -> None:
        for name in ("x_m", "y_m", "z_m"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not isinstance(self.reference_frame, ReferenceFrame):
            raise TypeError("reference_frame must be a ReferenceFrame")
        if not isinstance(self.source_measurement, RadarPolarDetectionMeasurement):
            raise TypeError("source_measurement must be a RadarPolarDetectionMeasurement")


def radar_measurement_to_point(
    measurement: RadarPolarDetectionMeasurement,
    *,
    reference_frame: ReferenceFrame,
) -> RadarPoint | None:
    """Project slant range and supplied angles without transforms or inference.

    None means no unique Cartesian point follows from a valid positive-range
    measurement with missing elevation. It does not mean invalid measurement,
    no detection, or lost evidence; the unchanged polar measurement remains
    authoritative. Missing elevation never implies a ground-plane position.

    Zero range (including negative zero) gives the origin even without elevation,
    but establishes no direction. Tiny positive ranges are not treated as zero.
    Existing angle bounds and units are preserved without wrapping, clamping,
    or snapping. Floating-point rounding and subnormal underflow are permitted;
    nonfinite Cartesian components are rejected by RadarPoint.
    """
    if not isinstance(measurement, RadarPolarDetectionMeasurement):
        raise TypeError("measurement must be a RadarPolarDetectionMeasurement")
    if not isinstance(reference_frame, ReferenceFrame):
        raise TypeError("reference_frame must be a ReferenceFrame")
    if measurement.range_m == 0:
        return RadarPoint(0.0, 0.0, 0.0, reference_frame, measurement)
    if measurement.elevation_rad is None:
        return None

    r = measurement.range_m
    a = measurement.azimuth_rad
    e = measurement.elevation_rad
    horizontal = r * cos(e)
    return RadarPoint(horizontal * cos(a), horizontal * sin(a), r * sin(e),
                      reference_frame, measurement)
