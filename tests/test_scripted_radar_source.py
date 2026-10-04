"""Scripted acquisitions and caller-composed normalized radar delivery."""

import json
from math import inf, nan
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement, RadarScan
from aegis.radar.scripted_source import iter_scripted_radar_scans


CONTEXT = dict(sensor_id="radar-test-01", reference_frame_id="radar-test-01:measurement")


def script():
    return (
        (MeasurementTime(0.0, "simulation:test"), (
            RadarPolarDetectionMeasurement(10.0, -0.25),
            RadarPolarDetectionMeasurement(20.0, 0.5, 0.0, -3.0),
        )),
        (MeasurementTime(0.1, "simulation:test"), ()),
        (MeasurementTime(0.2, "simulation:test"), (
            RadarPolarDetectionMeasurement(30.0, 0.75, 0.25, 0.0),
        )),
    )


def test_single_scan_preserves_exact_objects_and_explicit_session():
    entry = script()[0]
    source = iter_scripted_radar_scans((entry,), source_session_id=" session/a ")
    scan = next(source)
    assert isinstance(scan, RadarScan)
    assert scan.source_session_id == " session/a "
    assert scan.scan_id == "0"
    assert scan.scan_time is entry[0]
    assert isinstance(scan.detections, tuple)
    assert len(scan.detections) == 2
    for actual, measurement in zip(scan.detections, entry[1], strict=True):
        assert isinstance(actual, RadarDetection)
        assert actual.source_session_id == " session/a "
        assert actual.measurement_time is entry[0]
        assert actual.measurement is measurement
        assert actual.local_detection_id is None
    assert [item.evidence_id for item in scan.detections] == [
        '["scripted-radar-detection",1,"0",0]',
        '["scripted-radar-detection",1,"0",1]',
    ]
    with pytest.raises(StopIteration):
        next(source)


def test_empty_acquisition_consumes_scan_index_and_is_not_exhaustion():
    entries = script()
    source = iter_scripted_radar_scans(entries, source_session_id="session")
    first = next(source)
    empty = next(source)
    last = next(source)
    assert [scan.scan_id for scan in (first, empty, last)] == ["0", "1", "2"]
    assert [len(scan.detections) for scan in (first, empty, last)] == [2, 0, 1]
    assert isinstance(empty, RadarScan)
    assert empty.source_session_id == "session"
    assert empty.scan_time is entries[1][0]
    assert empty.detections == ()
    assert last.detections[0].evidence_id == '["scripted-radar-detection",1,"2",0]'
    assert first.detections[0].evidence_id != last.detections[0].evidence_id
    with pytest.raises(StopIteration):
        next(source)


def test_empty_script_exhausts_without_yielding_none():
    source = iter_scripted_radar_scans((), source_session_id="session")
    with pytest.raises(StopIteration):
        next(source)


@pytest.mark.parametrize("session", ["", " \t\n"])
@pytest.mark.parametrize("empty", [False, True])
def test_session_validation_is_lazy_even_for_empty_script(session, empty):
    source = iter_scripted_radar_scans(() if empty else script(), source_session_id=session)
    with pytest.raises(ValueError, match="source_session_id"):
        next(source)


def test_equivalent_replay_reproduces_scans_and_namespaces_remain_explicit():
    first = tuple(iter_scripted_radar_scans(script(), source_session_id="session-a"))
    replay = tuple(iter_scripted_radar_scans(script(), source_session_id="session-a"))
    other = tuple(iter_scripted_radar_scans(script(), source_session_id="session-b"))
    assert first == replay
    for original, changed in zip(first, other, strict=True):
        assert original.source_session_id == "session-a"
        assert changed.source_session_id == "session-b"
        assert original.scan_id == changed.scan_id
        assert original.scan_time == changed.scan_time
        for left, right in zip(original.detections, changed.detections, strict=True):
            assert left.evidence_id == right.evidence_id
            assert left.measurement == right.measurement
            assert left.measurement_time == right.measurement_time
            assert left.source_session_id != right.source_session_id
    left, = radar_detections_to_observations(first[2].detections, **CONTEXT).observations
    right, = radar_detections_to_observations(other[2].detections, **CONTEXT).observations
    assert left.observation_id != right.observation_id


@pytest.mark.parametrize("elevation,velocity", [
    (None, None), (0.0, 0.0), (None, -3.5), (0.25, None),
])
def test_optional_dimensions_are_preserved(elevation, velocity):
    measurement = RadarPolarDetectionMeasurement(1.0, 0.0, elevation, velocity)
    scan, = iter_scripted_radar_scans(
        ((MeasurementTime(0.0, "simulation:test"), (measurement,)),),
        source_session_id="session",
    )
    assert scan.detections[0].measurement is measurement
    assert scan.detections[0].measurement.elevation_rad == elevation
    assert scan.detections[0].measurement.radial_velocity_mps == velocity


def test_script_order_and_independent_clock_domains_are_preserved():
    times = (
        MeasurementTime(9.0, "simulation:a"),
        MeasurementTime(-2.0, "recording:b"),
        MeasurementTime(1.0, "simulation:a"),
    )
    measurement = RadarPolarDetectionMeasurement(1.0, 0.0)
    scans = tuple(iter_scripted_radar_scans(
        tuple((time, (measurement,)) for time in times), source_session_id="session",
    ))
    assert [scan.scan_id for scan in scans] == ["0", "1", "2"]
    for scan, time in zip(scans, times, strict=True):
        assert scan.scan_time is time
        assert scan.detections[0].measurement_time is time
        assert scan.scan_time.clock_domain == time.clock_domain
    assert [scan.scan_time.seconds for scan in scans] == [9.0, -2.0, 1.0]


@pytest.mark.parametrize("invalid", [[], {}, 1.0])
def test_non_tuple_script_is_rejected_on_advancement(invalid):
    source = iter_scripted_radar_scans(invalid, source_session_id="session")
    with pytest.raises(TypeError, match="script must be a tuple"):
        next(source)


@pytest.mark.parametrize("entry", [
    [], {}, 1.0, (), (MeasurementTime(0.0, "clock"),),
    (MeasurementTime(0.0, "clock"), (), "extra"),
    (0.0, ()),
    (MeasurementTime(0.0, "clock"), []),
    (MeasurementTime(0.0, "clock"), {}),
    (MeasurementTime(0.0, "clock"), (object(),)),
    (MeasurementTime(0.0, "clock"), (1.0,)),
    (MeasurementTime(0.0, "clock"), ({"range_m": 1.0},)),
])
def test_malformed_entry_is_rejected_when_reached(entry):
    source = iter_scripted_radar_scans((script()[0], entry), source_session_id="session")
    assert next(source).scan_id == "0"
    with pytest.raises(TypeError):
        next(source)


@pytest.mark.parametrize("seconds", [inf, -inf, nan])
def test_nonfinite_scan_time_is_rejected_even_for_empty_acquisition(seconds):
    source = iter_scripted_radar_scans(
        ((MeasurementTime(seconds, "clock"), ()),), source_session_id="session",
    )
    with pytest.raises(ValueError, match="scan_time.seconds"):
        next(source)


def test_invalid_measurement_does_not_yield_partial_scan():
    entry = (MeasurementTime(0.0, "clock"), (RadarPolarDetectionMeasurement(1.0, 0.0), object()))
    source = iter_scripted_radar_scans((entry,), source_session_id="session")
    with pytest.raises(TypeError, match="RadarPolarDetectionMeasurement"):
        next(source)


def test_scripted_scans_reach_caller_owned_consumer_through_real_adapter():
    entries = script()
    received = []
    scans = []
    events = []

    def consumer(batch):
        events.append("delivered")
        received.append(batch)

    source = iter_scripted_radar_scans(entries, source_session_id="session")
    for scan in source:
        scans.append(scan)
        events.append(scan.scan_id)
        batch = radar_detections_to_observations(scan.detections, **CONTEXT)
        if batch.observations:
            consumer(batch)
        else:
            assert batch == ObservationBatch(())

    assert len(scans) == 3
    assert scans[1] == RadarScan("session", "1", MeasurementTime(0.1, "simulation:test"), ())
    assert scans[1].scan_time is entries[1][0]
    assert events == ["0", "delivered", "1", "2", "delivered"]
    assert len(received) == 2
    assert [len(batch.observations) for batch in received] == [2, 1]
    for batch, scan_index in zip(received, (0, 2), strict=True):
        assert isinstance(batch, ObservationBatch)
        for ordinal, observation in enumerate(batch.observations):
            assert observation.sensor_id == "radar-test-01"
            assert observation.reference_frame == ReferenceFrame("radar-test-01:measurement")
            assert observation.measurement_time is entries[scan_index][0]
            assert observation.measurement_time.clock_domain == "simulation:test"
            assert observation.measurement is entries[scan_index][1][ordinal]
            evidence_id = f'["scripted-radar-detection",1,"{scan_index}",{ordinal}]'
            assert scans[scan_index].detections[ordinal].evidence_id == evidence_id
            assert observation.observation_id == json.dumps(
                ["radar-detection", 1, "radar-test-01", "session", evidence_id],
                separators=(",", ":"),
            )
            assert observation.source_local_id is None
    assert [o.measurement.range_m for b in received for o in b.observations] == [10.0, 20.0, 30.0]
    with pytest.raises(StopIteration):
        next(source)

    replay = []
    for scan in iter_scripted_radar_scans(script(), source_session_id="session"):
        batch = radar_detections_to_observations(scan.detections, **CONTEXT)
        if batch.observations:
            replay.append(batch)
    assert replay == received


def test_consumer_failure_propagates_before_requesting_another_scan():
    source = iter_scripted_radar_scans(script(), source_session_id="session")
    requests = []

    def observed_source():
        while True:
            requests.append("next")
            try:
                scan = next(source)
            except StopIteration:
                return
            yield scan

    failure = RuntimeError("consumer failed")
    consumer = Mock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        for scan in observed_source():
            batch = radar_detections_to_observations(scan.detections, **CONTEXT)
            if batch.observations:
                consumer(batch)
    assert caught.value is failure
    assert requests == ["next"]
    consumer.assert_called_once()
    delivered = consumer.call_args.args[0]
    assert len(delivered.observations) == 2
    assert delivered.observations[0].measurement.range_m == 10.0
    # Explicit inspection after the failed composition proves the next scan was unread.
    assert next(source).scan_id == "1"


def test_source_import_and_iteration_have_no_external_dependencies_or_clock_effects():
    source_path = Path(__file__).resolve().parents[1] / "src"
    code = """
import builtins
import sys
import time
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
forbidden = {"random", "secrets", "uuid", "datetime", "numpy", "cv2", "ultralytics", "torch"}
legacy = {"aegis.core.messages", "aegis.core.detections", "aegis.fusion.fusion_engine",
          "aegis.sensors.simulated_sensor"}
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden or name in legacy:
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
def no_clock(*args, **kwargs):
    raise AssertionError("Clock or sleep called")
time.time = time.monotonic = time.perf_counter = time.sleep = no_clock
time.time_ns = time.monotonic_ns = time.perf_counter_ns = no_clock
from aegis.fusion.contracts import MeasurementTime
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.radar.scripted_source import iter_scripted_radar_scans
stamp = MeasurementTime(-1.5, "simulation:test")
measurement = RadarPolarDetectionMeasurement(1.0, 0.0)
script = ((stamp, (measurement,)), (stamp, ()))
scans = tuple(iter_scripted_radar_scans(script, source_session_id="session"))
assert len(scans) == 2
assert scans[0].detections[0].measurement is measurement
assert scans[0].detections[0].measurement_time is stamp
assert scans[1].detections == ()
assert not forbidden.intersection(sys.modules)
assert not legacy.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(source_path)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
