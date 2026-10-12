"""Synthetic workspace behavior, independently of production geometry math."""

from dataclasses import asdict, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from examples.synthetic_observation_analysis import (
    SyntheticScenario, compare_scenarios, diagnose_scenario,
)
from examples.synthetic_observation_demo import build_synthetic_scenario
from examples.synthetic_observation_inspector import render_synthetic_workspace_html


ROOT = Path(__file__).resolve().parents[1]


def radar(key, seconds, domain="clock:a", *, local=None):
    source = SensorObservation(key, "radar", MeasurementTime(seconds, domain),
                               ReferenceFrame("radar:local"),
                               RadarPolarDetectionMeasurement(1.0, 0.0), local)
    return DerivedSensorEvidence(source)


def scenario(records=(), *, label="Explicit fixture", inventory=None):
    sources = records if inventory is None else inventory
    batch = ObservationBatch(tuple(e.source_observation for e in sources))
    return SyntheticScenario(label, ObservationHistory(records), 0, len(sources), (batch,))


class Timeline(HTMLParser):
    """Inspect semantic list entries and safe SVG attributes, not whitespace."""

    def __init__(self, document):
        super().__init__()
        self.deliveries, self.lanes, self.tags, self.attrs = [], [], [], []
        self.active = None
        self.item = None
        self.text = None
        self.heading = ""
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)
        if tag == "h3":
            self.text = []
        elif tag == "ol":
            kind = dict(attrs).get("class")
            if kind == "delivery":
                self.active = []
                self.deliveries.append(self.active)
            elif kind == "clock-lane":
                self.active = []
                self.lanes.append((self.heading, self.active))
        elif tag == "li" and self.active is not None:
            self.item = {}
        elif tag in ("dt", "dd") and self.item is not None:
            self.text = []

    def handle_data(self, text):
        if self.text is not None:
            self.text.append(text)

    def handle_endtag(self, tag):
        if tag == "h3":
            self.heading = "".join(self.text)
            self.text = None
        elif tag == "dt" and self.item is not None:
            self.label = "".join(self.text)
            self.text = None
        elif tag == "dd" and self.item is not None:
            self.item[self.label] = "".join(self.text)
            self.text = None
        elif tag == "li" and self.item is not None:
            self.active.append(self.item)
            self.item = None
        elif tag == "ol":
            self.active = None


def test_fixed_scenario_uses_actual_sources_and_preserves_provenance():
    fixed = build_synthetic_scenario()
    camera_batch, radar_batch = fixed.source_batches
    assert fixed.camera_observation_count == fixed.radar_observation_count == 1
    assert fixed.history.records[0].source_observation is radar_batch.observations[0]
    assert fixed.history.records[1].source_observation is camera_batch.observations[0]
    assert not any(f.severity == "Invalid" for f in diagnose_scenario(fixed))
    assert compare_scenarios(fixed, build_synthetic_scenario()) == ()


def test_positional_comparison_exposes_order_and_optional_evidence():
    fixed = build_synthetic_scenario()
    radar_evidence, camera = fixed.history.records
    right = replace(fixed, label="Variant", history=ObservationHistory((
        DerivedSensorEvidence(camera.source_observation), radar_evidence, radar_evidence)))
    differences = compare_scenarios(fixed, right)
    assert any(d.location == "scenario" and d.field == "history_occurrence_count"
               and (d.left, d.right) == (2, 3) for d in differences)
    assert any(d.location == "history 0" and d.field == "evidence.source_observation.sensor_id"
               and (d.left, d.right) == ("fixture:radar-sensor", "fixture:camera-sensor")
               for d in differences)
    assert any(d.location == "history 0" and d.field == "evidence.mapped_time"
               and d.right is None for d in differences)
    assert any(d.location == "history 2" and d.field == "occurrence"
               and (d.left, d.right) == ("Not present", "Present") for d in differences)
    document = render_synthetic_workspace_html(fixed, right)
    assert 'class="comparison"' in document
    assert "Left scenario" in document and "Right scenario" in document
    assert "Matching IDs do not associate objects" in document
    parsed = Timeline(document)
    assert [[r["Modality"] for r in rows] for rows in parsed.deliveries] == [
        ["radar", "camera"], ["camera", "radar", "radar"]]


def test_comparison_matching_ids_still_exposes_metadata_changes():
    original = radar("same", 2.0)
    changed_source = replace(original.source_observation, sensor_id="different", source_local_id="local")
    left = scenario((original,))
    right = scenario((DerivedSensorEvidence(changed_source),))
    differences = compare_scenarios(left, right)
    assert any(d.field == "evidence.source_observation.sensor_id" and d.right == "different"
               for d in differences)
    assert any(d.field == "evidence.source_observation.source_local_id" and d.left is None
               and d.right == "local" for d in differences)


def test_source_inventory_comparison_without_deliveries():
    a, b = radar("source:a", 1.0), radar("source:b", 1.0)
    left, right = scenario((), inventory=(a,)), scenario((), inventory=(b,))
    differences = compare_scenarios(left, right)
    assert any(d.location == "source inventory" and d.field.endswith("observation_id")
               and (d.left, d.right) == ("source:a", "source:b") for d in differences)


def test_repeated_reference_pattern_is_compared_without_memory_addresses():
    a = radar("same", 1.0)
    distinct = DerivedSensorEvidence(a.source_observation)
    left = scenario((a, a), inventory=(a,))
    right = scenario((a, distinct), inventory=(a,))
    differences = compare_scenarios(left, right)
    assert [(d.location, d.field, d.left, d.right) for d in differences] == [
        ("history 1", "same_evidence_as_position", 0, None)]


def test_timeline_preserves_delivery_and_separates_raw_domains():
    a, b, c = radar("a", 5.0), radar("b", 2.0, "clock:b"), radar("c", 1.0)
    value = scenario((a, b, c, a), inventory=(a, b, c))
    parsed = Timeline(render_synthetic_workspace_html(value))
    assert [r["History position"] for r in parsed.deliveries[0]] == ["0", "1", "2", "3"]
    assert [r["Raw timestamp (s)"] for r in parsed.deliveries[0]] == ["5.0", "2.0", "1.0", "5.0"]
    assert [heading for heading, _ in parsed.lanes] == [
        "Raw timestamp clock: clock:a", "Raw timestamp clock: clock:b"]
    assert [r["History position"] for r in parsed.lanes[0][1]] == ["0", "2", "3"]
    assert [r["Raw timestamp (s)"] for r in parsed.lanes[0][1]] == ["5.0", "1.0", "5.0"]
    assert [r["Observation ID"] for r in parsed.lanes[1][1]] == ["b"]


def test_mapped_intervals_have_separate_conditional_target_lane():
    fixed = build_synthetic_scenario()
    parsed = Timeline(render_synthetic_workspace_html(fixed))
    assert [heading for heading, _ in parsed.lanes] == [
        "Raw timestamp clock: fixture:radar", "Raw timestamp clock: fixture:camera",
        "Mapped interval clock: fixture:time"]
    mapped = parsed.lanes[2][1]
    assert [r["Mapped interval (target s)"] for r in mapped] == [
        "(204.75, 205.25)", "(101.75, 102.25)"]
    assert [r["History position"] for r in mapped] == ["0", "1"]


def test_visual_scaling_handles_negative_and_extreme_finite_times():
    value = scenario((radar("min", -1e308), radar("max", 1e308)))
    parsed = Timeline(render_synthetic_workspace_html(value))
    coordinates = [float(v) for name, v in parsed.attrs if name == "cx"]
    assert coordinates == [10.0, 10.0, 310.0, 310.0]
    single = Timeline(render_synthetic_workspace_html(scenario((radar("zero", 0.0),))))
    assert [v for name, v in single.attrs if name == "cx"] == ["160.000", "160.000"]


def test_diagnostics_classifications_and_exact_occurrence_locations():
    a, b, c = radar("a", 5.0), radar("b", 2.0, "clock:b"), radar("c", 1.0)
    value = scenario((a, b, c, a), inventory=(a, b, c))
    findings = diagnose_scenario(value)
    warnings = [(f.code, f.location, f.observation_id) for f in findings if f.severity == "Warning"]
    assert warnings == [("nonmonotonic_time", "history 2", "c"),
                        ("repeated_history_id", "history 3", "a")]
    repeated = [f for f in findings if f.code == "repeated_occurrence"]
    assert len(repeated) == 1 and repeated[0].location == "history 3"
    assert repeated[0].severity == "Informational" and "history 0" in repeated[0].message
    assert "not an independent acquisition" in repeated[0].message
    domain = [f for f in findings if f.code == "different_clock_domain"]
    assert len(domain) == 1 and domain[0].location == "history 1"
    assert not any(f.severity == "Invalid" for f in findings)


def test_repeated_source_id_is_not_a_repeated_history_reference():
    a, b = radar("same", 1.0), radar("same", 1.0)
    findings = diagnose_scenario(scenario((a, b)))
    repeated = [f for f in findings if f.code == "repeated_source_id"]
    assert len(repeated) == 1 and repeated[0].location == "batch 0, observation 1"
    assert repeated[0].severity == "Warning"
    assert not any(f.code in ("nonmonotonic_time", "repeated_occurrence") for f in findings)


def test_empty_batches_and_absent_inventory_remain_distinct():
    empty = SyntheticScenario("Empty", ObservationHistory(()), 0, 0,
                              (ObservationBatch(()), ObservationBatch(())))
    findings = diagnose_scenario(empty)
    assert [(f.code, f.location) for f in findings] == [
        ("empty_batch", "batch 0"), ("empty_batch", "batch 1"), ("empty_history", "history")]
    assert all(f.severity == "Informational" for f in findings)
    document = render_synthetic_workspace_html(empty)
    assert "No delivery occurrences." in document
    assert not Timeline(document).deliveries[0]
    unavailable = replace(empty, source_batches=None)
    assert [f.code for f in diagnose_scenario(unavailable)] == ["batches_unavailable", "empty_history"]
    assert compare_scenarios(empty, unavailable)


def test_optional_absence_and_zero_are_informational():
    value = scenario((radar("zero", 0.0),))
    findings = diagnose_scenario(value)
    codes = {f.code for f in findings}
    assert {"missing_local_id", "missing_spatial_projection", "missing_spatial_transform",
            "missing_transformed_geometry", "missing_mapped_time", "missing_elevation_rad",
            "missing_radial_velocity_mps"} <= codes
    assert all(f.severity == "Informational" for f in findings)
    parsed = Timeline(render_synthetic_workspace_html(value))
    assert parsed.deliveries[0][0]["Raw timestamp (s)"] == "0.0"
    assert parsed.deliveries[0][0]["Mapped interval (target s)"] == "Unavailable (not supplied)"


def test_invalid_requires_actual_existing_contract_violation():
    record = radar("bad", 1.0)
    value = scenario((record,))
    # Simulate corruption after valid construction; no new missing-time contract.
    object.__setattr__(record.source_observation.measurement_time, "seconds", None)
    findings = diagnose_scenario(value)
    invalid = [f for f in findings if f.severity == "Invalid"]
    assert [(f.code, f.location) for f in invalid] == [("invalid_time", "history 0")]
    with pytest.raises(ValueError, match="public contract"):
        render_synthetic_workspace_html(value)
    with pytest.raises(TypeError):
        DerivedSensorEvidence(record.source_observation)


def test_raw_source_timestamp_is_not_given_stricter_evidence_rules():
    source = radar("source", 1.0).source_observation
    source = replace(source, measurement_time=MeasurementTime(float("inf"), "clock"))
    value = SyntheticScenario("Source only", ObservationHistory(()), 0, 1,
                              (ObservationBatch((source,)),))
    assert not any(f.severity == "Invalid" for f in diagnose_scenario(value))


def test_escaping_in_comparison_diagnostics_and_timeline():
    text = '<script src="https://invalid/">& \'quoted\' Ω</script>'
    a = radar(text, 0.0, text)
    value = scenario((a, a), label=text, inventory=(a,))
    other = replace(value, label=text + " right")
    document = render_synthetic_workspace_html(value, other)
    assert escape(text, quote=True) in document
    parsed = Timeline(document)
    assert [row["Observation ID"] for row in parsed.deliveries[0]] == [text, text]
    assert "script" not in parsed.tags
    assert not set(parsed.tags) & {"link", "img", "iframe", "object", "embed"}
    assert not any(name in ("src", "href", "id") or name.startswith("on") for name, _ in parsed.attrs)
    assert "url(" not in document and "@import" not in document


def test_all_analysis_and_rendering_preserve_values_and_identity():
    left = build_synthetic_scenario()
    right = replace(left, history=ObservationHistory((left.history.records[1], left.history.records[0],
                                                     left.history.records[0])))
    before = asdict(left), asdict(right)
    records, batches = left.history.records, left.source_batches
    references = tuple((e.source_observation, e.spatial_projection, e.mapped_time,
                        None if e.mapped_time is None else e.mapped_time.source_mapping) for e in records)
    diagnose_scenario(left)
    compare_scenarios(left, right)
    assert render_synthetic_workspace_html(left, right) == render_synthetic_workspace_html(left, right)
    assert (asdict(left), asdict(right)) == before
    assert left.history.records is records and left.source_batches is batches
    for e, refs in zip(records, references, strict=True):
        current = (e.source_observation, e.spatial_projection, e.mapped_time, e.mapped_time.source_mapping)
        assert all(a is b for a, b in zip(current, refs, strict=True))


@pytest.mark.parametrize("change,error", [
    ({"label": " "}, ValueError), ({"history": ()}, TypeError),
    ({"radar_observation_count": True}, TypeError),
    ({"radar_observation_count": -1}, ValueError),
    ({"radar_observation_count": 0}, ValueError),
    ({"source_batches": []}, TypeError),
    ({"source_batches": (object(),)}, TypeError),
    ({"source_batches": ()}, ValueError),
])
def test_inconsistent_scenario_arguments_rejected(change, error):
    with pytest.raises(error):
        replace(scenario((radar("a", 1.0),)), **change)


def subprocess_command(*args, optimized=False):
    bootstrap = ("import runpy, sys; src, examples, script = sys.argv[1:4]; "
                 "sys.path[:0] = [src, examples]; sys.argv = [script] + sys.argv[4:]; "
                 "runpy.run_path(script, run_name='__main__')")
    return [sys.executable, "-I", "-S", "-B", *(["-O"] if optimized else []),
            "-c", bootstrap, str(ROOT / "src"), str(ROOT / "examples"),
            str(ROOT / "examples/synthetic_observation_demo.py"), *args]


@pytest.mark.parametrize("comparison", [False, True])
def test_isolated_offline_cli_is_deterministic(tmp_path, comparison):
    args = ["--html", *(["--compare"] if comparison else [])]
    runs = [subprocess.run(subprocess_command(*args), cwd=tmp_path, env={}, capture_output=True,
                           timeout=30, check=True) for _ in range(2)]
    assert runs[0].stdout == runs[1].stdout
    assert runs[0].stderr == runs[1].stderr == b""
    document = runs[0].stdout.decode("utf-8")
    assert document.startswith("<!DOCTYPE html>\n") and document.endswith("</body></html>\n")
    assert "DETERMINISTIC SYNTHETIC DEMO: PASS" not in document
    parsed = Timeline(document)
    assert len(parsed.deliveries) == (2 if comparison else 1)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args,optimized,message", [
    (("--compare",), False, b"--compare requires --html"),
    (("--html", "--compare", "--unknown"), False, b"unrecognized arguments"),
    (("--html", "--compare"), True, b"Run without -O"),
])
def test_new_cli_errors_emit_no_partial_html(tmp_path, args, optimized, message):
    run = subprocess.run(subprocess_command(*args, optimized=optimized), cwd=tmp_path, env={},
                         capture_output=True, timeout=30)
    assert run.returncode != 0 and run.stdout == b""
    assert message in run.stderr
