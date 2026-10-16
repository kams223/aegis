"""Replay fixture is produced by the existing reducer, never reconstructed in JS."""
from pathlib import Path
import importlib.util
import json

from aegis.platform.contracts import parse_json, to_document
from aegis.platform.monitoring import MonitoringSession, reduce_session
from examples.platform_monitoring_demo import demo_inputs, demo_session

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / 'web/monitoring-console'


def generator():
    spec = importlib.util.spec_from_file_location('fusion_replay_generator', CONSOLE / 'scripts/generate_fusion_replay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_prefix_matches_direct_monitoring_replay_and_preserves_inputs():
    initial, events = demo_inputs()
    before = (to_document(initial), tuple(to_document(event) for event in events))
    data = json.loads((CONSOLE / 'src/data/fusion-replay.json').read_bytes())
    assert set(data) == {'schema_version', 'prefixes'} and data['schema_version'] == 1
    assert len(data['prefixes']) == len(events) + 1
    for frontier, document in enumerate(data['prefixes']):
        parsed = parse_json(MonitoringSession, json.dumps(document).encode())
        assert parsed == reduce_session(initial, events[:frontier])
        assert [result.timestamp for result in parsed.event_results] == [event.timestamp for event in events[:frontier]]
        if frontier and parsed.event_results[-1].status == 'rejected':
            assert document['final_snapshot'] == data['prefixes'][frontier - 1]['final_snapshot']
    assert data['prefixes'][-1] == to_document(demo_session())
    assert before == (to_document(initial), tuple(to_document(event) for event in events))


def test_replay_generation_is_deterministic_and_explicit(tmp_path):
    module = generator()
    expected = (CONSOLE / 'src/data/fusion-replay.json').read_bytes()
    assert module.fixture_bytes() == module.fixture_bytes() == expected
    assert module.main(['--check']) == 0
    target = tmp_path / 'replay.json'
    assert module.main(['--output', str(target)]) == 0
    assert target.read_bytes() == expected
