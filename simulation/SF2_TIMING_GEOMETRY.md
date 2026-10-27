# SF-2: Timing, Geometry and Uncertainty Integration

SF-2 is an additive, offline, non-actuating integration boundary. It consumes
normalized external-object evidence and SF-1 admissions. Native aircraft
telemetry (Phase 75D), multi-sensor replay (Phase 76A), and the legacy scalar
FusionEngine are unchanged. It performs no association, tracking, estimation,
pursuit, interception, engagement, actuation or external transmission.

## Public interfaces and files

- `src/aegis/fusion/timing.py`: `TimingRequest`, `align_time`, `TimingResult`,
  `AlignmentRequest`, `align_batch`, `AlignmentResult`, `AlignmentBatch`.
- `src/aegis/fusion/geometry.py`: `LinearTransform`, `propagate_covariance`,
  `ExactCovariance`, `PropagationResult`, `GeometryRequest`,
  `transform_measurement`, `GeometryResult`.
- `src/aegis/fusion/acquisition.py`: `Acquisition`, `inspect_acquisitions`,
  `AcquisitionResult`, `AcquisitionBatch`.
- Three corresponding `tests/test_fusion_{timing,geometry,acquisition}.py` files
  provide analytical, adversarial and integration coverage.
- This document and an additive README entry complete the change manifest.

All operations are pure, independent of wall-clock time and I/O. Frozen result
containers retain source references without mutating observations, covariance,
clock mappings, calibration or ledgers. Callers retain ownership of input data.
Result dataclasses are records, not authentication or authorization tokens;
only the public validation operations establish their documented guarantees.

## Temporal semantics

Acquisition records when a measurement was made. Delivery records when it became
available. Evaluation is explicitly selected by the caller. A shared clock label
is an explicit input assertion, not proof of physical synchronization. Different
labels require a caller-supplied `BoundedClockMapping`; no matching-label heuristic,
clock fitting, mapping graph, extrapolation or wall-clock fallback is used.

`align_time` independently maps acquisition and delivery into evaluation time.
It preserves both source timestamps and mappings. Existing clock infrastructure
computes exact affine values and outward-rounded enclosing float bounds.
All eligibility comparisons use exact `Fraction` representations of those bounds.
Let acquisition be [a,b], delivery [c,d] and evaluation e:

- a > d rejects an inconsistent causal declaration.
- b > c defers causally ambiguous evidence.
- d > e defers pending or ambiguous availability.
- e-a > maximum age defers stale evidence; equality is eligible.
- Missing delivery remains unknown; acquisition is never substituted.
- Acquisition and delivery in the same source clock must be causally ordered
  before mapping; uncertainty cannot hide a confirmed source-clock reversal.
- Two explicit mappings for the same clock pair must have intersecting error
  bounds throughout their overlapping validity interval. Exact affine differences
  are checked at both inclusive endpoints. Disjoint validity intervals do not
  establish a contradiction, and no relationship between different source clocks
  is inferred.
- `max_age_seconds=None` explicitly disables age rejection.

`align_batch` attaches an explicit acquisition mapping through existing
`DerivedSensorEvidence`, then delegates once to SF-1 `admit_batch` in caller
order. Existing contradictory mappings reject rather than overwrite provenance.
Delivery must satisfy the existing SF-1 point-time contract in evaluation's
domain. Bounded delivery intervals can be inspected with `align_time`, but are
not collapsed into a favorable point for admission. Equal timestamps preserve
input ordering. Delayed observations are not reordered. Duplicate/conflict
precedence, ledger capacity and transactional rollback are inherited from SF-1;
deferred/rejected preparations do not reserve evidence identity. Operation IDs
and revisions remain in the wrapper result, independently of SF-1 fingerprints.

## Supported geometry

Column-vector convention: p_out = J p_in + offset. Axes and component units are
explicit in `MeasurementBasis`; frame names alone do not establish compatibility.

| Operation | Basis and behavior |
| --- | --- |
| identity | Entire basis unchanged, exact identity J and zero offset, 1–4 axes |
| pixel_affine | Two image-point axes u_px,v_px in px; explicitly declared 2×2 map and pixel offset |
| radar_cartesian | Existing radar polar projection, then explicit static rigid R p + t in metres |
| camera_direction | Existing calibrated ray and explicit selected pixel, then R d only |

Cartesian bases use x_m,y_m,z_m and metres. Direction bases use
direction_x,direction_y,direction_z and dimensionless components. Radar uses
+x forward, +y left, +z up; camera optical axes use +x right, +y down, +z forward.
Rigid transforms retain the existing proper-rotation tolerance (1e-12) and
floating geometry arithmetic without repair. Same-frame rigid transforms require
exact identity. Static pose validity is a caller assertion, not estimated here.
Camera translation never supplies depth or relocates a ray origin. Positive-range
radar without elevation defers instead of creating z=0. Existing zero-range radar
origin semantics are preserved. Range rate is not converted into velocity.

Pixel affine values use exact arithmetic. Radar/camera geometry uses existing
projection helpers; no nonlinear covariance Jacobian is inferred. The source
SF-1 admission is revalidated before use, with all source timing, evidence and
correlation provenance retained. Unsupported operations, frame mismatches and
inconsistent declared Jacobians produce structured rejection. Optional rigid
arguments must be either `None` or a valid explicit transform; false-valued
invalid inputs never select identity. Camera operations reject radar evidence.
Known radar source-frame mismatches reject even when elevation is unavailable.

## Covariance policy

`propagate_covariance(uncertainty, transform, restrictions=())` supports one
explicit linear operation on an SF-1 `ValidatedCovariance`:

    R_out = J R_in Jᵀ

J is a finite, immutable matrix with dimensions matching explicit source and
destination bases. Identity, pixel-affine, Cartesian rigid and direction-rotation
operations are closed choices; rigid Jacobians/offsets must match the supplied
`RigidTransform`. Translation does not change covariance. Raw radar polar and
camera pixel uncertainty cannot be rotated as though already Cartesian/directional.

The numerical policy is exact rational arithmetic for supplied integers and IEEE
float values. Output `ExactCovariance.matrix` contains immutable `Fraction`
entries. Negative zero becomes rational zero in derived output; the source
numeric representation remains untouched. Exact symmetry, all principal minors and rank are checked; no jitter,
clipping, symmetrization, tolerance or rounding is applied to covariance. Singular
and zero covariance retain `REQUIRES_SINGULAR_MODEL`. Marginal propagation does
not imply joint compatibility or independence; input restrictions are preserved
and conservative no-combination restrictions added. Source uncertainty/model
provenance and transformation identity/revision are retained.

Exact output can exceed finite float magnitude. It has no implicit conversion to
an SF-1 declaration, wire schema or recursive propagation input. Unknown
uncertainty returns deferred with the original unknown object; no identity matrix,
confidence-to-covariance conversion or independence assumption is substituted.

Radar Cartesian or camera direction processing requires a separate explicit
`projected_uncertainty` declaration in the **source projected basis**. It may be
unknown. When absent/unknown, geometry remains inspectable but the operation is
deferred. Known projected covariance is validated through SF-1 and then propagated
by the declared rigid Jacobian. Results flag that the nonlinear projection was
not propagated and that projected uncertainty is caller-declared. This declaration
never replaces or reinterprets the original raw measurement covariance.

## Acquisition completeness

`Acquisition` explicitly names sensor, session, acquisition ID, optional acquisition
time, status, ordered observation tuple and optional reason:

- `completed` requires a time and no unavailability reason. A nonempty tuple is
  completed-with-observations; an empty tuple is explicitly completed-empty.
- `unavailable` and `unconfirmed` require a reason and no observations; time may
  remain unknown. Missing callbacks are not represented as empty acquisitions.

Observation sensor identity and clock domain must match the acquisition; times
may differ and do not imply simultaneity. No implicit clock conversion is made.
Repeated acquisition keys in the explicit batch yield duplicate or conflict
diagnostics from deterministic content fingerprints, preserving order. Invalid
acquisitions never reserve keys. There is no hidden acquisition ledger, miss
counter, watermark or inference about physical coverage. This is independent of
existing radar scan, aircraft telemetry and replay schemas.

## Bounds and diagnostics

Alignment: at most 1024 requests; original SF-1 limits remain (4096 ledger entries,
1 MiB canonical text budget, bounded provenance and diagnostics). Additional
operation identity text is capped at 1 MiB. Acquisition: at most 1024 events and
1024 observations **in total**, sharing SF-1 canonical resource budgets. A batch
resource failure returns no accepted results. Normal per-record errors preserve
other results, including malformed acquisition objects or non-tuple observation
containers. Acquisition identity represents immutable evidence, not an updatable
lifecycle: differing completeness records with the same key conflict within a
batch. Geometry: one operation per call, dimensions 1–4, identifiers
<=1024 UTF-8 bytes, at most 16 caller restrictions. Numeric inputs use SF-1 finite
scalar bounds; exact output components are limited to 8192 numerator/denominator
bits. At most 4! determinant terms and 15 principal minors are needed. There is
no polling, background service, retained history copy or new dependency.

Results retain original requests, frame declarations, evidence identity,
clock-mapping provenance and uncertainty provenance. Diagnostic codes distinguish
unknown availability/uncertainty and missing calibration/elevation from confirmed
invalid inputs. Output size is bounded by input count; operations do not claim
that caller calibration, pose, synchronization or covariance models are accurate.

## Reproducible example and validation

From the repository root, with the existing environment:

```sh
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_fusion_timing.py tests/test_fusion_geometry.py tests/test_fusion_acquisition.py
```

The geometry tests include a pixel map J=((0,-2),(3,0)), offset=(10,20),
p=(320,240), R=diag(4,9). The independent analytical answer is p_out=(-470,980),
R_out=diag(36,36). A separate Gram-factor oracle checks JBBᵀJᵀ via
(JB)(JB)ᵀ. Tests cover exact fractional clock bounds, temporal equality,
delayed/duplicate evidence, explicit empty acquisitions, unknown uncertainty,
rank-deficient covariance, extreme finite scalars, source immutability and repeated
execution. Rigid tests verify a 90-degree rotation plus translation, camera
direction invariance to translation, and missing-elevation deferral.

Initial implementation validation, before independent-review fixes, based on merged PR #15 (`944ddeffe7920a479a430cddea041f69c6dc3741`):

| Check | Result | Wall time | Peak RSS (KiB) |
| --- | --- | --- | --- |
| Focused SF-2 | 49 passed | 1.88 s | 43,148 |
| Complete Python | 2,595 passed, 2 skipped | 89.29 s | 404,632 |
| Complete frontend | 396 passed, 19 files | 62.58 s | 337,796 |
| TypeScript | passed | 1.45 s | 274,260 |
| Production build | passed | 1.00 s | 234,052 |

Measurements use `/usr/bin/time -v`; RSS is the tool-reported process/child
high-water measure, not aggregate concurrent process memory. Python skips are
the existing opt-in real Gazebo sensors and Docker physics checks; neither was
run. Sandbox restrictions initially prevented existing frontend CLI subprocess
tests (`EPERM`) and blocked Python API tests; complete suites passed after running
outside that sandbox. Logs, resource reports and production build output remain
under `/tmp/aegis-sf2-*`, outside Git. Whitespace checks include new untracked
files. No dependencies, baselines or characterization tests were changed.
No dashboard behavior changes; browser validation is outside this Python-only
integration phase. Existing frontend regressions, typecheck and build are required.

## Limitations

No clock synchronization estimation, moving-platform pose interpolation, camera
depth, inferred bbox anchor, missing radar elevation, nonlinear uncertainty
propagation, covariance float serialization, recursive exact propagation, joint
covariance construction or evidence association is supported. A successful result
is conditional on explicit caller models and never an operational decision.

## Independent final review

The review reproduced and fixed these SF-2 defects without changing SF-1:

1. Contradictory acquisition/delivery clock mappings for the same source and
   target could be accepted. Exact compatibility checks now cover their common
   validity interval.
2. Same-source-clock acquisition after delivery was deferred when mapping error
   intervals overlapped. Confirmed source-clock causal reversal now rejects.
3. False-valued invalid rigid arguments selected identity; optional transforms
   are now validated explicitly, including when projection is unavailable.
4. Radar without a projection could be deferred as missing camera calibration;
   camera operations now reject the incompatible measurement type. Missing radar
   elevation also no longer masks a declared source-frame mismatch.
5. A malformed acquisition object/container discarded unrelated valid events;
   it now receives a per-record rejection, while resource overflows still roll
   back the batch.

New independent analytical/adversarial tests include nontrivial rotations,
rank collapse, mixed-unit radar identity, negative clock offsets, inconsistent
rates, extreme finite clock cancellation, evidence conflicts and per-record
acquisition failures. Rational matrix numerator/denominator encoding is tested
for repeatability without float conversion. This is a caller encoding example,
not a new public serialization format. No counterexample to the exact covariance
formula or principal-minor rank calculation was found in the reviewed cases.

Final independent-review validation (no legacy tests or baselines modified):

| Check | Result | Wall time | Peak RSS (KiB) |
| --- | --- | --- | --- |
| Focused SF-2 | 72 passed | 1.45 s | 43,520 |
| Complete Python | 2,618 passed, 2 existing opt-in skips | 126.31 s | 404,224 |
| Complete frontend, sequential rerun | 396 passed, 19 files | 51.64 s | 337,356 |
| TypeScript | passed | 7.81 s | 280,520 |
| Production build | passed | 7.29 s | 207,856 |

The first concurrent frontend run passed 395 tests and timed out in the existing
5-second keyboard-navigation test in `tests/hud.test.tsx`. The complete sequential
rerun passed all 396 tests without test or timeout changes. This is evidence of
resource-sensitive timing; it does not establish a functional frontend defect.
Full Python/frontend tests ran outside the restrictive sandbox for their existing
API/CLI subprocess requirements. RSS remains `/usr/bin/time -v` high-water data,
not aggregate concurrent memory. Logs, build output and reports are under
`/tmp/aegis-sf2-review-*`; no dependencies were installed. Git whitespace checks
cover tracked and new untracked files. The eight-file manifest, empty staging
area, unchanged base and absence of legacy/dependency/baseline changes were
reverified. No browser validation was claimed for this Python-only change.
