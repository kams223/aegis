"""Static frame conversion keeps metric positions distinct from directions."""

from dataclasses import FrozenInstanceError, fields, replace
from math import cos, hypot, inf, isfinite, nan, pi, sin, sqrt
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import CameraRay, ImagePoint
from aegis.spatial.radar import RadarPoint, radar_measurement_to_point
from aegis.spatial.transforms import (
    RigidTransform, RotatedDirection, TransformedPoint,
    rotate_camera_direction, transform_radar_point,
)


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
RX = ((1., 0., 0.), (0., 0., -1.), (0., 1., 0.))
RY = ((0., 0., 1.), (0., 1., 0.), (-1., 0., 0.))
RZ = ((0., -1., 0.), (1., 0., 0.), (0., 0., 1.))
SOURCE = ReferenceFrame("sensor:local")
TARGET = ReferenceFrame("explicit:target")


def transform(rotation=IDENTITY, translation=(0., 0., 0.)):
    return RigidTransform(SOURCE, TARGET, rotation, translation)


def point(x=1., y=2., z=3.):
    return RadarPoint(x, y, z, SOURCE, RadarPolarDetectionMeasurement(10, 0, 0, -2))


def ray():
    return CameraRay(0., 0., 1., SOURCE,
                     ImagePoint(1, 2, 10, 10, ReferenceFrame("camera:image")), "cal/v1")


def xyz(value):
    return value.x_m, value.y_m, value.z_m


def direction(value):
    return value.direction_x, value.direction_y, value.direction_z


def test_identity_preserves_positions_directions_and_provenance():
    p, d, t = point(), ray(), transform()
    position, rotated = transform_radar_point(p, t), rotate_camera_direction(d, t)
    assert xyz(position) == xyz(p)
    assert direction(rotated) == direction(d)
    assert position.reference_frame is rotated.reference_frame is TARGET
    assert position.source_point is p
    assert position.source_point.source_measurement is p.source_measurement
    assert rotated.source_ray is d
    assert rotated.source_ray.source_image_point is d.source_image_point
    assert rotated.source_ray.calibration_id == "cal/v1"


def test_translation_is_metres_and_ignored_for_directions():
    t = transform(translation=(4., 5., 6.))
    assert xyz(transform_radar_point(point(), t)) == (5., 7., 9.)
    assert direction(rotate_camera_direction(ray(), t)) == (0., 0., 1.)
    assert direction(rotate_camera_direction(ray(), transform(translation=(sys.float_info.max,) * 3))) == (0., 0., 1.)


@pytest.mark.parametrize("rotation,expected,expected_direction", [
    (RX, (1, -3, 2), (0, -1, 0)),
    (RY, (3, 2, -1), (1, 0, 0)),
    (RZ, (-2, 1, 3), (0, 0, 1)),
    (((1., 0., 0.), (0., -1., 0.), (0., 0., -1.)), (1, -2, -3), (0, 0, -1)),
])
def test_column_vector_rotations(rotation, expected, expected_direction):
    assert xyz(transform_radar_point(point(), transform(rotation))) == expected
    assert direction(rotate_camera_direction(ray(), transform(rotation))) == expected_direction


def test_rotation_precedes_translation():
    assert xyz(transform_radar_point(point(), transform(RZ, (4., 5., 6.)))) == (2., 6., 9.)


def test_wrong_source_frame_rejected():
    with pytest.raises(ValueError, match="reference_frame"):
        transform_radar_point(replace(point(), reference_frame=TARGET), transform())
    with pytest.raises(ValueError, match="optical_frame"):
        rotate_camera_direction(replace(ray(), optical_frame=TARGET), transform())


def test_equal_identifiers_match_and_frame_objects_are_retained():
    source = ReferenceFrame(SOURCE.frame_id)
    target = ReferenceFrame(TARGET.frame_id)
    t = RigidTransform(source, target, IDENTITY, (0., 0., 0.))
    assert source is not SOURCE
    assert t.source_frame is source and t.target_frame is target
    assert transform_radar_point(point(), t).reference_frame is target
    assert rotate_camera_direction(ray(), t).reference_frame is target


def test_same_frame_exact_identity_and_signed_zero_are_accepted():
    t = RigidTransform(SOURCE, ReferenceFrame(SOURCE.frame_id), IDENTITY, (-0., 0., -0.))
    assert xyz(transform_radar_point(point(), t)) == xyz(point())


@pytest.mark.parametrize("rotation,translation", [
    (RX, (0., 0., 0.)), (IDENTITY, (1e-200, 0., 0.)),
    (((1., -1e-14, 0.), (1e-14, 1., 0.), (0., 0., 1.)), (0., 0., 0.)),
])
def test_same_frame_requires_exact_identity(rotation, translation):
    with pytest.raises(ValueError, match="same-frame"):
        RigidTransform(SOURCE, ReferenceFrame(SOURCE.frame_id), rotation, translation)


def test_explicit_inverse_round_trip_without_public_inverse_api():
    t = transform(RZ, (4., 5., 6.))
    inverse = RigidTransform(TARGET, SOURCE,
                             ((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)),
                             (-5., 4., -6.))
    original = point()
    converted = transform_radar_point(original, t)
    # Explicitly construct the inverse input; the production API stays narrow.
    back_input = RadarPoint(*xyz(converted), TARGET, original.source_measurement)
    assert xyz(transform_radar_point(back_input, inverse)) == pytest.approx(xyz(original), rel=1e-12, abs=3e-12)


@pytest.mark.parametrize("rotation", [
    ((-1., 0., 0.), (0., 1., 0.), (0., 0., 1.)),
    ((0., 0., 0.), (0., 0., 0.), (0., 0., 0.)),
    ((2., 0., 0.), (0., 1., 0.), (0., 0., 1.)),
    ((1., .1, 0.), (0., 1., 0.), (0., 0., 1.)),
    ((1., 0., 0.), (1., 0., 0.), (0., 0., 1.)),
    ((sys.float_info.max, 0., 0.), (0., 1., 0.), (0., 0., 1.)),
])
def test_reflection_singular_scale_shear_and_excessive_entries_rejected(rotation):
    with pytest.raises(ValueError):
        transform(rotation)


@pytest.mark.parametrize("index", range(9))
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_rotation_entries_rejected(index, value):
    rows = [list(row) for row in IDENTITY]
    rows[index // 3][index % 3] = value
    with pytest.raises(ValueError, match="rotation entry"):
        transform(tuple(tuple(row) for row in rows))


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_translation_rejected(index, value):
    values = [0., 0., 0.]
    values[index] = value
    with pytest.raises(ValueError, match="translation"):
        transform(translation=tuple(values))


@pytest.mark.parametrize("rotation", [
    None, [], (), IDENTITY[:2], IDENTITY + (IDENTITY[0],),
    tuple(list(row) for row in IDENTITY),
    ((1., 0.), IDENTITY[1], IDENTITY[2]),
    ((1., 0., 0., 0.), IDENTITY[1], IDENTITY[2]),
])
def test_malformed_and_mutable_rotation_rejected(rotation):
    with pytest.raises(TypeError, match="rotation"):
        transform(rotation)


@pytest.mark.parametrize("translation", [None, [], [0., 0., 0.], (), (0., 0.), (0.,) * 4])
def test_malformed_and_mutable_translation_rejected(translation):
    with pytest.raises(TypeError, match="translation"):
        transform(translation=translation)


@pytest.mark.parametrize("value", [True, "1", None, complex(1)])
def test_nonnumerical_rotation_and_translation_rejected(value):
    with pytest.raises(TypeError):
        transform(((value, 0., 0.), IDENTITY[1], IDENTITY[2]))
    with pytest.raises(TypeError):
        transform(translation=(value, 0., 0.))


def test_near_valid_rotation_is_retained_without_repair():
    rotation = ((1. + 2e-13, 0., 0.), IDENTITY[1], IDENTITY[2])
    translation = (0., 0., 0.)
    t = transform(rotation, translation)
    assert t.rotation_target_from_source is rotation
    assert t.translation_target_from_source_m is translation
    assert transform_radar_point(point(), t).x_m == 1. + 2e-13
    with pytest.raises(ValueError):
        transform(((1. + 1e-12, 0., 0.), IDENTITY[1], IDENTITY[2]))


@pytest.mark.parametrize("field", ["x_m", "y_m", "z_m", "direction_x", "direction_y", "direction_z"])
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_result_construction_rejected(field, value):
    result = (transform_radar_point(point(), transform()) if field.endswith("_m")
              else rotate_camera_direction(ray(), transform()))
    with pytest.raises(ValueError, match=field):
        replace(result, **{field: value})


@pytest.mark.parametrize("components", [(0., 0., 0.), (0., 0., 2.), (0., 0., 1. + 2e-11)])
def test_invalid_unit_direction_rejected(components):
    with pytest.raises(ValueError, match="unit length"):
        RotatedDirection(*components, TARGET, ray())


def test_direction_tolerance_does_not_normalize():
    result = RotatedDirection(0., 0., 1. + 5e-12, TARGET, ray())
    assert result.direction_z == 1. + 5e-12


@pytest.mark.parametrize("field", ["source_frame", "target_frame"])
def test_transform_frame_types_rejected(field):
    with pytest.raises(TypeError, match=field):
        replace(transform(), **{field: "frame"})


@pytest.mark.parametrize("kind", ["point", "direction"])
def test_result_frame_and_source_types_rejected(kind):
    result = (transform_radar_point(point(), transform()) if kind == "point"
              else rotate_camera_direction(ray(), transform()))
    with pytest.raises(TypeError, match="reference_frame"):
        replace(result, reference_frame="frame")
    field = "source_point" if kind == "point" else "source_ray"
    with pytest.raises(TypeError, match=field):
        replace(result, **{field: None})


@pytest.mark.parametrize("invalid", [None, 1, {}, ray()])
def test_point_operation_input_types_rejected(invalid):
    with pytest.raises(TypeError, match="point"):
        transform_radar_point(invalid, transform())
    with pytest.raises(TypeError, match="transform"):
        transform_radar_point(point(), invalid)


@pytest.mark.parametrize("invalid", [None, 1, {}, point()])
def test_direction_operation_input_types_rejected(invalid):
    with pytest.raises(TypeError, match="ray"):
        rotate_camera_direction(invalid, transform())
    with pytest.raises(TypeError, match="transform"):
        rotate_camera_direction(ray(), invalid)


def test_large_coordinates_and_overflow_are_explicit():
    maximum = sys.float_info.max
    assert xyz(transform_radar_point(point(maximum, 0, 0), transform())) == (maximum, 0, 0)
    with pytest.raises(ValueError, match="overflow"):
        transform_radar_point(point(maximum, 0, 0), transform(translation=(maximum, 0., 0.)))
    diagonal = ((1 / sqrt(2), -1 / sqrt(2), 0.),
                (1 / sqrt(2), 1 / sqrt(2), 0.), (0., 0., 1.))
    with pytest.raises(ValueError):
        transform_radar_point(point(maximum, maximum, 0), transform(diagonal))
    near = ((1. + 2e-13, 0., 0.), IDENTITY[1], IDENTITY[2])
    with pytest.raises(ValueError, match="finite"):
        transform_radar_point(point(maximum, 0, 0), transform(near))


def test_fsum_preserves_small_component_during_cancellation():
    r = ((.5, .5, 1 / sqrt(2)), (.5, .5, -1 / sqrt(2)),
         (-1 / sqrt(2), 1 / sqrt(2), 0.))
    result = transform_radar_point(point(2e16, 2, 0), transform(r, (-1e16, 0., 0.)))
    assert result.x_m == 1.
    assert all(isfinite(v) for v in xyz(result))


def test_small_residuals_are_not_snapped():
    angle = 1e-200
    r = ((cos(angle), -sin(angle), 0.), (sin(angle), cos(angle), 0.), (0., 0., 1.))
    assert transform_radar_point(point(1, 0, 0), transform(r)).y_m == angle


@pytest.mark.parametrize("kind", ["transform", "point", "direction"])
def test_all_contract_fields_are_frozen(kind):
    value = {"transform": transform(), "point": transform_radar_point(point(), transform()),
             "direction": rotate_camera_direction(ray(), transform())}[kind]
    for field in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field.name, None)


def test_repeated_calls_are_deterministic_and_inputs_unchanged():
    p, d, t = point(), ray(), transform(RX, (4., 5., 6.))
    before = (replace(p), replace(d), replace(t))
    assert transform_radar_point(p, t) == transform_radar_point(p, t)
    assert rotate_camera_direction(d, t) == rotate_camera_direction(d, t)
    assert (p, d, t) == before


def test_no_depth_origin_or_missing_elevation_is_inferred():
    result = rotate_camera_direction(ray(), transform())
    assert {f.name for f in fields(result)} == {
        "direction_x", "direction_y", "direction_z", "reference_frame", "source_ray",
    }
    partial = RadarPolarDetectionMeasurement(10, 0)
    assert radar_measurement_to_point(partial, reference_frame=SOURCE) is None
    with pytest.raises(TypeError, match="point"):
        transform_radar_point(partial, transform())
    assert partial.elevation_rad is None


def test_fresh_interpreter_without_dependencies_clocks_randomness_or_io():
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = '''
import sys, time, importlib.abc
class BlockDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'cv2', 'torch', 'ultralytics',
                                      'random', 'secrets', 'uuid', 'datetime'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockDependencies())
def forbidden(*args, **kwargs):
    raise AssertionError('clock or sleep')
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = forbidden
def audit(event, args):
    if event == 'open':
        path = args[0]
        # Permit interpreter module loading only, not utility filesystem I/O.
        if not isinstance(path, str) or not path.endswith(('.py', '.pyc')):
            raise AssertionError('file I/O: ' + str(path))
    if event.startswith(('socket.', 'subprocess.', 'os.urandom')):
        raise AssertionError(event)
sys.addaudithook(audit)
from aegis.fusion.contracts import ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import CameraRay, ImagePoint
from aegis.spatial.radar import RadarPoint
import aegis.spatial.transforms as module
s, t = ReferenceFrame('source'), ReferenceFrame('target')
identity = ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
transform = module.RigidTransform(s, t, identity, (4.,5.,6.))
point = RadarPoint(1.,2.,3.,s,RadarPolarDetectionMeasurement(10,0,0))
ray = CameraRay(0.,0.,1.,s,ImagePoint(1,2,10,10,ReferenceFrame('image')),'cal')
for operation, value in ((module.transform_radar_point, point),
                         (module.rotate_camera_direction, ray)):
    assert operation(value, transform) == operation(value, transform)
assert not hasattr(module, 'inverse') and not hasattr(module, 'compose')
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c",
                             f"import sys; sys.path.insert(0, {source!r})\n" + script],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
