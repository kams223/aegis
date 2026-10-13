"""Explicit deterministic fixture generation; never reads evidence or recordings."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from examples.platform_monitoring_demo import demo_session, render_json
from aegis.platform.contracts import parse_json
from aegis.platform.monitoring import MonitoringSession


def fixture_bytes():
    data = render_json(demo_session()).encode('utf-8')
    parse_json(MonitoringSession, data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    data = fixture_bytes()
    if args.check:
        target = Path(__file__).resolve().parents[1] / 'src/data/session.json'
        if not target.is_file() or target.read_bytes() != data:
            parser.error('fixture is missing or differs from the unchanged Phase 62 demo')
        print('Phase 62 fixture: exact bytes verified')
    else:
        # Writing is explicitly requested by a developer, never by the console.
        args.output.write_bytes(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
