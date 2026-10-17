# AEGIS simulation foundation (Phase 74A)

This standard-library-only package defines simulation metadata, local lifecycle orchestration,
and offline recording validation. It runs no physics, opens no hardware or network interface,
and is not imported by FastAPI, monitoring reducers, or the React illustrative simulation.
Importing it performs no discovery or startup. No Docker/Compose setup was found in the
baseline repository; this checkpoint does not add an unverified container image or install tools.

## Structure and local inspection

- `contracts.py`: closed version-1 frozen dataclasses, owned serialization, strict bounded JSON.
- `scenarios.py`: explicit local file loading and canonical SHA-256 scenario identity.
- `session.py`: pure session creation, lifecycle transitions, explicit simulation-time observations.
- `recording.py`: whole-recording validation with structured first-error diagnostics.
- `adapter.py`: typed simulator adapter protocol and unavailable Gazebo/PX4 implementation.
- `service.py`: local transition coordination; no HTTP server or simulator command execution.
- `__main__.py`: scenario validation and optional executable discovery only.

From the repository root:

```sh
PYTHONPATH=src python -B -m aegis.simulation \
  --scenario examples/simulation/virtual-hover.json --detect-dependencies
PYTHONPATH=src python -B -m pytest tests/test_simulation_foundation.py -q
```

Exit 0 means the scenario was validated, not that a simulator is installed or running.
The report explicitly says `physics_running: false`; adapter availability is reported separately.
Exit 2 reports scenario input/I/O diagnostics. Discovery uses `shutil.which` only: paths can be
`not_found`, `located_unverified`, or `probe_failed`, and observed versions stay null.
No binaries are executed. Docker/ROS 2 discovery is informative, not a required capability.
PX4 is often built outside PATH; `not_found` does not prove no build exists elsewhere.

## Declared example and reproducibility

`examples/simulation/virtual-hover.json` contains a fictional 20 × 20 × 5 m environment,
an x500 aerial declaration, a stationary ground-model placeholder, seed 42, a 10 s limit,
a 10 ms simulation step, and a 1 m hover *intent*. There are no flight commands, generated
measurements, SDF world/model assets, or evidence of flight performance. The ground placeholder
is not an implemented rover model.

The closed target profile declares **gz-sim 8.3.0** and **PX4 SITL 1.16.0**. These are scenario
requirements, not detected installations or a validated compatibility claim. Other profiles
are rejected pending an explicit contract/profile update. Gazebo documents Harmonic as
[gz-sim 8.x](https://gazebosim.org/docs/harmonic/install/) and
[8.3.0](https://gazebosim.org/libs/sim/) as a published release; PX4 documents the
[v1.16 Gazebo SITL workflow](https://docs.px4.io/v1.16/en/simulation/).

Repeated scenario loading and canonical serialization yield the same SHA-256. Object member
order/whitespace do not change identity; supplied array order, nulls, versions, parameters,
and numeric values do. This ensures metadata reproducibility only. Reproducible physics still
requires pinned simulator/autopilot commits, model/world hashes, plugin/engine/toolchain and
image digests, deterministic seeds/lockstep, parameters and repeat-run validation.

## Clock and lifecycle contracts

Every timestamp is an exact canonical decimal-string uint64 count of **nanoseconds**. No float
conversion occurs. `create_session` declares `sim:<session_id>` with a session-start epoch and
`wall:unix` with a Unix epoch. Both clocks are carried explicitly; stamps must match their
assigned domains. Simulation time starts at zero, advances in declared steps, and stays inside
the duration limit. Receipt wall time may regress because wall clocks can adjust. It never
advances simulation time or determines record ordering.

Allowed transitions:

- created → ready or failed
- ready → running or failed
- running → paused, completed or failed
- paused → running, completed or failed
- completed/failed → terminal

Only running sessions accept `advance`. Pure transition/advance functions require caller-supplied
runtime observation references; they never discover or attest an actual simulator. The service
requires validated adapter availability, the specific capability, matching session/scenario digest,
matching observed versions and state, and matching clock domains before accepting a transition.
Unavailable, timed-out, malformed or failed adapter responses produce `failed` with diagnostics,
without advancing time or producing measurements. Invalid requested transitions fail before any
adapter call. A lifecycle history has at most 128 entries; exhaustion rejects before adapter work.
Failure is logical session state; a future adapter must also own process cleanup and report actual
runtime loss. No external simulator state can be verified by this foundation stub.

## Recording boundary

Recordings contain at most 256 ordered records; JSON input is at most 1 MiB. Schemas reject
unknown/missing fields, duplicate keys, unsupported versions, nonfinite numbers, invalid identities,
units and frames. Fields nullable in the schema require explicit nulls in JSON. Nested collections
are tuples; exported documents are owned copies. Source identity includes session, vehicle,
component, source and clock domain. Original sequence and timestamps are retained; records are
never sorted. Simulation timestamps may be equal, but cannot regress within one full source identity.
Different source identities do not inherit each other's watermarks. Record times must lie within
the observed session frontier.

`simulated` describes supplied virtual-runtime data. `recorded` describes offline replay whose
provenance retains `original_origin: simulated`. `real` is a distinct declared classification,
explicitly rejected by this simulation subsystem rather than relabeled. No real-data integration
is provided. Provenance includes scenario digest, producer, local reference identity and nullable
observed simulator/autopilot versions. Unknown observed versions stay null, never scenario defaults.
A null measurement requires `MISSING_MEASUREMENT` / `unavailable`; it never becomes zero.

Supported supplied measurements are position, linear velocity (three components with explicit
units/frame), and battery fraction (scalar unit `1`, no spatial frame). No acquisition or generation
is provided. Position units are m, speed m/s, declared angles rad. `world_enu`/`body_flu` and
`autopilot_ned`/`autopilot_frd` remain separate labels: transforms are explicitly unimplemented.
No conversion or cross-source physical association is inferred.

## Before actual physics-based testing

1. Install and independently verify exact simulator/autopilot builds; capture immutable build,
   dependency and asset identities. Decide and test the actual compatible runtime profile.
2. Supply tested SDF worlds/models and a real ground-robot model; validate inertial, collision,
   sensor and actuator configurations and coordinate transforms.
3. Implement the simulator-only adapter with isolated process ownership, resource/network
   boundaries, bounded timeouts, startup/version/runtime handshakes, pause/resume/stop and cleanup.
   The present adapter deliberately has no executable capabilities even if binaries are located.
4. Implement actual runtime clock observations and measurement recording with provenance,
   lockstep/seed behavior and loss/timeout handling. Validate physics reproducibility empirically.
5. Add an explicit read-only recording export boundary to existing offline consumers only after
   contract compatibility review. ROS 2 bridging, PX4 communications, frontend linkage, simulator
   startup, real vehicles and vehicle command interfaces are outside this checkpoint.
