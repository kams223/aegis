"""Fixed software-only demonstration; no physical simulation or association."""

import argparse
import json
from pathlib import Path
import sys

from aegis.core.frames import FrameMetadata
from aegis.fusion.camera_adapter import tracked_objects_to_observations
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame
from aegis.fusion.derived_evidence import derive_camera_evidence, derive_radar_evidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.perception.contracts import ObjectDetection
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.radar.scripted_source import iter_scripted_radar_scans
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.spatial.transforms import RigidTransform
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch


def _scenario_data():
    image_frame = ReferenceFrame("fixture:camera:image")
    tracking = TrackedObjectBatch(
        FrameMetadata("fixture:opening", 51, 2., 640, 480),
        (TrackedObject(7, ObjectDetection(0, "fixture", .75, 10., 20., 30., 40.)),),
    )
    image_point = ImagePoint(320., 240., 640, 480, image_frame)
    intrinsics = PinholeCameraIntrinsics(
        100., 100., 320., 240., 640, 480, image_frame,
        ReferenceFrame("fixture:camera:optical"), "fixture:calibration",
    )
    radar_time = MeasurementTime(5., "fixture:radar")
    measurement = RadarPolarDetectionMeasurement(10., 0., 0.)
    transform = RigidTransform(
        ReferenceFrame("fixture:radar:local"), ReferenceFrame("fixture:target"),
        ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), (1., 2., 3.),
    )
    camera_mapping = BoundedClockMapping("fixture:camera", "fixture:time", 1., 100., 0., 10., .25)
    radar_mapping = BoundedClockMapping("fixture:radar", "fixture:time", 1., 200., 0., 10., .25)
    source_values = (tracking, image_point, intrinsics, radar_time, measurement,
                     transform, camera_mapping, radar_mapping)
    # Primitive snapshots check preservation without printing whole-object repr.
    before = json.dumps(source_values, default=lambda value: vars(value), sort_keys=True)
    camera_batch = tracked_objects_to_observations(
        tracking, sensor_id="fixture:camera-sensor", clock_domain="fixture:camera",
        reference_frame_id="fixture:camera:image",
    )
    scan, = iter_scripted_radar_scans(
        ((radar_time, (measurement,)),), source_session_id="fixture:session",
    )
    radar_batch = radar_detections_to_observations(
        scan.detections, sensor_id="fixture:radar-sensor", reference_frame_id="fixture:radar:local",
    )
    camera_observation, = camera_batch.observations
    radar_observation, = radar_batch.observations
    camera = derive_camera_evidence(
        camera_observation, image_point=image_point, intrinsics=intrinsics,
        clock_mapping=camera_mapping,
    )
    radar = derive_radar_evidence(
        radar_observation, spatial_transform=transform, clock_mapping=radar_mapping,
    )
    records = (radar, camera)  # Explicit caller order, not timestamp sorting.
    history = ObservationHistory(records)
    assert history.records is records
    assert history.records[0] is radar and history.records[1] is camera
    assert camera.source_observation is camera_observation
    assert radar.source_observation is radar_observation
    assert camera_observation.measurement is not tracking.objects[0].detection
    assert camera_observation.measurement.confidence == tracking.objects[0].detection.confidence
    assert scan.scan_time is scan.detections[0].measurement_time is radar_time
    assert radar_observation.measurement_time is radar_time
    assert scan.detections[0].measurement is radar_observation.measurement is measurement
    assert camera.spatial_projection.source_image_point is image_point
    assert camera.camera_intrinsics is intrinsics
    assert radar.spatial_projection.source_measurement is measurement
    assert radar.spatial_projection.reference_frame is radar_observation.reference_frame
    assert radar.spatial_transform is transform
    assert radar.transformed_geometry.source_point is radar.spatial_projection
    assert radar.transformed_geometry.reference_frame is transform.target_frame
    for evidence, mapping in ((camera, camera_mapping), (radar, radar_mapping)):
        assert evidence.mapped_time.source_time is evidence.source_observation.measurement_time
        assert evidence.mapped_time.source_mapping is mapping
    assert json.dumps(source_values, default=lambda value: vars(value), sort_keys=True) == before

    ray, point, transformed = camera.spatial_projection, radar.spatial_projection, radar.transformed_geometry
    direction = (ray.direction_x, ray.direction_y, ray.direction_z)
    radar_point = (point.x_m, point.y_m, point.z_m)
    transformed_point = (transformed.x_m, transformed.y_m, transformed.z_m)
    camera_interval = (camera.mapped_time.lower_seconds, camera.mapped_time.upper_seconds)
    radar_interval = (radar.mapped_time.lower_seconds, radar.mapped_time.upper_seconds)
    assert direction == (0., 0., 1.)
    assert radar_point == (10., 0., 0.)
    assert transformed_point == (11., 2., 3.)
    assert camera_interval == (101.75, 102.25)
    assert radar_interval == (204.75, 205.25)
    assert tuple(e.source_observation.measurement_time.seconds for e in records) == (5., 2.)
    rows = []
    for position, evidence in enumerate(history.records):
        source = evidence.source_observation
        rows.append({
            "position": position,
            "modality": "radar" if isinstance(source.measurement, RadarPolarDetectionMeasurement) else "camera",
            "sensor_id": source.sensor_id,
            "observation_id": source.observation_id,
            "source_local_id": source.source_local_id,
            "measurement_seconds": source.measurement_time.seconds,
            "clock_domain": source.measurement_time.clock_domain,
            "reference_frame_id": source.reference_frame.frame_id,
            "has_projection": evidence.spatial_projection is not None,
            "has_transformation": evidence.spatial_transform is not None,
            "has_mapped_time": evidence.mapped_time is not None,
        })
    inspection = {
        "camera_observation_count": len(camera_batch.observations),
        "radar_observation_count": len(radar_batch.observations),
        "evidence_count": len(records), "history_record_count": len(history.records),
        "records": rows, "camera_direction": direction, "radar_point_m": radar_point,
        "radar_transformed_point_m": transformed_point,
        "camera_mapped_interval_seconds": camera_interval,
        "radar_mapped_interval_seconds": radar_interval,
    }
    return history, inspection, (camera_batch, radar_batch)


def _scenario():
    """Keep the original two-value example helper compatible."""
    history, inspection, _ = _scenario_data()
    return history, inspection


def build_synthetic_scenario():
    """Return the fixed example with its actual source batches for inspection."""
    try:
        from synthetic_observation_analysis import SyntheticScenario
    except ModuleNotFoundError as error:
        if error.name != "synthetic_observation_analysis":
            raise
        from examples.synthetic_observation_analysis import SyntheticScenario

    history, inspection, batches = _scenario_data()
    return SyntheticScenario(
        "Fixed camera/radar software fixture", history,
        inspection["camera_observation_count"], inspection["radar_observation_count"], batches,
    )


def _selected_scenario(args, parser):
    try:
        from synthetic_observation_scenarios import load_scenario, ScenarioLoadError
        from synthetic_observation_validation import render_validation_report
        from synthetic_observation_inspector import render_synthetic_workspace_html
    except ModuleNotFoundError as error:
        if error.name not in ("synthetic_observation_scenarios", "synthetic_observation_validation",
                              "synthetic_observation_inspector"):
            raise
        from examples.synthetic_observation_scenarios import load_scenario, ScenarioLoadError
        from examples.synthetic_observation_validation import render_validation_report
        from examples.synthetic_observation_inspector import render_synthetic_workspace_html

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioLoadError as error:
        parser.error("scenario: " + str(error))
    if args.html:
        try:
            document = render_synthetic_workspace_html(scenario, replay=args.replay)
        except (ValueError, TypeError) as error:
            parser.error(str(error) + "; use --validate-json or --validate-html for invalid metadata")
        exit_code = 0
    else:
        # No built-in profile or independent reconstruction is inferred from a file.
        document, exit_code = render_validation_report(scenario, html=args.validate_html)
    print(document, end="")
    return exit_code if args.strict else 0


def main():
    if not __debug__:
        raise RuntimeError("Run without -O: this demonstration requires assertion checks")
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--scenario", metavar="PATH", help="load a local schema-v1 JSON synthetic scenario")
    parser.add_argument("--html", action="store_true", help="emit an offline HTML inspection report")
    parser.add_argument("--compare", action="store_true",
                        help="with --html, compare the fixed fixture with an explicit delivery variant")
    parser.add_argument("--replay", action="store_true",
                        help="with --html, include local delivery-order replay controls")
    validation_modes = parser.add_mutually_exclusive_group()
    validation_modes.add_argument("--validate-json", action="store_true", help="emit deterministic software validation JSON")
    validation_modes.add_argument("--validate-html", action="store_true", help="emit an offline validation dashboard")
    parser.add_argument("--strict", action="store_true", help="with validation: exit 0 passed, 1 failed, 2 not evaluated")
    # Preserve the existing runpy launcher, whose two bootstrap paths remain
    # in argv. Ordinary CLI arguments still receive strict argparse validation.
    bootstrap_paths = [str(Path(__file__).resolve().parents[1] / "src"),
                       str(Path(__file__).resolve())]
    argv = sys.argv[1:]
    if "-c" in sys.orig_argv and argv == bootstrap_paths:
        argv = []
    args = parser.parse_args(argv)
    if (args.validate_json or args.validate_html) and (args.html or args.compare or args.replay):
        parser.error("validation modes cannot be combined with --html, --compare or --replay")
    if args.strict and not (args.validate_json or args.validate_html):
        parser.error("--strict requires --validate-json or --validate-html")
    if args.compare and not args.html:
        parser.error("--compare requires --html")
    if args.replay and not args.html:
        parser.error("--replay requires --html")
    if args.scenario is not None:
        if args.compare:
            parser.error("--scenario cannot be combined with --compare; comparison is built-in-fixture-only")
        return _selected_scenario(args, parser)
    first, first_view = _scenario()
    second, second_view = _scenario()
    assert first == second and first_view == second_view
    assert first is not second and first.records is not second.records
    for left, right in zip(first.records, second.records, strict=True):
        assert left is not right
        assert left.source_observation is not right.source_observation
        assert left.source_observation.measurement is not right.source_observation.measurement
        assert left.source_observation.measurement_time is not right.source_observation.measurement_time
    if args.validate_json or args.validate_html:
        from synthetic_observation_validation import render_validation_report

        scenario, reference = build_synthetic_scenario(), build_synthetic_scenario()
        document, exit_code = render_validation_report(
            scenario, html=args.validate_html, reference=reference, builtin_expectations=True)
        print(document, end="")
        return exit_code if args.strict else 0
    if args.html:
        from synthetic_observation_inspector import render_observation_history_html

        from synthetic_observation_analysis import SyntheticScenario
        from aegis.fusion.derived_evidence import DerivedSensorEvidence

        scenario = build_synthetic_scenario()
        assert scenario.history == first
        comparison = None
        if args.compare:
            radar, camera = scenario.history.records
            comparison = SyntheticScenario(
                "Explicit reordered/repeated partial-evidence fixture",
                ObservationHistory((DerivedSensorEvidence(camera.source_observation), radar, radar)),
                scenario.camera_observation_count, scenario.radar_observation_count,
                scenario.source_batches,
            )
        document = render_observation_history_html(
            scenario.history, scenario_label=scenario.label,
            camera_observation_count=scenario.camera_observation_count,
            radar_observation_count=scenario.radar_observation_count,
            source_batches=scenario.source_batches, comparison=comparison, replay=args.replay,
        )
        print(document, end="")
        return
    print(json.dumps(first_view, indent=2, sort_keys=True, allow_nan=False))
    print("DETERMINISTIC SYNTHETIC DEMO: PASS")


if __name__ == "__main__":
    sys.exit(main())
