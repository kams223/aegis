"""Pure projection of explicitly selected ideal/rectified image coordinates."""

from dataclasses import dataclass
from math import hypot, isclose, isfinite

from aegis.fusion.contracts import ReferenceFrame


def _dimensions(width: int, height: int) -> None:
    for name, value in (("image_width", width), ("image_height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")


def _finite(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _calibration(value: str) -> None:
    if not value.strip():
        raise ValueError("calibration_id must be nonblank")


@dataclass(frozen=True)
class ImagePoint:
    """Pixel-space coordinate selected by the caller; u right, v down.

    Dimensions and image_frame identify its pixel coordinate system. Finite
    out-of-bounds coordinates are allowed without clamping or visibility policy.
    No detection anchor, depth, or target identity is implied.
    """

    u_px: float
    v_px: float
    image_width: int
    image_height: int
    image_frame: ReferenceFrame

    def __post_init__(self) -> None:
        _finite("u_px", self.u_px)
        _finite("v_px", self.v_px)
        _dimensions(self.image_width, self.image_height)


@dataclass(frozen=True)
class PinholeCameraIntrinsics:
    """Explicit calibration for an ideal/rectified zero-skew pinhole image.

    Supplying this value asserts that the point coordinates are compatible with
    this model. No distortion correction or calibration inference occurs.
    Focal lengths and principal point are in pixels; the principal point need
    not be the image center. Optical axes are +x right, +y down, +z forward.
    Current process_video images are not proven rectified by this utility.
    """

    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    image_width: int
    image_height: int
    image_frame: ReferenceFrame
    optical_frame: ReferenceFrame
    calibration_id: str

    def __post_init__(self) -> None:
        for name in ("fx_px", "fy_px", "cx_px", "cy_px"):
            _finite(name, getattr(self, name))
        for name in ("fx_px", "fy_px"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        _dimensions(self.image_width, self.image_height)
        _calibration(self.calibration_id)


@dataclass(frozen=True)
class CameraRay:
    """Unit direction from the optical origin, expressed in optical_frame.

    Optical axes are +x right, +y down, +z forward. Metric distance is unknown:
    CameraRay does not establish target position or depth and is not a Point3D.
    The explicitly selected source point and calibration identity are retained.
    """

    direction_x: float
    direction_y: float
    direction_z: float
    optical_frame: ReferenceFrame
    source_image_point: ImagePoint
    calibration_id: str

    def __post_init__(self) -> None:
        for name in ("direction_x", "direction_y", "direction_z"):
            _finite(name, getattr(self, name))
        if not isclose(hypot(self.direction_x, self.direction_y, self.direction_z),
                       1.0, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("direction must have unit length")
        if self.direction_z <= 0:
            raise ValueError("direction_z must be positive")
        if not isinstance(self.source_image_point, ImagePoint):
            raise TypeError("source_image_point must be an ImagePoint")
        _calibration(self.calibration_id)


def image_point_to_camera_ray(
    point: ImagePoint, intrinsics: PinholeCameraIntrinsics,
) -> CameraRay:
    """Normalize ((u-cx)/fx, (v-cy)/fy, 1) without rescaling or transforms.

    Dimensions and image frames must match exactly. Floating-point overflow in
    normalized image coordinates raises ValueError rather than returning an
    invalid direction. No anchor is selected and no depth is inferred.
    """
    for name in ("image_width", "image_height", "image_frame"):
        if getattr(point, name) != getattr(intrinsics, name):
            raise ValueError(f"{name} must match intrinsics")
    x = (point.u_px - intrinsics.cx_px) / intrinsics.fx_px
    y = (point.v_px - intrinsics.cy_px) / intrinsics.fy_px
    _finite("normalized x", x)
    _finite("normalized y", y)
    # hypot evaluates sqrt(x*x + y*y + 1) without intermediate squaring overflow.
    norm = hypot(x, y, 1.0)
    return CameraRay(x / norm, y / norm, 1.0 / norm,
                     intrinsics.optical_frame, point, intrinsics.calibration_id)
