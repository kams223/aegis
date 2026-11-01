# SF-3: Deterministic Reference State Estimation

SF-3 is a standalone, offline scientific reference for fabricated trajectories
with explicitly known measurement correspondence. It is not a production
multi-object tracker or control component. It does not associate detections,
select targets, guide pursuit/interception/engagement, actuate hardware, transmit
telemetry or connect to aircraft. No legacy FusionEngine, SF-1/SF-2 contract,
characterization test or telemetry baseline is changed.

Starting checkpoint: merged PR #16, commit
`51d5b311cb0c6aef4aaa9fb7d310cfe98123363b`, with a clean tree, on new branch
`codex/sf3-reference-estimator`.

## Files and public interfaces

- `src/aegis/fusion/reference_estimator.py`: bounded pure estimator, synthetic
  input validation and additive SF-1/SF-2 adapter.
- `src/aegis/simulation/reference_estimation.py`: six deterministic fabricated
  scenarios, analytical ground truth, evaluation and canonical report bytes.
- `tests/test_reference_estimator.py`: independent analytical/numerical oracles.
- `tests/test_reference_estimator_integration.py`: SF-1/SF-2 restrictions and
  provenance integration, without changing their existing tests.
- `tests/test_reference_estimation_scenarios.py`: replay, evaluation, bounds and
  deterministic report checks.
- This document and an additive README entry complete the seven-file manifest.

Core operations return frozen structured results with diagnostics:

- `initialize(ReferencePrior) -> EstimationStep`: require all four prior means,
  including velocity, explicit covariance/model provenance, frame and time.
- `adapt_position(SyntheticPosition | GeometryRequest, ReferenceAssumptions,
  max_age_seconds) -> Adaptation`: validate a synthetic-only position or re-run
  existing admission/geometry validation, then make an explicit Cartesian x/y
  selection. Unknown input never becomes an identity covariance.
- `predict(ReferenceState, MeasurementTime, ReferenceModel) -> EstimationStep`.
- `correct(ReferenceState, ReferenceMeasurement, ReferenceModel, evaluation=None) -> EstimationStep`:
  atomically predict to acquisition and correct, or retain the original state.
- `replay(ReferencePrior, tuple[ReferenceMeasurement, ...], evaluation,
  ReferenceModel) -> ReferenceReplay`: deterministic bounded offline backtest.

`position_basis(frame)` and `state_basis(frame)` declare axes and units.
`ReferenceMeasurement` records the full original source, assumptions, evidence
key, acquisition/delivery/evaluation, frame, exact position/covariance, age policy,
fingerprint and original restrictions. `ReferenceState` retains the complete
prior and its pinned SHA-256 declaration, measurement references, an explicit
inspection `evaluation` distinct from estimate epoch `time`, and bounded contiguous
`PredictionRecord` lineage, including each model/revision. Public dataclasses are inspectable records, not
cryptographic proof of physical validity or authentication tokens. Use operation
results rather than manufacturing derived state records; derived numeric fields
must remain exact `Fraction` objects and are checked before arithmetic.

Simulation operations are `scenario(name)`, `ground_truth(time, acceleration)`,
`evaluate(fixture, model)` and `evaluation_bytes(result)`. The evaluator accepts
only an unchanged fixture produced by this module; arbitrary datasets require
explicit admission/adapter/replay calls, not an implicit fixture extension.

## Mathematical model and units

The estimated quantity is a single declared synthetic entity's 2D Cartesian
position and velocity in one fixed frame:

    x = [px, py, vx, vy]ᵀ
    F(dt) = [[1,0,dt,0], [0,1,0,dt], [0,0,1,0], [0,0,0,1]]
    x_next = F x
    P_next = F P Fᵀ + Q
    H = [[1,0,0,0], [0,1,0,0]]

Position units are metres; velocity units are metres/second; time is seconds.
Covariance component units are the products of those state-axis units. The
process is continuous white acceleration with equal independent x/y axes and
explicit spectral density q in m²/s³. This is not a per-step random constant
acceleration variance (which would give a different Q). For dt >= 0:

    Q = q * [[dt³/3, 0, dt²/2, 0],
             [0, dt³/3, 0, dt²/2],
             [dt²/2, 0, dt, 0],
             [0, dt²/2, 0, dt]]

q=0 explicitly means a deterministic constant-velocity model. q is supplied,
never inferred from residuals, confidence or sensor metadata. White increments,
prior and measurement noise independence are conditional scientific model
assumptions, not physical claims inferred by the software. There is no noise
sampling or random generator.

Correction uses a complete measured Cartesian position z and 2×2 R:

    residual = z - H x_pred
    S = H P_pred Hᵀ + R
    solve S Kᵀ = (P_pred Hᵀ)ᵀ
    x_post = x_pred + K residual
    A = I - K H
    P_post = A P_pred Aᵀ + K R Kᵀ

This is Joseph form. A 2×2 exact rational solve avoids floating-point inversion
or loss of symmetry. Initial velocity must be supplied explicitly; a single
position is not differentiated into a velocity. Later velocity corrections are
conditional on that prior and its predicted cross-covariance. A same-time
position with an uncorrelated velocity prior leaves velocity unchanged.

## Numerical policy and resource limits

Arithmetic uses exact rational representations of supplied finite built-in
integers/IEEE floats, matching SF-2's no-repair policy. No symmetrization,
clipping, jitter, pseudoinverse or covariance float conversion is performed.
Inputs use SF-1 finite numeric bounds; initial priors cannot use NaN, infinity,
bools or arbitrary objects. Internal derived state/measurement numerics must be
exact Fractions, preventing value-equal float replacements from changing the
arithmetic policy. Exact results can exceed finite float magnitude.

Prior P may be singular or zero: the supported PSD-state formulation never
inverts P. Measurement R must be strictly positive definite. Any upstream
`REQUIRES_SINGULAR_MODEL` measurement restriction defers, even if the selected
x/y principal submatrix alone is nonsingular. Unknown uncertainty remains
unknown. Both input/output covariance symmetry and all principal minors are
checked exactly; rank is the largest positive principal-minor order.

For innovation S=[[a,b],[b,d]], require a,d>0 and determinant=ad-b²>0. The
conservative infinity-norm condition product

    max(a+|b|, d+|b|)² / (ad-b²)

must be <=10¹² inclusively. A singular or more ill-conditioned innovation defers
without consuming evidence. There is no fallback solver. Exactness removes
roundoff; it does not remove rational-growth or model-conditioning limitations.

Bounds:

- At most 16 measurement inputs and 16 consumed identities per reference replay,
  matching SF-1's maximum explicit independence scope (2–16 distinct identities).
- At most 32 nonzero prediction transitions per state; dt is 0–86400 seconds per
  transition. Zero dt is an identity prediction with no new history record.
- Rational components have at most 4096 numerator/denominator bits. Products have
  bounded-size operands and sums/results are checked; output growth is explicitly
  rejected/deferred rather than approximated. Covariance dimension is at most 4.
- Existing SF-1 metadata/canonical provenance limits and 1024-byte identifiers
  apply; no background work, polling, services, histories copied by value or new
  dependencies. Matrix conversions are at most 4×4. History tuples retain source
  references, with bounded pointer copies.
- The fixture evaluator uses eight query times and at most eight observations;
  its report serializer bounds tuple lengths, nesting, identifiers and rational
  components. It accepts no external file input or executable configuration.

Prediction errors reject while retaining the input state. Correction innovation
conditioning and rational resource failures defer while retaining the input
state. Neither consumes an evidence key. Invalid priors/replay inputs produce
explicit rejection. Invalid synthetic fixtures raise bounded validation errors.

## Timing, ordering, identity and provenance

Acquisition, delivery and caller-selected evaluation remain separate. The
external adapter re-runs SF-2 geometry, which revalidates SF-1 admission. All
source timestamps and mappings remain reachable through the original source
request. Reference acquisition must be a singleton in the explicit inspection
clock; nonzero interval width defers. No clock mapping, wall clock or
synchronization is invented by SF-3.

Correction permits zero dt but rejects acquisition before current state time;
there is no incremental online rewind. Offline replay filters delivery at the
selected evaluation, checks selected-time age, and processes eligible observations
in (acquisition time, original input index) order. Equal timestamps retain caller
order; duplicate keys do not cause a second update. Changed content or assumptions
under the same key reject as evidence conflicts. Duplicate identity is independent
of evaluation value and age policy, as in SF-1. Source delivery and uncertainty
remain part of content identity.

A delayed observation may participate in a newly recomputed offline backtest
only after its known delivery. Earlier selected-time results never use a
future-delivered measurement. Correction defaults to the measurement's declared
evaluation, or accepts an explicit evaluation override. It checks delivery and
freshness at that context and cannot move an existing posterior's inspection
time backwards. Prediction preserves inspection time while changing the state
epoch; an epoch in the past can therefore be explicitly retrospective, rather
than being misrepresented as information available then. Replay passes its
selected evaluation through every correction and its final state.

An SF-1 `AdmittedMeasurement` does not retain its original maximum-age policy.
Consequently SF-3 cannot silently extend a geometry-derived admission beyond its
original evaluation. Earlier offline evaluations are allowed only when delivery
and all explicit policies are satisfied; age is then no greater than at original
admission. Later correction contexts defer with `EVALUATION_CONTEXT` and require
fresh SF-1 admission. Already-assimilated information can remain in a posterior
and be predicted forward; this is not a second admission of stale evidence.
SyntheticPosition has an explicit SF-3 age policy and is rechecked at selection.

Resumed states validate the pinned prior, every retained source measurement,
correspondence, frame, clock and inspection context before duplicate handling.
Measurement metadata is checked by exact runtime types before value equality,
so value-equal booleans or foreign frame objects cannot bypass admission.
This is not an online out-of-sequence filter. Missing observations cause
prediction only, never an invented zero measurement.

## Additive integration and correlation restrictions

SF-1 has no native complete 2D Cartesian admission type. The integration path
therefore accepts only SF-2 `radar_cartesian` geometry with complete measured 3D
position and explicitly declared propagated Cartesian uncertainty. Selecting x/y
is marginal selection, using the exact 2×2 principal covariance submatrix and
preserving off-diagonal terms; it is not conditioning on z or setting z=0.
Positive-range radar without elevation defers upstream. Raw and projected
uncertainty provenance must explicitly be `synthetic_model`.

A named `ReferenceAssumptions` declaration must identify the synthetic scenario,
known correspondence, prior, independence assumption and complete evidence scope,
and explicitly assert independence of measurement noise from the prior. For
external-object integration, SF-1 must already carry `independence_asserted` with
exactly the same assumption ID and ordered scope. Unknown/shared correlation
therefore defers. The joint model is pinned on the first correction and cannot
change within one trajectory. Correspondence is supplied by the fixture/caller;
no grouping by proximity, labels, appearance, timestamps or residuals occurs.

SF-2's conservative restrictions, including `NO_INDEPENDENT_COMBINATION` and
`JOINT_COMPATIBILITY_NOT_ASSESSED`, remain in the source/reference measurement.
SF-3 does not erase or reinterpret them as physical independence. Conditional
combination is confined to this explicitly declared synthetic joint model and
marked `CONDITIONAL_SYNTHETIC_JOINT_MODEL`; it is not permission to combine those
measurements elsewhere. SF-1 unknown/singular restrictions are never waived.

`SyntheticPosition` is a separate explicit synthetic-only unit/reference input,
requiring fixture revision, complete Cartesian values, covariance with synthetic
provenance and the same joint assumptions. It is not an adapter for raw real
sensors or aircraft telemetry. The external-object integration path cannot accept
unadmitted observations, native aircraft telemetry, camera pixels/directions or
raw radar polar covariance as Cartesian input. No SF-1/SF-2 API or baseline was
extended to accommodate SF-3.

## Fabricated scenarios and metrics

All fixtures describe one explicitly named external synthetic entity in a fixed
radar-local frame: +x forward, +y left, +z up. Initial truth is position (20,10)
metres and velocity (2,-1) m/s, with measured z=5 metres. The prior uses those
explicit means and diag(4,4,4,4) covariance. Known deterministic pixel-free offsets
are (+.2,-.1),(-.2,+.1),(+.1,+.2),(-.1,-.2) metres, repeated. Polar observations
are fabricated through atan2/hypot and pass existing SF-1/SF-2 operations; declared
Cartesian covariance is diag(1,1,1) m², separate from raw polar covariance.

- `constant_velocity`: eight one-second samples, constant-velocity truth.
- `acceleration_mismatch`: controlled acceleration (.5,.25) m/s², intentionally
  outside the mean constant-velocity model.
- `missing`: scans 2,3,6 are explicitly completed empty acquisitions; no samples
  are created for them.
- `delayed`: alternating samples delivered three seconds late; source admission
  evaluation and earlier selected replay queries remain distinct.
- `unequal_intervals`: times 0,.5,1.5,2,4,5,7,8 seconds.
- `singular_covariance`: declared projected y variance is zero; all measurement
  adaptations defer and the explicit prior is predicted without corrections.

Evaluation uses all eight query times. Position and velocity RMSE are sqrt of
mean squared **2D vector norm**, not per-axis RMSE. Results include per-query
errors, correction residuals, NIS=residualᵀ S⁻¹ residual, final covariance and
status counts. Marginal position NEES=e_xyᵀ P_xy⁻¹ e_xy is reported where the
marginal solve is supported; otherwise it is unavailable. Exact PSD checks remain
part of every operation. NIS/NEES are deterministic model-consistency scores,
not calibrated probabilities or a chi-square/ensemble validation. These fixed
offsets are not random sensor noise. Singular-scenario zero error under a perfect
mean prior is not evidence that missing/singular sensors are accurate.

## Reproducible example and report encoding

```sh
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B - <<'PY'
from aegis.fusion.reference_estimator import ReferenceModel
from aegis.simulation.reference_estimation import scenario, evaluate, evaluation_bytes
result = evaluate(scenario('acceleration_mismatch'), ReferenceModel(.25, 'sf3-cv-v1'))
print(evaluation_bytes(result).decode(), end='')
PY
```

`evaluation_bytes` emits a fixed-key UTF-8 JSON report with schema_version=1:
scenario_name, model_revision, acceleration_spectral_density, position_rmse_m,
velocity_rmse_mps, position_errors, velocity_errors, position_nees, innovations,
nis, final_covariance, correction_statuses and adaptation_statuses. Exact numbers
use decimal-string numerator/denominator objects; RMSE approximations use finite
float hexadecimal strings. RMSE scales the exact mean square by an even binary
exponent before float conversion and square root, avoiding premature squared-error
underflow/overflow. Only the final RMSE approximation is limited by float range;
positive results outside the nonzero finite float range reject explicitly. Keys are sorted, separators fixed,
and a final newline
is included. The serializer validates query counts, vector dimensions, exact PSD covariance,
nonnegative consistency scores, outcome/innovation counts and RMSE against the
supplied errors before encoding. It cannot certify that caller-supplied errors
came from a real experiment. There is no report loader or general serialization
of live estimator state. Original numeric representations remain in source provenance; negative
zero becomes rational zero in derived arithmetic. Hash reproducibility is verified
for this Python/math environment; atan2/hypot projection is not promised to be
bit-identical across different libm implementations.

## Validation evidence

Analytical cases independently verify integrated white-acceleration Q, prediction
semigroup equivalence, scalar/correlated Gaussian corrections and the Joseph
posterior, singular priors, rank/PSD, zero dt, inclusive time boundaries,
conditioning failures, strict units/frames, delayed eligibility, duplicate and
conflicting evidence, explicit velocity priors, capacity and immutability. Repeated
fixture execution compares canonical SHA-256 reports. Legacy tests and baselines
are not rewritten to pass these checks.

Initial implementation validation, before independent review, using the existing
Python/Node environments; no dependency installs.

| Check | Result | Wall time | Peak RSS (KiB) |
| --- | --- | --- | --- |
| Focused SF-3 | 60 passed | 17.26 s | 44,044 |
| Complete Python | 2,678 passed, 2 existing opt-in skips | 111.99 s | 407,376 |
| Complete frontend | 396 passed, 19 files | 50.80 s | 336,944 |
| TypeScript | passed | 4.81 s | 286,820 |
| Production build | passed | 5.06 s | 230,904 |
| Three-run scenario evaluation | all six hashes repeat | 20.30 s | 21,488 |

The complete frontend suite passed on its first sequential run. RSS is
`/usr/bin/time -v` high-water data, not aggregate concurrent process memory.
Tracked and new untracked file whitespace checks passed; the exact seven-file
manifest and empty staging area were reverified.
Python/frontend full suites require the existing API/CLI subprocess permissions
outside the restrictive sandbox. The skipped tests are the existing opt-in real
Gazebo sensors and Docker physics checks; neither was run. Logs, reports and build
outputs remain under `/tmp/aegis-sf3-*`, outside Git.

At q=.25 m²/s³, revision `sf3-cv-v1`:

| Scenario | Position RMSE (m) | Velocity RMSE (m/s) |
| --- | --- | --- |
| constant_velocity | 0.137628 | 0.122302 |
| acceleration_mismatch | 0.490848 | 0.800226 |
| missing | 0.325387 | 0.178486 |
| delayed | 0.226375 | 0.075832 |
| unequal_intervals | 0.137422 | 0.127246 |
| singular_covariance | 0.000000 | 0.000000 |

Acceleration mismatch sensitivity (fixture evidence unchanged):

| q (m²/s³) | Position RMSE (m) | Velocity RMSE (m/s) |
| --- | --- | --- |
| 0 | 1.028923 | 1.233006 |
| 0.25 | 0.490848 | 0.800226 |
| 1 | 0.275294 | 0.572113 |

Each canonical report was recomputed from a fresh fixture three times. All three
SHA-256 hashes matched for every scenario:

- `constant_velocity`: `78a7a178ae0f07b5b4318219522735900c7b9b401e79792f64e28d5d173b8295`
- `acceleration_mismatch`: `dacbcba4d6fd1d3cd07028d906a01fb69236f78caa9832ddc5c26ad3a3bc0f67`
- `missing`: `2c2ce8e7c32afea51e35bde4d0233243ebdaff89a519eeeb9ca1d57e4d75563e`
- `delayed`: `43490ecfe5736b6f97c32a5ef7a372c34a52eabdfe3d8dd4d5986f033a71bffc`
- `unequal_intervals`: `85fca8af7ef4b9508773c64edfb25d406db9b9bb1d025f2532b37199a61049bc`
- `singular_covariance`: `5dbca8b75d4fe649513716da7719ba1ddfcf5069c6c623d4753bb9df15f28866`

These scores demonstrate deterministic software behavior and process-model
sensitivity on fixed fabricated inputs. They are not general performance claims,
optimal q calibration or physical sensor-accuracy evidence.

## Remaining limitations

This is an exact, small, bounded scientific reference, not a scalable floating
estimation backend. There is no automatic initialization, association, lifecycle
management, multi-entity state, online delayed-state smoothing, arbitrary temporal
interval update, nonlinear measurement update, sensor fusion calibration, clock
estimation, moving-platform pose, camera depth, velocity derived from range rate,
robust outlier handling or physical sensor accuracy guarantee. Future numerical
or estimator work requires separate review; SF-3 adds no operational integration.

## Independent mathematical and integration review

The review confirmed and fixed:

- Geometry-derived admission was usable after its original evaluation even
  though SF-1 does not retain its age policy. Later reuse now defers until fresh
  admission; selected-time eligibility is shared by direct correction and replay.
- State epoch and inspection context were conflated. States now preserve both,
  and inspection context cannot move backwards after assimilating evidence.
- Duplicate handling could conceal an altered prior or fabricated retained
  source history. Prior declarations are pinned; retained measurements and their
  contexts are revalidated before they can suppress a legitimate update.
- Value equality admitted a boolean delivery timestamp or foreign frame object
  in a manufactured measurement. Exact metadata types are checked before equality.
- The report serializer accepted negative/non-numeric RMSE, wrong query counts
  or malformed covariance. Semantic report checks now reject these records.

Independent oracles include a 4D information-form posterior with nontrivial
position/velocity cross-covariance and a separate Gauss-Jordan inverse, plus
Simpson integration of the continuous acceleration impulse-response covariance
(the quadratic integrand makes Simpson exact). Near-degenerate/strongly correlated
innovations, the exact inclusive condition threshold, and actual rational-growth
failures at subnormal time steps are tested. Resource failures preserve the input
state and do not consume evidence identity. No covariance-model counterexample
was found in these analytical cases; no numerical repair was introduced.

A fixed-error metric oracle verifies the 2D-vector RMSE denominator and marginal
NEES independently of estimator calculations. A ground-truth access trap verifies
that estimator replay never calls ground truth. Changing future-delivered values
does not change earlier selected-time estimates.

Final review validation used Python 3.12.3 and Node v24.21.0 with the existing
environments and no dependency installs:

| Check | Result | Wall time | Peak RSS (KiB) |
| --- | --- | --- | --- |
| Focused SF-3 | 80 passed | 56.13 s | 44,160 |
| Complete Python | 2,698 passed, 2 existing opt-in skips | 142.84 s | 406,264 |
| Complete frontend | 396 passed, 19 files | 54.56 s | 344,476 |
| TypeScript | passed | 1.89 s | 273,376 |
| Production build | passed | 1.02 s | 244,600 |
| Hash-seed validation | 3 scenarios × 3 seeds matched | 21.69 s | 21,056 |

The complete frontend run passed on its first sequential execution. Full Python
and frontend suites ran sequentially outside the restrictive sandbox for their
existing API/CLI subprocess requirements. No real Gazebo or Docker physics was
run. RSS is `/usr/bin/time -v` high-water data, not summed process memory.
Revalidating bounded retained provenance increases exact-reference runtime;
this component remains limited to 16 measurements and 32 predictions rather
than serving as a high-throughput estimator.

Representative canonical reports matched under `PYTHONHASHSEED=0`, `1` and
`1729`, and retained the original implementation hashes:

- constant_velocity: `78a7a178ae0f07b5b4318219522735900c7b9b401e79792f64e28d5d173b8295`
- delayed: `43490ecfe5736b6f97c32a5ef7a372c34a52eabdfe3d8dd4d5986f033a71bffc`
- acceleration_mismatch: `dacbcba4d6fd1d3cd07028d906a01fb69236f78caa9832ddc5c26ad3a3bc0f67`

Reproduce each seed check with the documented scenario example, changing the
scenario name and prefixing the command with the chosen `PYTHONHASHSEED`.
Review logs, seed outputs, build output and resource reports remain under
`/tmp/aegis-sf3-review-*`. The exact seven-file manifest and tracked/untracked
whitespace are checked separately. Nothing is staged; no existing SF-1/SF-2
contracts, legacy behavior, dependencies or telemetry baselines changed.

## Checkpoint continuation review (2026-11-01)

The continuation review reverified the existing seven-file scope and unchanged
SF-2 base without rewriting the estimator. Existing exact information-form and
impulse-response covariance oracles remain the independent mathematical checks.

One additional confirmed numerical defect was found in evaluation: converting
an exact mean squared error to float before taking its square root could publish
zero for representable nonzero RMSE (e.g. 1e-200), or reject representable large
RMSE (e.g. 1e200). Evaluation and report validation now share binary-scaled root
calculation. Exact error vectors and estimator covariance arithmetic are unchanged;
no silent clipping, covariance repair, new dependency or earlier-phase edit was
introduced. Five adversarial cases reproduce both range failures, prevent publication of
an incorrect zero score, and require explicit rejection when the final nonzero
RMSE itself is outside finite float range.

Continuation validation used the existing Python 3.12.3 / Node v24.21.0 tools:

| Check | Result | Wall time | Peak RSS (KiB) |
| --- | --- | --- | --- |
| Focused SF-3 (final code) | 85 passed | 194.92 s | 43,964 |
| Complete Python | 2,703 passed, 2 existing opt-in skips | 171.42 s | 407,444 |
| Complete frontend | 396 passed, 19 files | 59.62 s | 333,032 |
| TypeScript | passed | 4.13 s | 286,172 |
| Production build | passed | 1.84 s | 249,476 |
| Hash-seed validation | 6 scenarios × 3 seeds matched | 44.56 s | 20,836 |

The complete frontend suite passed on its first sequential execution. Full Python
and frontend regressions ran sequentially outside the restrictive sandbox for their
existing API/CLI subprocess tests. The focused final run partly overlapped an
earlier 83-case coverage run; its elapsed time is an observation, not a comparative
performance benchmark. RSS is the tool-reported high-water measure, not aggregate
concurrent memory. No dependencies, browser binaries, Docker services or Gazebo
runs were introduced.

All six report hashes under seeds 0, 1 and 1729 matched each other and the six
original hashes listed above, including the metric range fix. New exact error
vectors and covariance remain unrounded; only RMSE is a declared finite-float
approximation. Results outside its nonzero finite range reject explicitly.

The original context, prior/history, metadata-equality and report-validation fixes
remain intact and passed the repeated analytical/integration suite. The only
additional implementation change in this continuation is the RMSE range fix,
in `reference_estimation.py`; its new cases are in the existing scenario tests.
The other approved files remain in the seven-file uncommitted SF-3 manifest.
Logs, build output, seed evidence and measurements remain under
`/tmp/aegis-sf3-recheck-*`. Nothing is staged, committed, pushed or published.
