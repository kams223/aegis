# Phase 76A offline multi-sensor replay

This is temporal alignment and read-only inspection of simulated aircraft
telemetry, not fusion, state estimation, aircraft control or an operational
recommendation. It has no live connection, network transmission, polling,
background service, Docker or Gazebo requirement.

## Input and reuse

The TypeScript engine in `web/monitoring-console/src/sensor/replay.ts` accepts
Phase 75D `offline_sensor_telemetry_inspection` files through the **unchanged**
`loadInspection` schema/semantic validator. It reuses `RecordRow`, `Timestamp`,
`Sensor`, exact uint64 parsing, and the original source/configuration metadata.
There is one implementation shared by the dashboard and the offline Node CLI.
The Python telemetry adapter, realism algorithm, v1 wire schema and established
inspection semantics are unchanged. Python `Timestamp`, `SensorTelemetry`,
`inspect` and `bounded_bytes` also produce the fabricated reproducible example.

`replayInspections(texts, evaluation, staleAfterNs)` is the bounded public text
entry point. `buildReplay(validatedDocs)` builds a reusable acquisition timeline;
`inspectReplay(history, evaluation, staleAfterNs)` evaluates it without reparsing.
Only documents returned by `loadInspection` should be passed to the lower-level
builder. It does not replace the loader's validation. Timeline entries reference
the loaded frozen records rather than cloning their fields.

## Clock, timeline and eligibility

- All clocks are caller-declared simulation domains. Matching opaque domain names
  are required; they are not a synchronization/epoch attestation. Mixed domains
  reject the replay as a whole, and unknown evaluation domains produce invalid
  selected-time states. No host clock or inferred conversion is used.
- Acquisition is when the recorded measurement was taken. Simulation time remains
  in its original record. Delivery is when it became available in that same
  declared domain, if the producer recorded it. Evaluation is caller-selected.
- Timestamps remain canonical decimal **uint64 nanosecond strings**, parsed using
  BigInt. Ordering requires acquisition <= simulation <= known delivery, as
  enforced by the existing loader. Ages are exact nonnegative decimal strings.
- The shared timeline orders acquisition, then sensor order **IMU, GNSS,
  barometer**, then input file position, then accepted-observation position within
  that file. Equal-time entries remain distinct; timestamp equality does not
  establish simultaneity or physical alignment. Different rates need no resampling.
- Eligibility requires acquisition <= evaluation and **known delivery <=
  evaluation**. Unknown delivery is conservatively unavailable; acquisition or
  simulation time is not substituted for availability. In particular, existing
  raw inspections with null delivery retain visible history but may have no
  eligible selected-time measurements. This is deliberately stricter than the
  unchanged Phase 75D freshness summary.
- Within each provenance channel, select the greatest eligible acquisition time.
  Equal acquisitions use the first entry in the stable timeline order. A delayed
  older arrival never supersedes a newer acquired eligible observation.
- Age = evaluation minus acquisition. Threshold equality is fresh; larger age is
  stale. Null values are missing/dropout, not zero. A newly eligible dropout
  replaces an older measurement with an explicit missing state; no fallback or
  interpolation fills the gap. A future-delivered dropout cannot erase a current
  measurement before it arrives.

A channel comprises sensor, full source identity (session, vehicle, component,
source ID, recorded origin, clock), original recording digest, raw/impaired origin,
and impairment configuration digest. Multiple channels produce an aggregate
`invalid` sensor state with `MULTIPLE_CHANNELS`; their individual states remain
separate. This means ambiguous aggregate provenance, not malformed individual
measurements. No raw/impaired/session/configuration preference is invented.

## Duplicates, ordering and diagnostics

Phase 75D rejects duplicate source/acquisition/origin observations. That behavior
is retained: a malformed inspection that claims duplicates as accepted records
still fails the loader. Original duplicate rejection diagnostics are carried
forward, but their unavailable rejected measurements cannot be reconstructed.
When two independently valid inspections overlap, the shared timeline retains
both observations and generates `DUPLICATE` diagnostics. No deduplication occurs.
Conflicting values at an equal channel/acquisition use the same first-input tie
rule; inspect the retained history to see the alternatives.

Known delivery regressions in supplied inspection order are reported, and the
producer's original `OUT_OF_ORDER`/`DELIVERY_REGRESSION` anomalies are retained.
Because Phase 75D normally sorts by delivery, the original arrival sequence cannot
be recovered from that sorted array; only its retained diagnostics can establish
an earlier regression. Newly computed diagnostics do not claim to recover it.

Replay diagnostics distinguish `input` facts (explicit dropout, duplicates,
rejections, ordering, selected-time stale age, conflicting recording digests)
from evidence `limitation` (missing history, unknown availability, no eligible
observation, multiple channels). Source `STALE` is namespaced `SOURCE_STALE` and
kept distinct from selected-time stale status. Physical-domain source labels do
not become accuracy attestations or automatic measurement repairs. Missing sample
counts/rates cannot be inferred from gaps alone.

Replay diagnostic `dataset` and `index` identify the input file and its accepted
observation position when known. Producer diagnostics refer to original input
indices, not accepted-array positions: replay `index` is null and the original
index, rejected sensor/severity/path/explanation or source acquisition is retained
in `detail`. Diagnostics are dataset-wide, including rejection details without
reliable timestamps; they are not guessed into selected-time intervals. Capping
reports `diagnostics_dropped` explicitly.

## Versioned output and provenance

The closed output is `offline_multisensor_replay`, schema version 1, defined in
`configs/simulation/multisensor-replay-v1.schema.json`. Its timeline's `record`
uses a local reference to the existing telemetry schema, not a competing sensor
record definition. No remote schema resolution occurs at runtime.

`inputs` retains exact selected-file SHA-256 hashes when loaded through the text
entry point, producer input-artifact digests when supplied, synthetic-fixture
markers and evidence attestations. The lower-level builder has no source bytes
and therefore leaves inspection byte hashes null unless explicitly supplied.
These are producer-supplied provenance, not authentication. Raw/impaired fields,
configuration JSON, digests, seed and native timestamps remain verbatim in each
referenced record. No source values are invented inside impaired records.

`sensors` always contains IMU, GNSS and barometer. Each channel has a
`history_index` pointing to its first timeline record for identity, and a
`timeline_index` pointing to the selected eligible record, or null. The referenced
record contains original values, acquisition/delivery and provenance; `age_ns`
and `status` describe selected-time inspection. Missing histories have no channels.
The full timeline deliberately includes future history for inspection; it must
not be confused with the selected eligible record references.

Malformed accepted records reject the file. Retained Phase 75D rejections can
include invalid timestamps, clock mismatch, bad provenance and other invalid
records. Invalid selected evaluation/threshold makes the in-process UI states
invalid without values. The CLI rejects invalid requests before emitting JSON,
writes an explicit error to stderr and returns exit code 2 with empty stdout.

## Offline example

With existing frontend dependencies, Python environment and supported Node:

```sh
export PATH="/tmp/node-v24.21.0-linux-x64/bin:$PATH"
cd /home/ali/Projects/aegis
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B \
  examples/multisensor_replay_fixture.py > /tmp/aegis76a-fixture.json
cd web/monitoring-console
node scripts/build_sensor_replay.mjs /tmp/aegis76a-cli
node /tmp/aegis76a-cli/sensor-replay.mjs \
  --domain fixture.sim --evaluation-ns 30 --stale-after-ns 15 \
  /tmp/aegis76a-fixture.json > /tmp/aegis76a-replay.json
sha256sum /tmp/aegis76a-replay.json
```

The fabricated fixture has 6 IMU, 2 GNSS and 3 barometer observations at different
rates, known deliveries, a barometer dropout and reordered GNSS delivery. It is
explicitly **not evidence**. To retain overlapping histories, append a second
Phase 75D inspection path with the same domain. File order is part of tie-breaking
and output provenance; reversing files can intentionally change output.

For the dashboard, launch the existing local console and choose Sensor Lab →
Sensor Telemetry, then select the generated Phase 75D fixture file. The new
**Shared multi-sensor replay** uses the existing evaluation/domain/threshold
controls and exposes all-sensor acquisition history independently of the existing
sensor filter. Its range cursor selects a historical entry without changing
evaluation or making that entry eligible. Selected-time panels and provenance
remain separate from the existing historical record inspector, charts and
original-versus-impaired comparison. The shared UI currently inspects only the
primary dataset; the programmatic/CLI entry point accepts up to two.

## Bounds, performance and limitations

At most two files, 8 MiB each, with **1024 total accepted plus rejected rows**.
Timeline length is at most 1024, diagnostics at most 4096, and serialized output
at most 8 MiB. CLI reads regular local files only, rejects symlinks and URL/UNC
inputs, reads with a strict byte bound and strict UTF-8, and never writes source
files. Output is completed and bounded before stdout is written. Generated bundles
must be built under `/tmp`; no production dependency or manifest changes exist.

The timeline is exact within the existing 1024-row bound, not sampled or expanded
into artificial uniform timesteps. Existing histories/charts retain Phase 75F's
bounded 256-point extrema/gap-aware sampling. Timeline construction sorts O(n log
n) references; evaluation makes three bounded linear passes and small channel
maps. Base diagnostics are reused and capped; no retained per-evaluation history,
large values copies, wall-clock timers or services are added. Parsing/export is
bounded but synchronous and can briefly block on large files.

Unknown delivery reduces selected-time availability; physical synchronization,
true arrival order omitted by the producer, rejected values, expected sample
rates and physical accuracy remain unknown. There is no sensor fusion, derived
state, frame conversion or real-world operational interpretation. The new panel
now has Phase 76A-specific Edge validation, documented in the final review below;
Phase 75F results are separate historical checks. Screen-reader output, physical
touch devices and browser peak memory remain unverified.

## Initial implementation validation and review manifest

Starting HEAD `427e603297ca4100562daf408a2104a07b701429` and clean tree were
verified. The checkout initially used `main`; the requested
`codex/phase76a-multisensor-replay` branch was created at that exact parent before
editing. No commit, push, merge, Docker or Gazebo run was performed.

| Check | Result | Measured wall time | Peak RSS |
| --- | --- | --- | --- |
| Replay + dashboard focused frontend | 30 passed (12 replay, 18 dashboard) | 14.45 s | 272 MiB |
| Complete frontend | 396 passed across 19 files | 90.99 s | 330 MiB |
| TypeScript | passed | 4.53 s | 268 MiB |
| Frontend production build | passed | 2.88 s | 235 MiB |
| Full Python regression | 2447 passed, 2 simulator opt-in skips | 146.05 s | 409 MiB |
| `git diff --check` and new-file whitespace audit | passed | — | — |

The Python runner reported 150.58 s internally; the table records external
`/usr/bin/time -v`. Peak RSS is a process/child maximum, not the sum of concurrent
workers. Frontend tests used two workers. Existing CLI child-process tests and
Python API tests required execution outside the sandbox, as in Phase 75F. No
runtime permission or dependency changes were added. Build artifacts are
`/tmp/aegis76a-dist` (477.77 kB JS / 120.69 kB gzip; 36.15 kB CSS / 8.14 kB gzip)
and `/tmp/aegis76a-cli` (bundled Node entry point). Logs are
`/tmp/aegis76a-{focused,frontend,typecheck,build,python,schema-final}.log`.

Three runs of each input produced identical bytes and SHA-256 hashes; all input
bytes remained unchanged. Fixture uses evaluation 30 ns / threshold 15 ns /
`fixture.sim`; recorded inspections use 2100000000 ns / 100000000 ns /
`gazebo75b.sim`. These are deterministic replay checks, not new accuracy evidence.

| Input | Rows | Output bytes | SHA-256 in each of runs 1, 2 and 3 |
| --- | --- | --- | --- |
| Fabricated mixed-rate fixture | 11 | 11849 | `c191ef0ee6333ac6ffaab5dcd193f4700c1ce076e96e7ef825e55788772cc0fe` |
| Existing Phase 75D raw inspection | 343 | 527300 | `9fa6d8cf62292588c1038adee87063f4c9fcaa39dfc8f9eb18fb65acd819cb47` |
| Existing Phase 75D impaired inspection | 343 | 666472 | `1c3a0c2d9d1893e6f4b674ea258bf9f2329b85b4212e3eb9eaaf6cc05dcd0770` |

The raw input remains
`8093ef55ed40183fa699e973c9ec175cf2eaf3ecb0d2085a54904a0958b1c0c3`;
impaired remains
`a7d4d104cbb4cecea67f2d69c6585f42a08e1f56d436aab817a82590d5bce0f1`.
Hashes, output files and per-run logs are `/tmp/aegis76a-hashes.json` and
`/tmp/aegis76a-{fixture,raw,impaired}-replay-{1,2,3}.{json,log}`.
First-run CLI measurements: fixture 0.20 s / 55 MiB peak RSS; raw 1.52 s / 75 MiB;
impaired 1.66 s / 78 MiB. Timings include validation, hashing and serialization
while other tests were running; no browser rendering benchmark is claimed.

Intended files:

- `configs/simulation/multisensor-replay-v1.schema.json`: closed output schema
  referencing existing telemetry records.
- `examples/multisensor_replay_fixture.py`: explicit fabricated Phase 75D input.
- `tests/test_multisensor_replay_fixture.py`: deterministic existing-contract check.
- `web/monitoring-console/src/sensor/replay.ts`: shared bounded temporal engine.
- `web/monitoring-console/src/sensor/replay-cli.ts`: read-only local file entry.
- `web/monitoring-console/scripts/build_sensor_replay.mjs`: temporary CLI bundle.
- `web/monitoring-console/src/sensor/SharedReplay.tsx`: shared timeline and states.
- `web/monitoring-console/src/sensor/SensorDashboard.tsx`: two-line integration.
- `web/monitoring-console/tests/sensor-replay.test.tsx`: replay, UI, schema and CLI coverage.
- `web/monitoring-console/tests/sensor-dashboard.test.tsx`: scope existing diagnostic
  queries to their original region now that replay also renders diagnostics.
- `simulation/MULTISENSOR_REPLAY.md`: semantics, example, results and limits.
- `simulation/SENSOR_TELEMETRY_DASHBOARD.md`: link and stricter availability note.

No existing Phase 74A–75F contract, loader, chart sampler, baseline, recording,
evidence, dependency manifest or lockfile changed. Generated outputs remain
outside Git. The initial stop-for-review browser gap is addressed below; unknown
availability and unrecoverable rejected values remain limitations.


## Final review and Phase 76A browser validation

Branch `codex/phase76a-multisensor-replay`, HEAD and merge base with `main` were
verified at `427e603297ca4100562daf408a2104a07b701429`. The working tree contains
exactly the 12 files listed above: three tracked modifications and nine new
files. Nothing is staged. The earlier manifest remains accurate; the only
application correction in this final review is in `SharedReplay.tsx`, with its
regression assertion in `sensor-replay.test.tsx` and the results here/in the
dashboard note. No Phase 76B work or changes to established contracts/evidence.

Review against Phase 75D and 75F confirmed separate acquisition/delivery/evaluation
semantics, exact stable equal-time ordering, different sampling rates, conservative
unknown-delivery handling, retained cross-inspection duplicates and producer
rejections, clock-domain isolation, raw/impaired provenance channels, existing
bounds and frozen source-record references. Existing Phase 75F historical charts,
sampling and comparison behavior remain unchanged.

Confirmed defect and fix: the replay panel said known delivery must “precede”
evaluation, which incorrectly suggested a strict inequality. The engine already
correctly includes delivery equal to evaluation. Text now says **at or before
evaluation**, with an assertion in the existing integration test. No replay
algorithm or output changed; all three recorded replay hashes below remain valid.

### Real-browser environment and exercised interactions

Used existing Windows Edge **155.0.4283.62**, headless via the native CDP debugging
pipe and existing Windows Node. No browser packages, binaries or production
dependencies were installed. The built UI was served locally on
`http://127.0.0.1:5184`; no existing server, Docker service or browser profile was
modified. An isolated `C:\Users\Public\aegis76a-review-pipe` profile was used
and this harness's browser was closed afterward. Windows interop required approved
execution outside the WSL sandbox.

The browser harness at `/tmp/aegis76a-review-browser.cjs` and log at
`/tmp/aegis76a-review-browser.log` cover:

- Sensor Lab → Sensor Telemetry navigation; local file selection of the existing
  343-record raw and impaired Phase 75D inspections. Raw history/charts render,
  shared selected-time states remain missing when delivery is unknown, and
  `AVAILABILITY_UNKNOWN` is shown. Impaired channels are labeled impaired and
  become fresh, stale or unavailable as evaluation changes.
- The 11-record fabricated mixed-rate fixture: no eligible observations at 1 ns;
  IMU available at its exact 2 ns delivery; barometer stale at 24 ns, dropout
  missing at 25 ns, and fresh again at 45 ns. Missing pressure is not zero-filled
  or replaced with the earlier reading. GNSS delivered at 45 ns is eligible at
  equality; its delayed older arrival at 60 ns does not replace acquisition 40 ns.
- Native keyboard Home/End updates the actual shared timeline entry text,
  including the equal-acquisition IMU-first tie. Fifteen Tab stops traverse file
  inputs, controls, old observation inspector, shared range and channel disclosures.
  Shift-Tab returns to the shared range, Enter opens native provenance disclosure,
  and the range has a visible focus outline and accessible value text.
- Evaluation domain `unknown.sim` shows `CLOCK_DOMAIN` and invalid states for all
  sensors. A temporary explicitly synthetic provenance-conflict variant renders
  `SOURCE_PROVENANCE`/`MULTIPLE_CHANNELS` and an invalid aggregate IMU state, while
  individual channels remain separate.
- Invalid version input gives a file-rejected alert and clears the shared replay.
- Desktop **1440×1000** and narrow **390×844** screenshots were inspected. Narrow
  document width equals viewport width in the tested fixture state (no horizontal
  overflow), with a channel disclosure open. The shared grid stacks on narrow
  screens. This is not an assertion about every possible input or device size.

File selection used CDP `DOM.setFileInputFiles`; navigation used DOM clicks and
evaluation changes dispatched native input/change events. Keyboard checks used
browser input events, not JavaScript `.click()` on the keyboard targets. The
initial harness attempts lacked Enter text and used the Alt bit for Shift; those
harness mistakes were corrected before the successful final run. They were not
application defects. Native operating-system file-picker keyboard interaction,
screen-reader announcements, physical touch input, browser peak memory, exhaustive
Tab traversal of every workspace, and pixel-baseline regression remain unverified.

Screenshots (outside Git):

- `/tmp/aegis76a-review-desktop.png`, `/tmp/aegis76a-review-narrow.png`
- `/tmp/aegis76a-review-narrow-full.png`
- `/tmp/aegis76a-review-raw.png`, `/tmp/aegis76a-review-impaired.png`
- `/tmp/aegis76a-review-clock.png`, `/tmp/aegis76a-review-invalid.png`

The final review CLI bundle is `/tmp/aegis76a-review-cli/sensor-replay.mjs`.
Three final runs per fixture/raw/impaired input were byte-identical and match the
SHA-256 table above exactly, with input hashes unchanged. Results are
`/tmp/aegis76a-review-hashes.json` and
`/tmp/aegis76a-review-{fixture,raw,impaired}-{1,2,3}.json`.

### Final-review regression results

After the wording correction, affected tests and the complete regression suites
were rerun successfully:

| Check | Final result | External wall time | Peak RSS |
| --- | --- | --- | --- |
| Replay/dashboard focused frontend | 30 passed | 9.30 s | 269 MiB |
| Full frontend | 396 passed across 19 files | 94.81 s | 330 MiB |
| Full Python | 2447 passed, 2 simulator opt-in skips | 141.98 s | 394 MiB |
| TypeScript | passed | 1.28 s | 268 MiB |
| Production frontend build | passed | 0.77 s | 241 MiB |
| Tracked/new-file whitespace audit | passed | — | — |

Python's internal test duration was 140.35 s. These process/child peak RSS figures
are not total concurrent memory or browser memory. Build/logs are
`/tmp/aegis76a-review-dist` and
`/tmp/aegis76a-review-{focused,frontend,python,typecheck,build,cli-build}.log`.
No source files, baseline recordings, dependencies or evidence were modified by
replay/browser validation. All 12 manifest files remain unstaged for review;
no screenshots, logs, bundles or temporary fixtures are in Git. No commit, push,
PR or merge was performed. Phase 76B was not started.
