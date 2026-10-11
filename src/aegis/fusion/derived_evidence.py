"""Independent derived evidence with explicit inputs and inspectable lineage.

No association, synchronization estimation, confidence generation, or pipeline
integration occurs. Pixel selection and calibration compatibility remain caller
assertions. Provenance starts at the normalized observation, not raw hardware.
"""

from dataclasses import dataclass
from math import isfinite

from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.clock_mapping import (
    BoundedClockMapping, MappedTimeInterval, map_measurement_time,
)
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import (
    CameraRay, ImagePoint, PinholeCameraIntrinsics, image_point_to_camera_ray,
)
from aegis.spatial.radar import RadarPoint, radar_measurement_to_point
from aegis.spatial.transforms import (
    RigidTransform, RotatedDirection, TransformedPoint,
    rotate_camera_direction, transform_radar_point,
)


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be nonblank")


def _finite(value: float, name: str) -> None:
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a built-in int or float, not bool")
    try:
        valid = isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be finite")


def _frame(value: ReferenceFrame) -> None:
    if not isinstance(value, ReferenceFrame):
        raise TypeError("reference frame must be ReferenceFrame")
    _identifier(value.frame_id, "frame_id")


def _observation(observation: SensorObservation) -> None:
    if not isinstance(observation, SensorObservation):
        raise TypeError("source_observation must be SensorObservation")
    # A closed set excludes arbitrary payloads and subclasses with mutable data.
    measurement = observation.measurement
    if type(measurement) not in (ImageTrackMeasurement, ImagePoint, RadarPolarDetectionMeasurement):
        raise TypeError("unsupported observation measurement type")
    for name in ("observation_id", "sensor_id"):
        _identifier(getattr(observation, name), name)
    if observation.source_local_id is not None:
        _identifier(observation.source_local_id, "source_local_id")
    if not isinstance(observation.measurement_time, MeasurementTime):
        raise TypeError("measurement_time must be MeasurementTime")
    _identifier(observation.measurement_time.clock_domain, "clock_domain")
    _finite(observation.measurement_time.seconds, "measurement_time.seconds")
    _frame(observation.reference_frame)
    if isinstance(measurement, (ImagePoint, ImageTrackMeasurement)):
        for name in ("image_width", "image_height"):
            value = getattr(measurement, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if isinstance(measurement, ImagePoint):
            _frame(measurement.image_frame)
            if measurement.image_frame != observation.reference_frame:
                raise ValueError("observation and image point frames must match")
        else:
            if type(measurement.class_id) is not int or not isinstance(measurement.label, str):
                raise TypeError("image class_id and label must be int and str")
            for name in ("confidence", "x1", "y1", "x2", "y2"):
                _finite(getattr(measurement, name), name)


def _optional(value, expected_type, name: str) -> None:
    if value is not None and not isinstance(value, expected_type):
        raise TypeError(f"{name} has unsupported type")


@dataclass(frozen=True)
class DerivedSensorEvidence:
    """One original observation and independent optional derivations.

All supplied objects are retained, without copying or replacing evidence.
Direct construction recomputes deterministic results and requires exact value
equality, plus identity for provenance links. No numerical repair occurs.
An absent projection does not imply absent detection or lost evidence.
Camera direction has no depth/origin relocation; radar range rate is not a
velocity vector. Temporal bounds remain conditional on caller assertions.
"""

    source_observation: SensorObservation
    spatial_projection: CameraRay | RadarPoint | None = None
    camera_intrinsics: PinholeCameraIntrinsics | None = None
    spatial_transform: RigidTransform | None = None
    transformed_geometry: RotatedDirection | TransformedPoint | None = None
    mapped_time: MappedTimeInterval | None = None

    def __post_init__(self) -> None:
        observation = self.source_observation
        _observation(observation)
        camera = isinstance(observation.measurement, (ImagePoint, ImageTrackMeasurement))
        _optional(self.spatial_projection, CameraRay if camera else RadarPoint, "spatial_projection")
        _optional(self.transformed_geometry, RotatedDirection if camera else TransformedPoint,
                  "transformed_geometry")
        _optional(self.camera_intrinsics, PinholeCameraIntrinsics, "camera_intrinsics")
        _optional(self.spatial_transform, RigidTransform, "spatial_transform")
        _optional(self.mapped_time, MappedTimeInterval, "mapped_time")
        projection = self.spatial_projection
        if camera:
            if (projection is None) != (self.camera_intrinsics is None):
                raise ValueError("camera ray and intrinsics must appear together")
            if projection is not None:
                point = projection.source_image_point
                intrinsics = self.camera_intrinsics
                _frame(point.image_frame)
                _frame(intrinsics.image_frame)
                _frame(intrinsics.optical_frame)
                _frame(projection.optical_frame)
                _identifier(intrinsics.calibration_id, "calibration_id")
                if isinstance(observation.measurement, ImagePoint) and point is not observation.measurement:
                    raise ValueError("selected point must be the original measurement")
                if point.image_frame != observation.reference_frame:
                    raise ValueError("selected point frame must match observation")
                for name in ("image_width", "image_height"):
                    if getattr(point, name) != getattr(observation.measurement, name):
                        raise ValueError("selected point dimensions must match observation")
                expected = image_point_to_camera_ray(point, intrinsics)
                if projection != expected:
                    raise ValueError("camera projection inconsistent with supplied inputs")
        else:
            if self.camera_intrinsics is not None:
                raise ValueError("radar evidence cannot contain camera intrinsics")
            if projection is not None:
                if projection.source_measurement is not observation.measurement:
                    raise ValueError("radar source measurement identity mismatch")
                if projection.reference_frame != observation.reference_frame:
                    raise ValueError("radar projection frame mismatch")
                expected = radar_measurement_to_point(
                    observation.measurement, reference_frame=observation.reference_frame,
                )
                if projection != expected:
                    raise ValueError("radar projection inconsistent with supplied inputs")
        if (self.spatial_transform is None) != (self.transformed_geometry is None):
            raise ValueError("transform and transformed geometry must appear together")
        if self.spatial_transform is not None:
            if projection is None:
                raise ValueError("transform requires a spatial projection")
            result = self.transformed_geometry
            source = result.source_ray if camera else result.source_point
            if source is not projection:
                raise ValueError("transformed source projection identity mismatch")
            expected = (rotate_camera_direction(projection, self.spatial_transform) if camera
                        else transform_radar_point(projection, self.spatial_transform))
            if result != expected:
                raise ValueError("transformed geometry inconsistent with supplied transform")
        if self.mapped_time is not None:
            if self.mapped_time.source_time is not observation.measurement_time:
                raise ValueError("mapped source timestamp identity mismatch")
            expected = map_measurement_time(observation.measurement_time, self.mapped_time.source_mapping)
            if self.mapped_time != expected:
                raise ValueError("mapped interval inconsistent with supplied mapping")


def derive_camera_evidence(
    observation: SensorObservation, *, image_point: ImagePoint | None = None,
    intrinsics: PinholeCameraIntrinsics | None = None,
    spatial_transform: RigidTransform | None = None,
    clock_mapping: BoundedClockMapping | None = None,
) -> DerivedSensorEvidence:
    """Derive only explicitly requested geometry/time; never select a bbox anchor.

For a track measurement, the selected point's relationship to that track is a
caller assertion. Finite out-of-bounds points remain permissible.
"""
    _observation(observation)
    if not isinstance(observation.measurement, (ImagePoint, ImageTrackMeasurement)):
        raise TypeError("camera helper requires camera observation")
    _optional(image_point, ImagePoint, "image_point")
    _optional(intrinsics, PinholeCameraIntrinsics, "intrinsics")
    _optional(spatial_transform, RigidTransform, "spatial_transform")
    _optional(clock_mapping, BoundedClockMapping, "clock_mapping")
    if (image_point is None) != (intrinsics is None):
        raise ValueError("image_point and intrinsics must appear together")
    projection = None if image_point is None else image_point_to_camera_ray(image_point, intrinsics)
    if spatial_transform is not None and projection is None:
        raise ValueError("transform requires explicit projection inputs")
    transformed = (None if spatial_transform is None
                   else rotate_camera_direction(projection, spatial_transform))
    mapped = None if clock_mapping is None else map_measurement_time(observation.measurement_time, clock_mapping)
    return DerivedSensorEvidence(observation, projection, intrinsics, spatial_transform, transformed, mapped)


def derive_radar_evidence(
    observation: SensorObservation, *, project_spatial: bool = True,
    spatial_transform: RigidTransform | None = None,
    clock_mapping: BoundedClockMapping | None = None,
) -> DerivedSensorEvidence:
    """Preserve partial polar evidence; missing elevation never becomes altitude."""
    _observation(observation)
    if not isinstance(observation.measurement, RadarPolarDetectionMeasurement):
        raise TypeError("radar helper requires radar observation")
    if type(project_spatial) is not bool:
        raise TypeError("project_spatial must be bool")
    _optional(spatial_transform, RigidTransform, "spatial_transform")
    _optional(clock_mapping, BoundedClockMapping, "clock_mapping")
    projection = (radar_measurement_to_point(observation.measurement,
                  reference_frame=observation.reference_frame) if project_spatial else None)
    if spatial_transform is not None and projection is None:
        raise ValueError("requested transform requires an available radar point")
    transformed = None if spatial_transform is None else transform_radar_point(projection, spatial_transform)
    mapped = None if clock_mapping is None else map_measurement_time(observation.measurement_time, clock_mapping)
    return DerivedSensorEvidence(observation, projection, None, spatial_transform, transformed, mapped)
