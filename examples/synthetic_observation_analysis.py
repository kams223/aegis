"""Example-local analysis of explicitly supplied synthetic contracts.

No input loading, scenario discovery, association, sorting or derivation occurs.
Source collections and delivery occurrences remain separate inventories.
"""

from dataclasses import dataclass, fields, is_dataclass
from math import isfinite

from aegis.fusion.camera_adapter import ImageTrackMeasurement
from aegis.fusion.contracts import ObservationBatch, MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint


def modality(measurement):
    if type(measurement) is RadarPolarDetectionMeasurement:
        return "radar"
    if type(measurement) in (ImageTrackMeasurement, ImagePoint):
        return "camera"
    raise TypeError("unsupported observation measurement type")


@dataclass(frozen=True)
class SyntheticScenario:
    """Named history plus explicit source counts and optional source batches.

    None means source batches were not supplied; () means a supplied empty
    collection. Counts need not equal history length because delivery can repeat
    evidence or contain a subset. No observations are inferred from those counts.
    """

    label: str
    history: ObservationHistory
    camera_observation_count: int
    radar_observation_count: int
    source_batches: tuple[ObservationBatch, ...] | None = None

    def __post_init__(self):
        if not isinstance(self.label, str):
            raise TypeError("scenario label must be a string")
        if not self.label.strip():
            raise ValueError("scenario label must be nonblank")
        if not isinstance(self.history, ObservationHistory):
            raise TypeError("history must be ObservationHistory")
        counts = {"camera": self.camera_observation_count, "radar": self.radar_observation_count}
        for name, count in counts.items():
            if type(count) is not int:
                raise TypeError(f"{name}_observation_count must be an integer")
            if count < 0:
                raise ValueError(f"{name}_observation_count must be nonnegative")
        for evidence in self.history.records:
            kind = modality(evidence.source_observation.measurement)
            if counts[kind] == 0:
                raise ValueError(f"{kind} history requires a positive source observation count")
        if self.source_batches is not None:
            if not isinstance(self.source_batches, tuple):
                raise TypeError("source_batches must be a tuple or None")
            actual = {"camera": 0, "radar": 0}
            for batch in self.source_batches:
                if not isinstance(batch, ObservationBatch):
                    raise TypeError("source_batches must contain ObservationBatch values")
                for observation in batch.observations:
                    if not isinstance(observation, SensorObservation):
                        raise TypeError("source batches require SensorObservation values")
                    actual[modality(observation.measurement)] += 1
            if actual != counts:
                raise ValueError("source counts must match supplied source batches")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    location: str
    observation_id: str | None
    message: str


def _metadata_findings(source, location, *, derived=False):
    # These checks mirror explicit envelope/evidence invariants, without
    # recomputing geometry. This is not a complete contract revalidator.
    findings = []
    for name in ("observation_id", "sensor_id"):
        value = getattr(source, name)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding("Invalid", "invalid_identifier", location,
                                    source.observation_id, f"{name} must be a nonblank string."))
    time = source.measurement_time
    if not isinstance(time, MeasurementTime) or (derived and type(time.seconds) not in (int, float)):
        findings.append(Finding("Invalid", "invalid_time", location, source.observation_id,
                                "Derived evidence requires a finite measurement timestamp and clock domain."))
    else:
        finite = True
        if derived:
            try:
                finite = isfinite(time.seconds)
            except OverflowError:
                finite = False
        if not finite or not isinstance(time.clock_domain, str) or not time.clock_domain.strip():
            findings.append(Finding("Invalid", "invalid_time", location, source.observation_id,
                                    "Derived evidence requires finite seconds and a nonblank clock domain."))
    frame = source.reference_frame
    if not isinstance(frame, ReferenceFrame) or not isinstance(frame.frame_id, str) or not frame.frame_id.strip():
        findings.append(Finding("Invalid", "invalid_frame", location, source.observation_id,
                                "Derived evidence requires a nonblank reference frame."))
    if source.source_local_id is None:
        findings.append(Finding("Informational", "missing_local_id", location, source.observation_id,
                                "Source-local ID was not supplied; this does not imply lost evidence."))
    elif not isinstance(source.source_local_id, str) or not source.source_local_id.strip():
        findings.append(Finding("Invalid", "invalid_local_id", location, source.observation_id,
                                "A supplied source-local ID must be nonblank."))
    return findings


def diagnose_scenario(scenario: SyntheticScenario) -> tuple[Finding, ...]:
    """Explain known quality conditions in stable inventory/delivery order.

    Warning means review is useful, not invalidity or a reliability score.
    Invalid is reserved for checked existing public-contract invariants.
    Equal IDs are diagnostic evidence keys, never physical-object association.
    """
    if not isinstance(scenario, SyntheticScenario):
        raise TypeError("scenario must be SyntheticScenario")
    result = []
    if scenario.source_batches is None:
        result.append(Finding("Informational", "batches_unavailable", "scenario", None,
                              "Source batches were not supplied; empty batches cannot be inferred."))
    else:
        source_ids = {}
        for batch_index, batch in enumerate(scenario.source_batches):
            if not batch.observations:
                result.append(Finding("Informational", "empty_batch", f"batch {batch_index}", None,
                                      "Explicit source batch is empty; no acquisition timing is implied."))
            for index, source in enumerate(batch.observations):
                location = f"batch {batch_index}, observation {index}"
                result.extend(_metadata_findings(source, location))
                if source.observation_id in source_ids:
                    result.append(Finding("Warning", "repeated_source_id", location, source.observation_id,
                                          f"Observation ID also occurs at {source_ids[source.observation_id]}; no association inferred."))
                else:
                    source_ids[source.observation_id] = location
    if not scenario.history.records:
        result.append(Finding("Informational", "empty_history", "history", None,
                              "No delivery occurrences were supplied."))
    ids, identities, previous_times, domains = {}, {}, {}, {}
    for position, evidence in enumerate(scenario.history.records):
        source = evidence.source_observation
        location = f"history {position}"
        metadata_findings = _metadata_findings(source, location, derived=True)
        result.extend(metadata_findings)
        if source.observation_id in ids:
            result.append(Finding("Warning", "repeated_history_id", location, source.observation_id,
                                  f"Observation ID also occurs at history {ids[source.observation_id]}; IDs do not associate objects."))
        else:
            ids[source.observation_id] = position
        if id(evidence) in identities:
            result.append(Finding("Informational", "repeated_occurrence", location, source.observation_id,
                                  f"Same evidence reference as history {identities[id(evidence)]}; not an independent acquisition."))
        else:
            identities[id(evidence)] = position
        invalid_time = any(f.code == "invalid_time" for f in metadata_findings)
        if not invalid_time:
            time = source.measurement_time
            domain = time.clock_domain
            if domain not in domains:
                if domains:
                    result.append(Finding("Informational", "different_clock_domain", location, source.observation_id,
                                          "Additional raw clock domain requires explicit interpretation; clocks are not aligned."))
                domains[domain] = position
            previous = previous_times.get(domain)
            if previous is not None and time.seconds < previous[1]:
                result.append(Finding("Warning", "nonmonotonic_time", location, source.observation_id,
                                      f"Raw timestamp decreases from history {previous[0]} within clock {domain}; delivery remains valid."))
            previous_times[domain] = (position, time.seconds)
        for name in ("spatial_projection", "spatial_transform", "transformed_geometry", "mapped_time"):
            if getattr(evidence, name) is None:
                result.append(Finding("Informational", "missing_" + name, location, source.observation_id,
                                      f"{name} was not supplied or is unavailable; no derivation is inferred."))
        measurement = source.measurement
        if type(measurement) is RadarPolarDetectionMeasurement:
            for name in ("elevation_rad", "radial_velocity_mps"):
                if getattr(measurement, name) is None:
                    result.append(Finding("Informational", "missing_" + name, location, source.observation_id,
                                          f"Optional {name} is unavailable; zero is not inferred."))
    return tuple(result)


def _flatten(value, prefix):
    if is_dataclass(value):
        rows = []
        for field in fields(value):
            rows.extend(_flatten(getattr(value, field.name), prefix + "." + field.name))
        return rows
    if type(value) is tuple and value:
        rows = []
        for index, item in enumerate(value):
            rows.extend(_flatten(item, f"{prefix}[{index}]"))
        return rows
    if value is not None and type(value) not in (str, int, float, bool, tuple):
        raise TypeError("unsupported comparison value")
    return [(prefix, value)]


def occurrence_fields(history):
    """Snapshot public values and repeated-reference pattern, without IDs as keys."""
    previous = {}
    result = []
    for position, evidence in enumerate(history.records):
        row = {"measurement_type": type(evidence.source_observation.measurement).__name__}
        row.update(_flatten(evidence, "evidence"))
        row["same_evidence_as_position"] = previous.get(id(evidence))
        previous.setdefault(id(evidence), position)
        result.append(row)
    return tuple(result)


@dataclass(frozen=True)
class Difference:
    location: str
    field: str
    left: object
    right: object


def compare_scenarios(left: SyntheticScenario, right: SyntheticScenario) -> tuple[Difference, ...]:
    """Compare values at the same delivery position, never match objects by ID."""
    if not isinstance(left, SyntheticScenario) or not isinstance(right, SyntheticScenario):
        raise TypeError("comparison requires SyntheticScenario values")
    differences = []
    for field in ("label", "camera_observation_count", "radar_observation_count"):
        a, b = getattr(left, field), getattr(right, field)
        if a != b:
            differences.append(Difference("scenario", field, a, b))
    inventory_a = dict(_flatten(left.source_batches, "source_batches"))
    inventory_b = dict(_flatten(right.source_batches, "source_batches"))
    for field in dict.fromkeys((*inventory_a, *inventory_b)):
        left_value = inventory_a.get(field, "Not present")
        right_value = inventory_b.get(field, "Not present")
        if left_value != right_value:
            differences.append(Difference("source inventory", field, left_value, right_value))
    a, b = occurrence_fields(left.history), occurrence_fields(right.history)
    if len(a) != len(b):
        differences.append(Difference("scenario", "history_occurrence_count", len(a), len(b)))
    for position in range(max(len(a), len(b))):
        if position >= len(a) or position >= len(b):
            differences.append(Difference(f"history {position}", "occurrence",
                                          "Not present" if position >= len(a) else "Present",
                                          "Not present" if position >= len(b) else "Present"))
            continue
        keys = dict.fromkeys((*a[position], *b[position]))
        for field in keys:
            left_value = a[position].get(field, "Not applicable")
            right_value = b[position].get(field, "Not applicable")
            if left_value != right_value:
                differences.append(Difference(f"history {position}", field, left_value, right_value))
    return tuple(differences)
