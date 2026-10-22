# Phase 75B-R — startup diagnosis and bounded stabilization

This review starts at `c6d61cc97fcd2a069de2399a2c6f1bb37605a00a` on
`codex/phase75b-simulated-sensors`, updating PR #9 without merging it. The
pinned image, SDF world/model identities, passive mechanics, physics, sensor
configuration, resource limits and Phase 74A contract are unchanged. No flight
or actuator features are added. Only the sensor observation startup path changes.

## Evidence and causal limits

The historical rejected run (`aegis75b-finalization-reviewed/repeat-2`) started
its container at `2026-10-21T20:29:13.223319118Z` and finished at
`20:29:19.754443498Z`. It retained six paused time-zero clock messages, no poses
or sensor samples, a false unpause acknowledgement, and server exit zero. Its
cgroup reported no memory maximum/OOM events; cleanup succeeded. The original
harness did not timestamp receipt, discovery or control milestones, so their
precise historical wall times cannot be reconstructed. They remain unknown.

[Gazebo's pause/run documentation](https://gazebosim.org/api/sim/8/pause_run_simulation.html)
describes WorldControl pause requests and checking world statistics. The
[8.15.0 SimulationRunner implementation](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/SimulationRunner.cc)
increments its bounded-run processed-iteration counter only while unpaused.
Thus paused waiting does not exhaust `--iterations 2000`. A true control response
acknowledges a queued request; the world applies it during message processing.
It is not proof of a particular physics state at response receipt. Multi-step
control is a separate paused stepping mode; this experiment continues to use
one `pause: false` request and the existing 2000-step server bound.

The installed Python wrapper calls blocking `request_raw`. The
[transport13 binding source](https://github.com/gazebosim/gz-transport/blob/gz-transport13/python/src/transport/_gz_transport_pybind11.cc)
does not release Python's GIL for that call, while subscription callbacks acquire
it. The image-level experiment confirms the scheduling consequence: a 1 s request
to an unavailable diagnostic service blocked the Python heartbeat for about
1.014 s (only one heartbeat tick fell within the request interval).

A separate controlled test used the unchanged sensor world, an independent
observer/control process, and a deliberately unavailable request in the original
observer process. With an 8 s blocking request, an immediate snapshot on return
had **two paused clocks and zero poses/IMU/GNSS/pressure**, with the server already
exited zero. Meanwhile the independent witness captured **200 pose messages and
201/41/101 sensor messages**, with advancing clock/sensor simulation timestamps.
After the blocked observer yielded, its queued callbacks also arrived. This
reproduces the historical captured signature without a paused or broken physics
engine: the observer can be starved through the entire run and snapshot/unsubscribe
before pending callbacks execute. Diagnostic pose counts refer to Pose_V messages;
the aggregate pose header was zero, so progression is established by witness
clock/sensor stamps, not that aggregate header.

This establishes the GIL starvation and premature snapshot mechanism. The exact
original service-reply/dispatch interleaving that caused its 3 s request to time
out is not recoverable. Reply loss versus callback/transport dispatch contention
is not proven separately. A missing acknowledgement alone must not be called a
rejected or undelivered request. The immutable image and raw diagnostic hashes
anchor the finding; the transport source branch URL is explanatory, not an
independent claim that the prebuilt image was rebuilt from that branch head.

## Minimal reliability change

`sensor_startup.py` sends control from a separate process with **no subscriptions**.
The observer process never makes a synchronous service request. Moving the call
to a Python thread would not solve a GIL-holding binding, so the isolation must
be a process boundary. The helper inherits the same network-none container,
loopback transport partition, UID, CPU/memory/PID caps and read-only source mount.

The sequence is bounded and each run sends at most one control request:

1. Register all observer subscriptions before spawning the paused server.
2. Wait at most 15 s for an actual world-statistics message.
3. Start the control-only helper. Within 10 s it must discover the expected
   publisher and observer schemas on statistics, pose, IMU, GNSS and pressure
   topics, and the WorldControl/Boolean service schema. Discovery is polled every
   20 ms; the former unconditional 0.5 s sleep is removed.
4. Send exactly one unpause request with a 3000 ms timeout. Record send and result
   separately. Discovery polls are not control retries.
5. Keep the observer active while control runs. Startup is verified only after an
   advancing unpaused clock, the aircraft pose and all three decoded sensor streams
   arrive. This gate has a 25 s bound from server spawn; normal physical/sample
   validation must still pass. Acknowledgement or log messages alone cannot pass.
6. Retain late control results through a bounded child wait. Stop owned process
   groups, join diagnostic readers, unsubscribe, inspect exits/cgroups and remove
   the owned container. The existing 35 s server / 55 s host wall limits remain.

Every first milestone records receipt UTC and monotonic time, with simulation
nanoseconds where applicable. Container create/start/exit/removal milestones are
recorded on the host; Docker also supplies actual start/finish UTC. Server startup,
world initialization and world discovery log lines are timestamped as **received**,
not as exact internal initialization times. Controller-emitted timestamps and
observer receipt timestamps are both retained. Compare monotonic intervals only
within the same kernel/domain; use UTC to relate host and container records.

Diagnostics distinguish an unattempted control due to failed discovery, an
explicit negative response, running physics with missing required streams, fully
observed running physics with an absent acknowledgement, and only paused clocks
with delivery/observer state unresolved. Resource exhaustion is assessed separately
from memory/PID events, peaks, CPU counters, OOM state and monitor scheduling gaps.
No normal server exit is treated as successful startup without observations.

## Attempt accounting and artifacts

Raw artifacts remain outside Git beneath the external root identified as
`aegis75br-20261022`; set `AEGIS_EVIDENCE_ROOT` to its retained location for local
review. The machine-readable `startup-reliability-results.json` includes hashes,
per-run timelines, latency/clock/sample/resource metrics, failure classifications,
exit/cleanup results and service-snapshot hashes.

Diagnostic probes (`inspect_node.py`, `gil_probe.py`, `api_probe.py`,
`blocking_observer.py`, `blocking_observer8.py`, `blocking_snapshot.py`) are not
independent reliability runs. They include deliberate scheduling faults and an
independent witness; they are not synthetic sensor evidence. Their sources and
raw outputs are retained externally and hashed, including the witness helper.

Development pilots are also separate. `fix-pilot-1` failed because the first draft
helper omitted its script entrypoint: no request was sent, the startup gate timed
out and cleanup passed. That programming error and report are preserved.
`fix-pilot-2` corrected the entrypoint and passed; it preceded final log-bound and
child-wait refinements. Neither pilot is counted in the ten-run validation series.

`run-01` through `run-10` are ten sequential, independent real runs, with a fresh
container/partition each time, one request each and **no retries or replacement
runs**. Host memory/disk preflight is checked before each. The unchanged Phase
74B and 75A baseline runs follow the series. Each launch has a separate attempt
record, even if preflight or startup fails. The service snapshot comparison spans
all probes, pilots, sensor validation and baselines.


## Recorded validation results

All **10/10 sequential independent sensor runs passed**, each with exactly one
acknowledged control request and no retries. Each retained 200 poses, 201 IMU,
41 GNSS and 101 pressure samples. Native sensor timestamps spanned 1,000,000
through 2,000,000,000 simulation ns. Clock publication was asynchronous: counts
ranged from 69 to 101, with final observed clocks from 1.942 to 1.998 s. The
checker requires actual advance and a late clock, not an invented final tick.

| Measurement | Minimum | Maximum |
| --- | --- | --- |
| Startup verified from server spawn | 5.046 s | 6.452 s |
| First advancing clock from server spawn | 5.002 s | 6.380 s |
| Control round trip | 101.44 ms | 111.05 ms |
| Peak memory | 115.60 MiB | 116.08 MiB |
| Peak cgroup tasks (including threads) | 29 | 29 |
| In-container harness wall duration | 9.568 s | 12.850 s |
| Largest observer-monitor interval per run | 98.73 ms | 147.97 ms |

There were no OOM events, PID-limit events or timed-out independent runs. The
extra control process accounts for additional tasks/memory compared with Phase
75B; caps remain 1 CPU, 1 GiB/no additional swap and 128 tasks. Zero failures
in this small local series does not prove general reliability or determinism.
The intentionally blocked diagnostic and development pilot failure remain visible.

Example `run-01` reconstructs the startup stages below. Times are UTC; simulation
nanoseconds appear only for received simulation messages. Log rows are receipt
times. The controller's discovery/request/result rows use its emitted timestamps.

| Stage | UTC | Simulation ns |
| --- | --- | --- |
| Container create requested (host) | 2026-10-22T02:24:07.408694+00:00 | — |
| Container created (host) | 2026-10-22T02:24:07.517218+00:00 | — |
| Container started (Docker) | 2026-10-22T02:24:07.584054994Z | — |
| Subscriptions registered | 2026-10-22T02:24:08.247148+00:00 | — |
| Server initialization log received | 2026-10-22T02:24:10.514487+00:00 | — |
| World initialization log received | 2026-10-22T02:24:10.514792+00:00 | — |
| World discovery log received | 2026-10-22T02:24:10.514831+00:00 | — |
| Transport schemas discovered | 2026-10-22T02:24:13.936303+00:00 | — |
| Control request emitted | 2026-10-22T02:24:13.936458+00:00 | — |
| Control result emitted | 2026-10-22T02:24:14.041633+00:00 | — |
| First advancing clock | 2026-10-22T02:24:14.061358+00:00 | 2000000 |
| First pose | 2026-10-22T02:24:14.112154+00:00 | 10000000 |
| First IMU | 2026-10-22T02:24:14.060465+00:00 | 1000000 |
| First GNSS | 2026-10-22T02:24:14.056418+00:00 | 1000000 |
| First pressure | 2026-10-22T02:24:14.059442+00:00 | 1000000 |
| Startup verified | 2026-10-22T02:24:14.142211+00:00 | — |

The unchanged Phase 74B gravity and Phase 75A aircraft baselines both passed,
with zero server/container exits and successful cleanup. All five unrelated
Docker containers retained identical identities, images, config hashes, status,
start times and restart counts: DuckDNS, Nginx Proxy Manager, and the three
Wazuh containers. Every independent attempt ended with no owned containers left.

Focused validation: **192 passed, 2 opt-in skips**. Added tests cover schema-based
discovery deadlines, one-request control without subscriptions, the helper
entrypoint guard, paused/partial observation gates, rejection versus unknown
acknowledgement classification, and startup timeout with a nominal control ack.
Unit fixtures only test these decisions; real evidence comes from the isolated
Gazebo runs. CI continues to skip the opt-in Docker integrations.

Full Python regression: **2368 passed, 2 opt-in skips**, no failures, in 89.45 s.
The external logs `aegis75br-focused.log` and `aegis75br-regression.log` are
hashed under `tests` in the reliability report. This validation supports the
local fix; exact historical reply interleaving remains an explicit causal limit.
With the image fixed by digest, the process boundary avoids patching/rebuilding
its transport binding.
