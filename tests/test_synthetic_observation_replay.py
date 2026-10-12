"""Synthetic adapter-to-history composition, without physical simulation.

The two observations are independent. Supplied local IDs, calibration, transforms,
and clock bounds are fixture assertions, not target identity or synchronization.
"""

from dataclasses import fields, replace
import json
import math
from pathlib import Path
import subprocess
import sys

from aegis.core.frames import FrameMetadata
from aegis.fusion.camera_adapter import tracked_objects_to_observations
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.comparability import (
    SpatialReason, SpatialStatus, TemporalReason, TemporalRelationship,
    assess_evidence_comparability,
)
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame
from aegis.fusion.derived_evidence import (
    DerivedSensorEvidence, derive_camera_evidence, derive_radar_evidence,
)
from aegis.fusion.observation_history import ObservationHistory
from aegis.perception.contracts import ObjectDetection
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.radar.scripted_source import iter_scripted_radar_scans
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.spatial.transforms import RigidTransform
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch


def _inputs(*, elevation=0.):
    image_frame = ReferenceFrame("fixture:camera:image")
    optical_frame = ReferenceFrame("fixture:camera:optical")
    radar_frame = ReferenceFrame("fixture:radar:local")
    # The bbox center is deliberately different from the explicitly selected pixel.
    camera_batch = TrackedObjectBatch(
        FrameMetadata("fixture:opening", 51, 2., 640, 480),
        (TrackedObject(7, ObjectDetection(0, "fixture", .75, 10., 20., 30., 40.)),),
    )
    point = ImagePoint(320., 240., 640, 480, image_frame)
    intrinsics = PinholeCameraIntrinsics(100., 100., 320., 240., 640, 480,
                                       image_frame, optical_frame, "fixture:calibration")
    radar_time = MeasurementTime(5., "fixture:radar")
    measurement = RadarPolarDetectionMeasurement(10., 0., elevation)
    script = ((radar_time, (measurement,)),)
    transform = RigidTransform(
        radar_frame, ReferenceFrame("fixture:target"),
        ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), (1., 2., 3.),
    )
    return dict(
        camera_batch=camera_batch, point=point, intrinsics=intrinsics,
        radar_time=radar_time, measurement=measurement, script=script, transform=transform,
        camera_mapping=BoundedClockMapping("fixture:camera", "fixture:time", 1., 100., 0., 10., .25),
        radar_mapping=BoundedClockMapping("fixture:radar", "fixture:time", 1., 200., 0., 10., .25),
    )


def _replay(inputs, *, mapped=True, camera_projection=True, radar_transform=True):
    """Private test composition using real APIs, with explicit arrival order."""
    camera_batch = tracked_objects_to_observations(
        inputs["camera_batch"], sensor_id="fixture:camera-sensor",
        clock_domain="fixture:camera", reference_frame_id="fixture:camera:image",
    )
    camera_observation, = camera_batch.observations
    scans = tuple(iter_scripted_radar_scans(inputs["script"], source_session_id="fixture:session"))
    scan, = scans
    radar_batch = radar_detections_to_observations(
        scan.detections, sensor_id="fixture:radar-sensor", reference_frame_id="fixture:radar:local",
    )
    radar_observation, = radar_batch.observations
    camera = derive_camera_evidence(
        camera_observation, image_point=inputs["point"] if camera_projection else None,
        intrinsics=inputs["intrinsics"] if camera_projection else None,
        clock_mapping=inputs["camera_mapping"] if mapped else None,
    )
    radar = derive_radar_evidence(
        radar_observation, spatial_transform=inputs["transform"] if radar_transform else None,
        clock_mapping=inputs["radar_mapping"] if mapped else None,
    )
    records = (radar, camera)
    history = ObservationHistory(records=records)
    return dict(camera_batch=camera_batch, radar_batch=radar_batch, scan=scan,
                camera=camera, radar=radar, records=records, history=history)


def _assert_lineage(inputs, run):
    camera, radar = run["camera"], run["radar"]
    assert camera.source_observation is run["camera_batch"].observations[0]
    assert radar.source_observation is run["radar_batch"].observations[0]
    assert radar.source_observation.measurement is inputs["measurement"]
    assert radar.source_observation.measurement_time is inputs["radar_time"]
    assert run["scan"].scan_time is inputs["radar_time"]
    detection, = run["scan"].detections
    assert detection.measurement is inputs["measurement"]
    assert detection.measurement_time is inputs["radar_time"]
    assert camera.spatial_projection.source_image_point is inputs["point"]
    assert camera.camera_intrinsics is inputs["intrinsics"]
    assert radar.spatial_projection.source_measurement is inputs["measurement"]
    assert radar.spatial_projection.reference_frame is radar.source_observation.reference_frame
    assert radar.spatial_transform is inputs["transform"]
    assert radar.transformed_geometry.source_point is radar.spatial_projection
    assert radar.transformed_geometry.reference_frame is inputs["transform"].target_frame
    for evidence, key in ((camera, "camera_mapping"), (radar, "radar_mapping")):
        assert evidence.mapped_time.source_time is evidence.source_observation.measurement_time
        assert evidence.mapped_time.source_mapping is inputs[key]
    assert run["history"].records is run["records"]
    assert run["history"].records[0] is radar
    assert run["history"].records[1] is camera


def test_both_adapters_scripted_source_and_complete_history_lineage():
    inputs = _inputs()
    before = repr(inputs)
    run = _replay(inputs)
    _assert_lineage(inputs, run)
    camera, radar = run["camera"], run["radar"]
    ray, point, transformed = camera.spatial_projection, radar.spatial_projection, radar.transformed_geometry
    assert (ray.direction_x, ray.direction_y, ray.direction_z) == (0., 0., 1.)
    assert (point.x_m, point.y_m, point.z_m) == (10., 0., 0.)
    assert (transformed.x_m, transformed.y_m, transformed.z_m) == (11., 2., 3.)
    assert (camera.mapped_time.lower_seconds, camera.mapped_time.upper_seconds) == (101.75, 102.25)
    assert (radar.mapped_time.lower_seconds, radar.mapped_time.upper_seconds) == (204.75, 205.25)
    assert tuple(e.source_observation.measurement_time.seconds for e in run["history"].records) == (5., 2.)
    assert camera.source_observation.measurement_time.clock_domain == "fixture:camera"
    assert radar.source_observation.measurement_time.clock_domain == "fixture:radar"
    assert json.loads(camera.source_observation.source_local_id) == ["fixture:opening", 7]
    assert camera.source_observation.measurement is not inputs["camera_batch"].objects[0].detection
    assert camera.source_observation.measurement.confidence == .75  # Copied backend evidence.
    assert len(run["scan"].detections) == 1  # No duplicate keys in normalization.
    assert repr(inputs) == before


def test_replay_equal_values_ids_and_correct_per_run_identity():
    inputs = _inputs()
    before = repr(inputs)
    first, second = _replay(inputs), _replay(inputs)
    assert first == second
    assert first["history"] is not second["history"]
    for run in (first, second):
        _assert_lineage(inputs, run)
    for kind in ("camera", "radar"):
        assert first[kind] is not second[kind]
        assert first[kind].source_observation is not second[kind].source_observation
        assert first[kind].source_observation.observation_id == second[kind].source_observation.observation_id
    assert repr(inputs) == before


def test_repeated_delivery_preserved_after_valid_normalization():
    run = _replay(_inputs())
    records = (run["radar"], run["camera"], run["radar"], run["camera"])
    history = ObservationHistory(records)
    assert history.records is records and len(history.records) == 4
    assert history.records[0] is history.records[2] is run["radar"]
    assert history.records[1] is history.records[3] is run["camera"]
    assert len(run["radar_batch"].observations) == 1


def test_missing_clock_mapping_does_not_synchronize_raw_times():
    run = _replay(_inputs(), mapped=False)
    for evidence in run["history"].records:
        assert evidence.mapped_time is None
    result = assess_evidence_comparability(run["radar"], run["camera"])
    assert result.temporal_relationship is TemporalRelationship.INDETERMINATE
    assert result.temporal_reason is TemporalReason.MISSING_MAPPED_TIME
    assert tuple(e.source_observation.measurement_time.seconds for e in run["history"].records) == (5., 2.)


def test_missing_elevation_and_unselected_camera_pixel_remain_partial():
    inputs = _inputs(elevation=None)
    run = _replay(inputs, camera_projection=False, radar_transform=False)
    camera, radar = run["camera"], run["radar"]
    assert radar.source_observation.measurement is inputs["measurement"]
    assert radar.source_observation.measurement.elevation_rad is None
    assert radar.spatial_projection is radar.transformed_geometry is None
    assert camera.spatial_projection is camera.camera_intrinsics is None
    assert camera.transformed_geometry is None
    assert camera.mapped_time is not None and radar.mapped_time is not None
    assert assess_evidence_comparability(camera, radar).spatial_reason is SpatialReason.MISSING_SPATIAL_GEOMETRY


def test_empty_scripted_scan_has_acquisition_context_but_no_observation():
    stamp = MeasurementTime(5., "fixture:radar")
    scan, = iter_scripted_radar_scans(((stamp, ()),), source_session_id="fixture:empty-session")
    assert scan.scan_time is stamp and scan.detections == ()
    batch = radar_detections_to_observations(scan.detections, sensor_id="fixture:radar-sensor",
                                            reference_frame_id="fixture:radar:local")
    assert batch.observations == ()
    assert ObservationHistory(tuple(derive_radar_evidence(o) for o in batch.observations)).records == ()


def test_temporal_classifications_do_not_assert_physical_correspondence():
    inputs = _inputs()
    disjoint = _replay(inputs)
    # Explicitly change the supplied mapping; nothing estimates synchronization.
    overlapping_inputs = dict(inputs, radar_mapping=replace(inputs["radar_mapping"], offset_seconds=97.))
    overlapping = _replay(overlapping_inputs)
    for run, expected in ((disjoint, TemporalRelationship.DISJOINT),
                          (overlapping, TemporalRelationship.OVERLAPPING)):
        result = assess_evidence_comparability(run["radar"], run["camera"])
        assert result.left is run["radar"] and result.right is run["camera"]
        assert result.temporal_relationship is expected
        assert result.temporal_reason is TemporalReason.SAME_DOMAIN_BOUNDED_INTERVALS
        assert result.spatial_status is SpatialStatus.INCOMPARABLE
        assert result.spatial_reason is SpatialReason.INCOMPATIBLE_GEOMETRY_TYPES
        assert [f.name for f in fields(result)] == [
            "left", "right", "spatial_status", "spatial_reason", "temporal_relationship", "temporal_reason",
        ]
        for evidence in run["history"].records:
            assert [f.name for f in fields(evidence)] == [
                "source_observation", "spatial_projection", "camera_intrinsics",
                "spatial_transform", "transformed_geometry", "mapped_time",
            ]
            assert not any(hasattr(evidence, name) for name in ("target_id", "track_id", "confidence", "score"))
        assert not hasattr(run["camera"].spatial_projection, "depth")


def test_camera_same_key_changed_payload_remains_inspectable():
    # Matching producer keys do not establish matching physical objects.
    inputs = _inputs()
    original = inputs["camera_batch"]
    tracked, = original.objects
    changed = TrackedObjectBatch(original.frame, (TrackedObject(
        tracked.track_id, replace(tracked.detection, x1=50., y1=60., x2=70., y2=80.),
    ),))
    before = repr((original, changed, inputs))
    context = dict(sensor_id="fixture:camera-sensor", clock_domain="fixture:camera",
                   reference_frame_id="fixture:camera:image")
    first, = tracked_objects_to_observations(original, **context).observations
    second, = tracked_objects_to_observations(changed, **context).observations
    assert first.observation_id == second.observation_id
    assert first.source_local_id == second.source_local_id
    assert first is not second
    assert first.measurement is not second.measurement
    assert first.measurement != second.measurement
    for observation, source in ((first, original), (second, changed)):
        detection = source.objects[0].detection
        assert observation.measurement is not detection
        assert (observation.measurement.x1, observation.measurement.y1,
                observation.measurement.x2, observation.measurement.y2) == (
                    detection.x1, detection.y1, detection.x2, detection.y2)
        assert observation.measurement_time == MeasurementTime(2., "fixture:camera")
        assert observation.reference_frame == inputs["point"].image_frame
    evidence = tuple(derive_camera_evidence(
        observation, image_point=inputs["point"], intrinsics=inputs["intrinsics"],
    ) for observation in (second, first))
    history = ObservationHistory(evidence)
    assert history.records is evidence and len(history.records) == 2
    for record, observation in zip(history.records, (second, first), strict=True):
        assert record.source_observation is observation
        assert record.spatial_projection.source_image_point is inputs["point"]
        assert record.camera_intrinsics is inputs["intrinsics"]
        assert not hasattr(record.spatial_projection, "depth")
    assert history.records[0] is evidence[0] and history.records[1] is evidence[1]
    assert history.records[0].source_observation.measurement != history.records[1].source_observation.measurement
    assert repr((original, changed, inputs)) == before


def test_radar_cross_call_same_key_changed_payload_preserved():
    # Characterize conflicting key reuse, without endorsing a producer policy.
    inputs = _inputs()
    scan, = iter_scripted_radar_scans(inputs["script"], source_session_id="fixture:session")
    original, = scan.detections
    changed_measurement = RadarPolarDetectionMeasurement(20., 0., 0.)
    changed = replace(original, measurement=changed_measurement)
    before = repr((original, changed, inputs))
    context = dict(sensor_id="fixture:radar-sensor", reference_frame_id="fixture:radar:local")
    # Separate calls respect the adapter's within-call duplicate-key restriction.
    first, = radar_detections_to_observations((original,), **context).observations
    second, = radar_detections_to_observations((changed,), **context).observations
    assert first.observation_id == second.observation_id
    assert first is not second
    assert first.measurement is original.measurement
    assert second.measurement is changed_measurement
    assert first.measurement != second.measurement
    assert first.measurement_time is second.measurement_time is inputs["radar_time"]
    assert first.reference_frame == second.reference_frame == ReferenceFrame("fixture:radar:local")
    evidence = tuple(derive_radar_evidence(observation) for observation in (second, first))
    history = ObservationHistory(evidence)
    assert history.records is evidence and len(history.records) == 2
    coordinates = []
    for record, observation in zip(history.records, (second, first), strict=True):
        assert record.source_observation is observation
        point = record.spatial_projection
        assert point.source_measurement is observation.measurement
        assert point.reference_frame is observation.reference_frame
        coordinates.append((point.x_m, point.y_m, point.z_m))
    assert coordinates == [(20., 0., 0.), (10., 0., 0.)]
    assert history.records[0] is evidence[0] and history.records[1] is evidence[1]
    assert repr((original, changed, inputs)) == before


def test_camera_normalization_preserves_nonfinite_values_rejected_by_evidence():
    inputs = _inputs()
    original = inputs["camera_batch"]
    tracked, = original.objects
    context = dict(sensor_id="fixture:camera-sensor", clock_domain="fixture:camera",
                   reference_frame_id="fixture:camera:image")
    baseline, = tracked_objects_to_observations(original, **context).observations
    original_before = repr(inputs)
    for field in ("x1", "confidence"):
        for value in (math.nan, math.inf, -math.inf):
            detection = replace(tracked.detection, **{field: value})
            source = TrackedObjectBatch(original.frame, (TrackedObject(tracked.track_id, detection),))
            source_before = repr(source)
            observation, = tracked_objects_to_observations(source, **context).observations
            measurement = observation.measurement
            stamp, frame = observation.measurement_time, observation.reference_frame
            normalized_before = repr(observation)
            for candidate in (getattr(detection, field), getattr(measurement, field)):
                if math.isnan(value):
                    assert math.isnan(candidate)
                else:
                    assert candidate == value
            for name in ("observation_id", "sensor_id", "source_local_id",
                         "measurement_time", "reference_frame"):
                assert getattr(observation, name) == getattr(baseline, name)
            for name in ("class_id", "label", "confidence", "x1", "y1", "x2", "y2"):
                if name != field:
                    assert getattr(measurement, name) == getattr(tracked.detection, name)
            for construct in (
                lambda: DerivedSensorEvidence(observation),
                lambda: derive_camera_evidence(
                    observation, image_point=inputs["point"], intrinsics=inputs["intrinsics"],
                ),
            ):
                try:
                    construct()
                except ValueError as error:
                    assert str(error) == f"{field} must be finite"
                else:
                    raise AssertionError(f"nonfinite {field} must be rejected")
                assert observation.measurement is measurement
                assert observation.measurement_time is stamp
                assert observation.reference_frame is frame
                assert repr(observation) == normalized_before
                assert source.objects[0].detection is detection
                assert source.frame is original.frame
                assert repr(source) == source_before
                assert repr(inputs) == original_before


def test_finite_backend_confidence_is_preserved_without_probability_inference():
    # Preserving a backend score does not establish a calibrated probability.
    inputs = _inputs()
    original = inputs["camera_batch"]
    tracked, = original.objects
    context = dict(sensor_id="fixture:camera-sensor", clock_domain="fixture:camera",
                   reference_frame_id="fixture:camera:image")
    baseline, = tracked_objects_to_observations(original, **context).observations
    original_before = repr(inputs)
    observations, records = [], []
    for confidence in (-0.25, 1.25):
        detection = replace(tracked.detection, confidence=confidence)
        source = TrackedObjectBatch(original.frame, (TrackedObject(tracked.track_id, detection),))
        source_before = repr(source)
        observation, = tracked_objects_to_observations(source, **context).observations
        assert observation.measurement.confidence == confidence
        for name in ("observation_id", "sensor_id", "source_local_id",
                     "measurement_time", "reference_frame"):
            assert getattr(observation, name) == getattr(baseline, name)
        evidence = derive_camera_evidence(observation)
        assert evidence.source_observation is observation
        assert evidence.source_observation.measurement is observation.measurement
        assert evidence.source_observation.measurement_time is observation.measurement_time
        assert evidence.source_observation.measurement.confidence == confidence
        assert evidence.spatial_projection is evidence.camera_intrinsics is evidence.mapped_time is None
        observations.append(observation)
        records.append(evidence)
        assert source.objects[0].detection is detection
        assert repr(source) == source_before
        assert repr(inputs) == original_before
    ordered = (records[1], records[0])
    history = ObservationHistory(ordered)
    assert history.records is ordered
    assert history.records[0] is records[1] and history.records[1] is records[0]
    assert history.records[0].source_observation is observations[1]
    assert history.records[1].source_observation is observations[0]
    assert tuple(record.source_observation.measurement.confidence for record in history.records) == (1.25, -0.25)
    assert repr(inputs) == original_before


def test_isolated_replay_without_external_dependencies_clocks_randomness_or_io():
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys, runpy, time, random
baseline = set(sys.modules)
sys.path.insert(0, sys.argv[1])
namespace = runpy.run_path(sys.argv[2])
assert all(name in sys.stdlib_module_names or name == 'aegis'
           for name in {key.split('.')[0] for key in set(sys.modules) - baseline})
def forbidden(*args, **kwargs):
    raise AssertionError('clock, randomness or I/O')
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = random.random = forbidden
def audit(event, args):
    if event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.urandom')):
        forbidden()
sys.addaudithook(audit)
inputs = namespace['_inputs']()
first, second = namespace['_replay'](inputs), namespace['_replay'](inputs)
assert first == second
namespace['_assert_lineage'](inputs, first)
namespace['_assert_lineage'](inputs, second)
'''
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source), str(Path(__file__).resolve())],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
