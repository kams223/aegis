"""Classification of available information without association or scoring."""

from dataclasses import FrozenInstanceError, fields, replace
import math
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.comparability import (
    EvidenceComparability, SpatialReason, SpatialStatus, TemporalReason,
    TemporalRelationship, assess_evidence_comparability,
)
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import derive_camera_evidence, derive_radar_evidence
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.spatial.transforms import RigidTransform


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def evidence(kind="radar", frame="frame", target=None, spatial=True,
             seconds=0., error=0., clock="mapped", mapped=True, elevation=0.):
    time = MeasurementTime(seconds, "source")
    f = ReferenceFrame(frame)
    mapping = BoundedClockMapping("source", clock, 1., 0., -sys.float_info.max,
                                  sys.float_info.max, error) if mapped else None
    transform = RigidTransform(f, ReferenceFrame(target), IDENTITY, (1., 2., 3.)) if target else None
    if kind == "radar":
        obs = SensorObservation("radar-event", "radar", time, f,
                                RadarPolarDetectionMeasurement(10., 0., elevation))
        return derive_radar_evidence(obs, project_spatial=spatial,
                                     spatial_transform=transform, clock_mapping=mapping)
    image_frame = ReferenceFrame("image")
    point = ImagePoint(320., 240., 640, 480, image_frame)
    obs = SensorObservation("camera-event", "camera", time, image_frame, point)
    intrinsics = PinholeCameraIntrinsics(100., 100., 320., 240., 640, 480, image_frame, f, "cal")
    return derive_camera_evidence(obs, image_point=point if spatial else None,
                                  intrinsics=intrinsics if spatial else None,
                                  spatial_transform=transform, clock_mapping=mapping)


@pytest.mark.parametrize("kind,reason", [("radar", SpatialReason.SAME_FRAME_METRIC_POINTS),
                                       ("camera", SpatialReason.SAME_FRAME_DIRECTIONS)])
@pytest.mark.parametrize("left_transformed,right_transformed", [(False, False), (False, True), (True, False), (True, True)])
def test_all_same_kind_local_and_transformed_combinations(kind, reason, left_transformed, right_transformed):
    left = evidence(kind, frame="left-source" if left_transformed else "common",
                    target="common" if left_transformed else None)
    right = evidence(kind, frame="right-source" if right_transformed else "common",
                     target="common" if right_transformed else None)
    result = assess_evidence_comparability(left, right)
    assert result.spatial_status is SpatialStatus.COMPARABLE
    assert result.spatial_reason is reason
    assert result.left is left and result.right is right


@pytest.mark.parametrize("kind", ["radar", "camera"])
def test_different_frames_and_no_fallback(kind):
    left = evidence(kind, frame="shared-source", target="target-a")
    right = evidence(kind, frame="shared-source", target="target-b")
    result = assess_evidence_comparability(left, right)
    assert result.spatial_status is SpatialStatus.INSUFFICIENT_INFORMATION
    assert result.spatial_reason is SpatialReason.DIFFERENT_SPATIAL_FRAMES
    assert assess_evidence_comparability(evidence(kind, frame="a"), evidence(kind, frame="b")).spatial_reason is SpatialReason.DIFFERENT_SPATIAL_FRAMES


@pytest.mark.parametrize("frame", ["frame", "other"])
def test_kind_mismatch_precedes_frame_mismatch(frame):
    result = assess_evidence_comparability(evidence("camera"), evidence("radar", frame=frame))
    assert result.spatial_status is SpatialStatus.INCOMPARABLE
    assert result.spatial_reason is SpatialReason.INCOMPATIBLE_GEOMETRY_TYPES


@pytest.mark.parametrize("kind", ["radar", "camera"])
@pytest.mark.parametrize("side", ["left", "right", "both"])
def test_missing_geometry_precedence(kind, side):
    left = evidence(kind, spatial=side not in ("left", "both"))
    right = evidence("camera" if kind == "radar" else "radar", spatial=side not in ("right", "both"))
    result = assess_evidence_comparability(left, right)
    assert result.spatial_status is SpatialStatus.INSUFFICIENT_INFORMATION
    assert result.spatial_reason is SpatialReason.MISSING_SPATIAL_GEOMETRY


def test_missing_elevation_and_direction_has_no_depth_or_origin_requirement():
    partial = evidence(elevation=None)
    assert assess_evidence_comparability(partial, evidence()).spatial_reason is SpatialReason.MISSING_SPATIAL_GEOMETRY
    directions = assess_evidence_comparability(evidence("camera", target="common"),
                                               evidence("camera", target="common"))
    assert directions.spatial_reason is SpatialReason.SAME_FRAME_DIRECTIONS
    assert not hasattr(directions.left.transformed_geometry, "origin")
    assert not hasattr(directions.left.spatial_projection, "depth")


@pytest.mark.parametrize("first,second,expected", [
    ((0., 1.), (0.5, 1.), TemporalRelationship.OVERLAPPING),
    ((0., 2.), (0., 0.), TemporalRelationship.OVERLAPPING),
    ((0., 1.), (2., 1.), TemporalRelationship.OVERLAPPING),
    ((0., 0.), (0., 0.), TemporalRelationship.OVERLAPPING),
    ((0., 0.), (1., 0.), TemporalRelationship.DISJOINT),
    ((-10., 1.), (-7., 1.), TemporalRelationship.DISJOINT),
    ((-10., 1.), (-9., 1.), TemporalRelationship.OVERLAPPING),
    ((-0., 0.), (0., 0.), TemporalRelationship.OVERLAPPING),
    ((0., 0.), (math.ulp(0.), 0.), TemporalRelationship.DISJOINT),
    ((math.ulp(0.), 0.), (math.ulp(0.), 0.), TemporalRelationship.OVERLAPPING),
    ((sys.float_info.max, 0.), (-sys.float_info.max, 0.), TemporalRelationship.DISJOINT),
    ((sys.float_info.max, 0.), (sys.float_info.max, 0.), TemporalRelationship.OVERLAPPING),
])
def test_closed_interval_relationships_without_subtraction(first, second, expected):
    left = evidence(seconds=first[0], error=first[1])
    right = evidence(seconds=second[0], error=second[1])
    for a, b in ((left, right), (right, left)):
        result = assess_evidence_comparability(a, b)
        assert result.temporal_relationship is expected
        assert result.temporal_reason is TemporalReason.SAME_DOMAIN_BOUNDED_INTERVALS


@pytest.mark.parametrize("side", ["left", "right", "both"])
def test_missing_mapping_despite_equal_raw_domains(side):
    left = evidence(mapped=side not in ("left", "both"), clock="a")
    right = evidence(mapped=side not in ("right", "both"), clock="b")
    assert left.source_observation.measurement_time.clock_domain == right.source_observation.measurement_time.clock_domain
    result = assess_evidence_comparability(left, right)
    assert result.temporal_relationship is TemporalRelationship.INDETERMINATE
    assert result.temporal_reason is TemporalReason.MISSING_MAPPED_TIME


def test_different_target_clocks_precede_numeric_overlap():
    result = assess_evidence_comparability(evidence(clock="a"), evidence(clock="b"))
    assert result.temporal_relationship is TemporalRelationship.INDETERMINATE
    assert result.temporal_reason is TemporalReason.DIFFERENT_CLOCK_DOMAINS


def test_equal_identifiers_and_equal_distinct_evidence_provenance():
    left, right = evidence(), evidence()
    assert left == right and left is not right
    assert left.spatial_projection.reference_frame is not right.spatial_projection.reference_frame
    result = assess_evidence_comparability(left, right)
    assert result.left is left and result.right is right
    reversed_result = assess_evidence_comparability(right, left)
    assert reversed_result.left is right and reversed_result.right is left
    assert result.spatial_status is SpatialStatus.COMPARABLE
    assert result.temporal_relationship is TemporalRelationship.OVERLAPPING


def test_commit19_synthetic_fixture_and_independent_classifications():
    camera = evidence("camera", frame="optical", seconds=2., mapped=False)
    radar = evidence(frame="radar-local", target="fixture:target", seconds=5., mapped=False)
    from aegis.fusion.clock_mapping import map_measurement_time
    c_mapping = BoundedClockMapping("source", "fixture:time", 1., 100., 0., 10., 0.25)
    r_mapping = BoundedClockMapping("source", "fixture:time", 1., 200., 0., 10., 0.25)
    camera = replace(camera, mapped_time=map_measurement_time(camera.source_observation.measurement_time, c_mapping))
    radar = replace(radar, mapped_time=map_measurement_time(radar.source_observation.measurement_time, r_mapping))
    assert (camera.spatial_projection.direction_x, camera.spatial_projection.direction_y,
            camera.spatial_projection.direction_z) == (0., 0., 1.)
    assert (radar.transformed_geometry.x_m, radar.transformed_geometry.y_m, radar.transformed_geometry.z_m) == (11., 2., 3.)
    assert (camera.mapped_time.lower_seconds, camera.mapped_time.upper_seconds) == (101.75, 102.25)
    assert (radar.mapped_time.lower_seconds, radar.mapped_time.upper_seconds) == (204.75, 205.25)
    result = assess_evidence_comparability(camera, radar)
    assert result.spatial_status is SpatialStatus.INCOMPARABLE
    assert result.spatial_reason is SpatialReason.INCOMPATIBLE_GEOMETRY_TYPES
    assert result.temporal_relationship is TemporalRelationship.DISJOINT
    # Spatial eligibility never changes with temporal relationship.
    assert assess_evidence_comparability(evidence(), evidence(seconds=5.)).spatial_status is SpatialStatus.COMPARABLE
    assert assess_evidence_comparability(evidence(spatial=False), evidence()).temporal_relationship is TemporalRelationship.OVERLAPPING


@pytest.mark.parametrize("field,values", [
    ("spatial_status", list(SpatialStatus)), ("spatial_reason", list(SpatialReason)),
    ("temporal_relationship", list(TemporalRelationship)), ("temporal_reason", list(TemporalReason)),
])
def test_direct_constructor_recomputes_every_classification(field, values):
    result = assess_evidence_comparability(evidence(), evidence())
    for value in values:
        if value is getattr(result, field):
            assert replace(result, **{field: value}) == result
        else:
            with pytest.raises(ValueError):
                replace(result, **{field: value})


@pytest.mark.parametrize("field", ["spatial_status", "spatial_reason", "temporal_relationship", "temporal_reason"])
@pytest.mark.parametrize("value", [None, "comparable", True, 1, SpatialReason.MISSING_SPATIAL_GEOMETRY])
def test_exact_enum_types_required(field, value):
    result = assess_evidence_comparability(evidence(), evidence())
    expected_error = ValueError if field == "spatial_reason" and isinstance(value, SpatialReason) else TypeError
    with pytest.raises(expected_error):
        replace(result, **{field: value})


@pytest.mark.parametrize("invalid", [None, 1, {}, object()])
@pytest.mark.parametrize("side", ["left", "right"])
def test_unsupported_inputs(invalid, side):
    good = evidence()
    args = (invalid, good) if side == "left" else (good, invalid)
    with pytest.raises(TypeError):
        assess_evidence_comparability(*args)
    result = assess_evidence_comparability(good, good)
    with pytest.raises(TypeError):
        replace(result, **{side: invalid})


def test_frozen_no_mutation_no_scores_and_deterministic():
    left, right = evidence(), evidence("camera")
    before = repr((left, right))
    result = assess_evidence_comparability(left, right)
    assert assess_evidence_comparability(left, right) == result
    assert repr((left, right)) == before
    assert {f.name for f in fields(result)} == {"left", "right", "spatial_status", "spatial_reason",
                                              "temporal_relationship", "temporal_reason"}
    for f in fields(result):
        with pytest.raises(FrozenInstanceError):
            setattr(result, f.name, None)


def test_fresh_import_without_dependencies_or_runtime_effects():
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys, time, random
baseline = set(sys.modules)
sys.path.insert(0, sys.argv[1])
from aegis.fusion.comparability import assess_evidence_comparability, SpatialStatus, TemporalReason
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.contracts import SensorObservation, MeasurementTime, ReferenceFrame
from aegis.radar.contracts import RadarPolarDetectionMeasurement
assert all(name in sys.stdlib_module_names or name == 'aegis'
           for name in {key.split('.')[0] for key in set(sys.modules) - baseline})
def forbidden(*args, **kwargs):
    raise AssertionError('clock/randomness/I/O')
time.time = time.time_ns = time.monotonic = time.monotonic_ns = forbidden
time.perf_counter = time.perf_counter_ns = time.sleep = random.random = forbidden
def audit(event, args):
    if event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.urandom')):
        forbidden()
sys.addaudithook(audit)
obs = SensorObservation('event','sensor',MeasurementTime(0,'clock'),ReferenceFrame('frame'),
                        RadarPolarDetectionMeasurement(10,0))
left, right = DerivedSensorEvidence(obs), DerivedSensorEvidence(obs)
r = assess_evidence_comparability(left,right)
assert r.left is left and r.right is right
assert r.spatial_status is SpatialStatus.INSUFFICIENT_INFORMATION
assert r.temporal_reason is TemporalReason.MISSING_MAPPED_TIME
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
