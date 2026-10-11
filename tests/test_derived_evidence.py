"""Independent evidence derivations, exact consistency, and object lineage."""

from dataclasses import FrozenInstanceError, fields, replace
import math
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.clock_mapping import BoundedClockMapping, map_measurement_time
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import (
    DerivedSensorEvidence, derive_camera_evidence, derive_radar_evidence,
)
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics, image_point_to_camera_ray
from aegis.spatial.radar import RadarPoint
from aegis.spatial.transforms import RigidTransform


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


@pytest.fixture
def camera():
    frame = ReferenceFrame("fixture:camera:image")
    point = ImagePoint(320., 240., 640, 480, frame)
    observation = SensorObservation("camera-event", "camera", MeasurementTime(2., "fixture:camera"),
                                    frame, point, "opening/track-1")
    intrinsics = PinholeCameraIntrinsics(100., 100., 320., 240., 640, 480, frame,
                                       ReferenceFrame("fixture:camera:optical"), "fixture:calibration")
    return observation, point, intrinsics


@pytest.fixture
def radar():
    return SensorObservation("radar-event", "radar", MeasurementTime(5., "fixture:radar"),
                             ReferenceFrame("fixture:radar:local"),
                             RadarPolarDetectionMeasurement(10., 0., 0., -3.), "session/return-1")


def clock(observation):
    offset = 100. if observation.sensor_id == "camera" else 200.
    return BoundedClockMapping(observation.measurement_time.clock_domain, "fixture:time",
                               1., offset, 0., 10., 0.25)


def transform(frame):
    return RigidTransform(frame, ReferenceFrame("fixture:target"), IDENTITY, (1., 2., 3.))


def camera_result(camera, **kwargs):
    observation, point, intrinsics = camera
    return derive_camera_evidence(observation, image_point=point, intrinsics=intrinsics, **kwargs)


@pytest.mark.parametrize("kind", ["camera", "radar"])
def test_original_only_and_temporal_only(camera, radar, kind):
    observation = camera[0] if kind == "camera" else radar
    direct = DerivedSensorEvidence(observation)
    helper = derive_camera_evidence if kind == "camera" else derive_radar_evidence
    options = {} if kind == "camera" else {"project_spatial": False}
    assert helper(observation, **options) == direct
    assert direct.source_observation is observation
    assert all(getattr(direct, f.name) is None for f in fields(direct)[1:])
    mapping = clock(observation)
    temporal = helper(observation, clock_mapping=mapping, **options)
    assert temporal.spatial_projection is None
    assert temporal.mapped_time.source_time is observation.measurement_time
    assert temporal.mapped_time.source_mapping is mapping


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("spatial_transform", [False, True])
def test_camera_lineage_and_direction_translation_ignored(camera, temporal, spatial_transform):
    observation, point, intrinsics = camera
    t = transform(intrinsics.optical_frame) if spatial_transform else None
    m = clock(observation) if temporal else None
    result = camera_result(camera, spatial_transform=t, clock_mapping=m)
    assert result.source_observation is observation
    assert result.camera_intrinsics is intrinsics
    ray = result.spatial_projection
    assert ray.source_image_point is point
    assert ray.optical_frame is intrinsics.optical_frame
    assert (ray.direction_x, ray.direction_y, ray.direction_z) == (0., 0., 1.)
    assert result.spatial_transform is t
    if t is not None:
        assert result.transformed_geometry.source_ray is ray
        assert result.transformed_geometry.reference_frame is t.target_frame
        assert result.transformed_geometry.direction_z == 1.
        assert result.transformed_geometry.direction_x == result.transformed_geometry.direction_y == 0.
    if m is not None:
        assert result.mapped_time.source_mapping is m
        assert (result.mapped_time.lower_seconds, result.mapped_time.upper_seconds) == (101.75, 102.25)


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("spatial_transform", [False, True])
def test_radar_lineage_and_metric_translation(radar, temporal, spatial_transform):
    t = transform(radar.reference_frame) if spatial_transform else None
    m = clock(radar) if temporal else None
    result = derive_radar_evidence(radar, spatial_transform=t, clock_mapping=m)
    assert result.source_observation is radar
    point = result.spatial_projection
    assert point.source_measurement is radar.measurement
    assert point.reference_frame is radar.reference_frame
    assert (point.x_m, point.y_m, point.z_m) == (10., 0., 0.)
    assert result.spatial_transform is t
    if t is not None:
        transformed = result.transformed_geometry
        assert transformed.source_point is point
        assert transformed.reference_frame is t.target_frame
        assert (transformed.x_m, transformed.y_m, transformed.z_m) == (11., 2., 3.)
    if m is not None:
        assert result.mapped_time.source_mapping is m
        assert (result.mapped_time.lower_seconds, result.mapped_time.upper_seconds) == (204.75, 205.25)


def test_fixture_records_are_independent_without_target_or_generated_confidence(camera, radar):
    c = camera_result(camera, clock_mapping=clock(camera[0]))
    r = derive_radar_evidence(radar, spatial_transform=transform(radar.reference_frame), clock_mapping=clock(radar))
    assert c is not r and c.source_observation is not r.source_observation
    assert c.source_observation.observation_id != r.source_observation.observation_id
    assert {f.name for f in fields(c)} == {
        "source_observation", "spatial_projection", "camera_intrinsics", "spatial_transform",
        "transformed_geometry", "mapped_time",
    }
    assert not hasattr(c.spatial_projection, "depth")
    assert not hasattr(c.transformed_geometry, "origin")
    assert not hasattr(r.spatial_projection, "velocity_x")
    assert r.spatial_projection.source_measurement.radial_velocity_mps == -3.


def test_explicit_track_point_can_be_outside_bbox_and_image(camera):
    observation, _, intrinsics = camera
    measurement = ImageTrackMeasurement(1, "label", 0.7, 1., 2., 3., 4., 640, 480)
    observation = replace(observation, measurement=measurement)
    point = ImagePoint(-100., 900., 640, 480, observation.reference_frame)
    result = derive_camera_evidence(observation, image_point=point, intrinsics=intrinsics)
    assert result.spatial_projection.source_image_point is point
    assert result.source_observation.measurement is measurement
    assert measurement.confidence == 0.7
    assert derive_camera_evidence(observation).spatial_projection is None


def test_image_point_requires_identity_not_equal_copy(camera):
    observation, point, intrinsics = camera
    with pytest.raises(ValueError, match="original measurement"):
        derive_camera_evidence(observation, image_point=replace(point), intrinsics=intrinsics)


@pytest.mark.parametrize("range_m", [10., 0., -0.])
def test_missing_elevation_retains_evidence_and_zero_exception(radar, range_m):
    observation = replace(radar, measurement=RadarPolarDetectionMeasurement(range_m, 0.))
    result = derive_radar_evidence(observation, clock_mapping=clock(observation))
    assert result.source_observation is observation
    assert observation.measurement.elevation_rad is None
    assert result.mapped_time is not None
    if range_m == 0:
        assert result.spatial_projection.x_m == result.spatial_projection.y_m == result.spatial_projection.z_m == 0
    else:
        assert result.spatial_projection is None
        with pytest.raises(ValueError, match="available radar point"):
            derive_radar_evidence(observation, spatial_transform=transform(observation.reference_frame))
        fake = RadarPoint(10., 0., 0., observation.reference_frame, observation.measurement)
        with pytest.raises(ValueError, match="inconsistent"):
            DerivedSensorEvidence(observation, spatial_projection=fake)


@pytest.mark.parametrize("field,value,error", [
    ("source_observation", None, TypeError),
    ("measurement", object(), TypeError),
    ("reference_frame", "frame", TypeError),
    ("measurement_time", 2., TypeError),
    ("measurement_time", MeasurementTime(math.nan, "clock"), ValueError),
    ("measurement_time", MeasurementTime(math.inf, "clock"), ValueError),
    ("measurement_time", MeasurementTime(True, "clock"), TypeError),
    ("observation_id", 2, TypeError),
    ("sensor_id", 2, TypeError),
    ("source_local_id", 2, TypeError),
])
def test_source_metadata_validation(camera, field, value, error):
    observation = camera[0]
    if field in ("observation_id", "sensor_id", "source_local_id"):
        # Existing constructors reject these before the new boundary is reached.
        # Build an isolated malformed contract to exercise local error policy.
        malformed = object.__new__(SensorObservation)
        for f in fields(observation):
            object.__setattr__(malformed, f.name, value if f.name == field else getattr(observation, f.name))
        with pytest.raises(error):
            DerivedSensorEvidence(malformed)
        return
    with pytest.raises(error):
        source = value if field == "source_observation" else replace(observation, **{field: value})
        DerivedSensorEvidence(source)


@pytest.mark.parametrize("dimension", ["image_width", "image_height"])
def test_track_dimension_mismatch(camera, dimension):
    observation, point, intrinsics = camera
    measurement = ImageTrackMeasurement(1, "label", 0.7, 1., 2., 3., 4., 640, 480)
    observation = replace(observation, measurement=replace(measurement, **{dimension: 100}))
    with pytest.raises(ValueError, match="dimensions"):
        derive_camera_evidence(observation, image_point=point, intrinsics=intrinsics)


@pytest.mark.parametrize("field,value", [("image_width", 100), ("image_height", 100),
                                          ("image_frame", ReferenceFrame("wrong"))])
def test_camera_intrinsics_coordinate_mismatch(camera, field, value):
    with pytest.raises(ValueError):
        derive_camera_evidence(camera[0], image_point=camera[1], intrinsics=replace(camera[2], **{field: value}))


def test_camera_frame_types_and_source_consistency(camera):
    observation, point, intrinsics = camera
    with pytest.raises(ValueError, match="frames"):
        DerivedSensorEvidence(replace(observation, reference_frame=ReferenceFrame("wrong")))
    bad_point = replace(point, image_frame="bad")
    with pytest.raises(TypeError):
        DerivedSensorEvidence(replace(observation, measurement=bad_point))
    with pytest.raises(TypeError):
        derive_camera_evidence(observation, image_point=point, intrinsics=replace(intrinsics, optical_frame="bad"))


@pytest.mark.parametrize("kind", ["camera", "radar"])
def test_wrong_projection_and_result_types(camera, radar, kind):
    c, r = camera_result(camera), derive_radar_evidence(radar)
    result, foreign = (c, r) if kind == "camera" else (r, c)
    with pytest.raises(TypeError):
        replace(result, spatial_projection=foreign.spatial_projection)
    c = camera_result(camera, spatial_transform=transform(camera[2].optical_frame))
    r = derive_radar_evidence(radar, spatial_transform=transform(radar.reference_frame))
    result, foreign = (c, r) if kind == "camera" else (r, c)
    with pytest.raises(TypeError):
        replace(result, transformed_geometry=foreign.transformed_geometry)


def test_camera_projection_exact_numeric_calibration_and_optical_frame_consistency(camera):
    result = camera_result(camera)
    for ray in (replace(result.spatial_projection, direction_z=math.nextafter(1., 2.)),
                replace(result.spatial_projection, calibration_id="other"),
                replace(result.spatial_projection, optical_frame=ReferenceFrame("other"))):
        with pytest.raises(ValueError, match="inconsistent"):
            replace(result, spatial_projection=ray)


def test_radar_projection_exact_numeric_frame_and_source_consistency(radar):
    result = derive_radar_evidence(radar)
    for point in (replace(result.spatial_projection, x_m=math.nextafter(10., 11.)),
                  replace(result.spatial_projection, reference_frame=ReferenceFrame("wrong")),
                  replace(result.spatial_projection, source_measurement=replace(radar.measurement))):
        with pytest.raises(ValueError):
            replace(result, spatial_projection=point)


@pytest.mark.parametrize("kind", ["camera", "radar"])
def test_transform_exact_numeric_frame_and_source_consistency(camera, radar, kind):
    result = (camera_result(camera, spatial_transform=transform(camera[2].optical_frame))
              if kind == "camera" else derive_radar_evidence(radar, spatial_transform=transform(radar.reference_frame)))
    field = "direction_z" if kind == "camera" else "x_m"
    source_field = "source_ray" if kind == "camera" else "source_point"
    geometry = result.transformed_geometry
    for changed in (replace(geometry, **{field: math.nextafter(getattr(geometry, field), math.inf)}),
                    replace(geometry, reference_frame=ReferenceFrame("wrong")),
                    replace(geometry, **{source_field: replace(result.spatial_projection)})):
        with pytest.raises(ValueError):
            replace(result, transformed_geometry=changed)
    with pytest.raises(ValueError):
        replace(result, spatial_transform=transform(ReferenceFrame("wrong")))


@pytest.mark.parametrize("kind", ["camera", "radar"])
def test_temporal_exact_consistency_and_timestamp_identity(camera, radar, kind):
    observation = camera[0] if kind == "camera" else radar
    result = DerivedSensorEvidence(observation, mapped_time=map_measurement_time(observation.measurement_time, clock(observation)))
    interval = result.mapped_time
    for changed in (replace(interval, lower_seconds=math.nextafter(interval.lower_seconds, -math.inf)),
                    replace(interval, upper_seconds=math.nextafter(interval.upper_seconds, math.inf)),
                    replace(interval, source_time=replace(observation.measurement_time))):
        with pytest.raises(ValueError):
            replace(result, mapped_time=changed)
    # A structurally valid interval may claim an inapplicable mapping.
    bad_mapping = replace(clock(observation), valid_until_source_seconds=1.)
    with pytest.raises(ValueError, match="outside"):
        replace(result, mapped_time=replace(interval, source_mapping=bad_mapping))
    for changed_mapping in (replace(clock(observation), source_clock_domain="wrong"),
                            replace(clock(observation), target_clock_domain="wrong")):
        with pytest.raises(ValueError):
            replace(result, mapped_time=replace(interval, source_mapping=changed_mapping))


def test_partial_parameter_combinations(camera, radar):
    observation, point, intrinsics = camera
    for options in ({"image_point": point}, {"intrinsics": intrinsics},
                    {"spatial_transform": transform(intrinsics.optical_frame)}):
        with pytest.raises(ValueError):
            derive_camera_evidence(observation, **options)
    c = camera_result(camera)
    with pytest.raises(ValueError):
        replace(c, camera_intrinsics=None)
    with pytest.raises(ValueError):
        DerivedSensorEvidence(observation, camera_intrinsics=intrinsics)
    with pytest.raises(ValueError):
        replace(derive_radar_evidence(radar), camera_intrinsics=intrinsics)
    with pytest.raises(ValueError):
        derive_radar_evidence(radar, project_spatial=False, spatial_transform=transform(radar.reference_frame))
    complete = derive_radar_evidence(radar, spatial_transform=transform(radar.reference_frame))
    for options in ({"spatial_transform": None}, {"transformed_geometry": None}, {"spatial_projection": None}):
        with pytest.raises(ValueError):
            replace(complete, **options)


@pytest.mark.parametrize("field", ["spatial_projection", "camera_intrinsics", "spatial_transform", "transformed_geometry", "mapped_time"])
def test_wrong_optional_envelope_types(camera, field):
    with pytest.raises(TypeError):
        DerivedSensorEvidence(camera[0], **{field: object()})


@pytest.mark.parametrize("name", ["image_point", "intrinsics", "spatial_transform", "clock_mapping"])
def test_camera_helper_wrong_parameter_types(camera, name):
    with pytest.raises(TypeError):
        derive_camera_evidence(camera[0], **{name: object()})


@pytest.mark.parametrize("name", ["project_spatial", "spatial_transform", "clock_mapping"])
def test_radar_helper_wrong_parameter_types(radar, name):
    with pytest.raises(TypeError):
        derive_radar_evidence(radar, **{name: object()})


def test_helper_sensor_type_rejection(camera, radar):
    with pytest.raises(TypeError):
        derive_camera_evidence(radar)
    with pytest.raises(TypeError):
        derive_radar_evidence(camera[0])


def test_equal_frame_values_accepted_and_provenance_unchanged(camera, radar):
    c = camera_result(camera, spatial_transform=transform(ReferenceFrame(camera[2].optical_frame.frame_id)))
    r = derive_radar_evidence(radar, spatial_transform=transform(ReferenceFrame(radar.reference_frame.frame_id)))
    assert c.transformed_geometry.source_ray is c.spatial_projection
    assert r.transformed_geometry.source_point is r.spatial_projection


def test_explicit_rotation_changes_direction_without_depth(camera):
    rotation = ((1., 0., 0.), (0., -1., 0.), (0., 0., -1.))
    t = RigidTransform(camera[2].optical_frame, ReferenceFrame("target"), rotation, (100., 200., 300.))
    result = camera_result(camera, spatial_transform=t)
    assert (result.transformed_geometry.direction_x, result.transformed_geometry.direction_y,
            result.transformed_geometry.direction_z) == (0., 0., -1.)
    assert not hasattr(result.transformed_geometry, "origin")


def test_selected_track_frame_is_explicit(camera):
    observation, point, _ = camera
    track = ImageTrackMeasurement(1, "label", 0.7, 1., 2., 3., 4., 640, 480)
    observation = replace(observation, measurement=track)
    wrong_point = replace(point, image_frame=ReferenceFrame("wrong-image"))
    wrong_intrinsics = replace(camera[2], image_frame=wrong_point.image_frame)
    with pytest.raises(ValueError, match="selected point frame"):
        derive_camera_evidence(observation, image_point=wrong_point, intrinsics=wrong_intrinsics)


@pytest.mark.parametrize("kind", ["camera", "radar"])
def test_helpers_reject_wrong_clock_and_outside_validity(camera, radar, kind):
    observation = camera[0] if kind == "camera" else radar
    helper = derive_camera_evidence if kind == "camera" else derive_radar_evidence
    for m in (replace(clock(observation), source_clock_domain="other"),
              replace(clock(observation), valid_until_source_seconds=1.)):
        with pytest.raises(ValueError):
            helper(observation, clock_mapping=m)


@pytest.mark.parametrize("dimension,value,error", [
    ("image_width", 0, ValueError), ("image_height", True, TypeError),
    ("image_width", 1.5, TypeError),
])
def test_original_track_dimensions_validated(camera, dimension, value, error):
    measurement = ImageTrackMeasurement(1, "label", 0.7, 1., 2., 3., 4., 640, 480)
    with pytest.raises(error):
        DerivedSensorEvidence(replace(camera[0], measurement=replace(measurement, **{dimension: value})))


def test_frozen_deterministic_and_no_input_mutation(camera, radar):
    before = repr((camera, radar))
    c = camera_result(camera, clock_mapping=clock(camera[0]))
    r = derive_radar_evidence(radar, clock_mapping=clock(radar))
    assert camera_result(camera, clock_mapping=clock(camera[0])) == c
    assert derive_radar_evidence(radar, clock_mapping=clock(radar)) == r
    assert repr((camera, radar)) == before
    for result in (c, r):
        for field in fields(result):
            with pytest.raises(FrozenInstanceError):
                setattr(result, field.name, None)


def test_fresh_interpreter_standard_library_and_pure_operations():
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys, time, random
baseline = set(sys.modules)
sys.path.insert(0, sys.argv[1])
from aegis.fusion.derived_evidence import derive_camera_evidence, derive_radar_evidence
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
assert all(name in sys.stdlib_module_names or name == "aegis"
           for name in {key.split('.')[0] for key in set(sys.modules) - baseline})
def forbidden(*args, **kwargs):
    raise AssertionError("clock, randomness or I/O")
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = random.random = forbidden
def audit(event, args):
    if event == "open" or event.startswith(("socket.", "subprocess.", "os.urandom")):
        forbidden()
sys.addaudithook(audit)
f = ReferenceFrame("image")
p = ImagePoint(320,240,640,480,f)
i = PinholeCameraIntrinsics(100,100,320,240,640,480,f,ReferenceFrame("optical"),"cal")
c = SensorObservation("camera-event","camera",MeasurementTime(2,"camera-clock"),f,p)
r = SensorObservation("radar-event","radar",MeasurementTime(5,"radar-clock"),
                      ReferenceFrame("radar-local"),RadarPolarDetectionMeasurement(10,0,0))
for obs, helper, options in ((c,derive_camera_evidence,dict(image_point=p,intrinsics=i)),
                             (r,derive_radar_evidence,{})):
    m = BoundedClockMapping(obs.measurement_time.clock_domain,"target-clock",1,100,0,10,0.25)
    result = helper(obs,clock_mapping=m,**options)
    assert result.source_observation is obs
    assert result.mapped_time.source_mapping is m
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
