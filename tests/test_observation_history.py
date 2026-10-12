"""Caller order and complete lineage, without chronological or track claims."""

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import (
    DerivedSensorEvidence, derive_camera_evidence, derive_radar_evidence,
)
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.spatial.transforms import RigidTransform


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def radar(seconds=5., *, frame="radar:local", clock="radar:clock", elevation=0.):
    return SensorObservation("radar-event", "radar", MeasurementTime(seconds, clock),
                             ReferenceFrame(frame),
                             RadarPolarDetectionMeasurement(10., 0., elevation, -3.),
                             "session/return-1")


@pytest.fixture
def camera():
    frame = ReferenceFrame("camera:image")
    point = ImagePoint(320., 240., 640, 480, frame)
    observation = SensorObservation("camera-event", "camera", MeasurementTime(2., "camera:clock"),
                                    frame, point, "opening/track-1")
    intrinsics = PinholeCameraIntrinsics(100., 100., 320., 240., 640, 480, frame,
                                       ReferenceFrame("camera:optical"), "calibration")
    return observation, point, intrinsics


def mapping(observation, *, offset=0.):
    return BoundedClockMapping(observation.measurement_time.clock_domain, "fixture:time",
                               1., offset, -100., 100., 0.25)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_cardinality_tuple_and_entry_identity(count):
    records = tuple(DerivedSensorEvidence(radar(i)) for i in range(count))
    history = ObservationHistory(records)
    assert history.records is records
    assert len(history.records) == count
    assert all(actual is source for actual, source in zip(history.records, records))
    assert list(history.records) == list(records)
    assert history.records[:] == records


def test_mixed_full_and_partial_evidence_preserves_complete_lineage(camera):
    observation, point, intrinsics = camera
    c_mapping = mapping(observation, offset=100.)
    c_transform = RigidTransform(intrinsics.optical_frame, ReferenceFrame("camera:target"),
                                 IDENTITY, (1., 2., 3.))
    c = derive_camera_evidence(observation, image_point=point, intrinsics=intrinsics,
                               spatial_transform=c_transform, clock_mapping=c_mapping)
    r_observation = radar()
    r_mapping = mapping(r_observation, offset=200.)
    r_transform = RigidTransform(r_observation.reference_frame, ReferenceFrame("radar:target"),
                                 IDENTITY, (1., 2., 3.))
    r = derive_radar_evidence(r_observation, spatial_transform=r_transform, clock_mapping=r_mapping)
    partial = derive_radar_evidence(radar(elevation=None))
    original = DerivedSensorEvidence(observation)
    history = ObservationHistory((r, original, c, partial))
    assert all(actual is source for actual, source in zip(history.records, (r, original, c, partial)))
    assert c.source_observation is observation
    assert c.source_observation.measurement is point
    assert c.camera_intrinsics is intrinsics
    assert c.spatial_projection.source_image_point is point
    assert c.spatial_transform is c_transform
    assert c.transformed_geometry.source_ray is c.spatial_projection
    assert r.source_observation is r_observation
    assert r.spatial_projection.source_measurement is r_observation.measurement
    assert r.spatial_transform is r_transform
    assert r.transformed_geometry.source_point is r.spatial_projection
    for evidence, clock_mapping in ((c, c_mapping), (r, r_mapping)):
        assert evidence.mapped_time.source_mapping is clock_mapping
        assert evidence.mapped_time.source_time is evidence.source_observation.measurement_time
    assert c.transformed_geometry.reference_frame != r.transformed_geometry.reference_frame
    assert observation.measurement_time.clock_domain != r_observation.measurement_time.clock_domain
    assert original.spatial_projection is original.mapped_time is None
    assert partial.spatial_projection is partial.mapped_time is None
    assert partial.source_observation.measurement.elevation_rad is None


@pytest.mark.parametrize("times", [(9., 5., 1.), (2., 2., 2.), (1., 9., 3.)])
def test_caller_order_despite_decreasing_equal_or_late_times(times):
    records = tuple(DerivedSensorEvidence(radar(t)) for t in times)
    history = ObservationHistory(records)
    assert history.records is records
    assert tuple(r.source_observation.measurement_time.seconds for r in history.records) == times


@pytest.mark.parametrize("times", [(2., 2.25), (2., 8.)])
def test_overlapping_and_disjoint_mapped_intervals_retained(times):
    observations = tuple(radar(t) for t in times)
    records = tuple(derive_radar_evidence(o, clock_mapping=mapping(o)) for o in observations)
    intervals = tuple(r.mapped_time for r in records)
    history = ObservationHistory(records[::-1])
    assert history.records[0].mapped_time is intervals[1]
    assert history.records[1].mapped_time is intervals[0]
    assert (intervals[0].lower_seconds, intervals[0].upper_seconds) == (1.75, 2.25)
    assert (intervals[1].lower_seconds, intervals[1].upper_seconds) == (times[1] - .25, times[1] + .25)


def test_duplicates_equal_distinct_and_different_derivations_preserved():
    observation = radar()
    first = DerivedSensorEvidence(observation)
    equal = replace(first)
    projected = derive_radar_evidence(observation)
    repeated_ids = DerivedSensorEvidence(radar(8.))
    records = (first, equal, first, projected, repeated_ids)
    history = ObservationHistory(records)
    assert first == equal and first is not equal
    assert history.records is records and len(history.records) == 5
    assert all(actual is source for actual, source in zip(history.records, records))
    assert projected.source_observation is first.source_observation
    assert projected.spatial_projection is not None and first.spatial_projection is None
    assert len({r.source_observation.observation_id for r in records}) == 1
    assert len({r.source_observation.source_local_id for r in records}) == 1


@pytest.mark.parametrize("records", [[], [None], "records", None, {}, set(), iter(()), (x for x in ())])
def test_unsupported_collection_rejected(records):
    with pytest.raises(TypeError, match="tuple"):
        ObservationHistory(records)


@pytest.mark.parametrize("entry", [None, 1, True, "evidence", {}, object(), radar()])
@pytest.mark.parametrize("mixed", [False, True])
def test_malformed_entries_rejected(entry, mixed):
    valid = DerivedSensorEvidence(radar())
    records = (valid, entry, valid) if mixed else (entry,)
    with pytest.raises(TypeError, match="DerivedSensorEvidence"):
        ObservationHistory(records)


def test_frozen_deterministic_without_mutation_or_extra_api():
    evidence = derive_radar_evidence(radar())
    records = (evidence, evidence)
    before = repr(records)
    first, second = ObservationHistory(records), ObservationHistory(records)
    assert first == second and first.records is second.records is records
    assert repr(records) == before
    assert [f.name for f in fields(first)] == ["records"]
    with pytest.raises(FrozenInstanceError):
        first.records = ()
    assert not any(name in ObservationHistory.__dict__ for name in (
        "__iter__", "__getitem__", "__len__", "append", "sort", "filter", "group", "merge",
        "track_id", "target_id", "confidence", "associate", "fuse", "compare", "persist",
    ))


def test_history_trusts_evidence_without_reconstruction(monkeypatch):
    record = DerivedSensorEvidence(radar())
    def forbidden(*args, **kwargs):
        raise AssertionError("history must not reconstruct or revalidate evidence")
    monkeypatch.setattr(DerivedSensorEvidence, "__post_init__", forbidden)
    assert ObservationHistory((record,)).records[0] is record


def test_fresh_interpreter_standard_library_without_runtime_effects():
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys, time, random
baseline = set(sys.modules)
sys.path.insert(0, sys.argv[1])
from aegis.fusion.observation_history import ObservationHistory
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.contracts import SensorObservation, MeasurementTime, ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
assert all(name in sys.stdlib_module_names or name == 'aegis'
           for name in {key.split('.')[0] for key in set(sys.modules) - baseline})
record = DerivedSensorEvidence(SensorObservation('event', 'radar', MeasurementTime(0, 'clock'),
    ReferenceFrame('radar'), RadarPolarDetectionMeasurement(10, 0)))
records = (record, record)
def forbidden(*args, **kwargs):
    raise AssertionError('clock, randomness or I/O')
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = random.random = forbidden
def audit(event, args):
    if event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.urandom')):
        forbidden()
sys.addaudithook(audit)
assert ObservationHistory(records).records is records
assert ObservationHistory(()).records == ()
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
