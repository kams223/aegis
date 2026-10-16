"""Generate offline prefix states with the existing pure monitoring reducer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from examples.platform_monitoring_demo import demo_inputs
from aegis.platform.contracts import parse_json, to_document
from aegis.platform.monitoring import MonitoringSession, reduce_session


def fixture_bytes():
    initial, events = demo_inputs()
    prefixes = []
    for frontier in range(len(events) + 1):
        session = reduce_session(initial, events[:frontier])
        document = to_document(session)
        parse_json(MonitoringSession, json.dumps(document).encode('utf-8'))
        prefixes.append(document)
    return (json.dumps({'schema_version': 1, 'prefixes': prefixes}, sort_keys=True,
                       separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    data = fixture_bytes()
    if args.check:
        target = Path(__file__).resolve().parents[1] / 'src/data/fusion-replay.json'
        if not target.is_file() or target.read_bytes() != data:
            parser.error('fusion replay differs from existing reducer prefix outputs')
        print('Monitoring replay: exact prefix bytes verified')
    else:
        args.output.write_bytes(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
