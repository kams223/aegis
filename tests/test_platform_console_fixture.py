"""Frontend fixture stays byte-identical to the existing validated Python demo."""
from pathlib import Path
import importlib.util
import json

from aegis.platform.contracts import parse_json
from aegis.platform.monitoring import MonitoringSession
from examples.platform_monitoring_demo import demo_session, render_json

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / 'web/monitoring-console'


def test_console_fixture_exact_bytes_and_platform_schema():
    data = (CONSOLE / 'src/data/session.json').read_bytes()
    assert data == render_json(demo_session()).encode('utf-8')
    assert parse_json(MonitoringSession, data) == demo_session()
    assert json.loads(data)['summary']['rejected_count'] == 1


def test_generation_command_check_and_explicit_output(tmp_path):
    path = CONSOLE / 'scripts/generate_fixture.py'
    spec = importlib.util.spec_from_file_location('console_fixture_generator', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(['--check']) == 0
    target = tmp_path / 'explicit.json'
    assert module.main(['--output', str(target)]) == 0
    assert target.read_bytes() == (CONSOLE / 'src/data/session.json').read_bytes()


def test_frontend_isolated_assets_and_no_external_runtime_services():
    html = (CONSOLE / 'index.html').read_text()
    assert "connect-src 'none'" in html and 'https://' not in html
    css = (CONSOLE / 'src/styles.css').read_text()
    assert '@import' not in css and 'url(' not in css
    source = '\n'.join(path.read_text() for path in (CONSOLE / 'src').glob('*.tsx'))
    for forbidden in ('dangerouslySetInnerHTML', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'serviceWorker', 'new Worker'):
        assert forbidden not in source
