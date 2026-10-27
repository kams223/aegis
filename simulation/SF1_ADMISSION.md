# SF-1: strict fusion admission and uncertainty contracts

SF-1 is a pure boundary for normalized **external-object** measurements, before
future association or estimation. It does not create tracks, assign physical
object identity, estimate state, combine measurements, infer depth, convert frames,
read a clock, perform acquisition, or connect to aircraft/control services.

Prerequisite: PR #14 was verified merged into `main` at
`3d0ea68d2ef3d4bc828541f1eac4a1919d4595f6`. SF-1 was developed additively on
`codex/sf1-fusion-contracts` from that clean checkpoint. Phase 75D/76A native
IMU/GNSS/barometer telemetry remains separate and unchanged. Those measurements
refer to the carrying platform, not an observed external object.

## Public operations and ownership

```python
validate_covariance(declaration, expected_basis) -> CovarianceCheck
admit_batch(requests, ledger) -> BatchAdmissionResult
```

Modules:

- `src/aegis/fusion/uncertainty.py`: `MeasurementBasis`,
  `UncertaintyProvenance`, `CovarianceDeclaration`, `UnknownUncertainty`,
  `ValidatedCovariance`, `CovarianceCheck`, `Diagnostic`, `validate_covariance`.
- `src/aegis/fusion/admission.py`: `AdmissionRequest`, `EvidenceKey`,
  `CorrelationClaim`, `LedgerEntry`, `AdmissionLedger`, `AdmittedMeasurement`,
  `AdmissionResult`, `BatchAdmissionResult`, `admit_batch`.

All containers are frozen dataclasses. Declarations are **untrusted typed input**:
annotations do not replace runtime validation, and a malformed declaration does
not become validated covariance merely by being constructed. Accepted matrices
require exact tuple-of-tuples storage, immutable numeric entries, a validated
basis and provenance. No list-to-tuple repair is performed. Direct construction
of `ValidatedCovariance` also validates its invariants and derives rank and
restrictions; malformed direct construction raises a validation error. The public
validation operation instead returns structured diagnostics.

Source observations and optional `DerivedSensorEvidence` are retained by identity.
SF-1 does not freeze, modify or repair caller data. Accepted payloads are a closed
set of existing immutable value types. Rejected/deferred/duplicate results contain
no admitted measurement. Unknown uncertainty remains an explicit object in the
result, not a replacement matrix. The accepted result contracts are operation
outputs, not a wire decoder or authentication mechanism.

## Supported measured quantities

Every request explicitly declares `entity_kind='external_object'`. This is a
caller assertion about the observation's role, not an object association or
physical truth claim. `quantity` names the observable being admitted; there is no
Cartesian state vector in SF-1.

| Exact payload type | Kind / quantity | Ordered axes | Component units |
| --- | --- | --- | --- |
| `ImagePoint` | `image_point` / `image_location` | `u_px, v_px` | `px, px` |
| `ImageTrackMeasurement` | `image_bbox` / `image_extent` | `x1, y1, x2, y2` | `px` on all four |
| `RadarPolarDetectionMeasurement` | `radar_polar` / `radar_polar` | `range_m, azimuth_rad`, then supplied `elevation_rad`, then supplied `radial_velocity_mps` | `m, rad`, optionally `rad, m/s` |

The source must be an exact `SensorObservation`, with supported exact payload
and reference/time types. Arbitrary subclasses and native `SensorTelemetry` or
legacy scalar packets are not accepted. Optional radar fields remain absent;
they are not filled with zero or silently removed from a covariance matrix.
Covariance shape and axes must match the actual 2–4 supplied components.

All numeric values must be finite built-in int/float values, excluding bool.
Image dimensions are positive integers up to 2,147,483,647; box class IDs are
integers in [0, 2,147,483,647]. Boxes must have positive area and ordered corners.
Finite out-of-image points/boxes remain permissible without clipping. Radar units,
range and angular conventions are those of the existing polar contract. A zero
range or zero range rate is a recorded value, not missing data.

Detector confidence must be finite but remains a backend score; values outside
[0,1] are not converted into probabilities or covariance. Class/label metadata and
source-local IDs are retained without becoming fused identity. Positive radar
range without elevation does not become a 3D point; range rate is not full
velocity. Boxes are not converted to centers, and camera depth is not inferred.

## Basis, frames and marginal covariance

`MeasurementBasis` includes kind, ordered axes, component units and an explicit
`ReferenceFrame`. All must match the source representation. The covariance basis
must match that exact basis by value. A frame-name match is conditional on producer
conventions; it is not proof of calibration. No frame/unit conversion occurs.
Optional existing derivations are revalidated with the existing evidence contract,
but their transformed geometry does not change the admitted raw measurement or
its covariance basis.

Covariance utilities support dimensions **1–4**. The utility can validate a
one-dimensional analytical basis, but admission supports only the payload types
above. Supported utility component units are `px`, `m`, `rad`, `m/s`, and `1`.
Entry R[i,j] has the product of component units u[i] * u[j]; basis units are not
matrix-entry unit strings such as `px²`.

A `CovarianceDeclaration` contains matrix, basis and `UncertaintyProvenance`:
nonblank model ID, revision and method (`caller_declared`, `calibration`, or
`synthetic_model`). These are retained declarations, not independently verified
accuracy claims. `UnknownUncertainty(reason)` has no matrix.

### Exact PSD and rank policy

- Exact square tuple shape; exact agreement with basis dimensions.
- Finite built-in numbers; no bool, coercion or arbitrary numeric subclasses.
- Integers have at most 1024 bits and absolute value at most
  `int(sys.float_info.max)`. The bound is compared as an integer, before any float
  conversion; integers just outside it must not round back into the allowed range.
  This bounds arithmetic, not physical measurement magnitude.
- `Fraction` represents each supplied int/IEEE float value exactly.
- Require exact numeric symmetry and **all principal minors >= 0**, not merely
  leading principal minors. At dimension four there are only 15 principal minors,
  each using at most 4! exact determinant terms.
- For a PSD matrix, rank is the largest size of a positive principal minor.
- Singular/zero covariance is valid PSD and carries `REQUIRES_SINGULAR_MODEL`.
  This does not prove physical exactness or authorize an ordinary inverse.
- No tolerance, symmetrization, eigenvalue clipping, diagonal jitter, rescaling,
  or replacement matrix is used. Supplied values, including signed zero, remain
  unchanged. A tiny negative principal minor is rejected, not rounded away.

This strict policy can reject a matrix intended to be PSD before upstream
floating-point rounding. A future propagation policy needs separate review;
SF-1 does not repair such declarations or propagate covariance.

## Temporal eligibility

The request requires explicit evaluation, availability (possibly None) and
maximum-age policy (possibly None). Existing `MeasurementTime` values remain in
seconds and retain their domain/values. Signed source-relative offsets are valid.
SF-1 does not convert native uint64 nanoseconds into absolute floating seconds.

Same-domain raw measurement time gives the singleton interval [t,t]. Otherwise,
only the original derivation's explicit validated `MappedTimeInterval` may be
used; its target domain must match evaluation. Missing mapping is deferred;
inconsistent supplied domains/derivations are rejected. The mapped interval
remains conditional on its caller-supplied calibration/error assertions.

Availability must be explicitly expressed in the evaluation domain. Unknown
availability is deferred; acquisition is not substituted. Given acquisition
interval [l,u], known availability d and evaluation e:

- l > d is a rejected causal inconsistency.
- l <= d < u is deferred temporal ambiguity.
- u <= d and d > e is deferred pending delivery.
- u <= d <= e is eligible, including exact equality.
- If a maximum age A is supplied, require e - l <= A. Equality is eligible;
  an exceeded worst-case age is deferred stale. Explicit None disables this age
  gate; it does not disable domain/availability checks.

Age comparisons use exact Fraction subtraction, avoiding overflow/cancellation
in float time differences. No synthetic age timestamp is generated. Invalid
known causal order is rejected even when uncertainty is unknown.

## Correlation and independence

`CorrelationClaim` has three modes:

- `unknown`: no group, assumption or scope; no independence is inferred.
- `shared_group`: a nonblank group ID, without an independence assertion.
- `independence_asserted`: named assumption and 2–16 distinct explicit evidence
  keys including this request, without a shared-group claim.

Different sensors, sessions or group names do not establish independence. SF-1
validates and retains scoped assertions, not their physical correctness, and does
not evaluate cross-covariance or joint compatibility. Every admitted measurement
carries `JOINT_COMPATIBILITY_NOT_ASSESSED`; unknown/shared correlation additionally
carries `NO_INDEPENDENT_COMBINATION`, while explicit independence carries
`INDEPENDENCE_IS_CALLER_ASSERTED`. Consumers must not interpret admission as
permission to perform arbitrary independent weighted fusion.

## Evidence identity, duplicates and results

`EvidenceKey = (sensor_id, source_session_id, observation_id)`.
The session is a producer acquisition-sequence scope, not a fresh consumer replay
UUID. IDs are opaque: SF-1 does not parse embedded camera/radar ID encodings or
infer correspondence from equal local IDs.

Two SHA-256 fingerprints use the `sf1-fingerprint-v1` canonical encoding:

- Evidence fingerprint: key, original observation and declared availability.
- Assumptions fingerprint: entity, quantity, basis, uncertainty declaration,
  correlation claim, optional derivation and evaluation **domain**.

Encoding uses exact supported dataclass field order/type names, tuple order,
ASCII JSON, decimal integers and `float.hex()`. Numeric types and signed zero are
preserved. Integer 1 and float 1.0 can therefore produce a conservative conflict.
Python object identity, evaluation **value** and maximum-age policy are excluded.
Fingerprints establish repeatable declarations, not authenticated origin.

Results preserve input order. No measurement-time sorting occurs here:

| Condition | Outcome / ledger |
| --- | --- |
| Valid known marginal uncertainty and eligible evidence | `admitted`; reserve key once |
| Unknown uncertainty, missing mapping/availability, pending/ambiguous/stale time | `deferred`; no reservation |
| Malformed input, incompatible metadata or causal inconsistency | `rejected`; no reservation |
| Same admitted key and unchanged fingerprints | `duplicate`; no second admitted measurement |
| Same admitted key with changed content/availability | `rejected`, `EVIDENCE_CONFLICT` |
| Same admitted key with changed assumptions | `rejected`, `ADMISSION_CONTEXT_CONFLICT` |

Only successful admissions reserve keys. A deferred record may later be retried
with newly supplied uncertainty/availability. Source IDs and times never become
physical-object identity. Duplicate checking precedes current temporal eligibility:
revisiting an admitted key at an earlier evaluation still yields a duplicate with
**no admitted measurement**, not an early measurement exposure. Use a fresh ledger
for a deliberate replay from an earlier frontier; there is no automatic rollback.

Validation precedence is source/type/basis, uncertainty/correlation and explicit
time structure, fingerprint/derivation consistency, duplicate/conflict, then
causal/eligibility checks. For otherwise valid unseen inputs, the first deferred
reason is unknown uncertainty, missing mapping, unknown availability, ambiguous
or pending delivery, then stale age. Invalid known causal order is not hidden by
unknown uncertainty. Per-record errors do not erase valid neighboring admissions.

Diagnostics are typed `Diagnostic(code, path, explanation)` tuples. Each result
has at most one primary diagnostic; accepted restrictions are separate. Codes
include `OBSERVATION_TYPE`, `UNSUPPORTED_MEASUREMENT_TYPE`, `ENTITY_KIND`,
`UNSUPPORTED_QUANTITY`, `BASIS`, `FRAME_MISSING`, `FRAME_MISMATCH`,
`UNITS_MISMATCH`, `NUMERIC_TYPE`, `NUMERIC_RANGE`, `NONFINITE_VALUE`,
`COVARIANCE_SHAPE`, `COVARIANCE_ASYMMETRIC`, `COVARIANCE_NOT_PSD`,
`UNCERTAINTY_TYPE`, `UNCERTAINTY_PROVENANCE`, `UNCERTAINTY_UNKNOWN`,
`CORRELATION`, `TIMESTAMP`, `CLOCK_DOMAIN`, `AGE_POLICY`, `CAUSAL_ORDER`,
`CLOCK_MAPPING_REQUIRED`, `AVAILABILITY_UNKNOWN`, `TEMPORAL_AMBIGUITY`,
`PENDING_DELIVERY`, `STALE_MEASUREMENT`, `DERIVATION`,
`DERIVATION_SOURCE_MISMATCH`, `EVIDENCE_CONFLICT`, `ADMISSION_CONTEXT_CONFLICT`,
`DUPLICATE`, `BOUND`, `LEDGER`, `REQUEST_TYPE`, `EVIDENCE_IDENTITY`, `TEXT`,
`PROVENANCE_TYPE`, `IMAGE_DIMENSIONS`, `IMAGE_BOX`, and `CLASS_ID`/`RADAR_DOMAIN`.

## Resource behavior

- 1024 requests per immutable batch, 4096 immutable ledger entries; no silent eviction.
- Covariance dimensions 1–4; optional correlation scope at most 16 keys.
- Text fields at most 1024 UTF-8 bytes, without controls or surrogate characters.
- Fingerprinting at most 1 MiB aggregate text and 524288 canonical nodes per batch;
  maximum nesting 16, individual metadata tuple length 16.
- At most 1024 result diagnostics, plus a batch diagnostic for whole-batch failure.
  Explanations are fixed bounded text, never a dump of untrusted payloads.

Oversized request tuples/invalid ledgers fail before admission. Canonical aggregate
budget overflow discards all tentative results and returns the original ledger.
Individual ledger-capacity failures reject new keys while existing duplicates
remain recognizable. Deferred/rejected inputs can still count toward fingerprint
work where validation reaches it. Exceeding that declared whole-batch budget can
therefore reject a batch containing otherwise valid observations; it never reserves
their keys. Retry a smaller batch with the unchanged original ledger. No generator inputs, automatic retention eviction, global
state, timers or I/O are used. Only small vectors/matrix arithmetic and bounded
ledger-reference projections are copied. Sequential callers must pass the returned
ledger into the next call; concurrent branches from one ledger are not globally
serialized. Ledger construction validates shape and digests, not authenticity.

## Public example

```python
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.spatial.camera import ImagePoint
from aegis.fusion.uncertainty import (
    MeasurementBasis, CovarianceDeclaration, UncertaintyProvenance, UnknownUncertainty,
)
from aegis.fusion.admission import AdmissionRequest, AdmissionLedger, CorrelationClaim, admit_batch

frame = ReferenceFrame('camera:image')
observation = SensorObservation('frame-1:point-1', 'camera-a',
    MeasurementTime(10.0, 'video:opening-a'), frame,
    ImagePoint(320.0, 240.0, 640, 480, frame))
basis = MeasurementBasis('image_point', ('u_px', 'v_px'), ('px', 'px'), frame)
request = AdmissionRequest(
    observation=observation, source_session_id='opening-a',
    entity_kind='external_object', quantity='image_location', basis=basis,
    uncertainty=CovarianceDeclaration(((4.0, 0.0), (0.0, 9.0)), basis,
        UncertaintyProvenance('pixel-model', '1', 'synthetic_model')),
    correlation=CorrelationClaim.unknown(),
    evaluation=MeasurementTime(12.0, 'video:opening-a'),
    available_at=MeasurementTime(10.5, 'video:opening-a'), max_age_seconds=5.0,
)
result = admit_batch((request, request), AdmissionLedger.empty())
assert [item.status for item in result.results] == ['admitted', 'duplicate']
assert result.results[0].admitted_measurement.source_observation is observation
assert 'NO_INDEPENDENT_COMBINATION' in result.results[0].admitted_measurement.restrictions

from dataclasses import replace
unknown = replace(request, uncertainty=UnknownUncertainty('calibration unavailable'))
deferred = admit_batch((unknown,), AdmissionLedger.empty())
assert deferred.results[0].status == 'deferred'
assert deferred.results[0].uncertainty is unknown.uncertainty
```

## Validation and compatibility

```sh
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B -m pytest -p no:cacheprovider \
  tests/test_fusion_uncertainty.py tests/test_fusion_admission.py \
  tests/test_fusion_admission_integration.py
PYTHONPATH=src /home/ali/venvs/aegis/bin/python -B -m pytest -p no:cacheprovider
```

Analytical cases cover PSD, non-PSD, singular and zero matrices, tiny negative
minors, non-leading negative minors, exact rank, subnormal/large numbers, NaN,
infinity, malformed shape and basis mismatch. Admission cases cover temporal
boundaries, missing frames, unknown uncertainty, duplicate/conflicting evidence,
correlation restrictions, ledger capacity, batch rollback and source immutability.
Integration tests exercise actual camera/radar adapters, missing radar components,
retained derivations, native-aircraft exclusion, deterministic reruns and an
isolated standard-library operation with heavy imports, clocks and I/O blocked.

Existing characterization tests are unchanged. No generic contract, adapter,
Phase 75D/76A schema, raw observation, scalar FusionEngine behavior or frontend
code is modified. SF-1 has no wire format/loader or persistence implementation;
its in-process contracts are not a new telemetry format. Calibration, noise and
independence claims remain caller assertions. No estimator, state covariance,
association, physical accuracy evaluation or operational decision is implemented.

## Implementation verification

Final local checks on the SF-1 branch:

| Check | Result | External wall time | Peak RSS |
| --- | --- | --- | --- |
| New SF-1 focused tests | 81 passed | 3.70 s | 43 MiB |
| Complete Python regression | 2528 passed, 2 simulator opt-in skips | 87.87 s | 393 MiB |
| Complete existing frontend suite | 396 passed across 19 files | 76.68 s | 331 MiB |
| TypeScript | passed | not timed separately | not measured |
| Production frontend build | passed | 1.20 s | 198 MiB |
| Tracked and new-file whitespace audit | passed | — | — |

Python's internal duration was 86.80 s. Process/child peak RSS is not the sum of
concurrent workers. No frontend source changed. The public documentation example
ran successfully in three fresh Python processes with hash seeds 0, 1 and random,
producing identical evidence/assumption fingerprints:

```text
32a4ffaccfb93f8be99865958102254961378b169d95e428afcb3bb342181162
5fcc0b895ead8cca4e04a2c8d2d0e2529168362c733aca1fc63e1f3fb995171a
```

Logs are `/tmp/aegis-sf1-{focused,python,frontend,typecheck,build}.log`;
reproducibility output is `/tmp/aegis-sf1-reproducibility.json`; the generated
frontend build is `/tmp/aegis-sf1-dist`. Existing API/CLI test subprocesses required
execution outside the sandbox, as in earlier phases; no runtime permissions were
added. No dependencies, existing baselines or characterization tests were changed,
and no Gazebo or model inference was run. There is no new frontend flow to validate
in a browser.

The complete change manifest is the two new modules, the three new test files,
this note, and an additive README link/description. No commit, push or PR has been
made. Suggested next step is review of the admission policies/restrictions before
a separately authorized commit; state estimation and joint uncertainty treatment
remain future work.


## SF-1 independent final review

The review reconfirmed `codex/sf1-fusion-contracts` at the Phase 76A merge parent
`3d0ea68d2ef3d4bc828541f1eac4a1919d4595f6`, with exactly the seven intended
files: the two SF-1 modules, three SF-1 test files, this document and an additive
README entry. Existing contracts, characterization tests, dependencies and
telemetry baselines remain unchanged.

One confirmed defect was reproduced before correction: Python `math.isfinite`
converts integer inputs through floating-point rounding. Both
`int(sys.float_info.max) + 1` and a larger integer still rounded to the largest
finite float and passed the documented magnitude bound. `_number` now compares
integer magnitude exactly against `int(sys.float_info.max)`; ordinary float
finiteness is checked separately. The largest permitted integer remains accepted,
and out-of-range positive/negative timestamp integers are rejected before any
admission or ledger reservation. This is a bounds correction, not a PSD policy
change or a new estimation feature.

No PSD/rank counterexample was found for valid bounded inputs. Added tests compare
all 125 symmetric 2×2 matrices over [-2,2] and all 729 symmetric 3×3 matrices over
[-1,1] against an independently formulated exact Schur-elimination oracle.
Four-dimensional non-leading/dependent-row cases, largest-finite float matrices
and mixed largest/subnormal diagonal entries verify rank without float
intermediate overflow or underflow. Negative zero remains mathematically zero
for PSD/rank but retains its source sign/type in fingerprints, as documented.

Additional admission tests exercise pending, stale, unknown-delivery,
missing-mapping and ambiguous-delivery deferrals, plus causal/derivation rejection
**after** fingerprinting. In each case the same key can subsequently be admitted
once and then identified as a duplicate. Rejected source/assumption conflicts do
not overwrite an admitted ledger entry. Aggregate rollback with a nonempty ledger
preserves that exact ledger object and permits later retry. No premature key
reservation, ledger-capacity consumption or input mutation was found.

The existing generic numerical and temporal contracts remain unchanged. Strict
symmetry/PSD, declared covariance/correlation assumptions, singular-model
restrictions, sequential caller-owned ledgers and lack of authentication remain
intentional limitations. No SF-2, association, tracking or estimator work is included.

### Final-review validation results

| Check | Final result | External wall time | Peak RSS |
| --- | --- | --- | --- |
| Focused SF-1 | 99 passed | 5.61 s | 44 MiB |
| Full Python | 2546 passed, 2 simulator opt-in skips | 118.53 s | 395 MiB |
| Full frontend | 396 passed across 19 files | 72.48 s | 333 MiB |
| TypeScript | passed | 1.46 s | 282 MiB |
| Production frontend build | passed | 1.35 s | 243 MiB |
| Tracked/new-file whitespace and scope audit | passed | — | — |

The 99 focused cases include 18 additional adversarial test instances; the
exhaustive matrix oracle also covers 854 matrices within one of those tests.
The two new positive-integer-boundary regressions failed against the pre-fix
implementation and pass after the exact guard correction. Python's internal
full-suite duration was 117.13 s. These are process/child memory maxima, not
aggregate simultaneous memory.

The public example was rerun in three fresh interpreters with different hash
seeds and reproduced the evidence/assumption fingerprints in the earlier section
unchanged. Current logs and reproducibility output are
`/tmp/aegis-sf1-review-{focused,python,frontend,typecheck,build}.log` and
`/tmp/aegis-sf1-review-reproducibility.json`; the generated build is
`/tmp/aegis-sf1-review-dist`. No dependency installation, simulator launch or SF-2
implementation occurred. The seven intended files remain unstaged, with no
commit, push, PR or merge. No blocking issue remains for a standalone SF-1 commit
once separately approved; this readiness does not claim physical calibration,
validated independence, or an implemented estimator.
