"""Report-local work reuse and explicit offline HTML composition."""

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
from examples import synthetic_observation_analysis as analysis
from examples import synthetic_observation_inspector as inspector
from examples import synthetic_observation_validation as validation
from examples.synthetic_observation_replay import ReplayState
from examples.synthetic_observation_demo import build_synthetic_scenario

ROOT = Path(__file__).resolve().parents[1]


def fixture(kind="small"):
    a = DerivedSensorEvidence(SensorObservation("shared", "radar", MeasurementTime(5., "a"),
        ReferenceFrame("local"), RadarPolarDetectionMeasurement(0., 0.)))
    b = DerivedSensorEvidence(SensorObservation("shared", "radar", MeasurementTime(2., "b"),
        ReferenceFrame("local"), RadarPolarDetectionMeasurement(0., 0.)))
    c = DerivedSensorEvidence(SensorObservation("third", "radar", MeasurementTime(1., "a"),
        ReferenceFrame("local"), RadarPolarDetectionMeasurement(0., 0.)))
    records = (a, b, a, c) * (12 if kind == "long" else 1)
    if kind == "empty":
        return analysis.SyntheticScenario("Empty", ObservationHistory(()), 0, 0,
            (ObservationBatch(()), ObservationBatch(())))
    scenario = analysis.SyntheticScenario("Prepared fixture", ObservationHistory(records), 0, 4,
        (ObservationBatch(()), ObservationBatch((a.source_observation, b.source_observation,
                                               c.source_observation, a.source_observation)), ObservationBatch(())))
    if kind in ("time", "both"):
        object.__setattr__(a.source_observation, "measurement_time", None)
    if kind in ("frame", "both"):
        object.__setattr__(a.source_observation, "reference_frame", None)
    return scenario


# Independently captured from the preserved pre-refactor analysis source.
# Hashes include every field, message and finding position, not only codes.
FINDING_HASHES = {'small': '875da883fdc9a72ca2ed9a018a847ac0f9f6eb9c2d7b6d62c5863adbb4327587', 'long': '0d8efbadadbbf3e75fbd141fdce3ad8d9d2ef4af107b6c286d21fad544d6afe0', 'empty': 'c4b6cd65d21d63d970343411d3aab6db98cf68c551fbb9c05845f374c6cd0e4e', 'time': '615d49a4aebcfbab05af5856f708a9ead451bd125b079244f376eb33d04e17da', 'frame': '27d38fe91e86b2fde82524d002027b22b06787af2c5dd79ab7a94343f70126df', 'both': 'a9301bfe7103db8f17154f4f8ccb207beee4f6b852a230485ea6bf53e6fdca1f'}


@pytest.mark.parametrize("kind", FINDING_HASHES)
def test_exact_diagnostic_findings_match_pre_refactor(kind):
    scenario = fixture(kind)
    before = asdict(scenario)
    findings = [asdict(f) for f in analysis.diagnose_scenario(scenario)]
    assert hashlib.sha256(json.dumps(findings, ensure_ascii=False).encode()).hexdigest() == FINDING_HASHES[kind]
    assert asdict(scenario) == before


def instrument(monkeypatch):
    calls = []
    original = analysis.diagnose_scenario
    def diagnose(scenario):
        calls.append(scenario)
        return original(scenario)
    monkeypatch.setattr(inspector, "diagnose_scenario", diagnose)
    monkeypatch.setattr(validation, "diagnose_scenario", diagnose)
    return calls


@pytest.mark.parametrize("kind", ["small", "long", "empty"])
def test_diagnose_once_per_report_and_no_persistent_cache(monkeypatch, kind):
    calls = instrument(monkeypatch)
    scenario = fixture(kind)
    before = asdict(scenario)
    first = inspector.render_synthetic_workspace_html(scenario, replay=True)
    assert calls == [scenario]
    second = inspector.render_synthetic_workspace_html(scenario, replay=True)
    assert calls == [scenario, scenario] and first == second
    assert asdict(scenario) == before
    assert first.count('class="replay-state"') == len(scenario.history.records) + 1


@pytest.mark.parametrize("same", [False, True])
def test_comparison_diagnostics_and_controls_remain_independent(monkeypatch, same):
    calls = instrument(monkeypatch)
    left = fixture()
    right = left if same else replace(fixture(), label="Right", history=ObservationHistory(tuple(reversed(fixture().history.records))))
    document = inspector.render_synthetic_workspace_html(left, right, replay=True)
    assert len(calls) == (1 if same else 2)
    assert calls[0] is left
    if not same:
        assert calls[1] is right
    parsed = Document(document)
    assert len(parsed.ids) == len(set(parsed.ids)) == 10
    assert all(target.startswith("#") and target[1:] in parsed.ids for _, target in parsed.links)
    for card, target in parsed.links:
        if card:
            assert target.startswith("#replay-left-") if card.startswith("replay-left-") else target.startswith("#replay-right-")


@pytest.mark.parametrize("kind", ["small", "empty", "time", "frame", "both"])
def test_validation_shares_findings_and_preserves_failed_reports(monkeypatch, kind):
    scenario = fixture(kind)
    calls = instrument(monkeypatch)
    manifest = validation.build_validation_manifest(scenario)
    calls.clear()
    document, exit_code = validation.render_validation_report(scenario, html=True)
    assert calls == [scenario]
    expected = "failed" if kind in ("time", "frame", "both") else "not_evaluated"
    assert manifest["overall_validation"]["status"] == expected
    assert exit_code == (1 if expected == "failed" else 2)
    assert "<dt>Validation status</dt><dd>" + expected + "</dd>" in document
    assert Document(document).tags.count("html") == 1
    calls.clear()
    assert validation.render_validation_html(scenario) == document
    assert calls == [scenario]


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags, self.ids, self.links = [], [], []
        self.card = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "article":
            self.card = attrs["id"]
        if tag == "a":
            self.links.append((self.card, attrs["href"]))

    def handle_endtag(self, tag):
        if tag == "article":
            self.card = None


def test_composition_handles_adversarial_markup_without_nested_documents():
    hostile = '<body></body></style><title>"& Ω<script>fake</script>'
    base = fixture()
    source = replace(base.history.records[0].source_observation, observation_id=hostile,
        sensor_id=hostile, source_local_id=hostile, reference_frame=ReferenceFrame(hostile),
        measurement_time=MeasurementTime(0., hostile))
    evidence = DerivedSensorEvidence(source)
    scenario = analysis.SyntheticScenario(hostile, ObservationHistory((evidence, evidence)), 0, 1,
                                         (ObservationBatch((source,)),))
    before = asdict(scenario)
    records, batches = scenario.history.records, scenario.source_batches
    for document in (inspector.render_synthetic_workspace_html(scenario, scenario, replay=True),
                     validation.render_validation_html(scenario)):
        parsed = Document(document)
        assert escape(hostile, quote=True) in document and hostile not in document
        for tag in ("html", "head", "body", "style"):
            assert parsed.tags.count(tag) == 1
        assert "script" not in parsed.tags and "link" not in parsed.tags
        assert all(target[1:] in parsed.ids for _, target in parsed.links)
    assert asdict(scenario) == before
    assert scenario.history.records is records and scenario.source_batches is batches


def test_prepared_replay_findings_retain_global_order(monkeypatch):
    scenario = fixture()
    actual = []
    original = inspector._diagnostics_html
    def capture(findings):
        actual.append(findings)
        return original(findings)
    monkeypatch.setattr(inspector, "_diagnostics_html", capture)
    inspector.render_replay_state_html(scenario, ReplayState(scenario.history, 2))
    expected = tuple(f for f in analysis.diagnose_scenario(scenario)
                     if f.location in {"history 2", "batch 1, observation 0", "batch 1, observation 3"})
    assert actual == [expected]
    assert any(f.code == "repeated_source_id" for f in expected)
    assert any(f.code == "repeated_occurrence" for f in expected)


@pytest.mark.parametrize("kind", ["small", "long"])
def test_replay_provenance_inventory_not_scanned_per_position(kind):
    class CountedBatches(tuple):
        iterations = 0
        def __iter__(self):
            self.iterations += 1
            return super().__iter__()
    scenario = fixture(kind)
    batches = CountedBatches(scenario.source_batches)
    scenario = replace(scenario, source_batches=batches)
    batches.iterations = 0
    inspector.render_synthetic_workspace_html(scenario, replay=True)
    # Envelope validation, diagnostics, and one provenance index; independent of length.
    assert batches.iterations == 3


# Captured from nine isolated executions before any implementation edits.
CLI_BASELINES = [([], 'd9caedddee1ae850fac263f1b457713441276df665035380c7791817b2f610d8'), (['--html'], 'e2f5bdfe61c6ce40eba747879ef397672386c8c34b5d0f88b433edf362c39a4c'), (['--html', '--compare'], 'ab4c5b5f1d011f8ba6fb143a9948f32218a3cfac293fd1487982e4f1f4bb2c59'), (['--html', '--replay'], '7859e6304c3a37e9fa700858e21b65e33c488b1df0b00913365141a72d3a92d2'), (['--html', '--compare', '--replay'], '0a4b4183bf120ad06e67df9e890d5e5aff66cca6374f7fd0beca1a2b7ada87ac'), (['--validate-json'], 'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'), (['--validate-html'], 'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7'), (['--validate-json', '--strict'], 'bdae4c6acfb3e21f92d73977060fe0210e1cbe9bfbd87bc156a57397ce546bab'), (['--validate-html', '--strict'], 'f5ca61bee7881b750522fa51d559d46d629a37a58ba75b457fbdff27f99331b7')]


@pytest.mark.parametrize("args,digest", CLI_BASELINES)
def test_all_nine_cli_modes_match_baseline_offline(tmp_path, args, digest):
    bootstrap = "import runpy,sys;sys.path[:0]=sys.argv[1:3];p=sys.argv[3];sys.argv=[p]+sys.argv[4:];runpy.run_path(p,run_name='__main__')"
    command = [sys.executable, "-I", "-S", "-B", "-c", bootstrap, str(ROOT / "src"),
               str(ROOT / "examples"), str(ROOT / "examples/synthetic_observation_demo.py"), *args]
    first = subprocess.run(command, cwd=tmp_path, env={}, capture_output=True, timeout=30)
    second = subprocess.run(command, cwd=tmp_path, env={}, capture_output=True, timeout=30)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout
    assert hashlib.sha256(first.stdout).hexdigest() == digest
    assert list(tmp_path.iterdir()) == []
