"""Closed local JSON scenarios, identity-preserving delivery and offline CLI."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examples import synthetic_observation_scenarios as loader
from examples.synthetic_observation_analysis import diagnose_scenario
from examples.synthetic_observation_demo import build_synthetic_scenario
from examples.synthetic_observation_inspector import render_synthetic_workspace_html
from examples.synthetic_observation_replay import ReplayState
from examples.synthetic_observation_validation import build_validation_manifest, render_validation_html, render_validation_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples/scenarios"


def document(name="baseline"):
    return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,status", [("baseline", "not_evaluated"),
    ("repeated_delivery", "not_evaluated"), ("metadata_edge_cases", "failed")])
def test_every_fixture_loads_deterministically_and_retains_manifest_contract(name, status):
    path = FIXTURES / (name + ".json")
    first, second = loader.load_scenario(path), loader.load_scenario(path)
    assert first == second and first is not second
    assert first.history is not second.history
    assert render_validation_json(first) == render_validation_json(second)
    assert render_validation_html(first) == render_validation_html(second)
    manifest = build_validation_manifest(first)
    assert manifest["schema_version"] == 1 and manifest["overall_validation"]["status"] == status
    assert [check["id"] for check in manifest["invariants"]] == [
        "source_inventory_counts", "history_source_references", "checked_metadata_contracts",
        "reconstruction_matches", "builtin_delivery", "builtin_geometry", "builtin_mapped_intervals"]
    for a, b in zip(first.history.records, second.history.records, strict=True):
        assert a is not b and a.source_observation is not b.source_observation


def test_baseline_matches_builtin_measurement_and_derivation_semantics():
    loaded = loader.load_scenario(FIXTURES / "baseline.json")
    builtin = build_synthetic_scenario()
    assert loaded.camera_observation_count == loaded.radar_observation_count == 1
    for a, b in zip(loaded.history.records, builtin.history.records, strict=True):
        assert a.source_observation.measurement == b.source_observation.measurement
        assert a.source_observation.measurement_time == b.source_observation.measurement_time
        assert a.source_observation.reference_frame == b.source_observation.reference_frame
        if a.spatial_projection is not None:
            for name in ("x_m", "y_m", "z_m", "direction_x", "direction_y", "direction_z"):
                assert getattr(a.spatial_projection, name, None) == getattr(b.spatial_projection, name, None)
        assert (a.mapped_time.lower_seconds, a.mapped_time.upper_seconds, a.mapped_time.clock_domain) == (
            b.mapped_time.lower_seconds, b.mapped_time.upper_seconds, b.mapped_time.clock_domain)
        assert a.mapped_time.source_time is a.source_observation.measurement_time
    radar, camera = loaded.history.records
    assert (radar.transformed_geometry.x_m, radar.transformed_geometry.y_m, radar.transformed_geometry.z_m) == (11., 2., 3.)
    assert radar.spatial_projection.source_measurement is radar.source_observation.measurement
    assert radar.transformed_geometry.source_point is radar.spatial_projection
    assert camera.spatial_projection.source_image_point.image_frame is camera.source_observation.reference_frame


def test_repeated_deliveries_identity_order_clocks_and_empty_batch():
    scenario = loader.load_scenario(FIXTURES / "repeated_delivery.json")
    rows = scenario.history.records
    assert [r.source_observation.observation_id for r in rows] == ["radar:0", "camera:0", "radar:0", "radar:1", "camera:0", "radar:1"]
    assert rows[0] is rows[2] and rows[1] is rows[4] and rows[3] is rows[5]
    assert [r.source_observation.measurement_time.seconds for r in rows] == [5., 2., 5., 1., 2., 1.]
    assert scenario.source_batches[2].observations == ()
    assert [s.observation_id for s in scenario.source_batches[1].observations] == ["radar:0", "radar:1"]
    assert rows[3].source_observation is scenario.source_batches[1].observations[1]
    findings = diagnose_scenario(scenario)
    assert any(f.code == "empty_batch" and f.location == "batch 2" for f in findings)
    assert any(f.code == "nonmonotonic_time" and f.location == "history 3" for f in findings)
    manifest = build_validation_manifest(scenario)
    assert manifest["counts"]["repeated_reference_occurrences"] == 3
    assert [(d["clock_domain"], d["history_positions"]) for d in manifest["clock_domains"]["raw"]] == [
        ("fixture:radar", [0, 2, 3, 5]), ("fixture:camera", [1, 4])]
    state = ReplayState(scenario.history).jump(2)
    assert state.current is rows[0] and state.step_backward().position == 1
    html = render_synthetic_workspace_html(scenario, replay=True)
    assert html.count('class="replay-state"') == 7
    assert 'id="replay-left-5"' in html and 'href="#replay-left-2"' in html


def test_intentional_faults_are_diagnostics_not_loading_errors():
    scenario = loader.load_scenario(FIXTURES / "metadata_edge_cases.json")
    first, second, repeat = scenario.history.records
    assert first is repeat and first.source_observation.measurement_time is None
    assert first.source_observation.reference_frame is None
    assert second.source_observation.measurement_time.clock_domain == ""
    assert second.source_observation.reference_frame.frame_id == ""
    assert second.source_observation.source_local_id == ""
    findings = diagnose_scenario(scenario)
    assert {f.code for f in findings if f.severity == "Invalid"} == {"invalid_time", "invalid_frame", "invalid_local_id"}
    manifest = json.loads(render_validation_json(scenario))
    assert manifest["overall_validation"]["status"] == "failed"
    assert manifest["history_occurrences"][0]["measurement_seconds"] is None
    assert "Inspection unavailable:" in render_validation_html(scenario)
    with pytest.raises(ValueError, match="public contract"):
        render_synthetic_workspace_html(scenario, replay=True)


def invalid(case):
    data = document()
    if case == "duplicate_source": data["sources"].append(deepcopy(data["sources"][0]))
    elif case == "duplicate_sensor": data["sources"][1]["sensor_id"] = data["sources"][0]["sensor_id"]
    elif case == "duplicate_observation": data["observations"].append(deepcopy(data["observations"][0]))
    elif case == "unresolved_source": data["observations"][0]["source_id"] = "unknown"
    elif case == "unresolved_delivery": data["deliveries"].append("unknown")
    elif case == "version": data["schema_version"] = 2
    elif case == "boolean_version": data["schema_version"] = True
    elif case == "kind": data["sources"][0]["kind"] = "unsupported"
    elif case == "array_type": data["sources"] = {}
    elif case == "object_type": data["observations"][0] = []
    elif case == "missing_time": del data["observations"][0]["measurement_seconds"]
    elif case == "implicit_missing_time": data["observations"][0]["measurement_seconds"] = None
    elif case == "missing_frame": del data["sources"][0]["reference_frame"]
    elif case == "unknown_field": data["extra"] = "ignored?"
    elif case == "boolean_number": data["observations"][0]["measurement_seconds"] = True
    elif case == "nonfinite": data["observations"][0]["measurement_seconds"] = float("inf")
    elif case == "negative_range": data["observations"][1]["measurement"]["range_m"] = -1.
    elif case == "dimensions": data["observations"][0]["measurement"]["image_width"] = 0
    elif case == "bad_transform": data["observations"][1]["derivation"]["transform"]["rotation_target_from_source"] = [[1, 0, 0]]
    elif case == "bad_mapping": data["observations"][0]["derivation"]["clock_mapping"]["source_clock_domain"] = "wrong"
    elif case == "unpaired_camera": del data["observations"][0]["derivation"]["intrinsics"]
    elif case == "override_with_derivation": data["observations"][0]["metadata_overrides"] = {"measurement_time": None}
    elif case == "opaque_override":
        del data["observations"][0]["derivation"]
        data["observations"][0]["metadata_overrides"] = {"measurement_time": {}}
    elif case == "override_conflict":
        del data["observations"][0]["derivation"]
        data["observations"][0]["metadata_overrides"] = {"measurement_time": None, "clock_domain": ""}
    elif case == "surrogate": data["scenario_id"] = chr(0xD800)
    elif case == "limit": data["deliveries"] = ["radar:0"] * (loader.MAX_ITEMS + 1)
    return data


@pytest.mark.parametrize("case", ["duplicate_source", "duplicate_sensor", "duplicate_observation",
    "unresolved_source", "unresolved_delivery", "version", "boolean_version", "kind", "array_type",
    "object_type", "missing_time", "implicit_missing_time", "missing_frame", "unknown_field",
    "boolean_number", "nonfinite", "negative_range", "dimensions", "bad_transform", "bad_mapping",
    "unpaired_camera", "override_with_derivation", "opaque_override", "override_conflict", "surrogate", "limit"])
def test_schema_failures_are_clear_deterministic_and_do_not_mutate_input(case):
    data = invalid(case)
    before = deepcopy(data)
    messages = []
    for _ in range(2):
        with pytest.raises(loader.ScenarioLoadError) as error:
            loader.scenario_from_document(data)
        messages.append(str(error.value))
    assert messages[0] == messages[1] and messages[0]
    assert data == before


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"schema_version":1,"schema_version":1}',
    b'{"number":NaN}', b'{"number":Infinity}', b'{"number":-Infinity}',
    b'{"number":1e309}', b'"\\xff"', b"1" * 5000, b"[" * 2000, b" " * (loader.MAX_BYTES + 1)])
def test_invalid_json_and_bounded_input(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(loader.ScenarioLoadError):
        loader.load_scenario(path)


def test_empty_sources_observations_and_history_are_supported():
    data = document()
    data["observations"], data["deliveries"] = [], []
    scenario = loader.scenario_from_document(data)
    assert scenario.camera_observation_count == scenario.radar_observation_count == 0
    assert all(batch.observations == () for batch in scenario.source_batches)
    assert scenario.history.records == ()
    assert build_validation_manifest(scenario)["overall_validation"]["status"] == "not_evaluated"
    data["sources"] = []
    assert loader.scenario_from_document(data).source_batches == ()


def test_camera_and_radar_zero_negative_timestamps_and_missing_optionals():
    data = document("repeated_delivery")
    data["observations"][2]["measurement_seconds"] = -1.
    scenario = loader.scenario_from_document(data)
    source = scenario.source_batches[1].observations[1]
    assert source.measurement_time.seconds == -1.
    assert source.measurement.range_m == 0. and source.measurement.elevation_rad is None
    assert scenario.history.records[3].spatial_projection is None


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def test_loaded_data_escaping_reports_and_nonmutation():
    data = document()
    hostile = '<script>"& Ω</script>'
    data["scenario_id"] = hostile
    data["observations"][0]["measurement"]["label"] = hostile
    original = deepcopy(data)
    scenario = loader.scenario_from_document(data)
    before = asdict(scenario)
    refs = scenario.history.records
    for renderer in (render_validation_html, lambda s: render_synthetic_workspace_html(s, replay=True)):
        first = renderer(scenario)
        assert first == renderer(scenario) and escape(hostile, quote=True) in first
        assert hostile not in first and "script" not in Markup(first).tags
    assert render_validation_json(scenario) == render_validation_json(scenario)
    assert data == original and asdict(scenario) == before and scenario.history.records is refs


def run_cli(tmp_path, *args, optimized=False):
    bootstrap = "import runpy,sys;sys.path[:0]=sys.argv[1:3];p=sys.argv[3];sys.argv=[p]+sys.argv[4:];runpy.run_path(p,run_name='__main__')"
    return subprocess.run([sys.executable, "-I", "-S", "-B"] + (["-O"] if optimized else []) +
        ["-c", bootstrap, str(ROOT / "src"), str(ROOT / "examples"),
         str(ROOT / "examples/synthetic_observation_demo.py"), *args],
        cwd=tmp_path, env={}, capture_output=True, timeout=30)


@pytest.mark.parametrize("name,args,code", [
    ("baseline", (), 0), ("baseline", ("--html",), 0),
    ("repeated_delivery", ("--html", "--replay"), 0),
    ("baseline", ("--validate-json",), 0), ("baseline", ("--validate-html",), 0),
    ("baseline", ("--validate-json", "--strict"), 2),
    ("baseline", ("--validate-html", "--strict"), 2),
    ("metadata_edge_cases", ("--validate-json", "--strict"), 1),
    ("metadata_edge_cases", ("--validate-html", "--strict"), 1),
    ("metadata_edge_cases", ("--validate-json",), 0),
])
def test_selected_cli_reports_are_complete_offline_and_deterministic(tmp_path, name, args, code):
    command = ("--scenario", str(FIXTURES / (name + ".json")), *args)
    first, second = run_cli(tmp_path, *command), run_cli(tmp_path, *command)
    assert first.returncode == second.returncode == code
    assert first.stderr == second.stderr == b"" and first.stdout == second.stdout
    assert b"PASS" not in first.stdout and b"/mnt/" not in first.stdout
    if "--html" in args or "--validate-html" in args:
        assert first.stdout.startswith(b"<!DOCTYPE html>") and first.stdout.endswith(b"</html>\n")
        assert "script" not in Markup(first.stdout.decode()).tags
    else:
        manifest = json.loads(first.stdout)
        assert manifest["overall_validation"]["status"] == ("failed" if name == "metadata_edge_cases" else "not_evaluated")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [("--scenario", "absent.json"),
    ("--scenario", "absent.json", "--html", "--compare"),
    ("--scenario", "absent.json", "--strict"),
    ("--scenario", "absent.json", "--validate-json", "--html")])
def test_selected_cli_errors_have_exit_two_and_no_stdout(tmp_path, args):
    result = run_cli(tmp_path, *args)
    assert result.returncode == 2 and result.stdout == b"" and b"error:" in result.stderr
    if "--compare" in args:
        assert b"comparison is built-in-fixture-only" in result.stderr
        assert b"unable to read" not in result.stderr


def test_malformed_file_and_invalid_inspection_fail_without_partial_output(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    result = run_cli(tmp_path, "--scenario", str(path), "--validate-json", "--strict")
    assert result.returncode == 2 and result.stdout == b"" and b"invalid UTF-8 JSON" in result.stderr
    result = run_cli(tmp_path, "--scenario", str(FIXTURES / "metadata_edge_cases.json"), "--html", "--replay")
    assert result.returncode == 2 and result.stdout == b"" and b"use --validate-json" in result.stderr
    result = run_cli(tmp_path, "--scenario", str(FIXTURES / "baseline.json"), "--validate-json", optimized=True)
    assert result.returncode != 0 and result.stdout == b"" and b"Run without -O" in result.stderr


def test_cli_selection_reads_once_and_skips_builtin_construction(monkeypatch, capsys):
    from examples import synthetic_observation_demo as demo
    calls = []
    original = loader.load_scenario
    def counted(path):
        calls.append(path)
        return original(path)
    def forbidden():
        raise AssertionError("selected input must not construct the unrelated built-in fixture")
    monkeypatch.setattr(loader, "load_scenario", counted)
    monkeypatch.setattr(demo, "_scenario", forbidden)
    path = str(FIXTURES / "baseline.json")
    monkeypatch.setattr(sys, "argv", ["demo", "--scenario", path, "--validate-json"])
    assert demo.main() == 0 and calls == [path]
    assert json.loads(capsys.readouterr().out)["scenario_label"] == "JSON baseline camera/radar fixture"


def test_loader_and_reports_have_no_writes_network_or_executable_input(tmp_path):
    script = """
import sys
sys.path[:0] = sys.argv[1:3]
from synthetic_observation_scenarios import load_scenario, scenario_from_document
from synthetic_observation_validation import render_validation_json, render_validation_html
from synthetic_observation_inspector import render_synthetic_workspace_html
import json
path = sys.argv[3]
def audit(event, args):
    if event == 'open':
        if args[0] != path or args[1] != 'r':
            raise AssertionError('unexpected I/O')
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.remove', 'os.rename', 'os.mkdir'):
        raise AssertionError('write/network/process operation')
sys.addaudithook(audit)
scenario = load_scenario(path)
render_validation_json(scenario)
render_validation_html(scenario)
render_synthetic_workspace_html(scenario, replay=True)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script,
        str(ROOT / "src"), str(ROOT / "examples"), str(FIXTURES / "baseline.json")],
        cwd=tmp_path, env={}, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"" and list(tmp_path.iterdir()) == []


# Independently captured before Phase 55 implementation.
CLI_BASELINES = [([], 'd9caedddee1ae850fac263f1b457713441276df665035380c7791817b2f610d8'), (['--html'], 'e2f5bdfe61c6ce40eba747879ef397672386c8c34b5d0f88b433edf362c39a4c'), (['--html', '--compare'], 'ab4c5b5f1d011f8ba6fb143a9948f32218a3cfac293fd1487982e4f1f4bb2c59'), (['--html', '--replay'], '7859e6304c3a37e9fa700858e21b65e33c488b1df0b00913365141a72d3a92d2'), (['--html', '--compare', '--replay'], '0a4b4183bf120ad06e67df9e890d5e5aff66cca6374f7fd0beca1a2b7ada87ac'), (['--validate-json'], 'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'), (['--validate-html'], 'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7'), (['--validate-json', '--strict'], 'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'), (['--validate-html', '--strict'], 'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7')]


@pytest.mark.parametrize("args,digest", CLI_BASELINES)
def test_no_scenario_cli_bytes_stderr_and_exit_match_baseline(tmp_path, args, digest):
    result = run_cli(tmp_path, *args)
    assert result.returncode == 0 and result.stderr == b""
    assert hashlib.sha256(result.stdout).hexdigest() == digest



def test_overflowing_json_number_in_supported_timestamp_field(tmp_path):
    text = json.dumps(document()).replace('"measurement_seconds": 2.0', '"measurement_seconds": 1e309', 1)
    path = tmp_path / "overflow.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(loader.ScenarioLoadError, match="finite"):
        loader.load_scenario(path)
