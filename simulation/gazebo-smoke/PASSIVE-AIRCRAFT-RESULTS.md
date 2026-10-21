# Phase 75A execution results — 2026-10-21

The final real bounded test **passed** on experimental Gazebo 8.15.0 with DART.
The checkout started at main `e081452`. These initial measurements precede finalization.

Raw evidence from the initial final-pass run is retained at
`outputs/phase75a-review/final-pass/report.json` and `container.log`, copied without
modification from `/tmp/aegis75a-pytest-final/test_real_bounded_passive_airc0/real/`.
The report SHA-256 is
`20ce7e98c631bfa9b70c860c3a5c4277b9975c1257f799ed48811a62fa88b01b`.
Generated raw artifacts are ignored by Git; preserve the output directory for review.
The source-side `passive-aircraft-results.json` summarizes all attempts and includes
raw report paths/hashes, source hashes at execution, measurements, verdict and security policy.
It contains measured values, not synthetic unit fixtures.

## Final measured run

| Observation | Result |
| --- | --- |
| Image | requested `ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6` |
| Local image ID | `sha256:6c8e5ebdd2a35796d4fd2cb0a1034438f32e86c9f540384128f074b346e1a6ac` |
| World SHA-256 | `a2444761884218b419c71a8ba5c2249d304ca13b94850b4752b3c74f11be3035` |
| Model SHA-256 | `b3e2086296198b5ecff61606f92db3ef3cd071f943f55b913f5d51289a3f24bc` |
| Actual pose samples | 200, from 0.010 to 2.000 simulation seconds |
| First model position (m) | (0, 0, 0.9994604500000001) |
| First quaternion (x/y/z/w) | (0, 0, 0, 1) |
| Clock messages | 31 including paused startup; last received 1.946 s / iteration 1946 |
| First measured contact | 0.434 s; fuselage collision against ground collision |
| Actual contact samples | 157, with positions and penetration depths |
| Derived linear velocities | 199 interval averages from actual consecutive positions |
| Final model position (m) | (1.37086044e−9, 9.63920101e−19, 0.07980835874293275) |
| Final quaternion (x/y/z/w) | (−6.49240308e−18, 8.60894380e−9, −1.24461716e−20, 1) |
| Late vertical range (1.5–2.0 s) | 0.0004999421597609577 m |
| Largest late quaternion component range | 2.153202785782516e−9 |
| cgroup peak memory | 106,455,040 bytes (101.52 MiB), cap 1 GiB |
| cgroup peak PIDs | 17, cap 128 |
| CPU usage | 4,732,400 μs (2,948,249 user; 1,784,151 system) |
| CPU throttling | 34 of 64 periods; 571,447 μs throttled |
| Server/checker wall interval | 5.502 s |
| Minimum host available RAM | 2,496,720,896 bytes |
| OOM / memory max events | all zero |
| Server / container exit | 0 / 0 |
| World unpause acknowledgement | received |
| Owned container cleanup | succeeded; subsequent Docker listing has no test containers |

Advancing simulation time and the gravity trajectory were checked against actual
pose and clock observations, not inferred from startup logs. Initial identity
orientation and late full-pose stability passed. No final clock counter was invented
from the configured 2000-step bound. Native twist was not provided; derived velocity
provenance is explicit in each report. Contact settling permits the approximately
0.5 mm residual vertical jitter shown above.

## Retained attempts

All six raw report/log pairs are under `outputs/phase75a-review/`, with report hashes
in the JSON summary. All owned containers were cleaned up; no failed attempt was
overwritten or reclassified as a pass.

1. `initial-pass`: first direct real run passed.
2. `failed-control-reply`: first opt-in pytest attempt failed on the world unpause
   acknowledgement. A running clock at 2 ms was observed, but no sufficient pose or
   contact evidence was collected before cleanup. No physics success is claimed.
3. `failed-no-observations`: after recording acknowledgement independently of the
   physics verdict, another attempt exited normally with only paused clock samples
   and no poses/contacts. The strict verdict rejected it. The cause of these two
   intermittent startup/transport failures is not established; they remain a limitation.
4. `independent-pass`: a fresh direct run passed.
5. `standalone-pytest-pass`: the isolated real integration test passed.
6. `final-pass`: all 27 aircraft tests, including the real integration test, passed
   in 8.18 s. This run includes final harness/helper source hashes in the raw report.

There are no automatic retries that conceal a failed verdict. Successful runs validate
this bounded scene, not reliable startup across all conditions or general determinism.

## Regression validation

The new unit checks independently verify component inertia, model/world structure,
passivity and matching geometry; reject missing/wrong/nonfinite observations, invalid
orientation, clock/iteration mismatch, wrong contacts and unsettled motion; and verify
read-only default behavior, model identity gating, velocity provenance, isolation and
owned-container cleanup on mocked passing/failing physics outcomes.

The first full-suite invocation lacked the repository's required `PYTHONPATH=src`
and failed collection (63 import errors). The corrected restricted invocation stalled
during collection and was interrupted. Running with normal process access completed:
2290 passed and one explicitly skipped real-container test in 89.42 s. Two cleanup
unit cases were added afterward; the complete final suite was then rerun as below.

Final complete Python regression: **2292 passed, 1 skipped, 0 failed in 86.03 s**.
Command: `PYTHONPATH=src python3 -B -m pytest -q`.
The skip is the explicit real-container opt-in, which passed separately as part of
**27 passed, 0 skipped, 0 failed in 8.18 s** with `AEGIS_REAL_GAZEBO=1`.
The final logs are `outputs/phase75a-review/regression-final.log` and
`outputs/phase75a-review/real-test-final.log`; their hashes are in the JSON summary.
No frontend files changed, so no frontend test execution is claimed.

Final profile inspection, source hashes against the executed report, XML loading
through real Gazebo, and tracked/new-file whitespace checks passed. A read-only
Docker listing after all runs showed no owned test containers; Nginx Proxy Manager
and DuckDNS were up, and Wazuh containers were stopped. No unrelated service was
started, stopped, recreated or edited. Phase 74A 8.3.0 artifacts and prior Phase 74B
runtime implementation remain unchanged.

## Finalization review

Current remote main was fetched and remains `e081452`. The review independently
rechecked the 2 kg mass allocation, mass-weighted COM, all six inertia entries,
and principal-moment positivity/triangle inequalities. Tests now also tie the
calculation dimensions and offsets to the actual SDF collision geometry. Contact
validation requires the full scoped ground/aircraft collision identities and one
finite nonnegative penetration depth per position. New negative cases reject
another model using the same collision basename and missing depth measurements.
The model and world hashes remain unchanged.

The JSON summary now uses repository-relative artifact paths and portable equivalent
test commands, with no machine-specific absolute paths. It explicitly identifies
itself as a measured summary and labels raw artifacts as local-only and untracked.
A regression test checks these properties and preserves both failed attempts.
Earlier execution hashes and results remain historical records; the finalization
run records the reviewed harness hash separately.

The unchanged Phase 74B baseline passed a new real run: 200 poses and 158 contact
samples, normal server/container exits, no OOM, and successful cleanup. Raw evidence
is `outputs/phase75a-review/finalization-baseline/report.json` and its sibling log.

The explicitly enabled reviewed aircraft suite passed **30 tests in 9.36 s**.
The real run recorded 200 poses, 157 contacts and 199 derived velocity intervals,
used 102,309,888 bytes peak memory and 17 peak PIDs, and exited/cleaned up normally.
Raw evidence is `outputs/phase75a-review/finalization-aircraft/report.json` and its
sibling log. Both new report hashes are preserved in the JSON summary.

The earlier intermittent startup failures remain unresolved and documented above;
these new passes do not establish that the issue is fixed. No automatic retry was
added, and no failure was removed from the review record. There are no aerodynamic
forces or native velocity observations, and the small contact jitter remains.

Finalization complete Python regression: **2295 passed, 1 skipped, 0 failed in 85.84 s**.
The only skip is the real-container opt-in, which passed in the separate 30-test
aircraft run. The new regression log is
`outputs/phase75a-review/finalization-regression.log`; its hash is recorded in the
JSON summary alongside the earlier regression hashes.

The post-test Docker listing matched the pre-test service statuses: no simulation
containers remained; Nginx Proxy Manager and DuckDNS remained running; Wazuh remained
stopped. All raw report hashes were reverified, all raw artifacts are ignored under
`outputs/`, and no raw evidence or simulator log is staged for Git. Only the eight
reviewed source/test/documentation files comprise this change.
