# Gazebo-only smoke preparation — Phase 74B-1C

**Custom-build candidate: NO-GO for launch.** For the verified prebuilt-image
experimental path and real physics evidence, see [EXPERIMENTAL.md](EXPERIMENTAL.md).
The custom-build files below are prepared scripts and authenticated metadata, not a
built or validated physics runtime. No PX4 inputs are required. The existing six
74B-1A files, Phase 74A scenario/version contracts, monitoring and frontend stay intact.

## Version decision

The existing scenario requires Sim **8.3.0**. On 2026-10-21, the signed OSRF Noble
amd64 index advertised **8.15.0-1~noble**; the current gz-sim8 pool contained no 8.3.0
artifacts, including Jammy artifacts. This does not prove that every historical archive
or source build is unavailable. An 8.3.0 source build would require a separately pinned,
compatible dependency stack and a larger build budget; it is not reproducibly obtainable
from the checked current binary repository. No downgrade or alias is attempted.

This independent profile therefore proposes **8.15.0**, explicitly incompatible with
the Phase 74A 8.3.0 scenario. Do not pass these results to the Phase 74A adapter as if
8.3.0 ran. The full Gazebo/PX4 candidate remains unmodified and unverified. A future
versioned contract migration should add an opt-in 8.15.0 profile, keep old 8.3.0 fixtures
unchanged, reject cross-profile observations/recordings, retain exact timestamp domains,
and test lifecycle, recording provenance and repeat-run results under the new profile.
Current regression tests retain rejection of the 8.15.0 / Phase 74A scenario pairing.
A successful box test would not validate PX4, flight, determinism or compatibility.

## Verified metadata and remaining input boundary

`inputs.json` records official-source URLs, exact advertised versions, dependency
expressions, sizes and SHA-256 hashes for the seven selected OSRF packages. This is
**not** a full package lock. No .deb archive or base-image layer was downloaded.

- Ubuntu 24.04 linux/amd64 manifest:
  `sha256:a2d43bffc46670d7108bb3c0468c67c5557c4c92e83e1e34cbff1322ad1b94dc`.
  Docker Hub's official `library/ubuntu` index selected this architecture-specific
  manifest; its downloaded bytes matched the digest. This verifies registry identity,
  not an independently signed image attestation or an installed runtime.
- OSRF key fingerprint: `D2486D2DD83DB69272AFE98867170598AF249743`.
  Its SHA-256 and the signed InRelease/index hashes are in the inventory. `gpgv`
  reported a good signature; compressed index size/hash matched the signed SHA256
  entry. Trust was bootstrapped using the HTTPS key URL in the official installation
  documentation, not an independent fingerprint attestation.
- Selected packages: gz-sim8-cli, libgz-sim8, libgz-sim8-plugins at 8.15.0-1~noble;
  gz-tools2 at 2.0.4-1~noble; libgz-physics7-dartsim at 7.8.0-1~noble;
  python3-gz-msgs10 at 10.4.0-1~noble; python3-gz-transport13 at 13.6.0-1~noble.
  No GUI is launched, though the distributed Sim binary library depends on GUI/sensor
  libraries; a small world does not imply a tiny dependency installation.

The fetched metadata and signature-check evidence remain in `/tmp/aegis74c-evidence/`
for this review. That directory is temporary, not a durable offline artifact store.
Before building, retain the authenticated Ubuntu/OSRF InRelease files, signed index
hashes, keys and complete dependency closure in a durable reviewed bundle. Resolve
against the exact base image's package status, **not the host's installed packages**.
Every added/upgraded package needs its exact version, architecture, source authority,
SHA-256, signed release hash and actual .deb. Retain immutable mirrors/artifacts; a
mutable repository plus version strings alone cannot reproduce an installation.

`closure_complete` remains false and `closure_packages` null. Missing artifacts are
intentional blockers, not empty dependencies or evidence of package unavailability.
No complete binary closure has been downloaded or authenticated in this checkpoint.

## Prepared offline build strategy

Build context is this directory. An eventual `artifacts/debs/` contains **all** required
.deb archives. `closure_packages` entries must have exactly `name`, `version`,
`architecture` (amd64/all), `filename` (flat .deb basename), `sha256`, `source`
(ubuntu/osrf), and `release_sha256`. Those entries must be derived from authenticated
indexes. Include Python 3.12 and its transitive dependencies as well as Gazebo's.

`smoke.verify_bundle` checks the complete lock, direct OSRF pins, unique identities,
file set and archive hashes; it does not reconstruct the cryptographic signature chain
from the summary inventory. Signature authentication must happen when preparing the
lock and retained release/index evidence. Never change the completion flag to bypass
that work. Generate `artifacts/SHA256SUMS` from the reviewed closure, with each line
`<sha256>  debs/<filename>` in sorted filename order. Recheck the bundle immediately
before building. The Dockerfile checks the supplied inventory/world hashes and exact
archive set before offline installation; Python checks the bundle again afterward.

The Dockerfile pins the base manifest literally, mounts archives only for its install
RUN, uses `--network=none` and APT `--no-download`, and records installed packages.
No pip, compiler, PX4 or mutable source checkout is involved. Missing inputs or unmet
local dependencies fail; there is no online fallback. Package-content reproducibility
still requires the completed lock and retained archives; byte-identical image output
and repeatable physics are separate, unverified properties.

Future preparation command, after a complete lock and a resource-bounded BuildKit
builder exist (do not execute now):

```sh
python3 -B simulation/gazebo-smoke/smoke.py --verify-bundle simulation/gazebo-smoke/artifacts
# Compute INPUTS_SHA256 and WORLD_SHA256 from the reviewed files with sha256sum.
docker build --network=none --platform=linux/amd64 \
  --build-arg INPUTS_SHA256="$INPUTS_SHA256" --build-arg WORLD_SHA256="$WORLD_SHA256" \
  -t aegis-gazebo-smoke:candidate simulation/gazebo-smoke
```

Docker/BuildKit itself must be version-recorded and bounded to 1 CPU, memory and PIDs
before building; Compose service limits do **not** constrain builds. No such builder
has been created. Base-image transfer is still required; `--network=none` constrains
RUN steps, not Docker's registry access. Do not run the build while its gate fails.

## Resource policy and lightweight checks

The Gazebo-only **runtime** proposes 2 GiB MemAvailable, 256 MiB free swap, 5 GiB physical
backing disk free and one CPU. The container cap is 1 GiB with zero extra swap, leaving
at least 1 GiB available outside the container at the screening boundary. Only two
models, DART physics and bounded read-only subscriptions are used: no GPU, rendering,
sensors, compiler or autopilot. This justifies a separate conservative runtime trial
policy, **not** a measured capacity claim. Abort below 512 MiB host available memory,
at 90% runtime cap, or at timeout. A first execution must establish measured peaks.
Image-building still requires at least 3 GiB available RAM. The full PX4/Gazebo profile
and its 3 GiB/30 GiB gates are untouched. Never alter swap/WSL settings or other containers.

```sh
python3 -B simulation/gazebo-smoke/smoke.py
python3 -B simulation/gazebo-smoke/launch.py --disk-path /mnt/c
# Exit 2 is expected while the artifact closure or resources are blocked.
docker compose -f simulation/gazebo-smoke/compose.json config --no-interpolate --quiet
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 python -B -m pytest -p no:cacheprovider -q \
  tests/test_gazebo_smoke.py tests/test_simulation_runtime.py tests/test_simulation_foundation.py
```

## Prepared bounded launch and verification

After build prerequisites, resource checks and actual local image identity pass:

```sh
python3 -B simulation/gazebo-smoke/launch.py --disk-path /mnt/c --launch \
  --image-id "$VERIFIED_LOCAL_IMAGE_ID" --output-dir /tmp/aegis-gazebo-review-UNIQUE
```

The script rejects tags; requires a local `sha256:` image ID, matching input/world/version
labels and a complete verified archive bundle. It creates one uniquely named container,
no image pull, network, ports, devices, host mounts or Docker socket, nonroot UID 10001,
all capabilities dropped, no-new-privileges, read-only root, bounded tmpfs, 1 CPU,
1 GiB RAM/no extra swap, 128 PIDs, bounded Docker logs and 45 s host timeout. It stops
and removes only its owned container and retains logs/report in the new audit directory.
The container is not auto-removed before its exit/OOM state is captured.

`compose.json` documents the same isolation envelope; its default only prints readiness.
Use the launcher for actual testing so resource/image guards and cleanup run. Do not use
Compose overrides or invoke the container's `--inside` mode directly to bypass host checks.

Inside the container, exact installed package versions and `gz sim --versions` are checked
before imports/startup. The **prepared, unexecuted** server command is:

```sh
gz sim -s -r --iterations 2000 -v 4 /opt/smoke/gravity.sdf
```

It uses the fixed SDF hash, 1 ms steps, gravity -9.81 m/s², static plane, 1 kg / 0.2 m
box initially centered at z=1 m, and a named DART plugin. There are no external assets,
actuators, joints, vehicles or sensors. The sole pose publisher is an observation system.
Gazebo's internal loopback transport must work under `network=none`; failure is a failure,
not permission to enable host networking. Unique GZ_PARTITION is naming isolation only.

The checker subscribes read-only to model poses and world statistics. It preserves their
integer simulation nanoseconds, checks frame/model identity, strictly advancing time,
iteration/time agreement, bounded free-fall trajectory and settling near z=0.1 m. Missing
samples/discovery loss fail instead of fabricating observations. Clock-domain agreement
is restricted to this same isolated world; nothing is aligned to PX4 or monitoring clocks.
Callbacks are locked and bounded; logs and scratch paths are bounded. It captures server
exit, timeout, version output, observed samples, cgroup peak memory/events/CPU usage and
logs. It terminates its own server process group, unsubscribes and removes temporary
scratch files. Host/container failures retain diagnostics; synthetic unit-test observations
are explicitly not evidence that Gazebo executed.

## Next acceptance boundary

NO-GO until dependency artifacts, authenticated closure, bounded builder, sufficient
build resources and matching built-image identity exist. Then execute exactly one
Gazebo-only test, inspect actual logs/poses/time/OOM/peak memory and repeat to assess
reproducibility. PX4, flight, the Phase 74A migration and production integration remain
separate work. Do not claim physics success from configuration or these unit tests.

Primary references:
- https://gazebosim.org/docs/harmonic/install_ubuntu/
- https://gazebosim.org/api/transport/13/python.html
- https://gazebosim.org/api/sim/8/physics.html
- https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/cmd/cmdsim.rb.in
- https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/pose_publisher/PosePublisher.cc
