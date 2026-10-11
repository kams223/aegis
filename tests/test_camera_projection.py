"""Explicit pinhole projection contracts and dependency isolation."""

from dataclasses import FrozenInstanceError, replace
from math import hypot, inf, nan, sqrt
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import ReferenceFrame
from aegis.spatial.camera import (
    CameraRay, ImagePoint, PinholeCameraIntrinsics, image_point_to_camera_ray,
)


def calibration():
    return PinholeCameraIntrinsics(100.0, 200.0, 123.25, 87.5, 640, 480,
                                  ReferenceFrame("camera:image"),
                                  ReferenceFrame("camera:optical"), " calibration/v1 ")


def point(u=123.25, v=87.5):
    return ImagePoint(u, v, 640, 480, ReferenceFrame("camera:image"))


def direction(ray):
    return ray.direction_x, ray.direction_y, ray.direction_z


@pytest.mark.parametrize("obj,field", [
    (point(), "u_px"), (calibration(), "fx_px"),
    (image_point_to_camera_ray(point(), calibration()), "direction_x"),
])
def test_values_are_frozen(obj, field):
    with pytest.raises(FrozenInstanceError):
        setattr(obj, field, 9.0)


def test_off_center_principal_point_projects_forward():
    intrinsics = calibration()
    assert intrinsics.cx_px != intrinsics.image_width / 2
    assert intrinsics.cy_px != intrinsics.image_height / 2
    assert direction(image_point_to_camera_ray(point(), intrinsics)) == (0, 0, 1)


@pytest.mark.parametrize("u,v,axis,sign", [
    (124.25, 87.5, 0, 1), (122.25, 87.5, 0, -1),
    (123.25, 88.5, 1, 1), (123.25, 86.5, 1, -1),
])
def test_optical_axes(u, v, axis, sign):
    ray = image_point_to_camera_ray(point(u, v), calibration())
    assert direction(ray)[axis] * sign > 0
    assert ray.direction_z > 0
    assert hypot(*direction(ray)) == pytest.approx(1)


def test_fractional_coordinates_unequal_focals_and_no_rescaling():
    source = point(173.5, 138.0)
    intrinsics = calibration()
    before = (replace(source), replace(intrinsics))
    ray = image_point_to_camera_ray(source, intrinsics)
    x, y = 0.5025, 0.2525
    norm = sqrt(x*x + y*y + 1)
    assert direction(ray) == pytest.approx((x/norm, y/norm, 1/norm))
    assert ray.source_image_point is source
    assert source.u_px == 173.5 and source.v_px == 138.0
    assert ray.optical_frame is intrinsics.optical_frame
    assert ray.calibration_id == " calibration/v1 "
    assert (source, intrinsics) == before


@pytest.mark.parametrize("u,v", [(-10.5, 900.25), (1000.5, -70.25), (1e200, -1e200)])
def test_finite_out_of_bounds_points_are_projectable(u, v):
    source = point(u, v)
    ray = image_point_to_camera_ray(source, calibration())
    assert source.u_px == u and source.v_px == v
    assert ray.direction_z > 0
    assert hypot(*direction(ray)) == pytest.approx(1)


@pytest.mark.parametrize("field", ["u_px", "v_px"])
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_point_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        replace(point(), **{field: value})


@pytest.mark.parametrize("field", ["fx_px", "fy_px", "cx_px", "cy_px"])
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_intrinsics_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        replace(calibration(), **{field: value})


@pytest.mark.parametrize("field", ["fx_px", "fy_px"])
@pytest.mark.parametrize("value", [0, -1])
def test_nonpositive_focals_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        replace(calibration(), **{field: value})


@pytest.mark.parametrize("obj", [point(), calibration()])
@pytest.mark.parametrize("field", ["image_width", "image_height"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_dimensions_rejected(obj, field, value):
    with pytest.raises(ValueError, match=field):
        replace(obj, **{field: value})


@pytest.mark.parametrize("value", ["", " \t\n"])
@pytest.mark.parametrize("obj", [calibration(), image_point_to_camera_ray(point(), calibration())])
def test_blank_calibration_rejected(obj, value):
    with pytest.raises(ValueError, match="calibration_id"):
        replace(obj, calibration_id=value)


@pytest.mark.parametrize("field,value", [
    ("image_width", 320), ("image_height", 240),
    ("image_frame", ReferenceFrame("other:image")),
])
def test_coordinate_system_mismatch_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        image_point_to_camera_ray(replace(point(), **{field: value}), calibration())


@pytest.mark.parametrize("field", ["direction_x", "direction_y", "direction_z"])
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_ray_rejected(field, value):
    ray = image_point_to_camera_ray(point(), calibration())
    with pytest.raises(ValueError, match=field):
        replace(ray, **{field: value})


@pytest.mark.parametrize("xyz", [(0, 0, 0), (0, 0, 2), (0, 0, -1), (1, 0, 0)])
def test_invalid_ray_direction_rejected(xyz):
    with pytest.raises(ValueError):
        CameraRay(*xyz, calibration().optical_frame, point(), "cal")


def test_explicit_source_point_required():
    with pytest.raises(TypeError, match="ImagePoint"):
        CameraRay(0, 0, 1, calibration().optical_frame, None, "cal")


def test_projection_overflow_rejected():
    with pytest.raises(ValueError, match="normalized x"):
        image_point_to_camera_ray(point(1e308), replace(calibration(), fx_px=1e-308))


def test_fresh_interpreter_without_heavy_dependencies_or_wall_clock():
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = '''
import sys
import time
import datetime
import importlib.abc
class BlockHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'cv2'}:
            raise AssertionError('heavy import: ' + fullname)
sys.meta_path.insert(0, BlockHeavy())
def forbidden(*args, **kwargs):
    raise AssertionError('wall clock read')
time.time = forbidden
time.time_ns = forbidden
class NoClock(datetime.datetime):
    now = classmethod(forbidden)
    utcnow = classmethod(forbidden)
    today = classmethod(forbidden)
datetime.datetime = NoClock
from aegis.fusion.contracts import ReferenceFrame
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics, image_point_to_camera_ray
frame = ReferenceFrame('image')
point = ImagePoint(3, 4, 10, 10, frame)
intrinsics = PinholeCameraIntrinsics(1, 1, 3, 4, 10, 10, frame, ReferenceFrame('optical'), 'cal')
assert image_point_to_camera_ray(point, intrinsics).direction_z == 1
assert 'numpy' not in sys.modules and 'cv2' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-c",
                             f"import sys; sys.path.insert(0, {source!r})\n" + script],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
