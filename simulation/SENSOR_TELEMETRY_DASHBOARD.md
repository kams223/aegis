# Phase 75E offline sensor telemetry dashboard

The existing React monitoring console now has **Sensor Lab → Sensor Telemetry**.
It inspects Phase 75D `offline_sensor_telemetry_inspection` v1 JSON outputs.
No Python contracts, Phase 74/75 evidence, impairment algorithms, or dependencies
were changed. No Gazebo run is needed.

## Launch locally

With the existing frontend dependencies installed and a supported Node version
(see `web/monitoring-console/package.json`):

```sh
export PATH="/tmp/node-v24.21.0-linux-x64/bin:$PATH" # Existing WSL Node installation
cd /home/ali/Projects/aegis/web/monitoring-console
npm run dev -- --port 5182
```

Open `http://127.0.0.1:5182`, select **Sensor Lab**, then **Sensor Telemetry**.
Use **Load synthetic example** for the existing explicitly fabricated barometer
fixture, or select your own Phase 75D inspection with the file picker. Nothing is
automatically loaded by this page. Refreshing/unmounting clears its local state.
There is no upload, persistence, polling, synchronization, telemetry subscription,
remote schema resolution, device connection, or control API. The local static
server serves application assets; telemetry stays in browser memory.

For a production static build, keep generated files outside Git:

```sh
npm run build -- --outDir /tmp/aegis75e-dashboard-dist
npm run preview -- --outDir /tmp/aegis75e-dashboard-dist --port 5182
```

The same UI can be served from any offline local static server. No remote APIs,
fonts, map tiles, or CDNs are used by the dashboard. Web Crypto requires a secure
context, which browsers provide for loopback HTTP. File URLs are not the supported
launch workflow. Runtime connections are limited to loading local app assets.

## Prepare inspection files

Use the existing read-only Phase 75D replay CLI described in
[SENSOR_TELEMETRY.md](SENSOR_TELEMETRY.md), with the recording's SHA-256 and explicit
simulation clock/evaluation. For example, after substituting an explicitly
selected recording and its actual digest:

```sh
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B examples/sensor_telemetry_replay.py \
  /tmp/selected-recording.json --input-kind impaired \
  --source-sha256 ACTUAL_RECORDING_SHA256 \
  --domain YOUR_SIMULATION_DOMAIN --evaluation-ns 2100000000 \
  --stale-after-ns 100000000 > /tmp/selected-inspection.json
```

Choose `/tmp/selected-inspection.json` with the browser picker. Raw native reports,
Phase 75C derived replays, and the closed telemetry wire envelope must first pass
through the Phase 75D CLI; they are intentionally not accepted as inspection
outputs. Files are opened for reading only and never modified.

## Inspect and compare

Overview shows dataset byte SHA-256, replay input digest when supplied, source
sessions, recording digests, simulation domains, accepted/rejected/missing/stale
counts, and acquisition/delivery ranges. “Valid” means structurally accepted,
including explicit missing observations; it is not physical accuracy validation.
Counts and ranges follow the sensor filter. Quality diagnostics retain original
input indices and remain dataset-wide so filtering cannot hide rejections.

The timeline scrubs observations in acquisition order, preserving exact uint64
nanosecond strings. Set evaluation nanoseconds, clock domain, and stale threshold
explicitly; initial values come from the inspection file. Freshness never reads
the viewer's clock. Age uses acquisition; equality with the threshold is fresh.
Missing, future, pending delivery, stale, and fresh states are separate. A domain
mismatch disables freshness rather than inventing synchronization. Scrubbing
selects a record independently of evaluation; the adjacent button explicitly
sets evaluation to the selected acquisition.

IMU plots show specific force, angular velocity and quaternion components when
available, with native body FLU framing. GNSS plots show timestamped latitude,
longitude and altitude, with explicit missing counts. WGS84 degree coordinates
and spherical-origin altitude are simulated references, not an accuracy or
geographic elevation attestation. Barometer plots retain pressure, variance and
explicit derived altitude if present. No altitude is calculated; atmosphere and
reference assumptions absent from Phase 75D remain unknown.

Charts use the selected observation's session, vehicle and source recording digest, and
its impairment configuration for impaired series. This prevents joining unrelated
runs or configurations. Select an impaired record to see its impaired histories.
Each chart uses acquisition time and a deterministic maximum of 256 points.
Stable min/max buckets preserve extrema within the available point budget;
segment boundaries prevent connections across omitted dropouts. See the Phase
75F reliability note below for exact guarantees and limitations. No interpolation
or zero fill occurs.

For original/impaired comparison, load a second Phase 75D inspection. The source
identity (including session and clock), original recording SHA-256 and acquisition
timestamp must agree exactly. Either raw or impaired may be the primary dataset.
Multiple candidate impairment configurations should be inspected as separate
files. Comparison never guesses correspondence by proximity. If the raw replay
was produced from different bytes than the original recording referenced by the
impaired replay, it intentionally does not match.

Phase 75D does not export original measurements inside impaired records, per-row
transformation descriptions, atmosphere assumptions, or the expected sampling
rate. This page preserves the available full impairment configuration, seed,
digests and source diagnostics, labels unavailable comparisons, and cannot infer
unrecorded dropouts. Source `STALE` labels represent recorded latency and remain
separate from selected-time freshness. The file's metadata is provenance supplied
by its producer, not authenticated evidence.

## Validation, bounds and performance

Files are limited to **8 MiB** (the Phase 75D output bound), **1024 accepted plus
rejected records**, and nesting depth 32. Two selected datasets may be held in
memory. Strict UTF-8, duplicate JSON keys, nonfinite numbers, unknown fields and
versions, invalid units/frames, incomplete vectors, uint64 overflow, timestamp
ordering, coupled sensor/clock identities, duplicate accepted observations,
configuration structure/digests/seeds, and inconsistent summaries/freshness are
checked before rendering. Malformed files produce explicit errors; a failed
primary load clears previous data. Invalid record details belong in Phase 75D's
`rejected` list; an invalid accepted record rejects the entire inspection file.

The browser validates against the checked-in telemetry JSON Schema using a small
validator for its exact keyword subset, plus a closed inspection-output schema
and semantic checks. It does not claim to implement arbitrary JSON Schema.
Vite permits imports of only the two specific repository-level schema/example
files in addition to the existing frontend root. No runtime filesystem path
selector or general-purpose path-serving feature was added.

Configuration JSON is kept verbatim for hashing (Python float spelling is not
round-tripped through JavaScript). Integer configuration fields above JavaScript's
safe integer range are explicitly rejected rather than rounded. Observation and
evaluation timestamps support the full uint64 range using BigInt. This is a
browser configuration limit, not a change to the Phase 75D contract.

All untrusted strings are React text nodes, never HTML, code, URLs, or styles.
Inputs are recursively frozen after validation; charts/sorting operate on
projections. SVG charts use no 3D engine or chart dependency. There are no timers
or background workers. Parsing is bounded but synchronous and can briefly block
the UI for a large file. Performance measurements and validation results for this
phase are recorded below; browser-process memory and visual device checks were
not measured.

## Checks

```sh
cd web/monitoring-console
npm run typecheck
npm test
npm run build -- --outDir /tmp/aegis75e-dashboard-dist
cd ../..
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B -m pytest -p no:cacheprovider
git diff --check
```

The focused `tests/sensor-dashboard.test.tsx` covers raw/impaired loads, all sensor
components, dropouts, diagnostics, invalid/oversized/malformed files, duplicate
keys, UTF-8, timestamp ordering, selected-time freshness, clock/version failures,
filtering/scrubbing, deterministic chart gaps, immutable source projections,
comparison identity, and safe untrusted metadata rendering.

Measured in this WSL environment with Node 24.21.0: the existing 343-record raw
inspection (457,440 bytes) validated in approximately 1.44 s, and the 343-record
impaired inspection (634,339 bytes) in 0.92 s under Vitest/jsdom while other checks
were running. Both source files remained byte-identical. These are validation
measurements, not browser rendering benchmarks. The final production build took about
0.63 s in Vite (1.08 s including process startup) with about 227 MiB peak RSS;
the entire console bundle was 467.69 kB JS (117.73 kB gzip) and 35.84 kB CSS
(8.10 kB gzip). The Python suite passed 2,446 tests with 2 opt-in simulator skips,
using about 395 MiB peak RSS. Logs, local compatibility checks and generated
builds are under `/tmp/aegis75e-*`, outside Git.


Final frontend validation: **379 tests passed across 18 files** with two workers,
about 61 s reported duration and 336 MiB peak RSS. The focused dashboard suite
passed **13 tests**, including the final impairment-rule validation adjustment.
TypeScript checking, the final production build, and `git diff --check` passed.
Existing CLI/API tests required running outside the sandbox after child-process
`EPERM` failures and an API test stall; no runtime permissions were added to the
application. No simulator was launched. No package manifest or lockfile changed.

Changed files for review:

- `README.md`: dashboard entry and documentation link.
- `simulation/SENSOR_TELEMETRY_DASHBOARD.md`: launch, semantics, bounds, results.
- `web/monitoring-console/index.html`: linked dashboard stylesheet under the existing CSP.
- `web/monitoring-console/vite.config.ts`: narrowly allowed shared schema/example imports.
- `web/monitoring-console/src/App.tsx`: dashboard integration.
- `web/monitoring-console/src/layout/workspaces.ts`: Sensor Telemetry navigation.
- `web/monitoring-console/src/layout/WorkspaceShell.tsx`: telemetry-specific source context.
- `web/monitoring-console/src/sensor/SensorDashboard.tsx`: loading, views, charts and timeline.
- `web/monitoring-console/src/sensor/model.ts`: validation and immutable projections.
- `web/monitoring-console/src/sensor/schema.ts`: fixed-schema validation and bounded JSON parsing.
- `web/monitoring-console/src/sensor/sensor.css`: responsive dashboard styling.
- `web/monitoring-console/tests/sensor-dashboard.test.tsx`: dashboard coverage.
- `web/monitoring-console/tests/workspace-shell.test.tsx`: updated navigation expectations.
- `web/monitoring-console/tests/hud.test.tsx`: updated linked-stylesheet expectation.


## Final review audit

All 14 files in the manifest were reviewed against parent commit
`620ce56519c8b8be2547418fa8a3e154285f5f85` on
`codex/phase75e-telemetry-dashboard`.

| Requirement | Review result |
| --- | --- |
| Local telemetry only | File API reads only explicitly selected files or the selected bundled synthetic example. |
| No aircraft control, navigation, targeting or interception | Changes contain inspection projections and viewer state only. |
| No telemetry networking or uploads | No network APIs in the dashboard; the existing `connect-src 'none'` CSP is preserved. |
| Missing and dropped readings | Nulls create chart gaps and explicit missing/unavailable labels; no zero fill. |
| Selected-time freshness | Uses supplied simulation evaluation and acquisition nanoseconds; no system clock. |
| Source and clock provenance | Original source identity, exact timestamps, recording/configuration digests and seed are retained. |
| Unavailable originals | Comparison requires exact provenance matches and explicitly labels absent originals unavailable. |
| Malformed or unknown-version data | Closed schemas and semantic validation reject the file with an explicit error. |
| Untrusted metadata | React text nodes only; no dataset HTML, code, links or styling is executed. |
| Bounds | 8 MiB per file, 1024 accepted plus rejected records, depth 32, and at most 256 points per chart. |
| Phase 74–75D baselines | No changes to their Python contracts, schemas, recordings, verified evidence or dependency files. |
| Desktop and smaller viewport usability | Responsive CSS and DOM behavior reviewed; **visual testing is unverified**. No browser automation connector or installed browser was found in the available tools/common executable locations. |

The final review rerun passed: 13 focused frontend tests, 379 frontend tests
across 18 files, TypeScript checking, production build, 2446 Python tests
with 2 opt-in simulator skips, and `git diff --check`. Its logs and
static build are `/tmp/aegis75e-final-review-*`, outside Git. Only the manifest's
14 source, test, configuration and documentation files are intended for the PR;
no generated build output, temporary recording or raw evidence is included.


## Phase 75F reliability and browser validation

Checkpoint: `codex/phase75f-dashboard-reliability`, parent
`5215dab417af3c363120d433e8141b2adb4e8888`, verified with a clean working tree.
The Phase 75E results above are historical; the results below supersede its
sampling and unverified-browser status. Python contracts, schemas, baselines,
evidence and dependency files remain unchanged.

### Sampling invariants and limits

The sampler sorts an independent projection by exact uint64 acquisition time;
equal timestamps retain input order. Original timestamps and source arrays are
unchanged. Invalid timestamps fail closed. Missing fields, dropouts and nonfinite
or nonnumeric field values become unavailable, never zero. File validation still
rejects malformed accepted records before the chart can receive them.

For a series longer than the budget, reserve the first and last valid readings.
Divide the time-ordered observation indices into equal buckets, using
`floor((budget - reserved endpoints) / 2)` buckets. Keep each bucket's minimum
and maximum available value, with earliest-index tie breaking. Fill unused slots
in input order and return selected indices in time order. The default and maximum
used by the UI is 256; the helper accepts integer budgets of at least two and
never exceeds the requested budget. An entirely unavailable series renders no
chart. No values or timestamps are interpolated.

Every unavailable observation advances a segment ID **before sampling**. A change
of source identity, recording digest, origin or impairment configuration also
starts a new segment. SVG lines are split when those IDs change, even if the
budget omits every gap marker. Histories additionally follow the selected
vehicle/session/recording/configuration, and raw/impaired have separate labeled
charts. This prevents a reduced point budget from reconnecting dropout gaps or
joining different channels.

A finite budget cannot preserve every local extremum or the endpoints of every
available segment. With budgets two or three, only valid endpoints are guaranteed;
with at least four, bucket extrema include the global minimum and maximum. Several
spikes/troughs inside one bucket can still compete, and intermediate segments can
be omitted entirely. Equal-time observations remain ordered but share the same
horizontal chart coordinate. Use the observation inspector for exact values.

### Accessibility and browser checks

File inputs retain wrapping labels; native buttons, selects, range controls and
provenance disclosures remain keyboard operable. Controls/disclosures have a
44 px minimum height, explicit visible focus, bounded file-input width and chart
grid minimum widths. Successful loading and selected observation/freshness have
status announcements; rejection and invalid clocks retain alert announcements.
The slider exposes its observation number, sensor and exact acquisition time.
Chart accessible names include origin, units, sampled range and clock domain in
addition to record/missing counts. Quality states and origins use text labels,
not color alone. Freshness remains based solely on the selected simulation
evaluation, independent of scrubbing and host time.

No WSL Chromium/Firefox, Playwright or Puppeteer installation was found. Existing
Windows Edge and Windows Node were available. WSL had about 2.4 GiB available RAM,
1 GiB swap and 928 GiB free disk at the initial check. No packages or browser
binaries were downloaded. The sandbox blocked Windows interop and existing CLI
child processes; approved execution outside it was required. Edge rendered a
blank page, but Windows denied a remote-debugging TCP port. A temporary CDP pipe
harness using only existing Windows Node/Edge successfully exercised the local
production build at `http://127.0.0.1:5183`.

Browser checks passed for Sensor Lab → Sensor Telemetry navigation, explicit
synthetic loading, local file selection, real 343-record multisensor rendering,
visible SVG charts, keyboard End scrubbing, GNSS filtering, diagnostic-section visibility,
comparison with unavailable mismatched recording bytes, matching synthetic
raw/impaired comparison, and invalid-file alerts/clearing. Desktop was 1440×1000;
narrow was 390×844 with document width equal to viewport width (no horizontal
overflow) in the tested GNSS-filtered state. The browser fixture had no rejected
records, so populated rejection/ordering diagnostics were covered by DOM tests,
not asserted in Edge. Navigation used programmatic DOM clicks; the range End
interaction used browser keyboard events. Full Tab-order traversal, file-picker
dialog keyboard interaction and screen-reader announcements were not exercised
in Edge. Screenshots were inspected; this is not a pixel-baseline regression
suite or a screen-reader/device certification.

Harness/logs and screenshots are outside Git:

- `/tmp/aegis75f-browser.cjs`, `/tmp/aegis75f-browser.log`
- `/tmp/aegis75f-desktop.png`, `/tmp/aegis75f-narrow.png`
- `/tmp/aegis75f-invalid.png`, `/tmp/aegis75f-comparison.png`
- `/tmp/aegis75f-charts.png` (desktop chart viewport)

The temporary Edge profiles are `C:\Users\Public\aegis75f-browser` and
`C:\Users\Public\aegis75f-pipe`. Only this phase's browser processes were
closed; no existing browser sessions or Docker services were changed.

### Final validation and performance

Final results and peak RSS are recorded below. Measurements use `/usr/bin/time
-v` on WSL; peak RSS is a process/child maximum, not the sum of simultaneously
running workers or Windows browser memory. Checks ran alongside other validation
work, so elapsed times are environment-dependent. Chart work is bounded by 1024
input observations and 256 output points; no new timers, retained datasets,
production dependencies or network behavior were added. Parsing remains bounded
and synchronous, and the existing two-file memory limit remains.

Remaining risks: extrema competition under small budgets, unavailable source
values and expected rates, unverified screen-reader output and physical touch
devices, and unmeasured Windows browser peak memory. The browser harness and
screenshots are temporary review artifacts rather than committed infrastructure.


| Check | Final result | Wall time | Peak RSS |
| --- | --- | --- | --- |
| Focused dashboard | 18 passed | 6.41 s | 266 MiB |
| Full frontend, two workers | 384 passed, 18 files | 61.99 s | 332 MiB |
| TypeScript | passed | 2.50 s | 277 MiB |
| Production build | passed | 1.19 s (Vite 559 ms) | 231 MiB |
| Full Python regression | 2446 passed, 2 opt-in simulator skips | 156.51 s | 395 MiB |
| `git diff --check` | passed | — | — |

The Python runner reported 163.14 s internally; the table records the external
`time` measurement. Build output is `/tmp/aegis75f-dist`. Final JS is 468.72 kB
(118.12 kB gzip) and CSS 36.15 kB (8.14 kB gzip); see the build log for exact sizes.
Logs are `/tmp/aegis75f-{focused,frontend,typecheck,build,python-full}.log`.
The initial Python collection attempt omitted `PYTHONPATH=src` and was corrected;
a sandbox rerun stalled in existing API tests and was stopped before the successful
unrestricted run. Existing frontend CLI tests likewise needed unrestricted child
process execution. No production permissions were changed.

Changed-file manifest for Phase 75F:

- `web/monitoring-console/src/sensor/model.ts`: stable extrema sampling and segment IDs.
- `web/monitoring-console/src/sensor/SensorDashboard.tsx`: gap-safe SVG paths,
  selected-vehicle isolation, chart text alternatives and status/slider semantics.
- `web/monitoring-console/src/sensor/sensor.css`: focus, control targets and width bounds.
- `web/monitoring-console/tests/sensor-dashboard.test.tsx`: five new focused
  regression cases plus corrected first-valid-reading expectation; existing tests
  continue to cover selected-time freshness, provenance, malformed/oversized files,
  invalid accepted records, raw/impaired distinction and unavailable comparisons.
- `simulation/SENSOR_TELEMETRY_DASHBOARD.md`: reliability invariants, limitations,
  browser environment, screenshots and measured results.

No baseline, dependency manifest, lockfile, evidence or generated artifact appears
in the diff. At the initial implementation checkpoint, no Gazebo run, commit, push or merge
was performed; the changes were stopped for review.

### Pre-PR audit

The five-file diff was reviewed again against the Phase 75F parent. No confirmed
implementation issue required a functionality change. Browser claims were narrowed
to the interactions actually asserted by the retained Edge harness/log; this audit
did not rerun Edge or expand the existing device/accessibility coverage.

The pre-PR rerun passed 18 focused dashboard tests, 384 frontend tests across 18
files, TypeScript checking, production build, 2446 Python regressions with two
opt-in simulator skips, and `git diff --check`. Its logs are
`/tmp/aegis75f-audit-{focused,frontend,typecheck,build,python}.log` and build output
is `/tmp/aegis75f-audit-dist`. Peak RSS was about 212 MiB focused, 330 MiB full
frontend, 274 MiB typecheck, 240 MiB build and 394 MiB Python. Only the five files
listed above are intended for the commit; generated artifacts, dependencies,
contracts, baselines and evidence remain outside the diff. GitHub Actions status
will be reported on the PR; the existing workflow runs Python tests only.


## Phase 76A shared temporal replay

The primary dataset also exposes a shared acquisition timeline and selected-time
IMU/GNSS/barometer panels. Known delivery is required for these panels; raw files
with unknown delivery remain historical inspection only. Existing Phase 75D
freshness summaries, charts, comparison and evidence are unchanged. See
[MULTISENSOR_REPLAY.md](MULTISENSOR_REPLAY.md) for eligibility, provenance channels,
diagnostics, bounds, the offline CLI and reproducible fabricated example.
Phase 75F browser results above do not cover the new replay panel.

Phase 76A now has separate real-browser checks in existing Windows Edge, covering
the new panel, delivery-boundary/status transitions, clock/source warnings,
keyboard traversal and desktop/narrow layouts. See the final review section of
[MULTISENSOR_REPLAY.md](MULTISENSOR_REPLAY.md) for the exact coverage, screenshots
and remaining device/screen-reader limitations. The delivery explanation was
corrected to “at or before evaluation” to match the existing inclusive rule.
