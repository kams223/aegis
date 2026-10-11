"""Radar-local geometry preserves partial evidence without inferred state."""

from dataclasses import FrozenInstanceError, fields, replace
from math import copysign, cos, hypot, inf, isfinite, nan, nextafter, pi, sqrt
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.radar import RadarPoint, radar_measurement_to_point


def coordinates(point):
    return point.x_m, point.y_m, point.z_m


def project(measurement):
    return radar_measurement_to_point(measurement, reference_frame=ReferenceFrame("radar:local"))


@pytest.mark.parametrize("azimuth,elevation,expected", [
    (0, 0, (10, 0, 0)),
    (pi / 2, 0, (0, 10, 0)),
    (-pi / 2, 0, (0, -10, 0)),
    (-pi, 0, (-10, 0, 0)),
    (pi / 4, 0, (10 / sqrt(2), 10 / sqrt(2), 0)),
    (-pi / 4, 0, (10 / sqrt(2), -10 / sqrt(2), 0)),
    (0, pi / 6, (5 * sqrt(3), 0, 5)),
    (0, -pi / 6, (5 * sqrt(3), 0, -5)),
    (0, pi / 2, (0, 0, 10)),
    (0, -pi / 2, (0, 0, -10)),
    (pi / 4, pi / 6, (5 * sqrt(1.5), 5 * sqrt(1.5), 5)),
    (-pi / 4, -pi / 6, (5 * sqrt(1.5), -5 * sqrt(1.5), -5)),
])
def test_cartesian_metres_and_right_handed_axes(azimuth, elevation, expected):
    result = project(RadarPolarDetectionMeasurement(10, azimuth, elevation))
    assert coordinates(result) == pytest.approx(expected, rel=1e-12, abs=10 * 1e-12)
    assert hypot(*coordinates(result)) == pytest.approx(10, rel=1e-12)


def test_range_scales_cartesian_metres():
    first = project(RadarPolarDetectionMeasurement(2, 0.3, -0.4))
    second = project(RadarPolarDetectionMeasurement(20, 0.3, -0.4))
    assert coordinates(second) == pytest.approx(tuple(10 * v for v in coordinates(first)))


@pytest.mark.parametrize("velocity", [None, 0.0, 3.5, -3.5])
def test_missing_elevation_retains_valid_partial_evidence(velocity):
    measurement = RadarPolarDetectionMeasurement(10, 0.2, radial_velocity_mps=velocity)
    frame = ReferenceFrame(" radar:local ")
    before = (replace(measurement), replace(frame))
    assert radar_measurement_to_point(measurement, reference_frame=frame) is None
    assert (measurement, frame) == before
    assert measurement.elevation_rad is None
    assert measurement.radial_velocity_mps == velocity


@pytest.mark.parametrize("range_m", [0.0, -0.0])
@pytest.mark.parametrize("elevation", [None, 0.0, pi / 2, -0.7])
def test_zero_range_is_origin_without_direction(range_m, elevation):
    measurement = RadarPolarDetectionMeasurement(range_m, 1.2, elevation)
    frame = ReferenceFrame("radar:local")
    result = radar_measurement_to_point(measurement, reference_frame=frame)
    assert coordinates(result) == (0.0, 0.0, 0.0)
    assert all(copysign(1, v) == 1 for v in coordinates(result))
    assert result.source_measurement is measurement
    assert result.reference_frame is frame
    assert copysign(1, measurement.range_m) == copysign(1, range_m)


@pytest.mark.parametrize("range_m", [sys.float_info.min, nextafter(0.0, 1.0)])
def test_tiny_positive_range_is_not_zero(range_m):
    result = project(RadarPolarDetectionMeasurement(range_m, 0, 0))
    assert coordinates(result) == (range_m, 0.0, 0.0)
    assert result.x_m > 0
    assert project(RadarPolarDetectionMeasurement(range_m, 0)) is None


@pytest.mark.parametrize("velocity", [None, 0.0, 3.5, -3.5])
def test_source_frame_identity_and_range_rate_preserved_without_velocity(velocity):
    measurement = RadarPolarDetectionMeasurement(10, 0.2, 0.3, velocity)
    frame = ReferenceFrame(" radar:measurement ")
    before = (replace(measurement), replace(frame))
    first = radar_measurement_to_point(measurement, reference_frame=frame)
    second = radar_measurement_to_point(measurement, reference_frame=frame)
    assert first == second
    assert first.source_measurement is measurement
    assert first.reference_frame is frame
    assert first.source_measurement.radial_velocity_mps == velocity
    assert (measurement, frame) == before
    assert {field.name for field in fields(first)} == {
        "x_m", "y_m", "z_m", "reference_frame", "source_measurement",
    }
    assert coordinates(first) == coordinates(project(replace(measurement, radial_velocity_mps=None)))


@pytest.mark.parametrize("field", ["x_m", "y_m", "z_m", "reference_frame", "source_measurement"])
def test_radar_point_is_frozen(field):
    result = project(RadarPolarDetectionMeasurement(10, 0, 0))
    with pytest.raises(FrozenInstanceError):
        setattr(result, field, None)


@pytest.mark.parametrize("field", ["x_m", "y_m", "z_m"])
@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_output_rejected(field, value):
    result = project(RadarPolarDetectionMeasurement(10, 0, 0))
    with pytest.raises(ValueError, match=field):
        replace(result, **{field: value})


@pytest.mark.parametrize("invalid", [None, {}, "radar:local", 1.0])
def test_invalid_frame_type_rejected_in_result_and_all_projection_paths(invalid):
    measurement = RadarPolarDetectionMeasurement(10, 0, 0)
    with pytest.raises(TypeError, match="reference_frame"):
        RadarPoint(0, 0, 0, invalid, measurement)
    for source in (measurement, replace(measurement, range_m=0),
                   replace(measurement, elevation_rad=None)):
        with pytest.raises(TypeError, match="reference_frame"):
            radar_measurement_to_point(source, reference_frame=invalid)


@pytest.mark.parametrize("invalid", [None, {}, 1.0, ReferenceFrame("radar:local")])
def test_invalid_measurement_type_rejected(invalid):
    frame = ReferenceFrame("radar:local")
    with pytest.raises(TypeError, match="source_measurement"):
        RadarPoint(0, 0, 0, frame, invalid)
    with pytest.raises(TypeError, match="measurement"):
        radar_measurement_to_point(invalid, reference_frame=frame)


@pytest.mark.parametrize("azimuth,elevation", [(0, 0), (pi / 4, pi / 6), (-pi, -pi / 2)])
def test_maximum_finite_range_does_not_overflow(azimuth, elevation):
    r = sys.float_info.max
    result = project(RadarPolarDetectionMeasurement(r, azimuth, elevation))
    assert all(isfinite(v) for v in coordinates(result))
    assert hypot(*(v / r for v in coordinates(result))) == pytest.approx(1, rel=1e-12)
    assert max(abs(v) for v in coordinates(result)) <= r


def test_subnormal_diagonal_rounding_is_finite_and_scale_aware():
    smallest = nextafter(0.0, 1.0)
    r = 8 * smallest
    result = project(RadarPolarDetectionMeasurement(r, pi / 4, pi / 6))
    for actual, factor in zip(coordinates(result), (sqrt(3 / 8), sqrt(3 / 8), 0.5)):
        assert isfinite(actual)
        assert abs(actual - r * factor) <= 2 * smallest


@pytest.mark.parametrize("azimuth", [-pi, nextafter(pi, -inf)])
def test_valid_azimuth_boundaries_are_retained_without_wrapping(azimuth):
    measurement = RadarPolarDetectionMeasurement(10, azimuth, 0)
    assert project(measurement).source_measurement.azimuth_rad == azimuth


@pytest.mark.parametrize("azimuth", [pi, nextafter(-pi, -inf), 2 * pi])
def test_existing_contract_rejects_angles_without_automatic_wrapping(azimuth):
    with pytest.raises(ValueError, match="azimuth_rad"):
        RadarPolarDetectionMeasurement(10, azimuth, 0)


def test_cardinal_and_pole_residuals_are_not_snapped():
    cardinal = project(RadarPolarDetectionMeasurement(10, pi / 2, 0))
    pole = project(RadarPolarDetectionMeasurement(10, 0, pi / 2))
    assert cardinal.x_m == pole.x_m == 10 * cos(pi / 2)
    assert cardinal.x_m > 0


@pytest.mark.parametrize("angle", [1e-200, -1e-200])
def test_near_zero_angles_are_not_snapped(angle):
    result = project(RadarPolarDetectionMeasurement(1, angle, angle))
    assert result.y_m == pytest.approx(angle, rel=1e-12, abs=0)
    assert result.z_m == pytest.approx(angle, rel=1e-12, abs=0)


def test_fresh_interpreter_needs_no_third_party_dependencies_or_clocks():
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = '''
import sys
import time
import importlib.abc
class BlockDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'cv2', 'torch', 'ultralytics',
                                      'random', 'secrets', 'uuid', 'datetime'}:
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, BlockDependencies())
def forbidden(*args, **kwargs):
    raise AssertionError('clock or sleep called')
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = forbidden
from aegis.fusion.contracts import ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.radar import radar_measurement_to_point
frame = ReferenceFrame('radar:local')
for measurement in (RadarPolarDetectionMeasurement(10, 0, 0),
                    RadarPolarDetectionMeasurement(0, 0),
                    RadarPolarDetectionMeasurement(10, 0)):
    first = radar_measurement_to_point(measurement, reference_frame=frame)
    assert first == radar_measurement_to_point(measurement, reference_frame=frame)
    if first is not None:
        assert first.reference_frame is frame
        assert first.source_measurement is measurement
assert 'numpy' not in sys.modules and 'cv2' not in sys.modules
'''
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c",
         f"import sys; sys.path.insert(0, {source!r})\n" + script],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
