"""Validate a local scenario and optionally inspect executable discovery; never launch."""
import argparse
import json
import sys
from .adapter import GazeboPx4Adapter
from .contracts import SimulationError, document
from .scenarios import read_scenario, scenario_digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--detect-dependencies', action='store_true')
    args = parser.parse_args(argv)
    try:
        scenario = read_scenario(args.scenario)
        report = {'scenario_id': scenario.scenario_id, 'scenario_sha256': scenario_digest(scenario),
                  'physics_running': False, 'versions': document(scenario.versions)}
        if args.detect_dependencies:
            report['adapter'] = document(GazeboPx4Adapter().probe(scenario))
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0
    except (SimulationError, OSError) as error:
        result = document(error.diagnostic) if isinstance(error, SimulationError) else {'code': 'SCENARIO_IO', 'explanation': 'Local scenario could not be read'}
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
