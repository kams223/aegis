# Phase 75D offline sensor telemetry v1

This adapter inspects recorded **simulation-origin** measurements. These are not validated real-world sensor readings. It has no Docker, Gazebo, device, wall-clock, or control dependency. Existing simulation `Contract`, `SourceIdentity`, `Timestamp`, `Field`, configuration validation, and structured `SimulationError` diagnostics are reused. General `Recording`/`Measurement` remains unchanged: its quantities and distinct receipt-clock requirement cannot represent these native sensor observations faithfully.

The closed wire envelope is `{"schema_version":1,"observations":[...]}`. See `configs/simulation/sensor-telemetry-v1.schema.json` for the structural JSON Schema and `SensorTelemetry.validate` for mandatory semantic constraints. Every property is required; unavailable optional values are null. Unknown fields, versions, types, frames, and units are rejected. Each nested contract also carries integer schema version 1. JSON Schema alone does not check coupled identities, complete vectors, uniqueness of field names, uint64 limits, time ordering, or configuration digests: load through the Python adapter for full validation.

Each observation contains:

- `observation_type`: imu, gnss, or barometer.
- `source`: recorded origin, caller-assigned simulation session/clock identity, passive_aircraft vehicle, sensor component, and stable `passive_aircraft::body::<sensor>` source ID. Generated session IDs include the original report SHA-256 to isolate runs.
- `acquisition`, `simulation`, `delivery`: existing Timestamp contracts with canonical decimal-string uint64 nanoseconds, explicit domain and ns unit. Delivery is null when unavailable. Acquisition <= simulation <= delivery when supplied. For native reports, simulation time equals the native simulation acquisition timestamp. No host receipt time is invented.
- `frame`: exact native sensor identifier. No frame conversion is performed. IMU is the coincident body FLU sensor frame; acceleration is specific force, angular velocity rad/s, orientation unit quaternion xyzw relative to initial world alignment. GNSS latitude/longitude are WGS84 degrees; altitude in metres is relative to the configured spherical origin, not a guaranteed geographic elevation. Barometric pressure is scalar Pa at the sensor origin, variance Pa². Optional `derived_altitude` in metres is accepted only if supplied explicitly; it is never calculated by this adapter.
- `values`: distinct named Field contracts, finite floats bounded to ±1e6, with exact units. IMU groups are optional but must be complete xyz or xyzw vectors when present, with at least one group. GNSS requires latitude, longitude, altitude. Barometer requires pressure; variance and derived altitude are optional. Null values represent a missing observation.
- `origin`: raw or impaired. Raw has null impairment metadata. Impaired retains the complete validated v1 configuration as canonical `config_json`, its canonical SHA-256, and decimal seed identifier. `source_sha256` identifies the original recording; the inspection's `input_sha256` identifies the actual input artifact. Replaying impaired values does not rerun noise or repair values.

Freshness uses only the required caller-supplied evaluation timestamp and nonnegative integer threshold. Age is evaluation minus acquisition, never delivery. Equality with the threshold is fresh. States are missing, future (acquisition after evaluation), pending (delivery after evaluation), stale, and fresh. The latest summary measurement excludes missing, future and pending observations. A stale measurement retains its original timestamp. Domain mismatch rejects a record. Callers must supply the actual simulation domain; the adapter does not synchronize or infer clocks.

Duplicates with the same source/acquisition/origin are rejected after the first valid record. Acquisition and delivery regressions are diagnosed in supplied order; they do not erase observations. Output sorts by delivery (acquisition when unknown), source ID, acquisition, origin, and session ID; timestamps remain strings. Record diagnostics retain original input indices. Impaired input rows use the exact Phase 75C Derived fields and an integer configuration version; known source diagnostic labels are retained separately as `source_diagnostics`, including Phase 75C latency-based STALE labels. These labels are not recomputed freshness: current freshness always uses caller evaluation time. A MISSING_OBSERVATION label must agree with null values; inconsistent rows are rejected. Physical-domain source diagnostics remain visible and do not attest valid physical readings. Summaries show per-sensor counts, latest available acquisition, freshness, missing values, rejections attributable to sensors, actual units/frames, and raw/impaired counts. All record provenance remains in the output. Empty streams are summarized as missing; the adapter does not infer absent samples from an expected rate.

Input modes are `raw` (75B full report), `impaired` (75C full derived replay), and `telemetry` (closed envelope). The tracked sensor-results.json and realism-results.json are summaries, not full recordings, and are rejected as replay inputs. Native report parsing reuses established native field names, units, frames and version identities; unrelated existing report metadata is not reinterpreted. A required caller-supplied SHA-256 pins input bytes. Semantic row errors are retained with indices while valid rows continue. Malformed JSON, duplicate keys, nonfinite numbers, envelope errors and file/output bounds failures reject the input as a whole with a structured CLI diagnostic and exit status 2. Physical calibration, quaternion normalization, geographic validity and atmosphere validation remain separate Phase 75B/75C checks; structural acceptance is not a physical truth attestation.

Limits: 16 MiB input, 1024 observations (native streams at most 256 each), 8 MiB output, contract strings of at most 1024 characters (identities at most 128), and nested contract arrays of at most 256 items. Native report metadata is bounded by file size; derived values are bounded to 10 fields, diagnostic arrays to 8 distinct known labels, and transformation arrays to 16 descriptions of at most 1024 characters. Full output is built and bounded before stdout receives bytes. Input contracts are frozen and input files are opened only for reading. No dependencies were added. Raw evidence and complete generated replay outputs belong outside Git.

From the repository root, using its existing Python environment:

```sh
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B examples/sensor_telemetry_replay.py \
  /tmp/aegis75c-final-replay-1.json --input-kind impaired \
  --source-sha256 8fdf1dfd7258a78103459ce5ba445bdddf3ecaebfa54a6a489c03e54f4e3aa1c \
  --domain gazebo75b.sim --evaluation-ns 2100000000 --stale-after-ns 100000000 \
  > /tmp/aegis75d-inspection.json
```

`examples/sensor_telemetry_example.json` carries explicit `example_kind: synthetic_fixture` and a no-evidence attestation inside the synthetic machine-readable inspection example. Its fabricated SHA-256 and fixture session identify illustrative values, not new Gazebo or hardware evidence. Tests construct synthetic native and derived fixtures so the regression suite does not depend on `/tmp` recordings. Manual evidence replay uses the previously verified full 75B and 75C artifacts and records validation metrics outside Git.

Final review replay references (evaluation 2100000000 ns, threshold 100000000 ns, domain gazebo75b.sim):

- Raw SHA-256: `8093ef55ed40183fa699e973c9ec175cf2eaf3ecb0d2085a54904a0958b1c0c3` (unchanged).
- Impaired SHA-256: `a7d4d104cbb4cecea67f2d69c6585f42a08e1f56d436aab817a82590d5bce0f1`. This replaces `2a01896c0a9a60673857f87d2f59c2af0fa0dc649a14adb03ffd6055b2c7bb32` because the inspection now retains Phase 75C source diagnostics. Sensor values, timestamps, impairment configurations, and original evidence are unchanged.

Each reference was reproduced with three offline runs and direct byte comparisons. References are derived outputs, not sensor accuracy attestations.
