"""Canonical radar evidence validation without a radar backend."""

from dataclasses import FrozenInstanceError, replace
from math import inf, nan, nextafter, pi

import pytest

from aegis.fusion.contracts import MeasurementTime
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement, RadarScan


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


def test_scan_preserves_fields_order_and_independent_detection_times():
    time = MeasurementTime(-2.5, "simulation:scan")
    first = replace(detection(), source_session_id=" session-a ")
    second = replace(
        first, evidence_id="event-b",
        measurement_time=MeasurementTime(-10.0, "recording:other-origin"),
    )
    detections = (first, second)
    scan = RadarScan(" session-a ", " scan/7 ", time, detections)
    assert scan.source_session_id == " session-a "
    assert scan.scan_id == " scan/7 "
    assert scan.scan_time is time
    assert scan.scan_time.seconds == -2.5
    assert scan.detections is detections
    assert isinstance(scan.detections, tuple)
    for actual, expected in zip(scan.detections, detections, strict=True):
        assert actual is expected
        assert actual.measurement_time is expected.measurement_time
    assert first.measurement_time.clock_domain == "device:boot-a"
    assert second.measurement_time.clock_domain == "recording:other-origin"
    assert [item.measurement_time.seconds for item in scan.detections] == [-0.25, -10.0]
    with pytest.raises(FrozenInstanceError):
        scan.scan_id = "other"
    with pytest.raises(FrozenInstanceError):
        scan.detections = ()


def test_empty_scan_preserves_acquisition_context():
    time = MeasurementTime(-0.5, "simulation:test")
    scan = RadarScan("session", "empty-scan", time, ())
    assert scan.source_session_id == "session"
    assert scan.scan_id == "empty-scan"
    assert scan.scan_time is time
    assert scan.detections == ()


@pytest.mark.parametrize("field", ["source_session_id", "scan_id"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_scan_rejects_blank_identifiers(field, value):
    scan = RadarScan("session", "scan", MeasurementTime(0.0, "simulation:test"), ())
    with pytest.raises(ValueError, match=field):
        replace(scan, **{field: value})


@pytest.mark.parametrize("value", [inf, -inf, nan])
def test_scan_rejects_nonfinite_time_even_when_empty(value):
    with pytest.raises(ValueError, match="scan_time.seconds"):
        RadarScan("session", "scan", MeasurementTime(value, "simulation:test"), ())


def test_scan_rejects_mutable_detection_collection():
    with pytest.raises(TypeError, match="tuple"):
        RadarScan("session-a", "scan", MeasurementTime(0.0, "clock"), [detection()])


@pytest.mark.parametrize("value", [None, 1.0, {}, RadarPolarDetectionMeasurement(1.0, 0.0)])
def test_scan_rejects_foreign_detection_elements(value):
    with pytest.raises(TypeError, match="RadarDetection"):
        RadarScan("session-a", "scan", MeasurementTime(0.0, "clock"), (value,))


def test_scan_rejects_detection_session_mismatch_without_stripping():
    with pytest.raises(ValueError, match="source_session_id"):
        RadarScan(" session-a ", "scan", MeasurementTime(0.0, "clock"), (detection(),))


@pytest.mark.parametrize("changed_measurement", [False, True])
def test_scan_rejects_duplicate_evidence_ids_independent_of_values(changed_measurement):
    first = detection()
    second = replace(first, measurement=RadarPolarDetectionMeasurement(9.0, 0.5)) if changed_measurement else first
    with pytest.raises(ValueError, match="Duplicate.*evidence_id"):
        RadarScan("session-a", "scan", first.measurement_time, (first, second))


def test_scan_accepts_identical_measurements_with_distinct_evidence_ids():
    first = detection()
    second = replace(first, evidence_id="another-event")
    scan = RadarScan("session-a", "scan", first.measurement_time, (first, second))
    assert scan.detections == (first, second)
    assert scan.detections[0].measurement is scan.detections[1].measurement
