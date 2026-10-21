# Phase 74B-1E — prebuilt-image physics verification

This is a separate experimental path using exactly:
`ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6`.
The local image is linux/amd64, Ubuntu 22.04, Gazebo 8.15.0 and includes Python transport
bindings. It is not the unbuilt Ubuntu 24.04 candidate or a completed dependency lock.
The Phase 74A 8.3.0 contract remains unchanged. The earlier custom-build candidates
remain unbuilt and separate from this experimental path. Experimental
8.15.0 observations must not be relabeled as Phase 74A scenario recordings.

From the repository root, default inspection launches nothing:

```sh
python3 -B simulation/gazebo-smoke/experimental.py
```

Explicit real test (requires Docker access and a new output directory):

```sh
python3 -B simulation/gazebo-smoke/experimental.py --run \
  --disk-path /mnt/c --output-dir /tmp/aegis-real-physics-UNIQUE
```

The launcher verifies the exact local RepoDigest, architecture, world/profile hashes
and at least 2 GiB host available RAM. It does not pull, install or build anything.
The container uses 1 GiB RAM (below the 2 GiB maximum), 1 CPU, 128 PIDs, no extra swap,
nonroot UID 10001, read-only root, bounded tmpfs, dropped capabilities, no-new-privileges,
no hardware/devices, no ports and network=none. Only this preparation directory is mounted
read-only at /opt/aegis, to supply the harness and SDF; no home, Docker socket or device
path is mounted. The previous no-mount build-candidate policy is unchanged.

The experimental SDF retains gravity, static plane and falling box and adds a contact
sensor and Contact system solely for collision evidence. The observation server starts
paused; subscriptions register before an internal world-control request unpauses physics.
That request advances the virtual world, not an actuator or vehicle command. Only the
server and observer communicate inside the same isolated network namespace and unique
Gazebo partition. External networking and host ports are never needed.

Actual pose, world-statistics (simulation clock and iterations) and contact messages
are recorded. Contact messages are decimated to at most one actual sample per 10 ms,
with timestamps retained; no values are fabricated or interpolated. The verdict requires
an observed initial height, advancing timestamps, free fall, measured ground/box collision
and a stable late height interval. World load or DART startup logs alone cannot pass.
The server is bounded to 2,000 x 1 ms steps, 35 s inside and 55 s host wall time.

Each new audit directory retains `container.log` and `report.json`, including image
identities, profile/world hash, observed samples, version, verdict, exit/OOM status,
cgroup memory.peak and memory/CPU counters, inspected security limits, host reserve,
server logs and cleanup result. Only the uniquely created test container/process group
is stopped/removed. Scratch files disappear with the container. Other services are untouched.
Synthetic unit fixtures are separate from reports marked `real_gazebo_transport`.

A passing report establishes only this bounded non-actuated physics test. It does not
validate PX4, flight, production integration, the 8.3.0 contract migration, byte-identical
image rebuilding or repeat-run physics determinism.

## Actual verification captured 2026-10-21

Run `/tmp/aegis74e-real-physics-003/report.json` **passed** with real Gazebo transport
observations; it is not a synthetic fixture. Its SHA-256 is
`56c2d7d8ad2d2fe39c5a25d129f00faf22b7344c7a3b3ab6ab5df042d4d954e8`.
The report and raw container log are retained outside Git for review.

- Exact image above, local image ID
  `sha256:6c8e5ebdd2a35796d4fd2cb0a1034438f32e86c9f540384128f074b346e1a6ac`.
- Gazebo 8.15.0, DART plugin loaded; experimental world SHA-256
  `b1a97a4bd9c0ac9908f7bc853ca439bbe3bc1921aa7be9f8dff1ee55788241e8`.
- 200 real model-pose samples from 0.010 to 2.000 simulation seconds.
- 30 clock/iteration messages, including paused startup at zero. The last received
  statistics message was at 1.951 s / iteration 1951; no final counter was fabricated
  from the configured 2000-step limit. The final pose timestamp was 2.000 s.
- First observed box center: 0.9994604500000001 m at 10,000,000 ns.
- First measured ground contact: 429,000,000 ns; 158 sampled contact messages identify
  the actual ground and box collisions, with contact positions and penetration depths.
- Final center height: 0.09999989388001289 m. Height range over the final 0.5 s:
  0.0000010000524656300636 m. Gravity trajectory and settling checks passed.
- cgroup memory.peak: 85,516,288 bytes (81.6 MiB); memory cap 1,073,741,824 bytes.
  No OOM events. Server and container exit code 0; container cleanup succeeded.
- Server/checker wall interval approximately 5.32 s. Minimum host available RAM
  observed by the launcher: 2,959,056,896 bytes.

Earlier attempts are retained, not overwritten:
1. `/tmp/aegis74e-real-physics-001/`: Docker refused its local logging configuration
   (compression with one log file). No server started. The experimental launcher now
   explicitly sets `compress=false`; finalization also applies that validated setting
   to the shared candidate launcher and Compose configuration.
2. `/tmp/aegis74e-real-physics-002/`: actual poses and clocks were collected, server
   exited normally, but no contacts arrived on the requested topic. The verdict failed.
   The actual Contact system publishes on the canonical world/model/link/sensor topic;
   using that observed topic produced the passing third run. The unused sensor topic
   override was removed from the experimental SDF and its identity updated explicitly.

All owned containers from these attempts were removed. That initial run established one bounded real physics pass; the additional repeatability
measurements below do not establish general determinism or PX4/Phase 74A compatibility. The
original build-candidate dependency-closure and builder prerequisites remain unresolved.

## Reproducing the pinned-image test

Requirements: Linux/amd64 Docker with cgroup v2 (`memory.peak`, `cpu.max`, `pids.max`),
a host Python 3 interpreter, at least 2 GiB available host RAM and 5 GiB free backing
storage. No host Gazebo, PX4, ROS, compiler or pip installation is required. The image
itself is Ubuntu 22.04 with Python 3.10 and Gazebo 8.15.0; it is not Ubuntu 24.04.

On a different machine that lacks the image, explicitly preload the exact digest:

```sh
docker pull --platform=linux/amd64 ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6
```

The launcher never pulls implicitly. From the checked-out repository root, run the
explicit command above with a unique output directory for each run. Set `--disk-path`
to the actual backing filesystem (`/mnt/c` for this C:-backed WSL VHD, `/` for a native
Linux root filesystem). Do not reuse audit directories. Verify `success`, `cleanup_ok`,
container exit/OOM status and the actual pose/clock/contact evidence in every report.

## Three additional sequential runs

The finalization runs used the same pinned image, world hash and resource envelope.
Every run passed, reported server/container exit 0, had no OOM events and was independently
checked absent from Docker after cleanup. Nginx Proxy Manager and DuckDNS stayed running;
all Wazuh containers stayed stopped. Audit reports/logs remain outside Git.

| Run | Pose / contact samples | Clock messages | Last observed iteration | Peak memory (MiB) | Wall interval (s) |
| --- | --- | --- | --- | --- | --- |
| 1 | 200 / 158 | 30 | 1921 | 104.46 | 5.422 |
| 2 | 200 / 158 | 32 | 1995 | 78.53 | 5.487 |
| 3 | 200 / 158 | 30 | 1935 | 78.30 | 5.353 |

All three runs observed initial z=0.9994604500000001 m at 0.010 s, first contact at
0.429 s and final z=0.09999989388001289 m at 2.000 s. Over the final 0.5 s, the vertical
range was 0.0000010000524656300636 m. At all 200 common pose timestamps, x/y/z values
were exactly equal across these three runs (maximum absolute difference 0). Full sampled
contact records were also equal. This is observed repeatability of this simple scene,
not a guarantee of deterministic physics across platforms, engines or more complex worlds.

Clock/statistics message sequences were **not identical**: wall-scheduled publication
and transport delivery produced different counts/timestamps and final observed counters.
No clocks were sorted, aligned to wall time or filled in. Wall duration, memory usage,
CPU counters and logs also varied. The complete reports are not byte-identical.

Reports and SHA-256 hashes for the local review:

- `/tmp/aegis74b-final-repeat-1/report.json`: `a97dbbc46cc97900bb1263d55f03c990d3d3124abba8cc526f9d94c9bfcca770`
- `/tmp/aegis74b-final-repeat-2/report.json`: `dee36e4e5c1b0cea070aa92d3d202b658ace57598401515d7b749cd69918cf90`
- `/tmp/aegis74b-final-repeat-3/report.json`: `139bdf31cf3cc7d34cb92bfe8241cb73b42829f8c115c54190b53c423ed64f5d`

The aggregate comparison is `/tmp/aegis74b-final-repeat-summary.json`. These temporary
paths describe review artifacts on the validation machine; no generated report, log,
image layer, package archive, credentials or machine-specific temporary file is included
in the source commit. Retain the external audit directory if long-term raw evidence is
needed. Synthetic unit fixtures remain separate from the real reports.

## Finalization validation and outstanding scope

The complete Python regression suite passed: **2,266 tests**, including the **244**
focused simulation/runtime/experimental tests. Both Compose configurations parse;
Python syntax, import-through-regression and tracked/untracked whitespace checks pass.
Real physics execution is a local manual validation, not a GitHub Actions physics job.
No frontend files or behavior changed, and no frontend CI execution is implied.

The Ubuntu 24.04 custom-image recipes still lack a complete authenticated dependency
bundle and bounded builder; they are preparation artifacts, not reproducibly rebuilt
images. The verified prebuilt image is sufficient for this isolated experiment only.
No PX4 launch, virtual flight, 8.3.0 contract migration, production integration or
external telemetry connection has been implemented or validated.
