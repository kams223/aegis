# Offline physics runtime candidate (74B-1A)

For the separately verified Gazebo-only prebuilt-image experiment and repeatability
results, see [EXPERIMENTAL.md](../gazebo-smoke/EXPERIMENTAL.md). This full Gazebo/PX4
custom-build profile remains unbuilt and unverified.

Nothing here builds, pulls, installs, starts physics, or controls vehicles automatically.
The default Compose command prints Python's version and exits. There is no runtime
adapter, flight command, PX4 process, Gazebo process, network, host mount or published port.
JSON is used as a Compose-compatible YAML subset so policy tests need only the stdlib.

## Identity and compatibility

`profile.json` is a closed version-1 **candidate**, not a verified runtime or a reproducible
image release. PX4 v1.16.0 is pinned to peeled commit
`6ea3539157ca358c70a515878b77077af7d4611d`, verified by the preceding online preflight;
this offline checkpoint does not re-fetch it. Expected Gazebo is 8.15.0, with candidate
Noble package version 8.15.0-1~noble. These are expectations, not installed observations.
The base and output digests, dependency lock and observed versions remain explicitly null.
A future separately reviewed profile schema must represent verified artifact identities;
this candidate schema cannot be upgraded merely by filling in attestation fields.

Phase 74A's scenario and contracts still require 8.3.0. `check_scenario` rejects pairing
them with this 8.15.0 candidate. Never relabel observations or loosen the old validator.
A matching version observation is not evidence of flight compatibility. No clock, frame,
physics, model/world or autopilot parameter compatibility has been validated.

## Lightweight checks (no Docker daemon operations)

From the repository root:

```sh
PYTHONPATH=src python -B -m aegis.simulation.runtime \
  --profile simulation/runtime/profile.json --compose simulation/runtime/compose.json \
  --disk-path /mnt/c
docker compose -f simulation/runtime/compose.json config --quiet
PYTHONPATH=src python -B -m pytest -p no:cacheprovider \
  tests/test_simulation_runtime.py tests/test_simulation_foundation.py -q
```

The preflight exits 2 on resource failure: at least 3 GiB available RAM, 256 MiB free
swap and 30 GiB free **physical backing storage**, plus one CPU, are required. These are
conservative screening floors, not a guarantee of build capacity. Select the real VHD
backing filesystem (`/mnt/c` on this machine); virtual ext4 free space alone is misleading.
Exit 0 means checks passed only. `build_allowed` stays false while locks are missing.
No command in this module executes Docker or a simulator. Never adjust WSL memory or
stop existing containers automatically to make this check pass.

## Future build preparation — NOT executed in this checkpoint

Before building, independently review and provide a local build context containing:

- This Dockerfile and a verified Ubuntu 24.04 linux/amd64 image digest.
- `osrf.gpg`: OSRF signing key verified against a separately trusted fingerprint.
- `PX4-Autopilot/`: clean checkout at the pinned commit, complete recursively pinned
  submodules and full Git metadata (no shallow/missing Git directories).
- `requirements.lock` with exact versions and hashes for the PX4 requirements and
  transitive dependencies; `wheels/` with the corresponding Python 3.12 amd64 wheels.

Missing inputs deliberately fail. Do not use invented hashes, mutable source tags or
unhashed pip installs. The recipe still accesses Ubuntu/OSRF APT repositories during a
future build: transitive APT packages are **not locked yet**. Capturing `/opt/packages.txt`
records versions but does not itself make the build reproducible. A reviewed snapshot/
package-hash lock, signing-key identity, source-bundle hashes, toolchain inventory and
final image digest are prerequisites to a verified release. Candidate exact Gazebo package
availability must also be rechecked before any build; do not silently substitute a version.

After resource approval and all prerequisites, the preparation-image command would be:

```sh
# Variables must refer to reviewed local inputs; this does NOT compile SITL.
docker build --platform linux/amd64 --build-arg BASE_IMAGE="$VERIFIED_UBUNTU_IMAGE" \
  -f simulation/runtime/Dockerfile -t aegis-physics-runtime:candidate "$REVIEWED_CONTEXT"
```

Do not run this command now. Compose runtime limits do **not** constrain Docker image
builds. A separately approved bounded builder is required before executing it. Compilation
is also deferred: use one job (`cmake --build <reviewed-build-dir> --parallel 1`) in a
separate resource-limited build service; do not invoke PX4 `make ... gz_x500` targets,
which can launch simulation. No executable compilation service is supplied at this stage.

## Future inspection only — not flight

After a separately approved local image build and identity review:

```sh
docker compose -f simulation/runtime/compose.json run --rm --no-deps --pull never inspect
```

Only Python version inspection runs. The service has a read-only root, bounded tmpfs,
1 CPU, 2 GiB RAM/no additional swap, 128 PIDs, no capabilities, no privilege escalation,
nonroot user and no network. Do not add override files, devices, bind mounts or command
substitutions. The closed policy validator rejects any changes, including additional
services. No Gazebo/PX4 version probes or flight readiness are implied by this command.
Capture actual package versions, source/submodule identities and build hashes later;
keep unavailable values unavailable. Real simulation will need separate review of IPC,
clock mapping, bounded recordings, lifecycle/process cleanup and a compatible scenario.
