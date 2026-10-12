"""Closed schema-v1 local JSON fixtures for synthetic software inspection.

JSON chooses data, never Python classes or executable scenario code. Intentional
metadata overrides corrupt only newly owned fixture objects, after normal public
construction; they are diagnostic inputs, not valid production evidence.
"""

import json
from math import isfinite
from pathlib import Path

from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.clock_mapping import BoundedClockMapping
from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import DerivedSensorEvidence, derive_camera_evidence, derive_radar_evidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint, PinholeCameraIntrinsics
from aegis.spatial.transforms import RigidTransform

try:
    from synthetic_observation_analysis import SyntheticScenario
except ModuleNotFoundError as error:
    if error.name != "synthetic_observation_analysis":
        raise
    from examples.synthetic_observation_analysis import SyntheticScenario


MAX_BYTES = 1024 * 1024
MAX_ITEMS = 256


class ScenarioLoadError(ValueError):
    """Invalid local JSON/schema/contract input, distinct from diagnostic findings."""


def _object(value, required, optional, location):
    if type(value) is not dict:
        raise ScenarioLoadError(f"{location}: expected an object")
    missing = sorted(set(required) - value.keys())
    extra = sorted(value.keys() - set(required) - set(optional))
    if missing:
        raise ScenarioLoadError(f"{location}: missing fields: {', '.join(missing)}")
    if extra:
        raise ScenarioLoadError(f"{location}: unsupported fields: {', '.join(extra)}")
    return value


def _text(value, location, *, nonblank=True):
    if type(value) is not str or (nonblank and not value.strip()):
        raise ScenarioLoadError(f"{location}: expected {'nonblank ' if nonblank else ''}string")
    # Lone surrogates are legal JSON escapes but cannot form a UTF-8 report.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ScenarioLoadError(f"{location}: text must be valid UTF-8") from error
    return value


def _number(value, location):
    if type(value) not in (int, float):
        raise ScenarioLoadError(f"{location}: expected finite number, not bool")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ScenarioLoadError(f"{location}: number must be finite within float range")
    return value


def _integer(value, location, *, positive=False):
    if type(value) is not int or (positive and value <= 0):
        raise ScenarioLoadError(f"{location}: expected {'positive ' if positive else ''}integer")
    return value


def _array(value, location):
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise ScenarioLoadError(f"{location}: expected array with at most {MAX_ITEMS} entries")
    return value


def _vector(value, length, location):
    if type(value) is not list or len(value) != length:
        raise ScenarioLoadError(f"{location}: expected array of length {length}")
    return tuple(_number(item, f"{location}[{index}]") for index, item in enumerate(value))


def _measurement(value, kind, location):
    if kind == "radar":
        _object(value, ("range_m", "azimuth_rad"), ("elevation_rad", "radial_velocity_mps"), location)
        numbers = {name: None if item is None and name in ("elevation_rad", "radial_velocity_mps")
                   else _number(item, location + "." + name) for name, item in value.items()}
        return RadarPolarDetectionMeasurement(**numbers)
    names = ("class_id", "label", "confidence", "x1", "y1", "x2", "y2", "image_width", "image_height")
    _object(value, names, (), location)
    return ImageTrackMeasurement(
        _integer(value["class_id"], location + ".class_id"),
        _text(value["label"], location + ".label", nonblank=False),
        *(_number(value[name], location + "." + name) for name in ("confidence", "x1", "y1", "x2", "y2")),
        *(_integer(value[name], location + "." + name, positive=True) for name in ("image_width", "image_height")),
    )


def _derive(source, kind, value, location):
    if value is None:
        return DerivedSensorEvidence(source)
    allowed = ("clock_mapping", "transform", "project_spatial") if kind == "radar" else (
        "clock_mapping", "transform", "image_point", "intrinsics")
    _object(value, (), allowed, location)
    mapping = None
    if "clock_mapping" in value:
        item = value["clock_mapping"]
        names = ("source_clock_domain", "target_clock_domain", "scale", "offset_seconds",
                 "valid_from_source_seconds", "valid_until_source_seconds", "error_bound_seconds")
        _object(item, names, (), location + ".clock_mapping")
        mapping = BoundedClockMapping(*(_text(item[name], location + "." + name) if name.endswith("clock_domain")
                                        else _number(item[name], location + "." + name) for name in names))
    transform = None
    if "transform" in value:
        item = value["transform"]
        _object(item, ("source_frame", "target_frame", "rotation_target_from_source",
                       "translation_target_from_source_m"), (), location + ".transform")
        rows = item["rotation_target_from_source"]
        if type(rows) is not list or len(rows) != 3:
            raise ScenarioLoadError(location + ".transform: rotation requires three rows")
        transform = RigidTransform(ReferenceFrame(_text(item["source_frame"], location + ".source_frame")),
            ReferenceFrame(_text(item["target_frame"], location + ".target_frame")),
            tuple(_vector(row, 3, location + ".rotation") for row in rows),
            _vector(item["translation_target_from_source_m"], 3, location + ".translation"))
    if kind == "radar":
        project = value.get("project_spatial", False)
        if type(project) is not bool:
            raise ScenarioLoadError(location + ".project_spatial: expected boolean")
        return derive_radar_evidence(source, project_spatial=project, spatial_transform=transform, clock_mapping=mapping)
    point = intrinsics = None
    if ("image_point" in value) != ("intrinsics" in value):
        raise ScenarioLoadError(location + ": image_point and intrinsics must appear together")
    if "image_point" in value:
        width, height = source.measurement.image_width, source.measurement.image_height
        point = ImagePoint(*_vector(value["image_point"], 2, location + ".image_point"),
                           width, height, source.reference_frame)
        item = value["intrinsics"]
        names = ("fx_px", "fy_px", "cx_px", "cy_px", "optical_frame", "calibration_id")
        _object(item, names, (), location + ".intrinsics")
        intrinsics = PinholeCameraIntrinsics(*(_number(item[name], location + "." + name) for name in names[:4]),
            width, height, source.reference_frame,
            ReferenceFrame(_text(item["optical_frame"], location + ".optical_frame")),
            _text(item["calibration_id"], location + ".calibration_id"))
    return derive_camera_evidence(source, image_point=point, intrinsics=intrinsics,
                                  spatial_transform=transform, clock_mapping=mapping)


def _invalid_metadata(source, value, location):
    """Explicit, closed fault injection into loader-owned diagnostic fixtures only."""
    _object(value, (), ("measurement_time", "reference_frame", "clock_domain", "frame_id",
                       "sensor_id", "source_local_id"), location)
    if "measurement_time" in value and "clock_domain" in value:
        raise ScenarioLoadError(location + ": missing time conflicts with clock override")
    if "reference_frame" in value and "frame_id" in value:
        raise ScenarioLoadError(location + ": missing frame conflicts with frame ID override")
    for name, item in value.items():
        if name in ("measurement_time", "reference_frame"):
            if item is not None:
                raise ScenarioLoadError(location + "." + name + ": only null is supported")
            object.__setattr__(source, name, None)
        else:
            if type(item) is not str or item.strip():
                raise ScenarioLoadError(location + "." + name + ": only blank strings are supported")
            target = source.measurement_time if name == "clock_domain" else source.reference_frame if name == "frame_id" else source
            object.__setattr__(target, name, item)


def scenario_from_document(document) -> SyntheticScenario:
    """Construct one scenario without I/O or mutation of the JSON value tree.

    Each named source becomes one batch, including empty batches. Observation
    order within each source follows the observations array; history follows
    deliveries. No fixed-fixture validation expectations are inferred.
    """
    try:
        return _construct(document)
    except ScenarioLoadError:
        raise
    except (TypeError, ValueError, OverflowError) as error:
        raise ScenarioLoadError("observation contract: " + str(error)) from error


def _construct(document):
    _object(document, ("schema_version", "scenario_id", "description", "sources", "observations", "deliveries"), (), "scenario")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ScenarioLoadError("schema_version: only version 1 is supported")
    label = _text(document["scenario_id"], "scenario_id")
    _text(document["description"], "description")
    sources, batches, observations, counts = {}, {}, {}, {"camera": 0, "radar": 0}
    for index, item in enumerate(_array(document["sources"], "sources")):
        location = f"sources[{index}]"
        names = ("source_id", "kind", "sensor_id", "clock_domain", "reference_frame")
        _object(item, names, (), location)
        for name in names:
            _text(item[name], location + "." + name)
        key = item["source_id"]
        if key in sources:
            raise ScenarioLoadError(location + ": duplicate source_id")
        if any(s["sensor_id"] == item["sensor_id"] for s in sources.values()):
            raise ScenarioLoadError(location + ": duplicate sensor_id")
        if item["kind"] not in counts:
            raise ScenarioLoadError(location + ": unsupported sensor kind")
        sources[key], batches[key] = item, []
    for index, item in enumerate(_array(document["observations"], "observations")):
        location = f"observations[{index}]"
        _object(item, ("observation_id", "source_id", "measurement_seconds", "measurement"),
                ("source_local_id", "derivation", "metadata_overrides"), location)
        key = _text(item["observation_id"], location + ".observation_id")
        source_key = _text(item["source_id"], location + ".source_id")
        if key in observations:
            raise ScenarioLoadError(location + ": duplicate observation_id")
        if source_key not in sources:
            raise ScenarioLoadError(location + ": unresolved source_id")
        context = sources[source_key]
        local = item.get("source_local_id")
        if local is not None:
            _text(local, location + ".source_local_id")
        source = SensorObservation(key, context["sensor_id"],
            MeasurementTime(_number(item["measurement_seconds"], location + ".measurement_seconds"), context["clock_domain"]),
            ReferenceFrame(context["reference_frame"]),
            _measurement(item["measurement"], context["kind"], location + ".measurement"), local)
        if "derivation" in item and item["derivation"] is None:
            raise ScenarioLoadError(location + ".derivation: omit instead of supplying null")
        evidence = _derive(source, context["kind"], item.get("derivation"), location + ".derivation")
        if "metadata_overrides" in item:
            if "derivation" in item:
                raise ScenarioLoadError(location + ": metadata overrides cannot accompany derivations")
            _invalid_metadata(source, item["metadata_overrides"], location + ".metadata_overrides")
        observations[key] = evidence
        batches[source_key].append(source)
        counts[context["kind"]] += 1
    deliveries = []
    for index, key in enumerate(_array(document["deliveries"], "deliveries")):
        _text(key, f"deliveries[{index}]")
        if key not in observations:
            raise ScenarioLoadError(f"deliveries[{index}]: unresolved observation_id")
        deliveries.append(observations[key])
    return SyntheticScenario(label, ObservationHistory(tuple(deliveries)), counts["camera"], counts["radar"],
                             tuple(ObservationBatch(tuple(items)) for items in batches.values()))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioLoadError("JSON: duplicate object member: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ScenarioLoadError("JSON: non-finite numeric constant is unsupported")


def load_scenario(path) -> SyntheticScenario:
    """Read one bounded local UTF-8 JSON file once; never write or access networks."""
    try:
        with Path(path).open("rb") as stream:
            contents = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise ScenarioLoadError("unable to read local scenario file") from error
    if len(contents) > MAX_BYTES:
        raise ScenarioLoadError("scenario file exceeds 1 MiB limit")
    try:
        document = json.loads(contents.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except ScenarioLoadError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ScenarioLoadError("invalid UTF-8 JSON scenario") from error
    return scenario_from_document(document)
