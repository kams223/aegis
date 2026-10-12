"""Reproducible software-check evidence; no sensor-performance evaluation."""

from dataclasses import asdict, replace
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.contracts import MeasurementTime, ObservationBatch, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from examples.synthetic_observation_analysis import SyntheticScenario
from examples.synthetic_observation_demo import build_synthetic_scenario
from examples.synthetic_observation_validation import (
    build_validation_manifest, render_validation_html, render_validation_json,
)

ROOT = Path(__file__).resolve().parents[1]


def checks(manifest):
    return {check["id"]: check["status"] for check in manifest["invariants"]}


def explicit():
    a = DerivedSensorEvidence(SensorObservation("reused-id", "radar", MeasurementTime(5., "a"),
        ReferenceFrame("local"), RadarPolarDetectionMeasurement(0., 0.)))
    b = DerivedSensorEvidence(replace(a.source_observation, measurement_time=MeasurementTime(2., "b")))
    c = DerivedSensorEvidence(replace(a.source_observation, measurement_time=MeasurementTime(1., "a")))
    batch = ObservationBatch(tuple(e.source_observation for e in (a, b, c)))
    return SyntheticScenario("Explicit", ObservationHistory((a, b, a, c)), 0, 3, (batch,))


def test_manifest_schema_builtin_values_and_independent_construction():
    scenario = build_synthetic_scenario()
    manifest = build_validation_manifest(scenario, reference=build_synthetic_scenario(), builtin_expectations=True)
    assert list(manifest) == ["schema_version", "scenario_label", "scope", "counts", "source_inventory",
                             "history_occurrences", "clock_domains", "diagnostics", "invariants",
                             "overall_validation", "unevaluated_capabilities"]
    assert manifest["schema_version"] == 1
    assert manifest["counts"] == {"camera_observations": 1, "radar_observations": 1,
        "source_observations": 2, "history_occurrences": 2, "repeated_reference_occurrences": 0}
    assert list(checks(manifest)) == ["source_inventory_counts", "history_source_references",
        "checked_metadata_contracts", "reconstruction_matches", "builtin_delivery", "builtin_geometry",
        "builtin_mapped_intervals"]
    assert set(checks(manifest).values()) == {"passed"}
    assert manifest["overall_validation"]["status"] == "passed"
    assert manifest["overall_validation"]["check_counts"] == {"passed": 7, "failed": 0, "not_evaluated": 0}
    assert manifest["diagnostics"]["severity_counts"] == {"Informational": 6, "Warning": 0, "Invalid": 0}
    rows = manifest["history_occurrences"]
    assert [(r["position"], r["modality"], r["measurement_seconds"], r["clock_domain"])
            for r in rows] == [(0, "radar", 5., "fixture:radar"), (1, "camera", 2., "fixture:camera")]
    assert rows[0]["sensor_id"] == "fixture:radar-sensor"
    assert rows[1]["observation_id"] == '["camera-track","fixture:camera-sensor","fixture:opening",51,7,0]'
    assert rows[0]["source_inventory_references"] == [{"batch_position": 1, "observation_position": 0}]
    assert rows[1]["source_inventory_references"] == [{"batch_position": 0, "observation_position": 0}]
    assert rows[0]["source_local_id"] is None
    assert manifest["clock_domains"]["raw"] == [
        {"clock_domain": "fixture:radar", "source_inventory_positions": [{"batch_position": 1, "observation_position": 0}], "history_positions": [0]},
        {"clock_domain": "fixture:camera", "source_inventory_positions": [{"batch_position": 0, "observation_position": 0}], "history_positions": [1]}]
    assert manifest["clock_domains"]["mapped"] == [{"clock_domain": "fixture:time", "history_positions": [0, 1]}]
    for check in manifest["invariants"]:
        assert list(check) == ["id", "status", "description", "details"]
    assert all(item["status"] == "not_evaluated" for item in manifest["unevaluated_capabilities"])


def test_missing_evaluation_is_never_success():
    scenario = replace(build_synthetic_scenario(), source_batches=None)
    manifest = build_validation_manifest(scenario)
    assert manifest["source_inventory"] == {"availability": "not_supplied", "batches": None}
    statuses = checks(manifest)
    assert statuses["source_inventory_counts"] == statuses["history_source_references"] == "not_evaluated"
    assert statuses["reconstruction_matches"] == statuses["builtin_geometry"] == "not_evaluated"
    assert manifest["overall_validation"]["status"] == "not_evaluated"
    assert all(row["source_inventory_references"] is None for row in manifest["history_occurrences"])


def test_repeated_reference_counts_warnings_domains_and_positions():
    manifest = build_validation_manifest(explicit(), reference=explicit())
    assert manifest["counts"]["source_observations"] == 3 and manifest["counts"]["history_occurrences"] == 4
    assert manifest["counts"]["repeated_reference_occurrences"] == 1
    assert [r["same_evidence_as_position"] for r in manifest["history_occurrences"]] == [None, None, 0, None]
    assert [r["measurement_seconds"] for r in manifest["history_occurrences"]] == [5., 2., 5., 1.]
    assert [(d["clock_domain"], d["history_positions"]) for d in manifest["clock_domains"]["raw"]] == [
        ("a", [0, 2, 3]), ("b", [1])]
    assert manifest["diagnostics"]["severity_counts"] == {"Informational": 33, "Warning": 6, "Invalid": 0}
    assert all(check["status"] != "failed" for check in manifest["invariants"])
    assert checks(manifest)["reconstruction_matches"] == "passed"
    assert any(f["code"] == "nonmonotonic_time" and f["location"] == "history 3"
               for f in manifest["diagnostics"]["findings"])


def test_empty_history_has_no_lineage_evidence():
    empty = SyntheticScenario("Empty", ObservationHistory(()), 0, 0, (ObservationBatch(()),))
    manifest = build_validation_manifest(empty)
    assert manifest["counts"] == {"camera_observations": 0, "radar_observations": 0,
                                  "source_observations": 0, "history_occurrences": 0, "repeated_reference_occurrences": 0}
    assert manifest["clock_domains"] == {"raw": [], "mapped": []}
    assert manifest["source_inventory"]["batches"] == [{"batch_position": 0, "observations": []}]
    assert checks(manifest)["source_inventory_counts"] == "passed"
    assert checks(manifest)["history_source_references"] == "not_evaluated"
    assert manifest["overall_validation"]["status"] == "not_evaluated"
    assert "No selected occurrence." in render_validation_html(empty)


def test_count_violation_and_identity_provenance_failure():
    scenario = build_synthetic_scenario()
    # Deliberately bypass frozen constructor guards to exercise a real invariant failure.
    object.__setattr__(scenario, "radar_observation_count", 2)
    manifest = build_validation_manifest(scenario)
    assert checks(manifest)["source_inventory_counts"] == "failed"
    assert manifest["overall_validation"]["status"] == "failed"
    assert "Inspection unavailable:" in render_validation_html(scenario)
    scenario = explicit()
    cloned_batch = ObservationBatch(tuple(replace(s) for s in scenario.source_batches[0].observations))
    manifest = build_validation_manifest(replace(scenario, source_batches=(cloned_batch,)))
    assert checks(manifest)["history_source_references"] == "failed"
    assert manifest["history_occurrences"][0]["source_inventory_references"] == []
    assert manifest["invariants"][1]["details"] == [
        "history 0: no identical source in inventory", "history 1: no identical source in inventory",
        "history 2: no identical source in inventory", "history 3: no identical source in inventory"]


def test_metadata_contract_failure_is_reported_in_json_and_html():
    scenario = explicit()
    object.__setattr__(scenario.history.records[0].source_observation, "sensor_id", " ")
    manifest = build_validation_manifest(scenario)
    assert checks(manifest)["checked_metadata_contracts"] == "failed"
    assert manifest["diagnostics"]["severity_counts"]["Invalid"] == 3
    assert json.loads(render_validation_json(scenario))["overall_validation"]["status"] == "failed"
    html = render_validation_html(scenario)
    assert "<dt>Validation status</dt><dd>failed</dd>" in html and "Inspection unavailable:" in html


def test_reconstruction_failure_and_reference_reuse():
    scenario = build_synthetic_scenario()
    reference = build_synthetic_scenario()
    reference = replace(reference, history=ObservationHistory(tuple(reversed(reference.history.records))))
    manifest = build_validation_manifest(scenario, reference=reference, builtin_expectations=True)
    assert checks(manifest)["reconstruction_matches"] == "failed"
    assert manifest["invariants"][3]["details"]
    assert manifest["overall_validation"]["status"] == "failed"
    assert checks(build_validation_manifest(scenario, reference=scenario))["reconstruction_matches"] == "failed"


def test_builtin_profile_failure_does_not_hide_inspection():
    scenario = build_synthetic_scenario()
    radar, camera = scenario.history.records
    scenario = replace(scenario, history=ObservationHistory((DerivedSensorEvidence(radar.source_observation), camera)))
    manifest = build_validation_manifest(scenario, builtin_expectations=True)
    assert checks(manifest)["builtin_delivery"] == "passed"
    assert checks(manifest)["builtin_geometry"] == checks(manifest)["builtin_mapped_intervals"] == "failed"
    html = render_validation_html(scenario, builtin_expectations=True)
    assert "<dt>Validation status</dt><dd>failed</dd>" in html
    assert "Deterministic replay" in html and "Observation timeline" in html


def test_source_only_nonfinite_timestamp_has_explicit_representation_status():
    source = SensorObservation("source", "radar", MeasurementTime(float("inf"), "source-clock"),
        ReferenceFrame("local"), RadarPolarDetectionMeasurement(0., 0.))
    scenario = SyntheticScenario("Source only", ObservationHistory(()), 0, 1, (ObservationBatch((source,)),))
    manifest = json.loads(render_validation_json(scenario))
    observation = manifest["source_inventory"]["batches"][0]["observations"][0]
    assert observation["measurement_seconds"] is None
    assert observation["measurement_seconds_status"] == "not_representable_as_finite_json_number"
    assert manifest["diagnostics"]["severity_counts"]["Invalid"] == 0


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.attrs = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)


def test_html_escaping_no_mutation_and_manifest_is_detached():
    scenario = explicit()
    hostile = '<script>"&\' π</script>'
    source = replace(scenario.history.records[0].source_observation, sensor_id=hostile,
                     observation_id=hostile, source_local_id=hostile,
                     measurement_time=MeasurementTime(0., hostile), reference_frame=ReferenceFrame(hostile))
    evidence = DerivedSensorEvidence(source)
    scenario = SyntheticScenario(hostile, ObservationHistory((evidence, evidence)), 0, 1, (ObservationBatch((source,)),))
    before, references = asdict(scenario), tuple(id(e) for e in scenario.history.records)
    manifest = build_validation_manifest(scenario)
    assert manifest == build_validation_manifest(scenario)
    json_text = render_validation_json(scenario)
    assert json.loads(json_text)["scenario_label"] == hostile
    html = render_validation_html(scenario)
    assert escape(hostile, quote=True) in html and hostile not in html
    parsed = Markup(html)
    assert "script" not in parsed.tags
    assert all(not name.startswith("on") and name not in ("src", "action") for name, _ in parsed.attrs)
    assert all(value.startswith("#replay-left-") for name, value in parsed.attrs if name == "href")
    assert asdict(scenario) == before and tuple(id(e) for e in scenario.history.records) == references
    manifest["history_occurrences"][0]["source_inventory_references"].clear()
    assert asdict(scenario) == before
    assert render_validation_html(scenario) == html
    assert render_validation_json(scenario) == json_text


@pytest.mark.parametrize("kwargs", [{"reference": ()}, {"builtin_expectations": "yes"}])
def test_argument_type_rejection(kwargs):
    with pytest.raises(TypeError):
        build_validation_manifest(explicit(), **kwargs)
    with pytest.raises(TypeError):
        build_validation_manifest(None)


def run_cli(tmp_path, *args, optimized=False):
    bootstrap = "import runpy,sys;sys.path[:0]=sys.argv[1:3];p=sys.argv[3];sys.argv=[p]+sys.argv[4:];runpy.run_path(p,run_name='__main__')"
    return subprocess.run([sys.executable, "-I", "-S", "-B"] + (["-O"] if optimized else []) +
        ["-c", bootstrap, str(ROOT / "src"), str(ROOT / "examples"),
         str(ROOT / "examples/synthetic_observation_demo.py"), *args],
        cwd=tmp_path, env={}, capture_output=True, timeout=20, check=False)


@pytest.mark.parametrize("mode", ["--validate-json", "--validate-html"])
def test_independent_offline_cli_bytes_and_limits(tmp_path, mode):
    first, second = run_cli(tmp_path, mode), run_cli(tmp_path, mode)
    assert first.returncode == second.returncode == 0 and first.stderr == second.stderr == b""
    assert first.stdout == second.stdout and b"PASS" not in first.stdout
    assert b"/mnt/" not in first.stdout and b"/home/" not in first.stdout
    if mode == "--validate-json":
        manifest = json.loads(first.stdout)
        assert manifest["overall_validation"]["status"] == "passed"
        assert b"pytest" not in first.stdout
    else:
        html = first.stdout.decode()
        assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>\n")
        assert "script" not in Markup(html).tags
        for heading in ("Checked invariants", "Diagnostic severity summary", "Source inventory",
                        "Clock-domain summary", "Deterministic replay", "Observation timeline", "Ordered history"):
            assert heading in html
        assert "do not validate a physical system" in html


@pytest.mark.parametrize("args", [
    ("--validate-json", "--validate-html"), ("--validate-json", "--html"),
    ("--validate-html", "--compare"), ("--validate-json", "--replay"),
    ("--validate-html", "--html", "--compare", "--replay"), ("--validate-json", "--unknown"),
])
def test_invalid_cli_combinations_emit_nothing(tmp_path, args):
    result = run_cli(tmp_path, *args)
    assert result.returncode != 0 and result.stdout == b""


@pytest.mark.parametrize("mode", ["--validate-json", "--validate-html"])
def test_optimized_execution_rejected_before_content(tmp_path, mode):
    result = run_cli(tmp_path, mode, optimized=True)
    assert result.returncode != 0 and result.stdout == b""
    assert b"Run without -O" in result.stderr


# Literal output hashes measured from the approved edc7900 baseline, independently
# executed before this feature. They protect every legacy CLI mode byte-for-byte.
@pytest.mark.parametrize("args, expected_hash", [
    ((), "d9caedddee1ae850fac263f1b457713441276df665035380c7791817b2f610d8"),
    (("--html",), "e2f5bdfe61c6ce40eba747879ef397672386c8c34b5d0f88b433edf362c39a4c"),
    (("--html", "--compare"), "ab4c5b5f1d011f8ba6fb143a9948f32218a3cfac293fd1487982e4f1f4bb2c59"),
    (("--html", "--replay"), "7859e6304c3a37e9fa700858e21b65e33c488b1df0b00913365141a72d3a92d2"),
    (("--html", "--compare", "--replay"), "0a4b4183bf120ad06e67df9e890d5e5aff66cca6374f7fd0beca1a2b7ada87ac"),
])
def test_all_legacy_cli_bytes(tmp_path, args, expected_hash):
    result = run_cli(tmp_path, *args)
    assert result.returncode == 0 and result.stderr == b""
    assert hashlib.sha256(result.stdout).hexdigest() == expected_hash


def test_generation_uses_no_runtime_io_network_clocks_or_randomness(tmp_path):
    script = """
import runpy, sys, time, random
sys.path[:0] = sys.argv[1:3]
demo = runpy.run_path(sys.argv[3])
validation = runpy.run_path(sys.argv[4])
def forbidden(*args, **kwargs):
    raise AssertionError('runtime I/O, clock, randomness or network access')
time.time = time.time_ns = time.monotonic = time.sleep = random.random = forbidden
def audit(event, args):
    if event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.urandom')):
        forbidden()
sys.addaudithook(audit)
scenario, reference = demo['build_synthetic_scenario'](), demo['build_synthetic_scenario']()
for name in ('render_validation_json', 'render_validation_html'):
    first = validation[name](scenario, reference=reference, builtin_expectations=True)
    second = validation[name](scenario, reference=reference, builtin_expectations=True)
    assert first == second
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script,
        str(ROOT / "src"), str(ROOT / "examples"), str(ROOT / "examples/synthetic_observation_demo.py"),
        str(ROOT / "examples/synthetic_observation_validation.py")],
        cwd=tmp_path, env={}, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""
