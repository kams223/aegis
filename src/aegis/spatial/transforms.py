"""Explicit static rigid coordinate conversions, without frame inference."""

from dataclasses import dataclass
from math import fsum, hypot, isclose, isfinite

from aegis.fusion.contracts import ReferenceFrame
from aegis.spatial.camera import CameraRay
from aegis.spatial.radar import RadarPoint


_ROTATION_TOLERANCE = 1e-12
_DIRECTION_TOLERANCE = 1e-11
_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    try:
        valid = isfinite(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not valid:
        raise ValueError(f"{name} must be finite")


def _frame(name: str, value: ReferenceFrame) -> None:
    if not isinstance(value, ReferenceFrame):
        raise TypeError(f"{name} must be a ReferenceFrame")


def _sum_finite(terms: tuple[float, ...]) -> float:
    """Reject intermediate/final overflow; do not correct or rescale geometry."""
    try:
        for term in terms:
            _finite("arithmetic term", term)
        result = fsum(terms)
        _finite("arithmetic result", result)
        return result
    except OverflowError as exc:
        raise ValueError("coordinate arithmetic overflow") from exc


@dataclass(frozen=True)
class RigidTransform:
    """Passive coordinate conversion: p_target = R p_source + t; d_target = R d_source.

    Vectors are columns. Matrix rows are stored in tuple order; R[i][j] is
    target component i of source basis axis j. Rotation is dimensionless;
    translation is the source origin expressed in target coordinates, in metres.
    The caller supplies compatible Cartesian frames and static parameters.

    Row/column orthogonality and determinant +1 use absolute tolerance 1e-12
    with zero relative tolerance. Accepted entries are retained without repair.
    Equal frame identifiers require exact identity rotation and zero translation.
    """

    source_frame: ReferenceFrame
    target_frame: ReferenceFrame
    rotation_target_from_source: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    translation_target_from_source_m: tuple[float, float, float]

    def __post_init__(self) -> None:
        _frame("source_frame", self.source_frame)
        _frame("target_frame", self.target_frame)
        rotation = self.rotation_target_from_source
        if not isinstance(rotation, tuple) or len(rotation) != 3:
            raise TypeError("rotation must be a tuple of three tuple rows")
        for row in rotation:
            if not isinstance(row, tuple) or len(row) != 3:
                raise TypeError("rotation rows must be tuples of three entries")
            for value in row:
                _finite("rotation entry", value)
                if abs(value) > 1 + _ROTATION_TOLERANCE:
                    raise ValueError("rotation entry exceeds unit bounds")
        for vectors in (rotation, tuple(zip(*rotation))):
            for i in range(3):
                for j in range(i, 3):
                    product = fsum(vectors[i][k] * vectors[j][k] for k in range(3))
                    if not isclose(product, float(i == j), rel_tol=0,
                                   abs_tol=_ROTATION_TOLERANCE):
                        raise ValueError("rotation must have orthogonal unit rows and columns")
        a, b, c = rotation
        determinant = fsum((
            a[0] * (b[1] * c[2] - b[2] * c[1]),
            -a[1] * (b[0] * c[2] - b[2] * c[0]),
            a[2] * (b[0] * c[1] - b[1] * c[0]),
        ))
        if not isclose(determinant, 1.0, rel_tol=0, abs_tol=_ROTATION_TOLERANCE):
            raise ValueError("rotation determinant must be +1")
        translation = self.translation_target_from_source_m
        if not isinstance(translation, tuple) or len(translation) != 3:
            raise TypeError("translation must be a tuple of three components")
        for value in translation:
            _finite("translation component", value)
        if self.source_frame == self.target_frame and (
            rotation != _IDENTITY or any(value != 0 for value in translation)
        ):
            raise ValueError("same-frame transform must be exact identity")


@dataclass(frozen=True)
class TransformedPoint:
    """Metric position in reference_frame; source radar evidence is unchanged."""

    x_m: float
    y_m: float
    z_m: float
    reference_frame: ReferenceFrame
    source_point: RadarPoint

    def __post_init__(self) -> None:
        for name in ("x_m", "y_m", "z_m"):
            _finite(name, getattr(self, name))
        _frame("reference_frame", self.reference_frame)
        if not isinstance(self.source_point, RadarPoint):
            raise TypeError("source_point must be a RadarPoint")


@dataclass(frozen=True)
class RotatedDirection:
    """Unit direction in reference_frame, not a position or relocated camera ray.

    No depth or target-frame ray origin is established. Target z may be negative.
    Source image/calibration evidence is retained through the original camera ray.
    Unit norm uses absolute tolerance 1e-11, zero relative tolerance; no normalization.
    """

    direction_x: float
    direction_y: float
    direction_z: float
    reference_frame: ReferenceFrame
    source_ray: CameraRay

    def __post_init__(self) -> None:
        for name in ("direction_x", "direction_y", "direction_z"):
            _finite(name, getattr(self, name))
        if not isclose(hypot(self.direction_x, self.direction_y, self.direction_z),
                       1.0, rel_tol=0, abs_tol=_DIRECTION_TOLERANCE):
            raise ValueError("direction must have unit length")
        _frame("reference_frame", self.reference_frame)
        if not isinstance(self.source_ray, CameraRay):
            raise TypeError("source_ray must be a CameraRay")


def transform_radar_point(point: RadarPoint, transform: RigidTransform) -> TransformedPoint:
    """Apply R p + t in metres with explicit source-frame matching.

    Floating-point rounding is permitted. Intermediate or final nonfinite
    arithmetic is rejected, even if exact arithmetic could cancel to a finite
    value. No missing radar elevation or other geometry is inferred.
    """
    if not isinstance(point, RadarPoint):
        raise TypeError("point must be a RadarPoint")
    if not isinstance(transform, RigidTransform):
        raise TypeError("transform must be a RigidTransform")
    if point.reference_frame != transform.source_frame:
        raise ValueError("point reference_frame must match transform source_frame")
    values = (point.x_m, point.y_m, point.z_m)
    try:
        components = tuple(_sum_finite(tuple(row[j] * values[j] for j in range(3)) + (offset,))
                           for row, offset in zip(transform.rotation_target_from_source,
                                                  transform.translation_target_from_source_m))
    except OverflowError as exc:
        raise ValueError("coordinate arithmetic overflow") from exc
    return TransformedPoint(*components, transform.target_frame, point)


def rotate_camera_direction(ray: CameraRay, transform: RigidTransform) -> RotatedDirection:
    """Apply R d only; translation never affects direction or supplies depth."""
    if not isinstance(ray, CameraRay):
        raise TypeError("ray must be a CameraRay")
    if not isinstance(transform, RigidTransform):
        raise TypeError("transform must be a RigidTransform")
    if ray.optical_frame != transform.source_frame:
        raise ValueError("ray optical_frame must match transform source_frame")
    values = (ray.direction_x, ray.direction_y, ray.direction_z)
    try:
        components = tuple(_sum_finite(tuple(row[j] * values[j] for j in range(3)))
                           for row in transform.rotation_target_from_source)
    except OverflowError as exc:
        raise ValueError("direction arithmetic overflow") from exc
    return RotatedDirection(*components, transform.target_frame, ray)
