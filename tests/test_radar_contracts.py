"""Canonical radar evidence validation without a radar backend."""

from dataclasses import FrozenInstanceError, replace
from math import inf, nan, nextafter, pi

import pytest

from aegis.fusion.contracts import MeasurementTime
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement


def detection():
    return RadarDetection(
        "session-a", "scan-1/return-2", MeasurementTime(-0.25, "device:boot-a"),
        RadarPolarDetectionMeasurement(42.5, 0.125),
    )


@pytest.mark.parametrize("kwargs", [{}, {"range_m": 1.0}, {"azimuth_rad": 0.0}])
def test_range_and_azimuth_are_required(kwargs):
    with pytest.raises(TypeError):
        RadarPolarDetectionMeasurement(**kwargs)


def test_optional_components_default_to_none_and_differ_from_measured_zero():
    absent = RadarPolarDetectionMeasurement(0.0, 0.0)
    zero = RadarPolarDetectionMeasurement(0.0, 0.0, 0.0, 0.0)
    assert absent.range_m == zero.range_m == 0.0
    assert absent.azimuth_rad == zero.azimuth_rad == 0.0
    assert absent.elevation_rad is None
    assert absent.radial_velocity_mps is None
    assert zero.elevation_rad == zero.radial_velocity_mps == 0.0
    assert absent != zero


def test_supplied_components_are_preserved_without_conversion():
    measurement = RadarPolarDetectionMeasurement(123.456, -0.75, 0.625, -12.345)
    assert measurement.range_m == 123.456
    assert measurement.azimuth_rad == -0.75
    assert measurement.elevation_rad == 0.625
    assert measurement.radial_velocity_mps == -12.345


@pytest.mark.parametrize("value", [-0.001, inf, -inf, nan])
def test_invalid_range_is_rejected(value):
    with pytest.raises(ValueError, match="range_m"):
        RadarPolarDetectionMeasurement(value, 0.0)


@pytest.mark.parametrize("value", [-pi, nextafter(pi, -inf)])
def test_azimuth_boundaries_are_preserved(value):
    assert RadarPolarDetectionMeasurement(1.0, value).azimuth_rad == value


@pytest.mark.parametrize("value", [pi, nextafter(-pi, -inf), inf, -inf, nan])
def test_invalid_azimuth_is_rejected_without_wrapping(value):
    with pytest.raises(ValueError, match="azimuth_rad"):
        RadarPolarDetectionMeasurement(1.0, value)


@pytest.mark.parametrize("value", [None, -pi / 2, pi / 2])
def test_elevation_boundaries_and_absence_are_preserved(value):
    assert RadarPolarDetectionMeasurement(1.0, 0.0, value).elevation_rad == value


@pytest.mark.parametrize("value", [
    nextafter(-pi / 2, -inf), nextafter(pi / 2, inf), inf, -inf, nan,
])
def test_invalid_elevation_is_rejected_without_clamping(value):
    with pytest.raises(ValueError, match="elevation_rad"):
        RadarPolarDetectionMeasurement(1.0, 0.0, value)


@pytest.mark.parametrize("value", [None, 0.0, 12.5, -12.5])
def test_radial_velocity_preserves_absence_zero_and_both_signs(value):
    measurement = RadarPolarDetectionMeasurement(1.0, 0.0, radial_velocity_mps=value)
    assert measurement.radial_velocity_mps == value


@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_radial_velocity_is_rejected(value):
    with pytest.raises(ValueError, match="radial_velocity_mps"):
        RadarPolarDetectionMeasurement(1.0, 0.0, radial_velocity_mps=value)


def test_detection_preserves_fields_objects_and_negative_event_time():
    source = detection()
    time = MeasurementTime(-12.345, "recording:origin-b")
    result = replace(
        source, source_session_id=" session/a ", evidence_id=' event/\"2\" ',
        local_detection_id=" scan/7 ", measurement_time=time,
    )
    assert result.source_session_id == " session/a "
    assert result.evidence_id == ' event/\"2\" '
    assert result.local_detection_id == " scan/7 "
    assert result.measurement_time is time
    assert result.measurement_time.seconds == -12.345
    assert result.measurement is source.measurement
    assert source.local_detection_id is None


@pytest.mark.parametrize("field", ["source_session_id", "evidence_id", "local_detection_id"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_blank_detection_identifiers_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        replace(detection(), **{field: value})


@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_nonfinite_event_time_is_rejected_locally(value):
    time = MeasurementTime(value, "device:boot-a")
    with pytest.raises(ValueError, match="measurement_time.seconds"):
        replace(detection(), measurement_time=time)


def test_detection_and_measurement_are_frozen():
    source = detection()
    for value, field, replacement in (
        (source, "evidence_id", "another-event"),
        (source.measurement, "range_m", 99.0),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
