# Phase 75C: offline sensor imperfections

This optional offline path preserves the Phase 74A 8.3.0 contract and all
74B/75A/75B assets. It starts no simulator, Docker service, network connection,
or control interface. No dependencies were added.

The version 1 configuration is defined by
`configs/simulation/sensor-imperfections-v1.schema.json`; the adjacent JSON is a
reproducible example. `src/aegis/simulation/sensor_realism.py` implements frozen
observations, configuration, transformation, validation and summary statistics.
It reuses simulation `Contract`, `SimulationError`, strict JSON decoding and
field validation. Existing simulation recording contracts support different
measurement quantities and wall receipt clocks; they are deliberately not
reinterpreted as native IMU/GNSS/pressure records. The replay adapter reuses
Phase 75B's `analyze_sensors`, pressure-altitude equation and inverse quaternion
rotation. Startup receipt wall times are never treated as sensor timestamps.

## Reproduction

From the repository root, set `REPORT` to a preserved successful Phase 75B
`report.json` and `DIGEST` to its SHA-256 in `startup-reliability-results.json`
or `sensor-results.json`. The digest must come from the evidence manifest;
a caller-supplied digest alone is not an authenticity attestation.

```sh
PYTHONPATH=src python3 -B simulation/gazebo-smoke/realism_replay.py \
  "$REPORT" configs/simulation/sensor-imperfections-v1.json \
  --source-sha256 "$DIGEST" > /tmp/sensor-replay-1.json
PYTHONPATH=src python3 -B simulation/gazebo-smoke/realism_replay.py \
  "$REPORT" configs/simulation/sensor-imperfections-v1.json \
  --source-sha256 "$DIGEST" > /tmp/sensor-replay-2.json
cmp /tmp/sensor-replay-1.json /tmp/sensor-replay-2.json
PYTHONPATH=src python3 -B -m pytest -q tests/test_sensor_realism.py
```

Raw input and full derived output stay outside Git. `realism-results.json`
contains the compact comparison summary from the example replay. Rejected
input produces JSON with an explicit reason and nonzero CLI exit status; no
partial input is accepted. The pure API exposes structured SimulationError
codes and indexed stream diagnostics. Successful source validation does not
make impaired data directly measured Gazebo output.

## Version 1 semantics

`Observation` uses the existing strict version-1 Contract loader via
`load_observation(bytes)`: exact dataclass fields are required, unknown fields
and versions are rejected. All dataclasses are frozen and nested fields are
tuples. `native_json` retains the canonical original decoded native sensor row,
including header metadata; `source_sha256` links the original raw report bytes.
Original numeric fields, acquisition timestamp and sensor identity remain in
every `Derived.original`, including dropped samples. Derived records retain
configuration version, configuration hash, seed identifier, delivery time,
transformation descriptions and diagnostic reasons. The replay embeds the full
configuration, making its hash reproducible.

Numeric fields have explicit units: acceleration m/s^2, angular velocity rad/s,
quaternion components dimensionless, geographic angles deg, altitude m,
pressure Pa and variance Pa^2. Native frame identities must exactly match
`passive_aircraft::body::<sensor>`. No unknown unit or frame is converted.
Quaternion component noise and variance impairments are rejected. Categorical
values, identifiers and acquisition timestamps cannot be selected for noise.

Rules apply `original + bias + drift_per_second * elapsed_seconds + noise`.
Noise is zero-mean Gaussian with standard deviation in the field's units;
bias uses those units, and drift uses units/second. Elapsed time is explicitly
`(simulation_ns - reference_ns)/1e9`, including negative elapsed times. Drift
never reads a wall clock. No physical hardware accuracy is implied without
measured calibration data.

SHA-256 keys select independent Python Random streams by seed, sensor, field,
acquisition timestamp and purpose. This makes the sequence independent of
other sensors, fields and dropout decisions. Repeatability is for the same
Python implementation/runtime; cross-language Gaussian bit identity is not
promised. Duplicate sensor/acquisition keys are rejected, including ties within
a sensor. Timestamp ties between different sensors are valid.

Dropout is Bernoulli per observation. A dropped entry has `values=null` plus
`MISSING_OBSERVATION`, never replacement values. Delivery jitter is uniform
integer nanoseconds in [-jitter_ns,+jitter_ns], added to a fixed nonnegative
latency. Jitter cannot exceed latency, so delivery cannot precede acquisition.
The adapter uses acquisition time as simulation time and baseline delivery
time: Phase 75B has no per-sample measured receipt clock. These baseline delivery
times are assumptions, not measured transport latencies. The API keeps all
three times distinct. The default configuration changes no values or times;
results are stably ordered by derived delivery time. Global supplied record
order can therefore change, while each sensor's default sequence is preserved.
Out-of-order means acquisition time regresses within a sensor in delivery
order. Stale means delivery minus acquisition exceeds the configured threshold.
Dropped entries retain hypothetical delivery times for auditing; delivered-only
latency/stale/order counts exclude them.

## Validation and comparison limits

Contract construction checks required fields, versions, finite numeric bounds,
units, identities and timestamp relations. `validate_stream` reports unexpected
or absent sensors, duplicates, acquisition/delivery regressions, staleness and
physical-domain errors without mutating evidence. The Phase 75B source checker
additionally rejects cadence gaps, missing boundaries, malformed native values
and invalid ground truth. Only a successful source report is accepted for this
experiment. Missing derived samples are explicitly retained; source gaps are
never repaired. Invalid derived pressure/geographic/quaternion values remain
visible with rejection diagnostics and are excluded from physical comparisons.

Input bounds: report 16 MiB, configuration/individual observation JSON 1 MiB,
256 native samples per sensor, 512 poses, 1024 pure-API observations, 256 field
rules, three sensor policies, 1024 characters per text field, numeric fields
within +/-1e6, uint64 nanoseconds. Unknown configuration/observation contract fields, duplicate JSON keys, nonfinite JSON,
excessive nesting and incorrect vector sizes are rejected. The source checker
retains the two-second passive experiment's bounds. CLI output is capped at
8 MiB before any output is written; serialization accumulates bounded chunks
and rejects excess output instead of emitting truncated JSON. These byte and
collection limits bound input/output sizes, not total process RSS. There is no
OS memory limit on the offline Python process. This is not a general
large-recording ingestion service. Numeric configuration quantities use JSON
decimal/exponent numbers, following the existing strict float contract loader;
integer-only tokens for those quantities are rejected. The JSON Schema is a
structural check; runtime also enforces these float types and semantic rules.

The summary includes original and impaired residual counts, signed mean, RMSE,
minimum and maximum; per-field perturbation statistics; configured bias/drift;
dropout; latency; stale/order counts; invalid count and rejection diagnostics.
Ground truth matches nearest actual pose within 11 ms with no interpolation.
GNSS uses the existing equatorial sub-metre WGS84 tangent approximation;
barometer altitude uses the existing Gazebo atmosphere inverse. IMU comparison
uses settled specific force after 1.5 s in sensor axes. Impact acceleration,
arbitrary moving-frame acceleration and general geodetic transformations are
not inferred from poses. Pressure-domain failures are not inverted into altitude.
All matching uses acquisition time, never jittered delivery time. Residuals
are accumulated in sensor/acquisition order so original comparison statistics
remain independent of seed-dependent arrival ordering. Source validation is
fail-closed: stream diagnostics remain available from the read-only validator;
transformation errors report a bounded first rejection and total rejection
count. Native report metadata is preserved; the closed-field rule applies to
configuration and normalized observation contracts, not legacy report metadata.

## Validation record

The recorded reliability-series run-01 report was checked against its manifest
SHA-256 `444f104edfecb19ae8fc7e7ed036886b493cd7064034a1bad5f39c8d19110965`
and passed the existing source checker. It contains 201 IMU, 41 GNSS and 101
barometer samples. Example results: 11 IMU dropouts, 53 out-of-order delivered
IMU samples, 38 stale delivered IMU samples, zero invalid derived measurements.
These counts describe the configured experiment, not physical sensor behavior.

Final review ran three standalone CLI replays using identical input/configuration.
All produced 650,765 bytes with SHA-256
`8fdf1dfd7258a78103459ce5ba445bdddf3ecaebfa54a6a489c03e54f4e3aa1c`.
End-to-end wall times were 0.68 s, 0.71 s and 1.07 s; peak process RSS was
24,784, 24,840 and 24,812 KiB. These measurements include interpreter startup,
source validation, transformation, comparison, bounded serialization and file
writing. They are observations of this run, not runtime or memory guarantees.

Seed 76 produced SHA-256
`d1f9252d7be979969df2b3ea8253bb1f790ef1b4b97cd5e432cd23a9c64cb699`
(652,797 bytes, 0.78 s, 25,020 KiB peak RSS). Review compared records by original
sensor/acquisition identity: 20 IMU dropout decisions, 201 IMU delivery times
and 101 barometer pressure values changed. Only configured stochastic outputs,
their diagnostics/statistics and seed/configuration provenance changed.
Original measurements, timestamps, native metadata, report digest, original
ground-truth statistics and unaffected fields remained identical. Default
identity was also checked against the same recorded stream.

Final review validation: 28 Phase 75C tests; focused simulation/sensor contracts:
345 passed, one opt-in skip. Full regression: 2396 passed, two opt-in skips in
87.63 s. External logs are named `aegis75c-final-focused.log` and
`aegis75c-full-tests-unsandboxed.log`. Full replay outputs and timing logs stay
outside Git. The earlier sandboxed full-suite attempt timed out without output;
the final bounded unsandboxed run passed. No new Gazebo/Docker run was needed.

Final review tightened the explicit output cap, preserved structured input
rejection codes, rejected overflowing JSON numbers in report metadata, bounded
large rejection messages and made residual aggregation order independent of
arrival order. Expanded tests cover cross-sensor/field/purpose random-stream
independence, unknown nested configuration fields/versions, invalid timestamps,
large rejection collections, malformed evidence and output limits. All existing
tracked files, including Phase 74A/74B/75A/75B contracts/assets, are unchanged
against the expected parent/main commit. Only the seven new Phase 75C files
are included for GitHub review; raw evidence and machine-specific paths are
excluded. The feature branch is submitted for review without merging.
