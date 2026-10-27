"""Print a fabricated Phase 75D inspection for offline multi-sensor examples.

No simulator or hardware evidence. Does not write files or read a wall clock.
"""
from aegis.simulation.contracts import SourceIdentity, Timestamp
from aegis.simulation.sensor_realism import Field
from aegis.simulation.sensor_telemetry import SensorTelemetry, bounded_bytes, inspect


def fixture():
    records = []
    for sensor, times in (('imu', range(0, 60, 10)), ('gnss', (0, 40)), ('barometer', (0, 20, 40))):
        for acquisition in times:
            delivery = acquisition + (2 if sensor == 'imu' else 5)
            if sensor == 'gnss':
                delivery = 60 if acquisition == 0 else 45
            stamp = lambda n: Timestamp(value_ns=str(n), domain='fixture.sim')
            fields = ([('acceleration.' + axis, 0., 'm/s^2') for axis in 'xyz'] if sensor == 'imu' else
                      [('latitude', 0., 'deg'), ('longitude', 0., 'deg'), ('altitude', 1., 'm')] if sensor == 'gnss' else
                      [('pressure', 101325., 'Pa')])
            source = SourceIdentity(session_id='synthetic-multisensor', vehicle_id='passive_aircraft', component_id=sensor,
                                    source_id='passive_aircraft::body::' + sensor, data_origin='recorded', clock_domain='fixture.sim')
            records.append(SensorTelemetry(observation_type=sensor, source=source, acquisition=stamp(acquisition),
                simulation=stamp(acquisition), delivery=stamp(delivery), frame=source.source_id, origin='raw',
                source_sha256='a' * 64, config_json=None, config_sha256=None, seed_identifier=None,
                values=None if sensor == 'barometer' and acquisition == 20 else tuple(Field(name=n, value=v, unit=u) for n, v, u in fields)))
    result = inspect(tuple(records), Timestamp(value_ns='100', domain='fixture.sim'), 15)
    result.update(example_kind='synthetic_fixture', evidence_attestation='Fabricated multi-rate timeline example; no simulator, hardware, or accuracy evidence.')
    return bounded_bytes(result)


if __name__ == '__main__':
    import sys
    sys.stdout.buffer.write(fixture())
