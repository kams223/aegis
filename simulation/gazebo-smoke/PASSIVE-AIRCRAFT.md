# Phase 75A — passive virtual aircraft

This experiment starts at main `e081452`. It extends the merged Phase 74B
Gazebo-only test using **experimental Gazebo Harmonic 8.15.0**, not the Phase 74A
8.3.0 contract. All earlier runtime files and Docker services remain unchanged.

`passive-aircraft.sdf` is a single rigid body with four box collision shapes and
matching blue visual shapes. `passive-aircraft-world.sdf` contains a static ground
plane, gravity (0, 0, −9.81 m/s²), the Physics and Contact systems, and one local
include of that model. The include deliberately names the read-only container path
`file:///opt/aegis/passive-aircraft.sdf`; it requires no model download. When using
another layout, that URI must be adjusted and the world identity reviewed again.

The aircraft has no joints, motors, propeller, thrust, control surfaces, controller,
autonomy, navigation, or interception logic. The only model plugin publishes poses;
the contact sensor only observes collisions. Unpausing the world is simulation
control and does not actuate the aircraft.

## Mechanical assumptions

This is a nominal 2 kg, 1.8 m span small fixed-wing trainer approximation. Dimensions
and mass allocations are engineering assumptions for a passive drop test, not
measurements of a particular aircraft. SI units apply. Body axes are x forward,
y left, z up. The initial model origin is (0, 0, 1) m with zero roll/pitch/yaw;
the fuselage bottom starts at z=0.92 m. There is no landing gear.

| Component | Mass (kg) | Box size x/y/z (m) | Center x/y/z (m) |
| --- | --- | --- | --- |
| Fuselage | 1.20 | 1.20 / 0.12 / 0.16 | 0 / 0 / 0 |
| Main wing | 0.60 | 0.24 / 1.80 / 0.04 | 0 / 0 / 0.06 |
| Horizontal tail | 0.15 | 0.18 / 0.60 / 0.03 | −0.48 / 0 / 0.06 |
| Vertical fin | 0.05 | 0.18 / 0.03 / 0.24 | −0.48 / 0 / 0.18 |

The fuselage mass represents structure and payload; the lighter wing/tail represent
foam-like structures. Each component's assigned mass is distributed uniformly over
its ideal box for inertia calculation. Overlapping geometry is a collision/visual
approximation; the mass distribution is the additive component idealization, not
a uniform-density solid union. Masses are assigned once, explicitly; Gazebo does
not infer inertia from overlapping collisions.

The center of mass is **(−0.048, 0, 0.027) m** relative to the model/link origin.
The inertia tensor about that COM, expressed in the body axes, is (kg·m²):

```text
[ 0.17369700   0            0.00604800 ]
[ 0            0.19464525   0          ]
[ 0.00604800   0            0.35683575 ]
```

For each box, `Ixx = m*(dy²+dz²)/12` (cyclic for y/z). Translate to the composite
COM with `m*((r·r)*identity − outer(r,r))`, then sum all components. The nonzero
Ixz is intentional; it is a tensor entry, with the parallel-axis minus sign.
Unit tests independently recompute all six entries and check physical positivity
and principal-moment triangle inequalities. Inertial pose locates the COM while geometry stays in
the link frame. Contact uses Gazebo/DART defaults, not calibrated material data.

## Execution and evidence

`aircraft.py` adapts the verified Phase 74B `experimental.py` orchestration and
imports its pinned-profile validation. It directly reuses `launch.container_args`,
`launch.resources`, `launch.docker`, and `smoke` hashing, cgroup, version checking,
and owned-process cleanup helpers. The original smoke worlds, checker, launcher,
profiles, and Compose files are untouched.

The exact locally preloaded image is:

```text
ghcr.io/openrobotics/gazebo@sha256:e8a4787b76fb6c5a8165e81ce86e48f9dddc75937e1301ad75edd96b099ad7c6
```

The launcher verifies RepoDigest, Linux/amd64, and source world/model hashes. It
never pulls or builds. Default invocation prints the validated profile and starts
nothing. Explicit bounded run from the repository root:

```sh
python3 -B simulation/gazebo-smoke/aircraft.py
python3 -B simulation/gazebo-smoke/aircraft.py --run \
  --disk-path /mnt/c --output-dir /tmp/aegis75a-review-UNIQUE
```

Use `/` instead of `/mnt/c` on a native Linux backing filesystem. Requirements are
the Phase 74B local image, Docker access, cgroup v2 including `memory.peak` and
`pids.peak`, 2 GiB available host RAM and 5 GiB free backing storage.

The headless container has no external network (`network=none`), devices, ports,
or hardware access. It has UID 10001, a read-only root and source mount, dropped
capabilities, no-new-privileges, bounded tmpfs, 1 CPU, 1 GiB RAM with no extra swap,
and 128 PIDs. There are 2000 steps of 1 ms, a 35 s server wall limit, and a 55 s host
wall limit. Memory reserves and log bounds are monitored. Each run creates one
unique owned container and removes it, including after a failed physics verdict.

Subscriptions register before starting the paused server. Actual world statistics
trigger readiness, then the harness requests unpause. A lost service acknowledgement
is recorded independently: it cannot prove or disprove physics by itself. The
strict trajectory, clock, contact and settling checks still must all pass; paused
startup or a normally exiting server cannot pass without those observations.

The report retains model position and quaternion, world simulation timestamps and
iteration counts, contact collision identities, positions and penetration depths,
image identity, model/world hashes, harness/helper hashes, server logs, exit/OOM
status, inspected container limits, memory peak/events, PID peak, CPU counters,
wall time and host memory reserve. Pose sampling is 100 Hz. Contact decimation
retains one real contact record per 10 ms, rather than interpolating measurements.
Clock publication is asynchronous; final iteration counts are never filled in.

Velocity samples are interval-average finite differences of consecutive observed
positions (m/s), with both endpoint timestamps. They are explicitly labeled derived;
this pose stream provides no native twist observation, and no angular velocity is
claimed. Quaternion observations establish initial orientation and late rotational
stability. The verdict requires early identity orientation, expected gravity fall,
actual named ground contact, and at least 0.3 s of late full-pose stability near the
0.08 m support height (position/quaternion ranges <0.002). This permits small solver
jitter and is not a zero-velocity assertion.

## Tests and limitations

Activate a Python environment with the project test dependencies first.
Synthetic unit fixtures only test checker behavior and never become runtime evidence.
The explicit integration test creates a real bounded Gazebo container and asserts
its report, verdict, exits and cleanup. Run:

```sh
PYTHONPATH=src python3 -B -m pytest -q
AEGIS_REAL_GAZEBO=1 python3 -B -m pytest -q \
  tests/test_passive_aircraft.py --basetemp=/tmp/aegis75a-real-tests-UNIQUE
```

`AEGIS_DISK_PATH` can override the integration test backing filesystem path. The
ordinary suite explicitly skips its real-container test unless opted in.

This verifies passive rigid-body loading, gravity, ground contact and settling for
one level release. It does not validate aerodynamics, flight, structural flexibility,
real aircraft impact behavior, pixel-rendered appearance, hardware, PX4, production
integration, Phase 74A compatibility, cross-platform determinism or image rebuilding.
The pinned prebuilt image still inherits Phase 74B's unresolved source rebuild limits.

Next phase: repeat this passive test across initial roll/pitch and release heights;
measure sensitivity to contact parameters and geometric simplification; add native
linear/angular velocity instrumentation and longer settling intervals. Review those
results before introducing any aerodynamic model. Actuation and controllers require
separate scope and validation.

See `PASSIVE-AIRCRAFT-RESULTS.md` for actual execution results and retained evidence.
