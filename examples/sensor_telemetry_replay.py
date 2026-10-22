"""Read-only bounded replay of Phase 75B/75C or version 1 telemetry."""
import argparse
from dataclasses import asdict
import sys
from aegis.simulation.contracts import SimulationError
from aegis.simulation.sensor_realism import encode
from aegis.simulation.sensor_telemetry import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--input-kind', choices=('raw', 'impaired', 'telemetry'), required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--evaluation-ns', required=True)
    parser.add_argument('--stale-after-ns', type=int, required=True)
    args = vars(parser.parse_args())
    try:
        output = replay(**args)
    except (ValueError, KeyError, TypeError, OSError, RecursionError) as error:
        diagnostic = asdict(error.diagnostic) if isinstance(error, SimulationError) else dict(code='SCHEMA', path='input', explanation=type(error).__name__)
        sys.stdout.buffer.write(encode(dict(schema_version=1, rejected=True, diagnostic=diagnostic)))
        return 2
    sys.stdout.buffer.write(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
