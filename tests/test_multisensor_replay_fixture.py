"""Phase 76A example remains a deterministic, valid Phase 75D inspection."""
import hashlib
import json
from pathlib import Path
import runpy
from aegis.simulation.contracts import load_contract
from aegis.simulation.sensor_realism import encode
from aegis.simulation.sensor_telemetry import SensorTelemetry


def test_fixture_repeatability_and_existing_contract():
    fixture = runpy.run_path(str(Path(__file__).parents[1] / 'examples/multisensor_replay_fixture.py'))['fixture']
    outputs = [fixture() for _ in range(3)]
    assert len({hashlib.sha256(output).hexdigest() for output in outputs}) == 1
    doc = json.loads(outputs[0])
    assert doc['artifact_kind'] == 'offline_sensor_telemetry_inspection'
    assert doc['example_kind'] == 'synthetic_fixture'
    assert len(doc['observations']) == 11
    for row in doc['observations']:
        load_contract(SensorTelemetry, encode(row['record']))
    assert not doc['rejected']
    assert doc['summary']['barometer']['missing'] == 1
    assert {s: d['count'] for s, d in doc['summary'].items()} == {'imu': 6, 'gnss': 2, 'barometer': 3}
    assert any(d['code'] == 'DELIVERY_REGRESSION' for d in doc['anomalies'])
