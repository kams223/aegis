# Phase 75B — real simulated sensor observations

Phase 75B-R startup diagnosis, reliability changes and the ten-run validation are
documented in [STARTUP-RELIABILITY.md](STARTUP-RELIABILITY.md). Historical results
below remain preserved; use the new reliability report for the current harness.

This separate passive experiment starts at commit
`48c25f88ef8401d7c6c477256093bff7a1af4aa1`. Phase 75A files and the
Phase 74A 8.3.0 simulation contract are unchanged. `sensor-aircraft.sdf`
copies the verified mechanical model and adds only three zero-offset,
body-aligned sensors. `sensor-aircraft-world.sdf` adds the Imu, NavSat and
AirPressure systems and an explicit WGS84 origin (0° latitude, 0° longitude,
0 m elevation), heading zero, world ENU. No actuation or flight model is added.

Compatibility was checked before implementation: the pinned image reports
8.15.0, has all three dedicated system libraries, and imports the msgs10 IMU,
NavSat and FluidPressure Python schemas with transport13. No rendering system,
GUI, bridge, external data or hardware is required. References:
[Sim 8 NavSat](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1NavSat.html),
[Sim 8 systems](https://gazebosim.org/api/sim/8/files.html),
[pressure implementation](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/AirPressureSensor.cc),
[pressure system](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/air_pressure/AirPressure.cc).
These branch references explain the model; runtime identity is established by
the pinned image digest and measured version, not by current branch contents.

| Sensor | Topic | Message | Rate | Native values |
| --- | --- | --- | --- | --- |
| IMU | `/aegis/sensors/imu` | `gz.msgs.IMU` | 100 Hz | acceleration m/s², angular velocity rad/s, quaternion xyzw |
| GNSS | `/aegis/sensors/gnss` | `gz.msgs.NavSat` | 20 Hz | latitude/longitude degrees, altitude m |
| Barometer | `/aegis/sensors/barometer` | `gz.msgs.FluidPressure` | 50 Hz | pressure Pa, variance |

All timestamps are sensor update simulation nanoseconds, not receipt times.
Native frame identifiers are retained and checked: IMU and pressure use header
metadata; NavSat uses its dedicated `frame_id`. Sensors are coincident with the
body link origin, x forward/y left/z up. Model pose is world ENU and quaternion
xyzw. IMU orientation is relative to its initial world alignment, which equals
world alignment in this level release. Quaternion comparison accounts for sign.
IMU acceleration is specific force `R_world_to_sensor * (a_world - gravity)`.
Free fall should read zero and stationary support approximately +9.81 along
sensor z; equality to world acceleration would be incorrect. The checker uses
free-fall force magnitude, settled force magnitude and direction, angular-speed
checks, and orientation comparison; impact spikes are retained but not used for those checks.
Settled specific force is compared to world up rotated into sensor axes using
the inverse ground-truth pose quaternion. This does not validate general
rotated-frame dynamics or lever-arm acceleration.

GNSS altitude uses the zero-elevation WGS84 origin. A local tangent approximation
with WGS84 equatorial radii compares latitude/longitude against y/x, respectively;
it is limited to this sub-metre drop at the equator. This is not an MSL/geoid
conversion or an independent GNSS receiver/fix-quality model. The protobuf has
no fix-validity flag; finite coordinates, geographic ranges, frame and timing
checks define acceptance. Proto3 scalar defaults cannot independently distinguish
an omitted zero-valued scalar from a genuine zero. Missing messages are never
filled with zero; gaps and absent streams are rejected.

Pressure is native sensor output. Altitude is calculated separately by inverting
Gazebo Sensors 8's lapse atmosphere: `P0=101325 Pa`, `T0=288.15 K`, lapse
`L=0.0065 K/m`, gravity `9.80665 m/s²`, molar mass `28.9644 kg/kmol`, gas constant
`8314.32`, Earth radius `6356766 m`. For exponent `n=g*M/(R*L)`, geopotential
height is `H=T0/L*(1-(P/P0)^(1/n))`; geometric height is `r*H/(r-H)`.
The air-pressure system supplies world sensor z with default reference altitude
zero; geographic elevation is not added. The world deliberately sets geographic
elevation zero so the two reference conventions coincide. No sensor noise is
configured; this validates ideal simulated observations, not hardware accuracy.

Each sensor sample matches the nearest actual pose within 11 ms; neither stream
is sorted, resampled or interpolated. Residual tolerance is 5 cm, allowing the
100 Hz pose cadence and integration timing. Rates must be within ±10%, every
interval within 0.5–1.5 nominal periods, and first/last samples within two periods
of simulation boundaries. IMU free-fall force tolerance is 0.2 m/s², settled
magnitude error 0.3 m/s², settled angular speed 0.1 rad/s, quaternion distance
0.02. Missing, delayed, invalid or regressing streams generate sensor-specific
diagnostics. The unchanged Phase 75A checker also verifies trajectory, contacts,
clock advance and settling after explicitly validating/adapting the new world
frame identity. Raw pose frame identifiers remain intact in evidence.

Run from the repository root with Docker access and the preloaded pinned image:

```sh
python3 -B simulation/gazebo-smoke/sensors.py
python3 -B simulation/gazebo-smoke/sensors.py --run \
  --disk-path / --output-dir /tmp/aegis75b-sensors-UNIQUE
python3 -B -m pytest -q tests/test_gazebo_sensors.py
```

Default invocation validates hashes and prints configuration without launching.
Set the disk path to the backing filesystem whose free space should be checked. The image is
`ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6`.
The harness reuses the pinned experimental profile and existing Docker launcher,
cgroup checks, transport readiness, bounded logging, process-group cleanup and
host memory reserves. Limits are 1 CPU, 1 GiB/no extra swap, 128 processes,
2000 × 1 ms steps, 35 s server and 55 s host wall time. Network is none;
no ports/devices/privilege, UID 10001, read-only root/source, dropped capabilities,
no-new-privileges and bounded tmpfs apply. Only the unique owned container is
stopped/removed; final absence is queried. Existing services are untouched.

`report.json` and `container.log` remain outside Git. Reports retain native
samples, clock/contact/pose records, derived velocities, sensor configuration,
rate statistics, residuals, rejection diagnostics, UTC time, model/world and
harness hashes, image/version, inspected isolation policy, memory/PID peaks,
exit/OOM status and cleanup result. The server log is embedded in the raw report.
Synthetic test fixtures exercise validators and lifecycle failures only.
See `sensor-results.json` for measured summaries and raw report digests.

## Initial implementation evidence on 2026-10-21

Raw reports and logs are retained under `/tmp/aegis75b-sensors-20261021-1`,
`/tmp/aegis75b-sensors-20261021-2`, `/tmp/aegis75b-sensors-20261021-final`,
and `/tmp/aegis75b-sensors-20261021-review`. The last directory verifies the
pre-finalization harness source hashes. Each contains `report.json` and `container.log`.
The first attempt published all sensors but was rejected by incorrect checker
frame assumptions (new world identity and NavSat's dedicated frame field).
That failure is retained, not relabeled. Subsequent attempts passed. No sensor
plugin startup failure was observed. The final verdict preserves the new world
frame in both raw observations and summarized initial/final poses.

The unchanged real baselines passed in `/tmp/aegis75b-aircraft-20261021` and
`/tmp/aegis75b-gravity-20261021`. All experiment containers were removed.
All initial implementation sensor runs retained 201 IMU, 41 GNSS and 101 pressure samples from
1,000,000 through 2,000,000,000 simulation ns. Mean rates were 100.0500,
20.0100 and 50.0250 Hz respectively; the first interval is 1 ms shorter
than the nominal period because the initial publication is at step 1.
GNSS and pressure-derived altitude residuals were at most 0.000530 m.
Free-fall specific force was zero; settled magnitude was 9.81 m/s², with
maximum magnitude error below 9e-15 m/s². These are ideal noiseless
simulation results, not a precision claim for physical instruments.

The JSON summary records each run's memory peak, PID peak, exits, cleanup,
configuration, rates, residuals and raw report SHA-256. To independently
recheck a current reliability-series report with the current validators, set
`AEGIS_EVIDENCE_ROOT` to the external `aegis75br-20261022` directory:

```sh
PYTHONPATH=simulation/gazebo-smoke python3 -B - <<'PY'
import json, os, sensors
from pathlib import Path
r = json.loads((Path(os.environ['AEGIS_EVIDENCE_ROOT']) / 'run-01/report.json').read_text())
e = r['evidence']
assert r['success'] and r['cleanup_ok']
for name, digest in r['harness_sha256'].items():
    assert sensors.smoke.digest(sensors.HERE / name) == digest, name
assert sensors.analyze_sensors(e['sensor_samples'], e['pose_samples'])['passed']
assert sensors.verdict(e['pose_samples'], e['clock_observations'],
    e['contact_samples'], e['server_exit_code'], e['timed_out'])['passed']
PY
```

This rechecks preserved transport evidence; it does not create new sensor evidence.
Full regression logs are `/tmp/aegis75b-full-tests-final.log`; focused results
are `/tmp/aegis75b-focused-tests.log`. An initial sandboxed full-suite attempt
stalled without output and did not respond to SIGINT; that task-owned process
was terminated with SIGTERM, then the suite reran outside the sandbox under a
360 s bound. No repository change was needed for that environment issue.

`peak_pids` is the cgroup-v2 `pids.peak` resource counter: it counts tasks,
including threads, rather than only process leaders. The final sensor run peaked
at 20 tasks and 110,751,744 bytes (105.62 MiB); the 128-task limit was enforced.

Final focused validation: **148 passed, 2 skipped** in 3.56 s.
Final complete Python regression: **2324 passed, 2 skipped**, no failures,
in 87.74 s. The two skipped tests are opt-in real Docker integrations;
their underlying real sensor/aircraft harnesses were run explicitly above,
as was the Phase 74B gravity baseline. The final sensor server, container and
attach exit codes were all zero; no OOM or timeout occurred. These were pre-finalization results; the finalization results below supersede them.

## Finalization review

Review against fetched `origin/main` confirmed parent
`48c25f88ef8401d7c6c477256093bff7a1af4aa1`. All Phase 74A simulation contracts,
Phase 74B assets/helpers, and Phase 75A assets/checkers remain byte-for-byte
unchanged. The separate model preserves mechanics and adds observation only.
Finalization adds explicit startup timeout classification, standalone ground-truth
validation, retained callback diagnostics, malformed/startup/timeout/cleanup
rejection tests, and the IMU settled-force direction check. The default backing
disk path is now `/`, and no local user or interpreter path is required.

Two review-stage repeats in the external `aegis75b-finalization` directory passed:
each captured 201 IMU, 41 GNSS, and 101 pressure records. Native sensor rows,
including every update timestamp and value, were exactly equal between those
two runs. Peak memory was 113,516,544 versus 104,800,256 bytes (108.26 versus
99.95 MiB), with 20 peak cgroup tasks each. Server wall times were 6.5491 versus
8.8404 s; clock message counts were 41 versus 63. This is measured repeatability
for these two runs under the earlier magnitude-only checker, not general
determinism or a claim about asynchronous clock publication.

The two **final-source** repeats in external `aegis75b-finalization-reviewed`
had mixed results:

| Observation | Repeat 1 | Repeat 2 |
| --- | --- | --- |
| Overall verification | Passed | Rejected |
| IMU / GNSS / pressure samples | 201 / 41 / 101 | 0 / 0 / 0 |
| Pose / clock samples | 200 / 35 | 0 / 6 |
| Clock advance observed | Yes | No; only paused time-zero statistics |
| Unpause acknowledged | Yes | No |
| Server / container / attach exit | 0 / 0 / 0 | 0 / 2 / 2 |
| Peak memory | 100.10 MiB | 106.64 MiB |
| Peak cgroup tasks | 20 | 20 |
| Server wall time | 5.9334 s | 5.7761 s |
| Timeout / OOM | Neither | Neither |
| Cleanup verified | Yes | Yes |

The second run's error is `Missing or excessive observations`. Systems loaded,
but there is no retained evidence of running physics or sensor publication.
A zero server exit and failed service acknowledgement do not establish whether
physics advanced unobserved. The cause remains unresolved. The failed report,
empty streams, paused statistics and server log are retained; no fixtures or
interpolation replace missing measurements. Sensor values and timestamps cannot
be compared for that final pair. This is an outstanding observation-startup issue,
not a successful sensor validation or a proven plugin-load failure.

The successful final-source run measured free-fall specific force zero and
settled force-vector error below 8.5e-11 m/s² after rotating world support force
with the inverse observed pose quaternion. GNSS and pressure-altitude residuals
remained below 0.000530 m. These values reflect an ideal noise-free simulation;
they do not imply corresponding real-world accuracy.

Before/after Docker snapshots for both repeat groups matched container IDs,
image IDs, configuration hashes, status, start times and restart counts for
Nginx Proxy Manager, DuckDNS, and all three Wazuh containers. No experiment
containers remained. Snapshot and lifecycle hashes, all four finalization report
hashes, exact stream comparisons, metrics and failure diagnostics are preserved
in `sensor-results.json`. Raw JSON, server/container/launcher logs, and service
snapshots stay outside Git. Tests of malformed messages and startup failure use
clearly separated unit fixtures; they do not attest additional real failures.

Finalization focused tests: **169 passed, 2 opt-in skips**. The CI workflow runs
Python unit/regression tests; it does not launch the opt-in real Gazebo tests.
The unresolved observation-startup issue must remain visible during PR review.
Finalization full Python regression: **2345 passed, 2 opt-in skips, no failures**,
in 87.37 s. Its external log is `aegis75b-finalization-regression.log`; focused
results are in `aegis75b-finalization-focused.log`. Their SHA-256 hashes are
recorded under `finalization.tests` in the JSON summary.
