"""Explicit delivery order and lineage, without transport latency or association."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

from aegis.core.frames import FrameMetadata
from aegis.fusion.camera_adapter import tracked_objects_to_observations
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.comparability import (
    TemporalReason, TemporalRelationship, assess_evidence_comparability,
)
from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame
from aegis.fusion.derived_evidence import derive_camera_evidence, derive_radar_evidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.perception.contracts import ObjectDetection
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.radar.scripted_source import iter_scripted_radar_scans
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch


def _inputs():
    script = tuple(
        (MeasurementTime(float(t), "delivery:radar"),
         () if t == 2 else (RadarPolarDetectionMeasurement(
             10., 0., None if t == 4 else 0.),))
        for t in range(1, 6)
    )
    image_frame = ReferenceFrame("delivery:camera:image")
    camera_batch = TrackedObjectBatch(
        FrameMetadata("delivery:opening", 7, 2., 640, 480),
        (TrackedObject(9, ObjectDetection(0, "fixture", .75, 10., 20., 30., 40.)),),
    )
    return dict(
        script=script, camera_batch=camera_batch,
        image_point=ImagePoint(320., 240., 640, 480, image_frame),
        intrinsics=PinholeCameraIntrinsics(
            100., 100., 320., 240., 640, 480, image_frame,
            ReferenceFrame("delivery:camera:optical"), "delivery:calibration"),
        radar_mapping=BoundedClockMapping("delivery:radar", "delivery:time", 1., 100., 0., 10., .25),
        camera_mapping=BoundedClockMapping("delivery:camera", "delivery:time", 1., 103., 0., 10., .25),
    )


def _deliver(records, consumer):
    for record in records:
        consumer(record)


def _replay(inputs, *, select_camera_point=True):
    scans = tuple(iter_scripted_radar_scans(inputs["script"], source_session_id="delivery:session"))
    batches = tuple(radar_detections_to_observations(
        scan.detections, sensor_id="delivery:radar-sensor", reference_frame_id="delivery:radar:local",
    ) for scan in scans)
    # Acquisition inventory remains separate; empty scans have no evidence record.
    inventory = tuple(tuple(derive_radar_evidence(
        observation, clock_mapping=None if index == 3 else inputs["radar_mapping"],
    ) for observation in batch.observations) for index, batch in enumerate(batches))
    camera_batch = tracked_objects_to_observations(
        inputs["camera_batch"], sensor_id="delivery:camera-sensor",
        clock_domain="delivery:camera", reference_frame_id="delivery:camera:image",
    )
    camera = derive_camera_evidence(
        camera_batch.observations[0],
        image_point=inputs["image_point"] if select_camera_point else None,
        intrinsics=inputs["intrinsics"] if select_camera_point else None,
        clock_mapping=inputs["camera_mapping"],
    )
    schedule = (inventory[4][0], camera, inventory[0][0], inventory[4][0], inventory[3][0])
    delivered = []
    _deliver(schedule, delivered.append)
    records = tuple(delivered)
    return dict(scans=scans, batches=batches, inventory=inventory, camera_batch=camera_batch,
                camera=camera, schedule=schedule, history=ObservationHistory(records))


def _assert_lineage(inputs, run):
    for entry, scan, batch, evidence_rows in zip(
        inputs["script"], run["scans"], run["batches"], run["inventory"], strict=True,
    ):
        assert scan.scan_time is entry[0]
        for measurement, detection, observation, evidence in zip(
            entry[1], scan.detections, batch.observations, evidence_rows, strict=True,
        ):
            assert detection.measurement is observation.measurement is measurement
            assert detection.measurement_time is observation.measurement_time is entry[0]
            assert evidence.source_observation is observation
            if evidence.spatial_projection is not None:
                assert evidence.spatial_projection.source_measurement is measurement
            if evidence.mapped_time is not None:
                assert evidence.mapped_time.source_time is entry[0]
                assert evidence.mapped_time.source_mapping is inputs["radar_mapping"]
    camera = run["camera"]
    assert camera.source_observation is run["camera_batch"].observations[0]
    assert camera.source_observation.measurement_time.seconds == 2.
    assert camera.source_observation.measurement_time.clock_domain == "delivery:camera"
    assert camera.mapped_time.source_time is camera.source_observation.measurement_time
    assert camera.mapped_time.source_mapping is inputs["camera_mapping"]
    if camera.spatial_projection is not None:
        assert camera.spatial_projection.source_image_point is inputs["image_point"]
        assert camera.camera_intrinsics is inputs["intrinsics"]
    assert all(actual is requested for actual, requested in zip(
        run["history"].records, run["schedule"], strict=True))


def test_reordered_delivery_preserves_measurement_times_and_lineage():
    inputs = _inputs()
    run = _replay(inputs)
    _assert_lineage(inputs, run)
    records = run["history"].records
    assert tuple(r.source_observation.measurement_time.seconds for r in records) == (5., 2., 1., 5., 4.)
    assert records[0].source_observation.measurement_time.clock_domain == records[2].source_observation.measurement_time.clock_domain
    assert records[2].source_observation.measurement_time is inputs["script"][0][0]
    ray = run["camera"].spatial_projection
    assert (ray.direction_x, ray.direction_y, ray.direction_z) == (0., 0., 1.)
    assert not hasattr(ray, "depth")


def test_repeated_delivery_preserves_occurrences_and_identity():
    run = _replay(_inputs())
    records = run["history"].records
    assert len(records) == 5
    assert records[0] is records[3] is run["inventory"][4][0]
    assert len(run["batches"][4].observations) == 1
    assert records[0].source_observation is records[3].source_observation


def test_empty_and_withheld_acquisitions_create_no_placeholders():
    run = _replay(_inputs())
    assert tuple(scan.scan_time.seconds for scan in run["scans"]) == (1., 2., 3., 4., 5.)
    assert run["scans"][1].detections == ()
    assert run["batches"][1] == ObservationBatch(())
    assert run["inventory"][1] == ()
    withheld, = run["inventory"][2]
    assert withheld.source_observation is run["batches"][2].observations[0]
    assert withheld.source_observation.measurement_time.seconds == 3.
    assert all(r is not withheld for r in run["history"].records)
    assert withheld.source_observation.observation_id not in {
        r.source_observation.observation_id for r in run["history"].records}


def test_partial_evidence_survives_interleaved_delivery():
    run = _replay(_inputs(), select_camera_point=False)
    partial = run["history"].records[4]
    assert partial is run["inventory"][3][0]
    assert partial.source_observation.measurement.range_m > 0
    assert partial.source_observation.measurement.elevation_rad is None
    assert partial.spatial_projection is partial.transformed_geometry is partial.mapped_time is None
    assert run["camera"].spatial_projection is run["camera"].camera_intrinsics is None
    assert run["camera"].mapped_time is not None
    result = assess_evidence_comparability(partial, run["camera"])
    assert result.temporal_relationship is TemporalRelationship.INDETERMINATE
    assert result.temporal_reason is TemporalReason.MISSING_MAPPED_TIME


def test_delivery_replay_is_deterministic_without_input_mutation():
    inputs = _inputs()
    before = repr(inputs)
    first, second = _replay(inputs), _replay(inputs)
    assert first == second
    for run in (first, second):
        _assert_lineage(inputs, run)
    for left, right in zip(first["history"].records, second["history"].records, strict=True):
        assert left == right and left is not right
        assert left.source_observation is not right.source_observation
        assert left.source_observation.observation_id == right.source_observation.observation_id
    assert repr(inputs) == before


def test_consumer_failure_stops_delivery_without_retry():
    run = _replay(_inputs())
    attempted, accepted = [], []
    failure = RuntimeError("chosen consumer failure")
    def consumer(record):
        attempted.append(record)
        if record is run["schedule"][2]:
            raise failure
        accepted.append(record)
    try:
        _deliver(run["schedule"], consumer)
    except RuntimeError as caught:
        assert caught is failure
    else:
        raise AssertionError("consumer failure must propagate")
    assert len(attempted) == 3 and len(accepted) == 2
    assert all(actual is expected for actual, expected in zip(attempted, run["schedule"][:3], strict=True))
    assert all(actual is expected for actual, expected in zip(accepted, run["schedule"][:2], strict=True))


def test_consumer_side_effect_survives_failure_and_explicit_replay():
    run = _replay(_inputs())
    schedule = run["schedule"]
    effects = []
    failure = RuntimeError("side effect before failure")

    def consumer(record):
        effects.append(record)
        if len(effects) == 2:
            raise failure

    try:
        _deliver(schedule, consumer)
    except RuntimeError as caught:
        assert caught is failure
    else:
        raise AssertionError("consumer failure must propagate")
    assert len(effects) == 2
    assert effects[0] is schedule[0] and effects[1] is schedule[1]
    before_replay = tuple(effects)

    # The caller explicitly starts a new attempt; no delivery layer retries it.
    _deliver(schedule, consumer)
    expected = before_replay + schedule
    assert len(effects) == 7
    assert all(actual is original for actual, original in zip(effects, expected, strict=True))
    assert effects[0] is effects[2] is effects[5] is schedule[0]
    assert effects[1] is effects[3] is schedule[1]
    assert run["schedule"] is schedule


def test_partial_batch_consumer_state_is_not_rolled_back():
    stamp = MeasurementTime(3., "delivery:radar")
    measurements = (RadarPolarDetectionMeasurement(10., 0., 0.),
                    RadarPolarDetectionMeasurement(20., 0., 0.))
    scan, = iter_scripted_radar_scans(
        ((stamp, measurements),), source_session_id="delivery:partial-batch",
    )
    assert scan.detections[0].evidence_id != scan.detections[1].evidence_id
    batch = radar_detections_to_observations(
        scan.detections, sensor_id="delivery:radar-sensor",
        reference_frame_id="delivery:radar:local",
    )
    first, second = batch.observations
    original_rows = batch.observations
    identifiers = tuple(row.observation_id for row in original_rows)
    before = repr(batch)
    effects, attempted = [], []
    failure = RuntimeError("second observation failed")

    def consumer(delivered_batch):
        attempted.append(delivered_batch)
        for observation in delivered_batch.observations:
            if observation is second:
                raise failure
            effects.append(observation)

    for attempt in range(2):
        # Both attempts are explicit caller invocations, not an automatic retry.
        try:
            consumer(batch)
        except RuntimeError as caught:
            assert caught is failure
        else:
            raise AssertionError("partial batch failure must propagate")
        assert len(effects) == attempt + 1
        assert all(effect is first for effect in effects)
        assert len(attempted) == attempt + 1
        assert all(delivered is batch for delivered in attempted)
        assert batch.observations is original_rows
        assert batch.observations[0] is first and batch.observations[1] is second
        assert tuple(row.observation_id for row in batch.observations) == identifiers
        for row, detection, measurement in zip(
            batch.observations, scan.detections, measurements, strict=True,
        ):
            assert row.measurement_time is detection.measurement_time is stamp
            assert row.measurement is detection.measurement is measurement
            assert row.measurement_time.clock_domain == "delivery:radar"
        assert repr(batch) == before


def test_explicit_temporal_relationships_do_not_imply_correspondence():
    inputs = _inputs()
    run = _replay(inputs)
    late, camera, early, _, partial = run["history"].records
    for other, expected in ((late, TemporalRelationship.OVERLAPPING),
                            (early, TemporalRelationship.DISJOINT)):
        result = assess_evidence_comparability(camera, other)
        assert result.left is camera and result.right is other
        assert result.temporal_relationship is expected
        assert result.temporal_reason is TemporalReason.SAME_DOMAIN_BOUNDED_INTERVALS
        assert not any(hasattr(result, name) for name in ("target_id", "score", "confidence", "eligible"))
    assert assess_evidence_comparability(camera, partial).temporal_reason is TemporalReason.MISSING_MAPPED_TIME
    different = _replay(dict(inputs, camera_mapping=replace(
        inputs["camera_mapping"], target_clock_domain="delivery:other-time")))
    result = assess_evidence_comparability(different["camera"], different["inventory"][4][0])
    assert result.temporal_relationship is TemporalRelationship.INDETERMINATE
    assert result.temporal_reason is TemporalReason.DIFFERENT_CLOCK_DOMAINS


def test_isolated_replay_without_dependencies_clocks_randomness_or_io():
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
namespace['test_consumer_failure_stops_delivery_without_retry']()
'''
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(source), str(Path(__file__).resolve())],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
