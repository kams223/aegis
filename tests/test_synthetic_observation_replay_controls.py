"""Replay cursors and static browser navigation, without browser dependencies."""

from dataclasses import FrozenInstanceError, asdict, replace
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
from examples.synthetic_observation_analysis import SyntheticScenario
from examples.synthetic_observation_demo import build_synthetic_scenario
from examples.synthetic_observation_inspector import render_replay_state_html, render_synthetic_workspace_html
from examples.synthetic_observation_replay import ReplayState

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    first = DerivedSensorEvidence(SensorObservation(
        "same", "radar", MeasurementTime(5., "clock:a"), ReferenceFrame("local"),
        RadarPolarDetectionMeasurement(0., 0.)))
    second = DerivedSensorEvidence(replace(first.source_observation,
        measurement_time=MeasurementTime(2., "clock:b")))
    third = DerivedSensorEvidence(replace(first.source_observation,
        measurement_time=MeasurementTime(1., "clock:a")))
    history = ObservationHistory((first, second, first, third))
    batch = ObservationBatch(tuple(e.source_observation for e in (first, second, third)))
    return SyntheticScenario("Replay fixture", history, 0, 3, (batch,))


class Markup(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.ids, self.cards, self.links, self.tags, self.attributes = [], {}, [], [], []
        self.card = None
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "article":
            self.card = attrs["id"]
            self.cards[self.card] = []
        if tag == "a":
            self.links.append((self.card, attrs["href"]))

    def handle_data(self, data):
        if self.card is not None:
            self.cards[self.card].append(data)

    def handle_endtag(self, tag):
        if tag == "article":
            self.card = None


def test_empty_and_single_boundaries():
    empty = ReplayState(ObservationHistory(()))
    assert empty.current is None and empty.total_count == 0
    assert empty.visited_prefix == empty.previous_occurrences == empty.future_occurrences == ()
    assert empty.step_forward() is empty and empty.step_backward() is empty and empty.reset() is empty
    with pytest.raises(IndexError):
        empty.jump(0)
    single = ReplayState(ObservationHistory((fixture().history.records[0],)))
    selected = single.step_forward()
    assert selected.position == 0 and selected.current is single.history.records[0]
    assert selected.step_forward() is selected
    assert selected.step_backward() == single
    assert selected.reset() == single
    assert selected.visited_prefix == single.history.records
    assert selected.previous_occurrences == selected.future_occurrences == ()


def test_step_jump_reset_prefix_and_identity():
    scenario = fixture()
    initial = ReplayState(scenario.history)
    cursor = initial
    for index, evidence in enumerate(scenario.history.records):
        cursor = cursor.step_forward()
        assert cursor.position == index and cursor.current is evidence
        assert cursor.visited_prefix == scenario.history.records[:index + 1]
        assert cursor.previous_occurrences == scenario.history.records[:index]
        assert cursor.future_occurrences == scenario.history.records[index + 1:]
    assert cursor.step_forward() is cursor
    assert initial.jump(2).current is initial.jump(0).current
    assert initial.jump(2).position != initial.jump(0).position
    assert cursor.step_backward().position == 2
    assert initial.jump(0).step_backward() == initial
    assert cursor.reset() == initial and initial.position is None
    assert [ReplayState(scenario.history, i).current.source_observation.measurement_time.seconds
            for i in range(4)] == [5., 2., 5., 1.]
    assert [e.source_observation.measurement_time.clock_domain for e in cursor.visited_prefix] == [
        "clock:a", "clock:b", "clock:a", "clock:a"]
    with pytest.raises(FrozenInstanceError):
        cursor.position = 0


@pytest.mark.parametrize("position", [-1, 4, 100])
def test_invalid_indices(position):
    state = ReplayState(fixture().history)
    with pytest.raises(IndexError):
        state.jump(position)
    with pytest.raises(IndexError):
        ReplayState(state.history, position)


@pytest.mark.parametrize("position", [True, 1., "1", ()])
def test_invalid_position_types(position):
    state = ReplayState(fixture().history)
    with pytest.raises(TypeError):
        state.jump(position)
    with pytest.raises(TypeError):
        ReplayState(state.history, position)


def test_invalid_history_and_state_pairing():
    with pytest.raises(TypeError):
        ReplayState(())
    scenario = fixture()
    with pytest.raises(ValueError):
        render_replay_state_html(scenario, ReplayState(ObservationHistory(scenario.history.records)))
    with pytest.raises(TypeError):
        render_replay_state_html(scenario, None)
    with pytest.raises(ValueError):
        render_replay_state_html(scenario, ReplayState(scenario.history), scope="<bad>")
    with pytest.raises(TypeError):
        render_synthetic_workspace_html(scenario, replay="yes")


def test_exact_selected_fixture_metadata_and_provenance():
    scenario = build_synthetic_scenario()
    card = render_replay_state_html(scenario, ReplayState(scenario.history, 0))
    for text in ("fixture:radar-sensor", "fixture:radar:local", "fixture:radar",
                 "204.75", "205.25", "fixture:time", "10.0", "batch 1, observation 0",
                 "Original radar measurement retained by reference"):
        assert text in card
    camera = render_replay_state_html(scenario, ReplayState(scenario.history, 1))
    for text in ("fixture:camera-sensor", "fixture:camera:image", "fixture:calibration",
                 "101.75", "102.25", "batch 0, observation 0", "320.0", "240.0"):
        assert text in camera
    camera_id = '["camera-track","fixture:camera-sensor","fixture:opening",51,7,0]'
    radar_id = ('["radar-detection",1,"fixture:radar-sensor","fixture:session",'
                r'"[\"scripted-radar-detection\",1,\"0\",0]"]')
    assert "<dt>Observation ID</dt><dd>" + escape(radar_id, quote=True) + "</dd>" in card
    assert "<dt>Observation ID</dt><dd>" + escape(camera_id, quote=True) + "</dd>" in camera
    assert '<dt>Source-local ID</dt><dd>[&quot;fixture:opening&quot;,7]</dd>' in camera
    assert "<details>" in card and "<details>" in camera


def test_diagnostics_relevance_missing_values_and_zero():
    scenario = fixture()
    repeated = render_replay_state_html(scenario, ReplayState(scenario.history, 2))
    assert "repeated_occurrence" in repeated and "history 2" in repeated
    assert "nonmonotonic_time" not in repeated
    backwards = render_replay_state_html(scenario, ReplayState(scenario.history, 3))
    assert "nonmonotonic_time" in backwards and "history 3" in backwards
    assert "repeated_occurrence" not in backwards
    assert "Unavailable (not supplied)" in backwards
    assert "<dt>Range (m)</dt><dd>0.0</dd>" in backwards
    assert "Previously visited occurrences" in backwards and "Future occurrences" in backwards
    initial = render_replay_state_html(scenario, ReplayState(scenario.history))
    assert "No selected occurrence." in initial
    assert "<dt>Visited prefix count</dt><dd>0</dd>" in initial


def test_inventory_uses_identity_not_matching_ids():
    scenario = fixture()
    clone = replace(scenario.history.records[0].source_observation)
    scenario = replace(scenario, source_batches=(ObservationBatch((clone,) * 3),))
    card = render_replay_state_html(scenario, ReplayState(scenario.history, 0))
    assert "<dt>Source inventory references by identity</dt><dd>No identical source in supplied inventory</dd>" in card


def test_static_controls_match_model_and_unique_comparison_targets():
    scenario = fixture()
    doc = render_synthetic_workspace_html(scenario, scenario, replay=True)
    parsed = Markup(doc)
    assert len(parsed.ids) == len(set(parsed.ids)) == 10
    for card, href in parsed.links:
        assert href.startswith("#") and href[1:] in parsed.ids
    for scope in ("left", "right"):
        for position in (None, 0, 1, 2, 3):
            state = ReplayState(scenario.history, position)
            card = "replay-" + scope + "-" + ("initial" if position is None else str(position))
            targets = [href for source, href in parsed.links if source == card]
            expected = [state.step_backward().position, state.step_forward().position, state.reset().position]
            assert targets[:3] == ["#replay-" + scope + "-" +
                                   ("initial" if p is None else str(p)) for p in expected]
    assert "script" not in parsed.tags
    assert all(not key.startswith("on") and key not in ("src", "action") for key, _ in parsed.attributes)
    assert "Observation timeline" in doc and "Ordered history" in doc
    empty = SyntheticScenario("Empty", ObservationHistory(()), 0, 0, ())
    assert Markup(render_synthetic_workspace_html(empty, replay=True)).ids == ["replay-left-initial"]


def test_escaping_determinism_and_no_mutation():
    scenario = fixture()
    hostile = '<script>"&\' fake</script>'
    evidence = scenario.history.records[0]
    source = replace(evidence.source_observation, observation_id=hostile, sensor_id=hostile,
                     source_local_id=hostile, reference_frame=ReferenceFrame(hostile),
                     measurement_time=MeasurementTime(0., hostile))
    history = ObservationHistory((DerivedSensorEvidence(source),) * 2)
    scenario = SyntheticScenario(hostile, history, 0, 1, (ObservationBatch((source,)),))
    before = asdict(scenario)
    refs = tuple(id(e) for e in history.records)
    doc = render_synthetic_workspace_html(scenario, replay=True)
    assert escape(hostile, quote=True) in doc and hostile not in doc
    assert "script" not in Markup(doc).tags
    assert asdict(scenario) == before and tuple(id(e) for e in history.records) == refs
    assert doc == render_synthetic_workspace_html(scenario, replay=True)


def run_cli(tmp_path, *args, optimized=False):
    # Isolated Python ignores site packages and environment path configuration.
    bootstrap = "import runpy,sys;sys.path[:0]=sys.argv[1:3];p=sys.argv[3];sys.argv=[p]+sys.argv[4:];runpy.run_path(p,run_name='__main__')"
    return subprocess.run([sys.executable, "-I", "-S", "-B"] + (["-O"] if optimized else []) +
        ["-c", bootstrap, str(ROOT / "src"), str(ROOT / "examples"),
         str(ROOT / "examples/synthetic_observation_demo.py"), *args],
        cwd=tmp_path, env={}, capture_output=True, check=False)


@pytest.mark.parametrize("args", [("--html", "--replay"), ("--html", "--compare", "--replay")])
def test_offline_independent_execution(tmp_path, args):
    first, second = run_cli(tmp_path, *args), run_cli(tmp_path, *args)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout and first.stderr == second.stderr == b""
    assert first.stdout.startswith(b"<!DOCTYPE html>") and first.stdout.endswith(b"</html>\n")
    assert b"PASS" not in first.stdout
    assert b"Deterministic replay" in first.stdout
    assert "script" not in Markup(first.stdout.decode()).tags


@pytest.mark.parametrize("args", [("--replay",), ("--html", "--replay", "--unknown")])
def test_cli_invalid_combinations(tmp_path, args):
    result = run_cli(tmp_path, *args)
    assert result.returncode != 0 and result.stdout == b""


def test_optimized_rejected_before_output(tmp_path):
    result = run_cli(tmp_path, "--html", "--replay", optimized=True)
    assert result.returncode != 0 and result.stdout == b""
    assert b"Run without -O" in result.stderr


@pytest.mark.parametrize("args", [(), ("--html",), ("--html", "--compare")])
def test_legacy_modes_have_no_replay(tmp_path, args):
    result = run_cli(tmp_path, *args)
    assert result.returncode == 0 and result.stderr == b""
    assert b"Deterministic replay" not in result.stdout
    if not args:
        assert result.stdout.endswith(b"DETERMINISTIC SYNTHETIC DEMO: PASS\n")
