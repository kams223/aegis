# SF-4 proposal: Offline Correspondence and Continuity Evaluation

Status: independent implementation review completed; awaiting commit authorization. No observation identities
are assigned by this proposal. No correspondence result is fed into SF-3. No
production tracking, target acquisition, pursuit, interception, engagement,
autonomous control, real-time deployment or external transmission is proposed.

## Verified checkpoint and current change

PR #17 was independently verified merged into main. Fetched origin/main and
fast-forwarded local main both point to
`8b82fd6b92857374d716705c3b12fa593fafd5a4`. PR #17 was squash-merged:
the merge and reviewed SF-3 feature commit
`86d23b3ff05d3fc71b363d5c902d58e83c85f3de` have the identical repository tree
`076c92a1ff1662cff33fdc53bdd0e542db73ea49`; the feature commit itself is not an
ancestor of main. Content inclusion is verified by tree equality and empty diff,
not incorrectly required feature-commit ancestry. The working tree was clean before
creating `codex/sf4-association-research` from updated main.

At the architecture checkpoint, the only addition was this document. Architecture
approval subsequently authorized exactly the 15-file implementation manifest in
Appendix E. The implementation and validation record is in Appendix F. No
dependencies, earlier contracts or telemetry baselines are changed.

## 1. Existing interfaces and compatibility constraints

Abbreviated `fusion/...` and `simulation/...` source paths in this audit table
are relative to `src/aegis/`; documentation paths are stated separately.

| Existing implementation | Reuse / restriction |
| --- | --- |
| `src/aegis/fusion/contracts.py`: SensorObservation, MeasurementTime, ReferenceFrame | Preserve original typed payload, time and frame. Constructors alone are not strict admission. IDs are opaque; equal local IDs do not establish correspondence. |
| `fusion/admission.py`: EvidenceKey, AdmissionRequest, CorrelationClaim, admit_batch | Reuse scoped evidence identity and strict external-object validation. Preserve full request and age policy; AdmittedMeasurement alone loses maximum-age policy. Admission is not an identity decision. |
| `fusion/uncertainty.py`: CovarianceDeclaration, UnknownUncertainty, validate_covariance | Retain declarations/bases/provenance, exact symmetry/PSD validation and singular restrictions. Unknown stays unknown; no confidence-to-covariance conversion. |
| `fusion/clock_mapping.py`, `fusion/timing.py`: BoundedClockMapping, align_time, align_batch | Explicit bounded acquisition mappings and selected evaluation; no synchronization inference, wall clock or favorable endpoint selection. |
| `fusion/acquisition.py`: Acquisition, inspect_acquisitions | Completed nonempty, completed empty, unavailable and unconfirmed are distinct. SF-4 adds inspection-availability and opportunity metadata outside this unchanged class. |
| `fusion/derived_evidence.py`, `fusion/geometry.py` | Retain validated derivation references when present; do not infer geometry, depth, elevation or moving-platform pose. Geometry is not needed to score supplied identity claims. |
| `fusion/observation_history.py`: ObservationHistory | Caller order and duplicate occurrences are evidence, not tracks. History does not establish recursive payload validity. |
| `fusion/comparability.py`: assess_evidence_comparability | Compatibility of representations/time bounds is not physical correspondence. Do not convert its result into a matching rule. |
| `fusion/reference_estimator.py`: SF-3 operations / ReferenceAssumptions | Inspect as a boundary only. SF-4 does not import/call initialize, adapt_position, predict, correct or replay, create their assumptions, or export estimator inputs. |
| `simulation/reference_estimation.py` | Useful precedent for authored synthetic scenarios and deterministic reports. Its one-entity fixtures are not already a multi-identity correspondence dataset. Do not change them. |
| `simulation/sensor_telemetry.py`, Phase 75D/76A schemas | Aircraft IMU/GNSS/barometer histories are separate contracts, not external-object observations. Do not extend or reinterpret them. |

Reviewed tests include `test_fusion_admission*`, `test_fusion_uncertainty.py`,
`test_fusion_timing.py`, `test_fusion_geometry.py`, `test_fusion_acquisition.py`,
`test_observation_history.py`, `test_observation_delivery_replay.py` and the three
SF-3 reference test files. Their contracts and characterization expectations must
remain unchanged.

SF-1 carries JOINT_COMPATIBILITY_NOT_ASSESSED; unknown/shared correlation carries
NO_INDEPENDENT_COMBINATION. SF-2 retains/adds conservative restrictions. SF-4
preserves these flags verbatim. Counting correctness of externally supplied labels
does not fuse measurements, prove independence, or grant estimator admission.
Unknown or singular uncertainty can accompany a scorable identity label if all
source/time requirements are satisfied; it never becomes known estimator noise.

## 2. Architecture and information separation

Use three separate input artifacts and one separate output artifact:

```text
Observations + acquisition inventory + declared clock/age policies
                         |
                         +---- strict source/time validation ----+
                                                               |
Ground truth (oracle-only identities/opportunities) -------------+--> evaluator
                                                               |       |
Externally authored hypotheses + external label alignment ------+       v
                                                         read-only report

No hypothesis generator, nearest-neighbour rule, optimizer or SF-3 output path.
```

A hypothesis producer, if supplied externally, receives an observations-only
view/hash. Ground truth is available only to the scorer. File separation is an
API/data-flow discipline, not a security sandbox or proof that a producer never
looked at truth. No automatic best-label alignment (including Hungarian matching),
candidate search, distance gate, residual gate or identity allocation is present.

Each input binds to exact observation-artifact SHA-256. An external label means
only what the external hypothesis declares. Its mapping to a truth identity must
also be supplied externally; the evaluator never searches for the most favorable
mapping. Alignment protocol/provenance must be declared before scoring; externally
optimized alignment cannot be represented as independently verified. Many labels may explicitly map to one truth identity so fragmentation
can be measured. One label maps to at most one truth identity in an artifact;
reusing it on another entity is scored as an error, not repaired by remapping.

SF-4 only produces research annotations and counts. Even a correct score is not
an association decision returned to a runtime or permission to fuse evidence.

## 3. Proposed versioned data contracts

All wire documents use `schema_version: 1`, a distinct `artifact_kind`, exact
required fields and `additionalProperties: false` at every object. Unknown
versions/fields reject. These are research envelopes and lossless codecs around
existing normalized types, not a competing telemetry/measurement contract.
The normative field registry in Appendix A fixes wire names, required/null
semantics and closed nested shapes. Prose saying "optional" means an explicitly
nullable field unless that registry states otherwise; implementations cannot
choose their own envelope keys or derive missing values.

### 3.1 Observation dataset: offline_correspondence_observations

Required fields:

- dataset_id, revision, observation_view_id and generator provenance
  (generator_id, revision, declared configuration digest).
- scenario_clock_domain: the one canonical inspection domain for this report.
- steps: ordered Step records with step_id and nonoverlapping half-open windows
  [start,end) in that domain. Widths are positive; windows are strictly ordered.
- clock_mappings: ID/revision wrappers around existing BoundedClockMapping values.
- occurrences: ordered EvidenceOccurrence records.
- acquisitions: ordered AcquisitionEnvelope records.
- provenance: explicit synthetic raw/impaired view and bounded derivation lineage.

EvidenceOccurrence fields:

- occurrence_id: unique occurrence identity, distinct from source evidence.
- step_ref and acquisition_ref: explicit fixture membership, never guessed.
- admission_request: losslessly encoded existing AdmissionRequest, retaining its
  original observation, session, quantity/basis, uncertainty, correlation, age
  policy, evaluation and optional validated derivation.
- acquisition_mapping_ref: optional explicit mapping for original acquisition.
- optional occurrence_received_at: separate retransmission receipt provenance;
  never overwrite/infer the original known delivery from receipt order.
- source provenance: generator/configuration/source digests, origin, and optional
  derived-from EvidenceKey/digest. Original sensor/channel/session remain intact.

The versioned, closed source-graph codec in Appendix A supports existing
ImagePoint, ImageTrackMeasurement and
RadarPolarDetectionMeasurement payloads only, with closed tagged encodings of
their existing fields. Its derivation branches use the existing closed set of
DerivedSensorEvidence/calibration/rigid/mapped-time types; it must reconstruct
and revalidate them, not trust cached projection or interval fields. Source/time/
point links are encoded as references and reconstructed with the original shared
objects; equal copied payloads cannot replace required provenance identity links. Unrecognized
payload/derivation types reject, not stringify. In-memory objects retain source
references; the report uses references/digests rather than copying full payloads.

EvidenceKey is unchanged: (sensor_id, source_session_id, observation_id).
Acquisition identity is (sensor_id, source_session_id, acquisition_id). Source
local detector/track IDs remain opaque metadata and cannot become entity IDs.

AcquisitionEnvelope fields:

- acquisition_ref, step_ref, the existing Acquisition fields and nullable explicit
  acquisition_mapping_ref (needed even for an empty acquisition). The wire
  envelope stores observation occurrence refs; the loader reconstructs the
  unchanged Acquisition using the original referenced SensorObservation objects.
- available_at: explicit inspection-clock completion/availability time, or null.
- completeness_provenance: producer/generator assertion ID and revision.

A completed envelope includes its entire declared observation occurrence list.
Its completion must not precede the mapped acquisition or delivery of any member; repeated occurrences
must be referentially consistent. A completed empty acquisition is explicit.
Unavailable/unconfirmed is never empty completion. A missing callback is represented
as an explicit unconfirmed opportunity where an expected acquisition was declared;
absence of a schedule entry is not a scheduled miss.

A dataset contains one declared raw/impaired observation view. Different content
under one EvidenceKey within that view is a conflict. Compare raw and impaired
variants as separate digest-bound bundles, preserving their original keys and
explicit lineage. Do not pool variants as independent measurements or silently
rename their IDs to evade conflicts.

### 3.2 Ground truth: offline_correspondence_truth

Required fields: dataset_sha256, truth_id, revision, entity_catalog,
evidence_labels, opportunities and terminal_annotations.

- Catalog: explicit synthetic truth_entity_id and generator episode identity.
- Evidence label: exactly one record per distinct EvidenceKey, with either
  `known` and one truth_entity_id, `ambiguous` and 2–8 possible identities, or
  `unavailable` and a reason. Basic fixtures use fully known labels; partial truth
  is an explicit limitation case, not an excuse to omit a difficult row.
- Opportunity: (truth_entity_id, step_ref), expectation `expected` or
  `not_observable`, and explicit required acquisition_refs. An expected opportunity
  requires 1–8 acquisition refs; an empty schedule is not an observation opportunity.
  No automatic Cartesian product of every entity, sensor and time. Duplicate opportunity keys reject.
- Terminal annotation: explicit ended step and declared visibility time in the
  inspection clock. Visibility cannot precede the terminal step. It is oracle
  fixture metadata, not an inferred timeout.

Truth labels refer to logical evidence, not duplicate occurrences. Labels for
identical duplicate evidence must agree. Unknown references, contradictions
between labels and declared visibility, or observations after a declared terminal
step invalidate the bundle. End is exclusive at the start of its terminal step:
known/candidate truth labels cannot include that entity in the terminal step or
any later step. An explicit new episode requires a new supplied catalog identity,
never an evaluator-allocated replacement. A truth catalog entity not scheduled in a step does
not create an observation opportunity there. Clutter/no-entity scoring is outside
v1; it requires a separately reviewed truth class, not null meaning both clutter
and unknown.

### 3.3 Hypotheses: offline_correspondence_hypotheses

Required fields: dataset_sha256, hypothesis_id, revision, producer_provenance,
external_label_catalog, label_alignment and decisions.

- Catalog: every supplied external label is explicitly declared; all decision
  labels must refer to this catalog, including labels with no alignment.
- Alignment: external_label -> truth_entity_id, explicitly provided by the caller.
  An unmapped label remains unaligned. No optimizer fills in missing alignment.
- Decision: one per EvidenceKey, with `assigned` and one external_label,
  `ambiguous` and 2–8 distinct candidate labels, or `unresolved` and a reason.
- Every decision carries explicit decision_available_at and declared
  information_cutoff (each may be null), plus observations-only input-view digest.
  These are producer assertions, not independently established causal validity.
  Known decision time cannot precede the referenced source delivery; a known
  information cutoff must cover that delivery and not exceed decision time.
  Contradictory causal declarations are unresolved/ineligible with
  HYPOTHESIS_CAUSAL_CONFLICT, not scored as successful causal decisions.
- Missing decision becomes unresolved with MISSING_HYPOTHESIS; it is never an
  automatic negative detection or an identity assignment.

Unknown EvidenceKeys, contradictory duplicate decisions, unknown catalog IDs in
alignment, or invalid payloads reject the hypothesis artifact. Identical repeated
decision rows can be retained as diagnostic occurrences but count only once.
Candidates are never ranked, selected or reduced to one identity. A set of
candidate labels mapping to the same truth identity is still externally ambiguous.

This is an offline snapshot protocol. At a selected evaluation, future-declared
hypotheses are pending/unresolved; unknown decision availability is unresolved.
An information cutoff later than evaluation is ineligible. A missing cutoff is
marked causal_provenance_unverified; v1 can report retrospective label scores but
must not describe them as causal/online performance. A supplied cutoff/input digest
is not proof against hindsight. Report this limitation separately from accuracy.

### 3.4 Evaluation request and report

EvaluationRequest: evaluation time, dataset/truth/hypothesis expected digests,
policy_id/revision, explicit age policy selection, and caller-declared scope
(see the closed request/policy/scope registry in Appendix A).
No default wall-clock evaluation or implicit maximum-age policy. Source age
policies cannot be silently loosened. Effective age limit is the stricter of
source and report limits; None is explicit unbounded under SF-1, not an unknown
policy. A source with no recoverable age declaration is unsupported, not silently
assigned None. Repeated source requests for a key must agree on source age policy;
a conflict is CONTEXT_POLICY_CONFLICT even though SF-1 identity fingerprints omit
age. Preserve original request evaluation values as provenance without making
them identity or implicit synchronization facts. A changed context uses fresh existing
SF-1/SF-2 validation against the retained full request, not a cached admission.

CorrespondenceReport required fields:

- schema_version=1, artifact_kind=offline_correspondence_evaluation;
- status: complete, incomplete (explicit unscorable evidence), or rejected;
- exact input digests, policy ID/revision/hash, evaluation and scope;
- input population counts, duplicate counts and exclusions by reason;
- per-logical-evidence rows, with occurrence refs, original time/frame/provenance
  refs, timing status, estimator-admission status/restrictions, truth status,
  supplied hypothesis status, comparison outcome and ordered reason codes;
- passive lifecycle rows and continuity/fragmentation summaries;
- metrics with explicit populations and exact integer numerator/denominator;
- bounded structured diagnostics and diagnostics_dropped count.

Rejected artifacts yield metrics=null, not partially favorable performance
metrics. Incomplete reports can score their explicit eligible population, but
must expose excluded populations and cannot claim full-dataset accuracy. Zero
metric denominator means null plus EMPTY_POPULATION, never a perfect score.

## 4. Numeric, temporal and duplicate rules

Lossless scalar wire encoding: `{"kind":"int","value":"12"}` or
`{"kind":"float","value":"0x1.8000000000000p+3"}`. Use canonical decimal int
and float.hex spellings, strict built-in numeric types on decode, and existing
SF-1 finite/magnitude checks. Preserve signed float zero and int/float distinction.
No bool-as-number, NaN, infinity, interpolation or decimal float round-trip loss.
MeasurementTime remains the existing seconds/domain type. Native Phase 75D/76A
nanosecond timestamps are not coerced or admitted by this external-object profile.

Each report has one inspection clock. Reuse SF-2 explicit acquisition mappings
and exact/outward interval policy. In v1 delivery/completion/decision availability
must be point times in that domain. Different/unknown delivery domains remain
unscorable with a reason; no bounded interval is collapsed to a point. Adding
bounded delivery support is a future contract revision, not an implicit workaround.

Source metadata validation, timing eligibility and estimator admission are separate
columns. Use existing SF-1/SF-2 validation, including an independent align_time
check when uncertainty is unknown: SF-1's primary deferral reason alone does not
establish availability. Invalid values/frames/covariances invalidate input;
unsupported clock relationships are explicitly unscorable, not guessed. Unknown
or singular uncertainty alone need not prevent an ID-only oracle comparison, but
retains its estimator restrictions and never becomes an estimator input.

A record is available only when known delivery <= evaluation, acquisition bounds
establish causal eligibility, and every applicable explicit age limit is satisfied
using worst-case age. Inclusive delivery and age boundaries follow SF-2. Its full
mapped acquisition interval must fit its declared step window; crossing a window
boundary is TEMPORAL_ORDER_AMBIGUOUS, not arbitrary step selection. Stable display
order is (step ordinal, original occurrence ordinal); it asserts no simultaneity.
Equal timestamps belong to the same nonoverlapping time window. Within-step
observations are aggregated as sets for continuity, not linearized into switches.

Identical EvidenceKey/content/assumptions repetitions retain occurrence order and
DUPLICATE_EVIDENCE diagnostics; primary metrics use one logical evidence item.
Repeated keys must also agree on step/acquisition membership, source provenance,
mapping declaration and source age policy. A retransmission may change only its
occurrence ID/receipt metadata and original request evaluation value in the same
evaluation domain. Conflicting membership cannot move a duplicate into another
step to alter continuity. Content equality uses the existing SF-1 type-preserving canonical rules, without
object identity or selected evaluation value. Different content/assumptions under
one key rejects the bundle; no first-row-wins or silent dropping. Truth/hypothesis
conflicts are likewise explicit. Hashes establish repeatability, not authenticity.

## 5. Decision outcomes and populations

Let E be all distinct, valid, temporally eligible evidence in scope. Let T be
its subset with a single known ground-truth identity. Primary metrics use T.
Every logical evidence item remains visible in the report, including exclusions.

Comparison precedence:

1. Ineligible input: unscored, with delivery/clock/staleness reason.
2. Truth unavailable: unresolved, reason TRUTH_UNAVAILABLE (outside T).
3. Truth ambiguous: ambiguous, reason TRUTH_AMBIGUOUS (outside T).
4. No available hypothesis, unresolved declaration or unmapped assigned label:
   unresolved, with distinct missing/pending/unaligned reason (inside T).
5. Explicit candidate decision: ambiguous; never count it correct merely because
   the candidate set includes truth (inside T).
6. Available singleton label with supplied alignment: correct if its aligned truth
   ID equals the known label, otherwise incorrect (inside T).

Per-row truth_status and hypothesis_status remain separate, so precedence cannot
hide the source of uncertainty. Decisions outside a partial truth candidate set
can receive a diagnostic, but do not enter primary accuracy as fully known truth.
No evaluator output fills a missing hypothesis or assigns an unknown identity.
The exact populations, scope behavior and report-status rules are fixed in
Appendix B; do not mix outside-T outcomes into the four primary counts.

For T, counts C,I,A,U are disjoint and sum to |T|:

| Metric | Exact definition |
| --- | --- |
| Conditional resolved accuracy | C/(C+I) |
| Resolved coverage | (C+I)/\|T\| |
| Strict correctness | C/\|T\|, includes ambiguous/unresolved in denominator |
| Unresolved fraction | U/\|T\| |
| Ambiguous fraction | A/\|T\| |
| Eligible-data coverage | \|E\| / number of valid logical evidence items in scope |
| Known-truth coverage | \|T\|/\|E\| |

Always show counts beside ratios. Report truth-unavailable/ambiguous counts,
unsupported/pending/stale populations and raw occurrence/duplicate counts
separately. An all-unresolved result has strict correctness zero (when |T|>0),
conditional accuracy null, and unresolved fraction one. This prevents selective
abstention, duplicate inflation or omitted rows from appearing perfect.

## 6. Passive lifecycle and continuity metrics

Lifecycle rows are oracle-side research annotations keyed by already declared
truth identity; they are not maintained active tracks or identities assigned to
measurements. Continuity summaries use a separate external-label namespace and cite supplied
decisions. V1 accepts only oracle terminal annotations, not an unspecified
hypothesis-terminal protocol. No automatic births or terminations.

- observed: valid, delivered evidence has this known truth label in a declared
  opportunity. Source age may add STALE_AT_EVALUATION; it does not erase the
  historical observation or make it a physical miss.
- temporarily_missing: entity explicitly expected, all required acquisitions are
  known completed at evaluation, all member truth labels are known-single with
  valid temporal placement, and no delivered evidence for it is present. Stale
  evidence, partial truth or excluded source timing cannot establish absence.
- resumed: an observed -> temporarily_missing+ -> observed pattern within one
  fully assessed episode block. Missing -> first observation is observed, not
  resumed. Unknown, not-scheduled, not-observable and scope boundaries reset this
  pattern; they cannot establish a previous physical loss.
- ended: explicit terminal oracle annotation visible by evaluation; never inferred
  from a missing-count threshold or end of file.
- unknown: absence cannot be established; distinct pending, unavailable,
  unconfirmed, partial-truth and temporal causes are retained as reason codes.
- not_observable: explicitly supplied truth expectation, not inferred absence.
  Not-scheduled intervals are continuity break reasons, not automatically
  generated entity-by-step lifecycle rows. No physical miss is asserted.

Completion metadata cannot precede member deliveries. A late member therefore
keeps its acquisition unclosed at earlier evaluation, preventing false missing
annotations. Terminal annotations after the selected evaluation are not applied.
A hypothesis's absence/wrong label does not erase a truth-side observed event.
Ambiguous/unavailable member truth makes absence unassessable in v1; never use
lack of a known-single truth match to assert a physical miss. Lifecycle is an
availability view of recorded history, distinct from age-filtered scoring. A
scoring exclusion (stale age, incompatible time, unverified placement) is an
unassessed continuity boundary, not an assessed hypothesis gap.

For each selected truth opportunity, first establish assessment completeness:
all required acquisitions must be closed by evaluation; member truth must be
known-single; acquisition placement and source scoring eligibility must be
established; and scope must not hide any of its evidence. Otherwise it is an
unassessed continuity boundary. Presence can still be oracle-observed from an
available member before acquisition closure, but uniqueness of a supplied label
cannot yet be assessed.

Only for an assessed opportunity, collect correct singleton supplied labels:

- One distinct label: resolved step, even across multiple sensors. Also retain
  counts of all incorrect/ambiguous/unresolved rows. Any non-correct row alongside
  correct rows marks MIXED_STEP; the retention metric is explicitly conditioned
  on correct singleton labels and cannot replace overall correctness/coverage.
- Two or more distinct labels: split, with IDENTITY_SPLIT; no majority/first label
  is chosen, and the step is an assessed gap for resolved-segment construction.
- No correct singleton: assessed gap, with a physical-empty or decision-gap cause.
  All involved rows remain in the primary counts; no missed detection is invented.

Comparable links join successive resolved steps in a known active episode with
only assessed opportunities between them. They may span confirmed missing or
decision gaps. Unknown/not-observable intervals and ambiguous temporal placement
break assessment; equal-time observations never create sequential links.

Metrics:

- same_label_links S and changed_label_links W; identity retention S/(S+W), null
  if no comparable link exists. Report unassessed breaks separately.
- confirmed reappearance gaps: known observed -> missing+ -> observed sequences,
  independent of whether supplied labels were correct.
- segment_count per assessed block: maximal runs of resolved steps with one label,
  broken by any assessed gap or label change. Fragmentation is the sum over blocks
  of max(0, segment_count-1), not distinct-label count minus one.
- split_steps: multiple correct supplied labels for one truth entity at one step.
- contaminated_labels: supplied singleton labels used on observations belonging to
  more than one known truth identity. Also report same-step LABEL_COLLISION and
  adjacent_step_identity_changes: for that label, two adjacent dataset step
  ordinals each must be fully assessed and have exactly one distinct known truth
  identity among its available singleton claims. Count a change only if those
  identities differ. Missing, colliding or unassessed steps create no such link;
  do not skip across them. This statistic is not a physical identity switch claim.
  This examines all available singleton assignments on eligible single-truth
  evidence, including incorrect assignments and unaligned labels (U). Alignment
  is unnecessary to inspect the supplied token's truth support. Candidate labels
  are not treated as assignments. Do not exclude wrong rows to conceal reuse.

Examples: A,A gives one segment/zero fragmentation. A,B,A gives three segments/two
fragments. A,confirmed-gap,A gives two segments/one fragment but retains its label
across the comparable endpoint link. A,unknown,A gives two separate assessment
blocks and an unassessed break; no invented fragmentation across missing evidence.
Known decision gaps can fragment a hypothesis even while truth remains observed.
These are explicitly defined research metrics, not claims of standard MOTA/IDF1;
no optimal identity matching or inferred missed-detection denominator is performed.

## 7. Hand-calculated acceptance example

Known entity g, mappings L1->g, L2->g, LB->other. All listed evidence is unique,
available and single-truth unless noted. Hypotheses are externally authored.

| Step | Acquisition/truth evidence | Supplied decision | Outcome / oracle lifecycle |
| --- | --- | --- | --- |
| 0 | e0 for g | assigned L1 | correct / observed |
| 1 | e1 for g | candidates L1,L2 | ambiguous / observed |
| 2 | expected g, completed empty | no evidence decision | no evidence row / temporarily_missing |
| 3 | e3 for g | assigned L2 | correct / resumed |
| 4 | expected g, unconfirmed acquisition | none | unknown; no physical miss |
| 5 | e5 for g | assigned LB | incorrect / observed, resumption unconfirmed |
| 6 | e6 for g | omitted hypothesis | unresolved / observed |
| 7 | explicit terminal annotation | none | ended once terminal time is visible |

\|T\|=5, C=2, I=1, A=1, U=1. Conditional accuracy=2/3, resolved coverage=3/5,
strict correctness=2/5, ambiguous=1/5, unresolved=1/5. Retransmitting e0 identically
does not change these numbers. The first assessed block has two resolved segments
(L1 then L2), one fragmentation and one changed-label link. Step 4 introduces an
unassessed boundary. No new identity or correspondence was generated.

A second oracle case supplies two labels for two sensors observing g at one step:
both per-observation decisions can be correct, yet split_steps=1. A label assigned
to both g and another entity is contamination/collision, not a reason to remap it.

## 8. Proposed APIs, files and dependency order

Public operations implemented by the research modules:

```text
load_research_bundle(paths, expected_digests, policy) -> BundleLoadResult
validate_research_bundle(observations, truth, hypotheses, policy) -> BundleValidation
evaluate_supplied_hypotheses(validated_bundle, evaluation_request) -> CorrespondenceReport
report_bytes(report) -> bounded canonical bytes
```

Evaluator inputs/outputs are immutable; no hidden ledger, polling or background
state. It has no API for allocating labels, proposing candidates or sending
assignments to an estimator. A rejected validation has no evaluator-ready bundle.

Proposed future file manifest:

- `src/aegis/simulation/correspondence_contracts.py`: frozen research wrappers,
  closed outcomes, policy and bound declarations; refer to existing source types.
- `src/aegis/simulation/correspondence_evaluation.py`: pure scoring, passive
  annotations, diagnostics and explicitly defined continuity metrics.
- `src/aegis/simulation/correspondence_io.py`: strict bounded lossless codec,
  input digest verification and canonical report serialization.
- `configs/simulation/correspondence-observations-v1.schema.json`
- `configs/simulation/correspondence-truth-v1.schema.json`
- `configs/simulation/correspondence-hypotheses-v1.schema.json`
- `configs/simulation/correspondence-report-v1.schema.json`
- `examples/correspondence_research_fixture.py`: deterministic authored datasets
  plus literal supplied hypotheses with independent expected counts; no algorithm
  constructs hypotheses from hidden truth at evaluation time.
- `tests/test_correspondence_contracts.py`
- `tests/test_correspondence_evaluation.py`
- `tests/test_correspondence_lifecycle.py`
- `tests/test_correspondence_io.py`
- `tests/test_correspondence_research_fixture.py`
- This document (refine proposed details after review) and additive README entry.

No changes to existing fusion, timing, spatial, telemetry, reference-estimator or
characterization implementations/tests are proposed. No monitoring-console work
is needed for the first offline evaluator. No new dependency is assumed; existing
requirements do not declare a JSON-schema package. Runtime closed decoding can
use stdlib validation; schema/tooling additions require separate approval if they
need an extra package.

Implementation sequence, each gated by its acceptance tests:

1. Approve profiles, populations, outcome precedence and lifecycle definitions.
2. Add closed contracts/codecs and schema parity/immutability/bound tests.
3. Add label-only scorer and independently hand-calculated decision/count tests.
4. Add passive annotations/continuity metrics and chronology/collision tests.
5. Add authored fixtures and bounded read-only loader/report entry point.
6. Run focused tests, full Python/frontend regressions, typecheck, production
   build, hash-seed checks and tracked/untracked whitespace/manifest audit.
7. Independent design/implementation review before any commit authorization.

## 9. Determinism, resource and failure policies

Proposed v1 caps (hard validation limits, not silent truncation):

| Resource | Bound |
| --- | --- |
| Observation input bytes | 4 MiB |
| Ground-truth bytes | 1 MiB |
| Hypothesis bytes | 1 MiB; aggregate inputs <=6 MiB |
| Occurrences / logical evidence / acquisitions / steps | <=1024 each |
| Truth identities / supplied labels | <=128 / <=256 |
| Explicit opportunity rows | <=4096, never a generated cross product |
| Required acquisition refs per expected opportunity / total edges | 1–8 / <=8192 |
| Candidates per truth/hypothesis ambiguity | 2–8 |
| Clock mappings / lineage entries per source | <=64 / <=16 |
| Source graph nodes per occurrence | <=128; also subject to aggregate node cap |
| Decision rows / label alignments / terminal rows | <=1024 / <=256 / <=128 per artifact |
| Lifecycle rows | <=4096 selected opportunities + <=128 terminals |
| Evidence rows / per-entity summaries / per-label summaries | <=1024 / <=128 / <=256 |
| Diagnostic code / path / explanation lengths | <=128 / <=256 / <=512 UTF-8 bytes |
| Identifier length | <=128 UTF-8 bytes (stricter profile; never truncate originals) |
| Aggregate canonical source text | <=1 MiB |
| Decoded nodes / nesting | <=100,000 / <=16 |
| Diagnostics | <=256 retained, exact dropped count |
| Report bytes | <=8 MiB |

Count/budget overflow rejects atomically with bounded diagnostics; never sample
primary metrics, evict evidence, or emit partial success. Report-output overflow
returns a minimal rejected envelope with metrics=null. Diagnostic overflow alone
retains deterministic earliest diagnostics and exact total/dropped counts.

Parse strict UTF-8, reject duplicate JSON keys/nonfinite constants, bound reads
and lexical depth/node budgets before JSON object construction (including quoted
string escape handling), and convert parser/recursion failures into bounded
diagnostics. Accept explicit regular local files only (no URLs, archives,
symlink following or input mutation). Hash exact input bytes before decoding.
Canonical output has fixed schema/revision, field and array ordering, exact
integer count ratios and lossless source scalar encodings. Do not include current
time, elapsed runtime, absolute machine paths or random IDs in hashed reports.
Measurements of runtime/RSS go outside canonical artifacts under /tmp.

Order evidence by preserved ordinals and diagnostic stages; sort independent
summary keys by canonical identifier encoding, never Python set iteration. Test
PYTHONHASHSEED=0,1,1729. Equal source timestamps retain stable occurrence order;
order must not manufacture temporal/identity certainty. Separate SHA-256 bindings
for observations, truth, hypotheses and policy prevent unintended cross-dataset
reuse and make raw/impaired runs distinguishable.

Target complexity O(B + N log N + O log O), linear bounded storage in bytes B,
evidence/hypothesis records N and explicit opportunities O. Use indexes/grouped
lists, not all-pairs distance matrices, exhaustive assignments or a tracker.
Decode once, retain immutable source references, and avoid repeated large copies.
Inputs remain byte-for-byte unchanged. No Docker, Gazebo, browser, network access,
new heavyweight dependency or background service is required.

## 10. Test plan and acceptance criteria

The approved test plan follows; executed results are recorded in Appendix F:

| Area | Required independent/adversarial cases |
| --- | --- |
| Outcome metrics | Hand table above; all-correct/incorrect/ambiguous/unresolved; omitted decisions; causal-declaration conflicts; partial/unavailable truth; candidates containing truth never selected; unaligned labels stay unresolved; zero denominator gives null. |
| Identity namespace | Same local ID across sensors/sessions; explicit many-label-to-one alignment; no inferred alignment; declared but unmapped labels; undeclared label references reject; different dataset digests; unrelated raw/impaired views cannot mix. |
| Duplicates | Identical retransmission cannot improve metrics; conflicting content/assumptions/truth/decisions reject; independent EvidenceKeys preserved. |
| Acquisition | Completed nonempty vs empty vs unavailable vs unconfirmed; unscheduled channel not a miss; malformed completion before member delivery; no callback never implies empty. |
| Timing | Delivery/evaluation equality, stale-bound equality, delayed/out-of-order delivery, missing availability, incompatible clocks, negative offsets, bounded mapping inconsistency, equal timestamps, interval/window boundary ambiguity. |
| Provenance | Exact original times/frames/scalars/digests/restrictions retained; source arrays and files unchanged; unknown/singular covariance never replaced or promoted. |
| Lifecycle | Observed/missing/resumed/end examples; unknown breaks; later terminal unavailable at earlier evaluation; no automatic timeout end; no observed entity resurrects after explicit end; stale evidence remains historically observed and partial truth cannot establish missing. |
| Continuity | A,A; A,B,A; A,gap,A; A,unknown,A; within-step label splits; same label on two entities; wrong assignments included in contamination, not silently excluded. |
| Numeric/schema | Int/float/bool distinctions, signed zero, finite extremes, nonfinite values, invalid covariance/frame, duplicate JSON keys, unknown fields/versions, malformed UTF-8, nesting/count/text/file/output limits. |
| Isolation | SF-3 entrypoints patched to fail if called; no automatic assignment API, estimator inputs or live services; earlier contracts and evidence untouched. |
| Repeatability | Three fresh executions and three hash seeds; stable full report bytes and ordered diagnostics; no wall-clock metadata; no pairwise matching hidden in metric code. |

Acceptance requires all count invariants, independent lifecycle/metric oracles,
explicit exclusion populations, immutable sources, bounded error results, and
full regression compatibility. Documentation must distinguish executed tests from
proposed tests. Any contract conflict must stop implementation for review rather
than weakening SF-1/SF-2/SF-3 restrictions.

## 11. Scientific limitations and review decision

This evaluates supplied labels against authored truth; it does not discover
correspondence or demonstrate operational association capability. Truth quality,
visibility/opportunity annotations, completeness assertions, external alignment
and causal-provenance assertions are conditional inputs. Hashes do not authenticate
them. New fixtures should use opaque evidence IDs independent of truth identity
so a test cannot succeed by parsing a truth label embedded in an ID. Existing
source identities must not be rewritten to manufacture this property. Fixed
fixtures are not statistically representative sensor experiments.

Accuracy is conditional on its reported population. Truth ambiguity and unsupported
timing reduce scorable coverage and cannot be presented as successful correspondence.
Continuity is label-token stability relative to declared truth, not a verified
physical track or estimator state. Fragmentation definitions are proposal-specific
and must accompany any score. Unknown acquisition gaps cannot justify asserted
physical loss/resumption/termination. Input frames/covariance remain evidence
metadata, not identity features or calibrated association probabilities.

There is no clutter/no-entity metric, learned matcher, best-label assignment,
Mahalanobis gate, MOTA/IDF1 optimizer, hypothesis feedback, SF-3 coupling, real-time
tracker, autonomous control or operational deployment. Any extension requires
separate scope/contract review. The architecture review and its corrections are recorded in the appendices.
The approved design is now implemented within the Appendix E manifest. Appendix F
distinguishes executed validation from the architecture-stage test plan. No commit
is authorized; independent implementation review remains required.

## Appendix A. Normative closed wire-field registry (architecture review)

This registry closes omissions in the prose contract. Every named object has
exactly the listed keys, all required. `?` below means a required nullable value,
not an omitted key. Arrays may be empty unless a lower bound is stated. No
extension/free-form metadata dictionaries are accepted. A different field set or
semantics requires another schema version; unknown keys/versions reject.

### A.1 Shared types and source codec

- Text identifiers: nonblank UTF-8, <=128 bytes, no controls/surrogates. Free-form
  reasons/explanations <=512 bytes; paths <=256. No truncation. Original source
  fields exceeding this stricter research profile reject without renaming them.
- Digest: exactly 64 lowercase hexadecimal characters. Counts/indices: built-in
  integers, not bool, nonnegative and within the specified collection bounds.
- Scalar: exactly `{kind,value}`; kind=int with canonical decimal string, or
  kind=float with finite canonical float.hex string. Int -0/leading zeros are
  noncanonical; float signed zero is preserved. SF-1 magnitude bounds still apply.
- Time: exactly `{seconds,clock_domain}` with Scalar and identifier, decoded to
  existing MeasurementTime. Frame: `{frame_id}`. EvidenceKey: exactly
  `{sensor_id,source_session_id,observation_id}`. No truth identity in these types.
- AssertionProvenance: `{assertion_id,revision}`. Generator:
  `{generator_id,revision,configuration_sha256}`.
- LineageEntry: `{operation_id,revision,configuration_sha256,input_sha256}`.
- DerivedFrom: `{dataset_sha256,evidence_key}`.
- Provenance: `{generator,origin,upstream_source_sha256,derived_from,lineage}`;
  origin=synthetic_raw|synthetic_impaired; upstream_source_sha256 and derived_from
  are nullable, lineage has <=16 entries. Upstream hashes refer to independent
  source/configuration artifacts, not the artifact's own enclosing bytes. Raw
  data may have no upstream artifact; impaired data requires explicit upstream
  binding/lineage. Own artifact digest is computed externally, avoiding self-hash
  fixed points. Hashes do not authenticate generator assertions.
- ClockMapping: `{mapping_id,revision,mapping}`. Mapping's exact field set is
  source_clock_domain, target_clock_domain, scale, offset_seconds,
  valid_from_source_seconds, valid_until_source_seconds, error_bound_seconds,
  using existing BoundedClockMapping numeric/domain rules. No inferred mapping.

`admission_request` uses a **closed source-graph codec**, not arbitrary Python
serialization: `{root_ref,objects}`. Each node is exactly `{object_id,type,fields}`;
object_id is unique locally, type is one of the following audited tags, and fields
has exactly that row's keys. A dataclass-valued field is a closed `{ref}` object
or null where the existing type permits null. Tuples are arrays; numeric leaves
use Scalar (int-only where the existing contract requires an integer). Strings,
enums and null follow the unchanged source types. No generic object tags,
executable constructors, pickles, import-by-name or extra fields are accepted.

| Tag | Exact existing field names |
| --- | --- |
| AdmissionRequest | observation, source_session_id, entity_kind, quantity, basis, uncertainty, correlation, evaluation, available_at, max_age_seconds, derivation |
| SensorObservation | observation_id, sensor_id, measurement_time, reference_frame, measurement, source_local_id |
| MeasurementTime | seconds, clock_domain |
| ReferenceFrame | frame_id |
| EvidenceKey | sensor_id, source_session_id, observation_id |
| CorrelationClaim | mode, group_id, assumption_id, scope |
| MeasurementBasis | measurement_kind, axes, units, reference_frame |
| CovarianceDeclaration | matrix, measurement_basis, uncertainty_provenance |
| UnknownUncertainty | reason |
| UncertaintyProvenance | model_id, revision, method |
| ImagePoint | u_px, v_px, image_width, image_height, image_frame |
| ImageTrackMeasurement | class_id, label, confidence, x1, y1, x2, y2, image_width, image_height |
| RadarPolarDetectionMeasurement | range_m, azimuth_rad, elevation_rad, radial_velocity_mps |
| DerivedSensorEvidence | source_observation, spatial_projection, camera_intrinsics, spatial_transform, transformed_geometry, mapped_time |
| CameraRay | direction_x, direction_y, direction_z, optical_frame, source_image_point, calibration_id |
| PinholeCameraIntrinsics | fx_px, fy_px, cx_px, cy_px, image_width, image_height, image_frame, optical_frame, calibration_id |
| RadarPoint | x_m, y_m, z_m, reference_frame, source_measurement |
| RigidTransform | source_frame, target_frame, rotation_target_from_source, translation_target_from_source_m |
| TransformedPoint | x_m, y_m, z_m, reference_frame, source_point |
| RotatedDirection | direction_x, direction_y, direction_z, reference_frame, source_ray |
| BoundedClockMapping | source_clock_domain, target_clock_domain, scale, offset_seconds, valid_from_source_seconds, valid_until_source_seconds, error_bound_seconds |
| MappedTimeInterval | lower_seconds, upper_seconds, clock_domain, source_time, source_mapping |

Root must be AdmissionRequest. Root generator and provenance.generator agree;
occurrence origins agree with the declared observation view.
 Enforce the existing allowed field type unions,
not just these key sets. Reject unknown/unused nodes, dangling refs, cycles, wrong
root, invalid derived values, copied substitutes for required identity links,
and graphs exceeding 128 nodes/depth 16. The aggregate decoded-node budget also
applies. Resolve shared refs to the same immutable object; re-run source/derived
validation rather than trusting graph tags or cached fields. An existing mapped
acquisition must agree exactly with its explicit acquisition_mapping_ref; no
search among alternative mappings is allowed. ExactCovariance, SF-3 state or
assumptions, and native aircraft telemetry are not supported source tags.

Shared schema definitions reside under $defs in the proposed observation schema;
the other three proposed schemas reference those fixed local definitions. No
user-defined/remote $ref resolution or fifth telemetry schema is introduced.
Independent round-trip/invalid-reference tests must cover every source tag.

### A.2 Exact four artifact shapes

Every top-level shape includes integer schema_version=1 and the literal
artifact_kind named below. These fields were implicit in the earlier lists.

**Observation root** (`offline_correspondence_observations`):
schema_version, artifact_kind, dataset_id, revision, observation_view_id, generator,
scenario_clock_domain, steps, clock_mappings, occurrences, acquisitions, provenance.

- Step: `{step_id,start,end}`; Time endpoints share scenario domain, start<end,
  windows do not overlap. Step IDs are unique, ordinals are array positions.
- Occurrence: `{occurrence_id,step_ref,acquisition_ref,admission_request,
  acquisition_mapping_ref,occurrence_received_at,provenance}`. Last mapping and
  receipt fields are nullable; receipt never replaces original source delivery.
- AcquisitionEnvelope: `{acquisition_ref,step_ref,sensor_id,source_session_id,
  acquisition_id,acquisition_time,status,observation_occurrence_refs,reason,
  acquisition_mapping_ref,available_at,completeness_provenance}`.
  acquisition_time/reason/mapping/available_at are nullable under existing
  Acquisition and timing rules. Status=completed|unavailable|unconfirmed.
  Reconstruct existing Acquisition from these fields and the original referenced
  observations; do not invent an alternative acquisition class. Completed with
  refs is nonempty; completed without refs is empty. Completion availability must
  cover the whole mapped acquisition interval and every original member delivery.

Every occurrence belongs to exactly one acquisition, and every envelope ref must
resolve back to it with matching sensor/session/step. Repeated logical evidence
cannot change acquisition or step membership. Retransmission receipt may differ.
Known-single truth labels require an explicit expected opportunity covering their
step and acquisition; no opportunity is generated from a label. Ambiguous truth
candidates must all be compatible with declared opportunities/episode boundaries.

**Truth root** (`offline_correspondence_truth`):
schema_version, artifact_kind, dataset_sha256, truth_id, revision, entity_catalog,
evidence_labels, opportunities, terminal_annotations.

- Entity: `{truth_entity_id,episode_id}`; identity is unique in the catalog and
  names one supplied episode, not an evaluator-assigned birth.
- Known label: `{evidence_key,status,truth_entity_id}`, status=known.
- Ambiguous label: `{evidence_key,status,candidates}`, status=ambiguous, 2–8
  distinct catalog identities. No singleton reduction is performed.
- Unavailable label: `{evidence_key,status,reason}`, status=unavailable.
- Opportunity: `{truth_entity_id,step_ref,expectation,required_acquisition_refs}`.
  expectation=expected needs 1–8 distinct refs; not_observable needs an empty list.
- Terminal: `{truth_entity_id,step_ref,visible_at,provenance}`; visible_at is a
  non-null inspection-clock Time at/after terminal step start. At most one per
  catalog identity. End excludes the entire terminal step and later steps.

Evidence-label keys are unique and cover every logical source key exactly once;
contradictory or repeated truth assertions reject, including identical duplicate
label rows (only observation/hypothesis retransmissions have a duplicate policy).
Expected opportunities at/after an entity's end are invalid. No late observation
or possible truth candidate may resurrect an ended identity under another token.

**Hypothesis root** (`offline_correspondence_hypotheses`):
schema_version, artifact_kind, dataset_sha256, hypothesis_id, revision,
producer_provenance, external_label_catalog, label_alignment, decisions.

- ProducerProvenance: `{producer_id,revision,alignment_protocol_id}`; protocol ID
  is nullable and unverified, never an implicit best-alignment operation.
- external_label_catalog: distinct identifier strings, including unaligned labels.
- Alignment: `{external_label,truth_entity_id}`; one per external label at most,
  both refs valid. Many labels may map to one entity; never the converse.
- Assigned decision: `{evidence_key,status,external_label,decision_available_at,
  information_cutoff,input_view_sha256}`, status=assigned.
- Candidate decision: same common fields with candidates instead of external_label,
  status=ambiguous, 2–8 distinct declared external labels.
- Unresolved decision: same common fields with reason instead of external_label,
  status=unresolved. Each union branch forbids the other branches' fields.
- decision_available_at and information_cutoff are nullable Time; input_view_sha256
  is nullable only when cutoff is null. A declared cutoff requires its exact
  observations-only view digest. Unknown cutoff cannot supply a verified digest.

Decision row occurrences are <=1024 total; exact repetitions collapse by source
key, preserving row ordinals. Differences in status, candidates, label or temporal
assertions under one key reject rather than choosing an update. Unaligned means
a declared label has no supplied alignment; undeclared labels are invalid refs.

**Report root** (`offline_correspondence_evaluation`):
schema_version, artifact_kind, status, bindings, evaluation, policy, scope,
populations, evidence_rows, lifecycle_rows, continuity, metrics, diagnostics,
diagnostics_dropped.

- Bindings: `{dataset_sha256,truth_sha256,hypotheses_sha256,policy_sha256}`;
  each nullable if its bounded input could not be read/validated. No self hash.
- evaluation is Time; policy/scope use A.3. On rejection before request validation,
  evaluation/policy/scope/populations may be null. They are non-null for complete
  or incomplete outputs. Any minimal rejection fallback may null those fields
  while retaining known input/policy hashes, including after output overflow.
- EvidenceRow: `{evidence_key,occurrence_refs,step_ref,acquisition_ref,source_ref,
  truth_ref,hypothesis_refs,timing_status,temporal_reason,admission_status,source_diagnostics,restrictions,
  uncertainty_status,truth_status,hypothesis_status,comparison_status,reason_codes,
  continuity_eligibility}`. source_ref is `{primary_occurrence_ref}` resolved under
  bindings.dataset_sha256, retaining original timestamps/frames/provenance through
  that ref. truth_ref is the original truth-label row ordinal; hypothesis_refs
  lists every identical original decision-row ordinal, or [] for a missing
  hypothesis. No factual input is replaced with inferred or current values.
- timing_status=eligible|ineligible. temporal_reason is null for eligible,
  otherwise an exclusion code in Appendix D. admission_status is existing
  admitted|deferred|rejected or not_evaluated, never an SF-4 identity decision.
  restrictions is the exact returned restriction list when available, otherwise
  null (not an empty list suggesting permission). Original declarations remain
  reachable through source_ref in every case. source_diagnostics uses existing
  Diagnostic's closed `{code,path,explanation}` shape; codes are bounded source
  text, not unknown evaluator enums. SF-4 never promotes a deferred source into
  an estimator-admitted one.
- uncertainty_status=known_psd|unknown; truth_status=known|ambiguous|unavailable;
  hypothesis_status=assigned|ambiguous|unresolved|missing|pending|unaligned|invalid_context;
  comparison_status=correct|incorrect|ambiguous|unresolved|unscored;
  continuity_eligibility=assessed|unassessed.
- LifecycleRow: `{truth_entity_id,step_ref,status,reason_codes,opportunity_ref,
  evidence_refs}`; status=observed|temporarily_missing|resumed|ended|unknown|not_observable.
  opportunity_ref is nullable only for an explicit terminal row. Pending,
  unavailable and unconfirmed are distinct causes under unknown, not competing
  primary states. observed/resumed rows cite the known delivered evidence for
  that entity/step; aggregate such evidence refs <=1024. Other lifecycle states
  use [] and their opportunity/required-acquisition refs, not copies of all member
  evidence. No entity-by-step Cartesian product is generated.
- Continuity: `{entities,labels}`. EntitySummary keys: truth_entity_id,
  assessed_steps, resolved_steps, assessed_gaps, unassessed_opportunities,
  not_observable_steps, unassessed_breaks, block_segment_counts, fragment_count,
  same_label_links, changed_label_links, split_steps, mixed_steps,
  confirmed_reappearances, resolved_step_coverage, identity_retention.
- LabelSummary keys: external_label, assigned_known_truth_count, truth_support,
  contaminated, collision_step_count, adjacent_step_identity_changes,
  assessed_adjacent_links. truth_support is the sorted set of actual known truth
  refs for supplied singleton claims, not an optimized alignment or chosen label.
- Metrics has exactly the seven names in section 5, using snake_case:
  conditional_resolved_accuracy, resolved_coverage, strict_correctness,
  unresolved_fraction, ambiguous_fraction, eligible_data_coverage,
  known_truth_coverage. A metric is null or `{numerator,denominator}` with explicit
  integer counts and denominator>0; preserve count denominators without reduction.
- Rejected output has metrics=null, empty result-row arrays/continuity summaries,
  known bindings and bounded diagnostics. No partial success or invented metrics.
  A minimal fallback envelope must fit <=4096 bytes, even on output overflow.

Populations' exact keys: occurrence_count, logical_evidence_count, in_scope_count,
eligible_count, known_truth_count, duplicate_occurrence_count, excluded_scope_count,
excluded_by_reason, truth_ambiguous_count, truth_unavailable_count, correct_count,
incorrect_count, ambiguous_count, unresolved_count. excluded_by_reason is a sorted
array of `{reason_code,count}`, not an open map. Each excluded item has exactly
one primary source exclusion; additional reasons are preserved per row.

The following digest objects have exact fields (not new artifact types):

- SourceFacts: profile="sf4-source-facts-v1", sf1_evidence_sha256,
  sf1_assumptions_sha256, source_max_age_seconds, step_ref, acquisition_ref,
  acquisition_mapping_ref, provenance. SF-1-style declaration digests use the
  original request's evaluation domain and existing type-preserving canonical
  profile; they are available as canonical declarations even when admission is
  deferred, and are never represented as an admission grant. The value of the
  request evaluation is excluded as in SF-1. SourceFacts SHA uses the canonical
  JSON profile below, never raw source-graph node IDs.
- EnvelopeFacts: profile="sf4-acquisition-facts-v1", acquisition_ref, step_ref,
  sensor_id, source_session_id, acquisition_id, acquisition_time, status,
  logical_evidence_keys, reason, acquisition_mapping_ref, available_at,
  completeness_provenance. The distinct logical keys retain primary occurrence
  order; receipt/duplicate occurrence IDs are excluded.

Report source_diagnostics per evidence row is capped at 8, restrictions at 32,
reason-code lists at the finite unique SF-4 code set; excess rejects as BOUND,
not silent loss. Source refs and hypothesis refs sum to their respective <=1024
input-row caps. These caps are in addition to the 8 MiB report byte limit.

### A.3 Closed request, policy, scope and reproducible views

EvaluationRequest is an internal immutable input, not a fifth file artifact:
`{schema_version,evaluation,expected_digests,policy,scope}`. expected_digests has
exactly dataset_sha256, truth_sha256, hypotheses_sha256 (all required Digests).
Policy: `{policy_id,revision,additional_max_age_seconds}`, last field Scalar or
null. The definitions in this proposal are fixed for v1; an ID cannot select
arbitrary code, gates, matching heuristics or a different metric definition.

Scope: `{evidence_keys,opportunity_keys}`; each null means all, [] means none,
otherwise a unique list of existing refs. OpportunityKey is
`{truth_entity_id,step_ref}`. No silently ignored unknown refs. Scope is declared
before scoring and bound into policy_sha256 together with policy using canonical
bytes. It is reported, never optimized. C/I/A/U use selected evidence only;
oracle presence/absence examines the full declared acquisition inventory. A
filter hiding evidence cannot turn an observed entity into temporarily_missing.
Continuity requires complete scope coverage of an opportunity's member evidence;
otherwise SCOPE_EXCLUDED is an unassessed boundary, not a fragmentation claim.

A declared information_cutoff must be in the scenario domain and <= decision time.
`input_view_sha256` has this exact preimage (no truth or hypothesis fields):

1. Canonical header `{profile:"sf4-observation-view-v1",dataset_sha256}`.
2. One event for each logical evidence item with known scenario-domain delivery
   by cutoff, regardless of age or acquisition-clock scorable status; plus one
   for each acquisition-status declaration whose scenario-domain available_at is
   known by cutoff (including unavailable/unconfirmed). View inclusion is not
   proof of acquisition closure. Evidence
   events are `{kind:"evidence",evidence_key,source_sha256}`; acquisition events
   are `{kind:"acquisition",acquisition_ref,envelope_sha256}`. Source/envelope hashes
   use canonical validated source/envelope bytes, excluding occurrence receipts
   and duplicate repetitions. Canonical source facts use the existing SF-1
   evidence/assumptions canonical digests plus source-age policy, mapping,
   membership and provenance as in section 4, excluding source-graph object IDs
   and request evaluation value. Envelope facts use the closed envelope and
   ordered distinct logical member keys, not occurrence receipts/IDs. They do
   not hash their own containing value. Duplicate equality is decoded fact
   equality, not arbitrary source-graph node naming or JSON whitespace.
3. Canonical suffix `{kind:"cutoff",time}`.

Events sort by (availability time, kind order evidence before acquisition, original
primary ordinal). Hash the header/events/suffix each preceded by its 4-byte
big-endian byte length. Canonical JSON here uses ASCII escaping, lexicographically
sorted keys, fixed separators, arrays in declared order, tagged source scalars,
no insignificant whitespace and a final newline per encoded object. Digest is
SHA-256 over those length-prefixed bytes. No source age filtering: this manifest
binds known delivered facts, not the potentially smaller scoring population.
Only unknown/unsupported delivery or status-availability clocks prevent view
membership; an unsupported acquisition clock alone does not erase a known
delivered fact. No time is guessed to fill the view. The producer receives only corresponding observation data, never truth.

Hashing a manifest certifies declared data membership, not actual producer use or
absence of hindsight. Unknown cutoff has null view hash and unverified causal
provenance; it can support explicitly retrospective label scores, not online
claims. A wrong supplied view digest rejects the hypothesis artifact.

An implementation can sort availability once, update one hash prefix, copy it per
cutoff and append the suffix. This avoids O(observations × decisions) repeated
full manifests and preserves the bounded O(N log N) objective. Independent small
oracles must recompute each prefix naively to verify this optimization.

## Appendix B. Population, lifecycle and continuity decision rules

### B.1 Populations and completion status

Let L be distinct valid logical evidence in the observation artifact, regardless
of evaluation. Let Ls be its declared evidence scope, E the source-timing/window/
age-eligible subset of Ls, and T the single-truth subset of E. Thus:

- logical_evidence_count=|L|, in_scope_count=|Ls|, excluded_scope_count=|L|-|Ls|.
- eligible_count=|E|; |Ls|=|E|+sum(excluded_by_reason.count).
- |E|=known_truth_count+truth_ambiguous_count+truth_unavailable_count.
- Only T contributes to C/I/A/U; C+I+A+U=known_truth_count.
- Raw occurrence/duplicate counts are independent of L and never weight accuracy.

Future, stale, unsupported-clock and boundary-ambiguous evidence remains in Ls,
with exactly one primary exclusion. Primary exclusion precedence is:
CLOCK_MAPPING_REQUIRED / DELIVERY_CLOCK_UNSUPPORTED / ACQUISITION_UNKNOWN,
then DELIVERY_UNKNOWN, then TEMPORAL_ORDER_AMBIGUOUS, then PENDING_DELIVERY,
then STALE_MEASUREMENT. Invalid mappings or known causal reversals are input
errors, not selectable exclusions. Multiple additional facts remain reason flags.

Hypothesis contextual eligibility is separate and never shrinks T. Decision
availability/cutoff in a wrong clock, a future/unknown decision time, a future
cutoff or a contradictory causal assertion produces U on known truth. Input-view
digest mismatch rejects the hypothesis, rather than claiming an unverified valid
view. For valid decisions, unmapped singleton is U; candidate set is A; mapped
singleton is C or I. An unknown cutoff alone can yield explicitly retrospective
scores with CAUSAL_PROVENANCE_UNVERIFIED, never a causal performance claim.

Each displayed ratio uses its exact count denominator in section 5. None means
undefined, not zero or one. Example: empty L gives all seven ratios null. Nonempty
T with all U gives conditional accuracy null, strict correctness 0/|T|, resolved
coverage 0/|T| and unresolved |T|/|T|. All A is analogous with ambiguity one.

Rejected means structural, binding, source-value, truth-consistency, reference or
resource validation failed; no performance metrics are emitted. Incomplete means
a valid bundle has source exclusions, partial truth, or a selected expected
opportunity unassessable because of unavailable/unknown evidence. Complete means
those requested populations are assessable. All-A/all-U hypotheses can still be
a complete evaluation with poor coverage; they do not imply invalid input. Empty
valid populations are complete with null ratios. Explicit not-observable rows
and undeclared opportunities do not create missing-data obligations. Causal
provenance uncertainty is separately reported, never hidden by complete status.

### B.2 Lifecycle precedence and evidence needed for absence

Only declared selected opportunities (plus visible explicit terminals) create
lifecycle rows; no entity×step expansion. Evaluate each at the selected inspection
time, using original evidence times and full acquisition membership:

1. A visible terminal at this/later step gives ended. Truth validation prohibits
   known/candidate observations and expected opportunities in or after that step;
   it does not discard late observations to make the truth look consistent.
2. Otherwise, any valid delivered known-single observation for the entity gives
   observed. This remains a fact even if other acquisitions are unconfirmed or
   its source age makes it stale for accuracy. Resumed replaces observed only
   for an O,M+,O sequence within a known episode block.
3. Explicit not_observable gives not_observable; a contradictory observation
   would already have invalidated truth.
4. For expected, if all required acquisitions are completed, available and
   temporally placed, all member truth labels are known-single, and no delivered
   member is for this entity, give temporarily_missing. An empty completed
   acquisition satisfies the member-truth requirement vacuously, but never an
   absent acquisition reference or an unconfirmed callback.
5. Otherwise give unknown, preserving all causes: pending closure, unknown
   closure time, unavailable/unconfirmed acquisition, unknown clock/placement or
   partial member truth. No precedence between those causes changes the state.

A missing referenced acquisition row rejects the bundle as UNKNOWN_REFERENCE.
A present unconfirmed row is valid unknown evidence; the evaluator never inserts
that placeholder itself. Unknown closure time cannot establish absence. Dropping
out-of-scope or stale evidence cannot establish absence. Opportunity selection
can restrict which rows are requested but cannot edit their full inventory.

An observed fact before acquisition closure does not prove a unique hypothesis
label for that step. Continuity assessment requires all required acquisitions
closed, all member truth/placement known and source scoring eligibility plus
scope coverage for all members. This distinction prevents a delayed second
sensor from being silently ignored when testing for a split.

First sightings following initial misses remain observed. Unknown,
not-observable, not-scheduled, unselected opportunity intervals, or excluded
source eligibility break resumption assessment. Do not infer physical loss,
return, termination or a new identity across such a break.

### B.3 Exact continuity construction and independent examples

For each entity, process its explicit opportunity refs by step ordinal. Missing
intermediate dataset step ordinals with no entity opportunity are not_scheduled
breaks; no synthetic opportunity row is made. Partition assessed expected steps
into blocks separated by unassessed/not-observable/not-selected intervals.
Within a block, give each step exactly one class:

- R(label): the set of C singleton labels has cardinality one.
- X: that set has cardinality >=2 (split); a split is an assessed gap, not R.
- G: no C singleton (physical empty or I/A/U decision gap).

Mixed C and I/A/U rows do not disappear: increment mixed_steps, retain all primary
counts and identify the conditional nature of R. They do not turn incorrect rows
into correct ones or force an evaluator-selected label. All members classified X
are still available per-observation C rows if their supplied alignments are right.

For resolved steps within each block, compare successive R endpoints: same label
increments S, different label W, including across G/X. These links describe
supplied endpoint-label retention, not uninterrupted observation. A segment is a
maximal run of adjacent R steps with the same label; any G/X or label change
breaks a segment. Blocks with no R have segment_count=0, not a perfect track.

Always report assessed_steps=resolved_steps+assessed_gaps, resolved_step_coverage
=resolved_steps/assessed_steps (null for zero denominator), split_steps,
mixed_steps and unassessed breaks alongside retention and fragmentation. Sum
max(0, segment_count-1) within each block only. Never count an unassessed boundary
as either same identity or a confirmed fragment. Total block/segment metadata is
bounded by selected opportunities; do not generate arbitrary time samples.

Here A and B are different **supplied labels aligned to the same truth identity**;
M is a confirmed physical missing step, U is an assessed unresolved decision, and
? is unknown acquisition/placement. All other facts are known/closed:

| Sequence | Primary count example | S,W / retention | Segments by block / fragmentation | Additional findings |
| --- | --- | --- | --- | --- |
| A,A | C=2 | 1,0 / 1/1 | [1] / 0 | resolved coverage 2/2 |
| A,B,A | C=3 | 0,2 / 0/2 | [3] / 2 | accuracy can be 1 despite label changes |
| A,M,A | C=2, no evidence at M | 1,0 / 1/1 | [2] / 1 | one confirmed reappearance; resolved coverage 2/3 |
| A,U,A | C=2,U=1 | 1,0 / 1/1 | [2] / 1 | no oracle missing/resumed event if truth observed at U |
| A,?,A | C=2, unknown opportunity | 0,0 / null | [1,1] / 0 | one unassessed break; no claimed resumption |
| A,{A,B},A | C=4 across 3 steps | 1,0 / 1/1 | [2] / 1 | split_steps=1; resolved coverage 2/3 |
| {A,B} only | C=2 | 0,0 / null | [0] / 0 | split_steps=1; resolved coverage 0/1 |
| M,A | C=1 | 0,0 / null | [1] / 0 | first observation, not resumed |

For contamination, use **all available assigned singleton decisions on T**,
including wrong and unaligned labels, never candidate sets. Group their actual
truth refs per external label. |truth_support|>=2 means contaminated; more than
one truth at a step increments collision_step_count once, not per pair. For
adjacent_step_identity_changes count only adjacent dataset steps both fully
assessed and with singleton truth support for that token. A collision/unknown/
absent group supplies no link; never choose one truth or skip past a collision.

Example: one label L aligned to g1, used on g1 then g2 at adjacent assessed steps,
gives C=1,I=1, contaminated=true and one adjacent-step identity change. If both
uses are at the same step, C=1,I=1, collision_step_count=1, and zero sequential
changes. A,B both aligned to g at one step gives C=2, split_steps=1 and no
contamination: it is many labels for one truth, not one label for many truths.

## Appendix C. Required adversarial design cases and expected outcomes

All ratios below assume selected-time/source eligibility unless stated otherwise.
These are review oracles, not tests claimed executed against an implementation.

| Case | Expected outcome and rationale |
| --- | --- |
| Empty observation collection | Valid with empty acquisitions/truth-label/decision arrays as applicable; \|L\|=\|E\|=\|T\|=0, seven primary ratios null and EMPTY_POPULATION. Catalog/opportunities may be empty; explicit expected completed-empty opportunities can still yield temporarily_missing, never accuracy=1. No identities are allocated. |
| All unresolved | For n>0 known-truth observations: U=n,C=I=A=0; conditional accuracy null, strict=0/n, coverage=0/n, unresolved=n/n. Assessed decision gaps produce resolved_step_coverage=0; no fabricated observed-label segments. |
| All ambiguous | A=n,C=I=U=0; conditional accuracy null, strict/coverage=0/n, ambiguous=n/n. Including truth in candidates does not earn correctness. No candidate is selected. |
| Same evidence identity twice | Same content/context/membership/provenance is one logical item plus duplicate occurrence; C/I/A/U and continuity unchanged. Different content, policy, mapping, step or acquisition is a rejected conflict, not first-row-wins or two independent observations. |
| Contradictory ground truth | Two labels for one key, unknown entity, inconsistent opportunity or explicit end conflict rejects with metrics=null. Truth is not repaired using the hypothesis, majority votes or motion. |
| Incomplete acquisition inventory | Missing required acquisition ref rejects as UNKNOWN_REFERENCE. Present unconfirmed/unavailable/unknown-completion record is valid unknown lifecycle, incomplete assessment, no physical miss or automatic empty row. Observed members can establish presence but not full continuity uniqueness. |
| Delayed evidence, valid acquisition | Before known delivery: retained source row unscored/PENDING_DELIVERY; no C/I/A/U contribution and no false missing from a premature closure. At delivery equality: eligible if all other bounds hold, scored in its acquisition step, not moved into a later step. Out-of-order receipt does not overwrite acquisition/availability. |
| Cross-clock, no declared mapping | Retain original source/domain; row unscored with mapping/unsupported-clock reason, still in coverage denominator. No conversion by matching labels. If all n rows excluded, E=T=0, eligible coverage=0/n and other primary ratios null; lifecycle remains unknown. |
| Label changes without truth changes | A,B,A aligned to one truth: C=3, S=0,W=2, retention=0/2, fragmentation=2; no new truth identity. This exposes continuity failures despite perfect per-observation correctness. |
| Multiple labels for one truth | At one fully assessed step two correctly aligned singleton labels give C=2, split_steps=1, no R step and resolved coverage=0/1. Different-step changes follow A,B,A. No majority/best label is chosen. |
| One label for multiple truths | A mapping row for L pointing to two truths rejects as HYPOTHESIS_CONFLICT; with one fixed alignment to g1, decision reuse on g1/g2 gives C=1,I=1 and contamination. Same-step case is a collision with no ordered switch; adjacent assessed steps give one identity change. Never remap L to maximize score. |
| Terminal then later observation | Known/candidate truth label at terminal step or later violates exclusive end; reject as TERMINAL_CONFLICT, metrics=null. Do not discard the observation, extend end, allocate a replacement identity or feed a correction to SF-3. |
| Initial missing then first observation | M,A yields temporarily_missing then observed, not resumed; no previous sighting exists to resume. |
| Stale delivered observation | Excluded from accuracy under age policy, kept historically observed with STALE_AT_EVALUATION, and unassessed for age-filtered continuity. Never a physical miss. |
| Ambiguous/unavailable member truth | Cannot establish absence from lack of a known-single match. It is unknown lifecycle/continuity, not temporarily_missing; outside-T outcome/status remains separate from primary C/I/A/U. |
| Same-time observations | Both belong to one step; aggregate sets for split/collision. Input ordinal is display order only; it never manufactures changes or earlier/later physical acquisitions. |
| Scope hides a delivered observation | Accuracy uses its declared selected population; full-inventory oracle presence remains observed. Continuity becomes unassessed if member coverage is incomplete, not confirmed missing. Scope and excluded counts remain visible. |
| Future or causally contradictory hypothesis | Known truth observation stays in T; the decision is U with pending/causal-conflict reason, reducing strict correctness. A missing cutoff alone permits only explicitly retrospective/unverified scores. |

## Appendix D. Deterministic diagnostics, limits and isolation

SF-4 reason codes are closed by stage. Existing source Diagnostic codes are
preserved as bounded source text in source_diagnostics and do not silently become
new evaluator enum values. Rejection/exclusion/quality roles are distinct:

| Stage | Closed SF-4 codes | Effect |
| --- | --- | --- |
| io/schema | IO_ERROR, UTF8, SCHEMA, VERSION, BOUND, DIGEST_MISMATCH | Reject input/request. |
| references | UNKNOWN_REFERENCE, GRAPH_CYCLE, GRAPH_TYPE, EVIDENCE_CONFLICT, REFERENCE_MEMBERSHIP_CONFLICT, CONTEXT_POLICY_CONFLICT, TRUTH_CONFLICT, HYPOTHESIS_CONFLICT, TERMINAL_CONFLICT | Reject; no partial metrics. |
| source | SOURCE_INVALID, CLOCK_MAPPING_INVALID, COMPLETION_CONFLICT | Reject, retaining original validator diagnosis. |
| source notes | DUPLICATE_EVIDENCE, DUPLICATE_HYPOTHESIS, UNCERTAINTY_UNKNOWN, SINGULAR_UNCERTAINTY | Count duplicates/restrictions without independent measurement promotion. |
| source eligibility | SCOPE_EXCLUDED, CLOCK_MAPPING_REQUIRED, DELIVERY_CLOCK_UNSUPPORTED, ACQUISITION_UNKNOWN, DELIVERY_UNKNOWN, TEMPORAL_ORDER_AMBIGUOUS, PENDING_DELIVERY, STALE_MEASUREMENT | Primary excluded population or explicit assessment boundary. |
| hypothesis | MISSING_HYPOTHESIS, HYPOTHESIS_UNRESOLVED, HYPOTHESIS_PENDING, HYPOTHESIS_AVAILABILITY_UNKNOWN, HYPOTHESIS_UNALIGNED, HYPOTHESIS_CAUSAL_CONFLICT, HYPOTHESIS_CLOCK_UNSUPPORTED, HYPOTHESIS_CUTOFF_FUTURE | U on T, never a selected identity. |
| hypothesis view | INPUT_VIEW_MISMATCH | Reject digest claim; no silent recomputation to repair it. |
| comparison | TRUTH_UNAVAILABLE, TRUTH_AMBIGUOUS, LABEL_MATCH, LABEL_MISMATCH, CAUSAL_PROVENANCE_UNVERIFIED | Outcome or explicit evidence limit, not estimator confidence. |
| lifecycle | ACQUISITION_UNCONFIRMED, ACQUISITION_UNAVAILABLE, ACQUISITION_PENDING, COMPLETION_UNKNOWN, UNKNOWN_MEMBER_TRUTH, NOT_SCHEDULED, NOT_OBSERVABLE, STALE_AT_EVALUATION | Causes/quality flags; never an automatic miss/timeout. |
| continuity | OPPORTUNITY_UNASSESSED, IDENTITY_SPLIT, LABEL_COLLISION, CONTAMINATED_LABEL, MIXED_STEP | Explicit research counts/coverage limits; no identity resolution. |
| summary | EMPTY_POPULATION, OUTPUT_BOUND | Null denominator or minimal rejected output. |

Diagnostic is exactly `{code,stage,severity,reference,path,explanation}`.
Severity=info|limitation|error; reference is null or
`{artifact,collection,index}` with closed artifact names observations|truth|
hypotheses|request|report and collection one of the registered array field names
in Appendix A (or null for root). Index is nullable for root; otherwise a valid
original input/output ordinal. Explanation/path/code lengths follow section 9.
A structural error is not downgraded because diagnostics fill their cap.

Canonical diagnostic order: stage table order, artifact order above, original
row ordinal (root first), field path bytes, code table order. Summary arrays sort
by UTF-8 identifier bytes; evidence/occurrence/decision source ordinals are never
rewritten. Ratios are exact and count-based, with no float scores or hidden
rounding. Diagnostic truncation keeps first 256 in that order, with exact dropped
count. Validate all bounded input before publishing success. Output overflow uses
one OUTPUT_BOUND diagnostic and a <=4096-byte rejected envelope; it can null
request metadata, retain known digests, empty row/summary arrays, and declare
how many prior diagnostics were omitted.

Additional aggregate bounds: graph nodes <=128 per source and <=100,000 decoded
nodes overall; graph/source acyclicity and depth<=16; alignment rows <=256;
truth terminals<=128; decision rows including retransmissions<=1024; total
lifecycle rows<=4224; evidence rows<=1024; entity summaries<=128; label summaries
<=256. Total block metadata<=4096 and total truth-support edges<=1024. Identical
retransmissions count against input bounds even though they do not weight metrics.
No hidden N×entity or label×truth expansion is allowed.

Canonical report JSON uses the same ASCII/sorted-key/fixed-separator/newline
profile as view objects. Counts are unsigned integers within caps, never bool;
source numeric fields remain tagged scalars. Every bounded file is hashed before
parse; no hash is filled in by editing an input. No parser-generated identities,
null-as-zero values, arbitrary object imports or wall-clock values are allowed.

Isolation acceptance is structural as well as behavioral: the proposed three
simulation modules may depend on SF-1/SF-2 validation/types, but not SF-3 estimator
operations, operational tracking/control packages or live transport. They do not
change package exports, register callbacks, mutate original evidence, or return
ReferenceMeasurement/ReferenceAssumptions/estimator-update objects. Tests must
trap SF-3 calls and compare input bytes/objects before and after. Reports may cite
supplied labels and oracle truth for diagnostics, but are never estimator inputs.

## Appendix E. Review verdict, final manifest and exact implementation sequence

Architecture verdict at design review: coherent after the corrections in
Appendices A–D, suitable for user review before implementation. No contract waiver, identity assignment,
SF-3 integration or operational component is required. That review established design approval
readiness; the subsequent implementation was separately authorized. Neither
authorization permits a commit. Executed results are recorded in Appendix F.

Confirmed design omissions/contradictions corrected:

1. "Closed" artifacts lacked exact field/union/null shapes and shared-reference
   codec semantics. Registry A now specifies them, bounds source graphs and
   forbids arbitrary Python or SF-3 object serialization.
2. Producer input-view hash and scope were undefined. Their canonical preimages,
   required refs, information cutoffs, source-age handling and scope-independent
   oracle presence checks are now explicit. No self-referential artifact hash.
3. Lifecycle could confuse an initial sighting with resumption, a partly closed
   acquisition with unique hypothesis support, or an observation in the terminal
   step with a valid end. Rules B.2 separate these cases. V1 drops the previously
   undefined optional hypothesis-terminal protocol; only explicit oracle ends
   are accepted, and hypothetical terminal fields are unknown keys in v1.
4. Continuity lacked full assessment prerequisites, resolved-step coverage and
   exact split/mixed/contamination handling. B.3 provides constructive definitions
   and counts; zero fragments alone never means successful continuity.
5. Duplicate membership conflicts, partial populations, report completion status,
   minimal rejection output and deterministic diagnostic ordering were incomplete.
   They are now specified without modifying SF-1/SF-2 behavior.
6. The original test matrix did not give expected outcomes for every adversarial
   case. Appendix C supplies those outcomes and rationale, including both forms
   of incomplete inventory and same-time collisions.

Approved implementation manifest (all paths are now implemented):

| File | Scope |
| --- | --- |
| `src/aegis/simulation/correspondence_contracts.py` | New immutable research envelopes, closed statuses, fixed bounds/policy. |
| `src/aegis/simulation/correspondence_io.py` | New bounded local codec, graph/reference validation, view/report hashing. |
| `src/aegis/simulation/correspondence_evaluation.py` | New pure supplied-hypothesis scoring and passive diagnostics. |
| `configs/simulation/correspondence-observations-v1.schema.json` | New closed observation artifact and shared $defs. |
| `configs/simulation/correspondence-truth-v1.schema.json` | New closed oracle truth artifact. |
| `configs/simulation/correspondence-hypotheses-v1.schema.json` | New closed external hypothesis artifact. |
| `configs/simulation/correspondence-report-v1.schema.json` | New closed report/request-policy/scope definitions. |
| `examples/correspondence_research_fixture.py` | New authored small bundles and literal external decisions. |
| `tests/test_correspondence_contracts.py` | New source compatibility, shape/ref/budget tests. |
| `tests/test_correspondence_io.py` | New lossless round-trip, read-only, digest, parser and report tests. |
| `tests/test_correspondence_evaluation.py` | New independent population/outcome/metric oracles. |
| `tests/test_correspondence_lifecycle.py` | New lifecycle, coverage, split/fragment/contamination cases. |
| `tests/test_correspondence_research_fixture.py` | New authored-fixture counts, seed checks and SF-3 isolation guards. |
| `simulation/SF4_ASSOCIATION_RESEARCH.md` | Refine this reviewed design with actual validation evidence later. |
| `README.md` | Additive offline research entry only, after implementation approval. |

Exact dependency/acceptance order:

1. User approves this corrected architecture and its definitions; stop otherwise.
2. Implement contracts and four schemas with contract tests: closed keys/unions,
   typed source graph/ref identity, scalar fidelity, every tag, episode/scope and
   all declared aggregate bounds. Do not add a scorer yet.
3. Implement bounded reading/decoding, exact input binding and observation-view
   digests in IO; independently test invalid bytes/refs/cycles, duplicate keys,
   cutoff prefixes, immutability and atomic failures. No extra dependency assumed.
4. Implement source/timing eligibility and external-decision outcomes/populations
   in evaluation, using unchanged SF-1/SF-2 checks. Pass C/I/A/U/coverage arithmetic
   oracles, unknown-clock and delayed/stale/duplicate cases before lifecycle work.
5. Implement oracle lifecycle, assessed blocks and continuity counts in the same
   evaluator. Pass B.2/B.3 and every relevant Appendix C oracle, including no
   future visibility, no false miss, no first-sighting resumption and no tie choice.
6. Complete closed canonical report encoding and capped rejection envelopes;
   test count invariants, output limits, null denominators, deterministic order
   and preservation of source diagnostics/restrictions without estimator promotion.
7. Add the authored fixture/example and fixture tests. Verify all adversarial
   expected outcomes, three fresh runs, three hash seeds, no SF-3 calls/import
   path, no control/transport exports and unchanged input bytes/objects.
8. Run complete focused and existing Python/frontend regressions, typecheck,
   production build, schema/codec parity and whitespace/manifest audit. Measure
   RSS/time where practical, run heavy suites sequentially, and retain artifacts
   under /tmp. Perform independent implementation review; commit/push/PR still
   require separate user authorization.

Remaining scientific limitations: oracle identities/opportunities/completeness
and external alignment are supplied assertions; causal cutoff provenance is not
authenticated; no metric proves physical correspondence or sensor accuracy. The
metrics are explicitly conditional and proposal-specific, not optimized MOT
scores. Partial truth/time/scope reduces coverage. Unknown callbacks cannot prove
loss or resumption. A read-only report provides no SF-3 update mechanism, verified
track state, automatic identity, real-time behavior or actuation authority.

## Appendix F. Implementation and reproducible validation

The implementation is additive and restricted to the 15 approved paths. The four
checked-in schemas are generated from the same closed field registry used by the
stdlib runtime validator; tests check their equality and closed object shapes.
Cross-reference integrity, numeric canonicality, source type unions and semantic
count/clock rules additionally require the runtime validator, not just JSON
Schema shape validation. No new dependency or remote schema resolver is used.

Public interfaces:

- `correspondence_contracts`: immutable `FrozenMap`, `ContractError`, fixed bounds,
  source-tag registry, `scalar`/`unscalar`, closed shape and report-count validation.
- `correspondence_io`: `Artifact`, `parse_artifact`, `artifact_from_data`,
  `read_artifact`, `encode_source`/`decode_source`, `canonical_bytes`, `digest`,
  `source_facts`, `view_digests`, and explicit time/evidence-key codecs.
- `correspondence_evaluation`: `validate_research_bundle`, `load_research_bundle`,
  `evaluate_supplied_hypotheses`, `report_bytes`; immutable `ResearchBundle` and
  `BundleValidation` (`BundleLoadResult` alias). A failed validation has no bundle;
  a failed evaluation has no metrics or result rows. File loading takes an
  explicit policy as well as expected input digests; evaluation always takes the
  complete closed request. `report_bytes` returns bytes and never writes them.

An immutable `Artifact` can only be publicly constructed from bounded bytes and
an artifact kind; its digest and decoded cache cannot be independently supplied
or replaced. This closes a provenance counterexample found during implementation:
a freely replaceable digest could bind changed contents under an older hash.
An `Artifact` does not by itself constitute source admission or a valid
three-artifact bundle. Bundle validation performs reference/source checks; the
pure evaluator rechecks them at the selected context rather than trusting cached
admission. Cached source objects must agree with the source graph. Shared object
references survive decoding, and a derivation containing an equal copied source
observation is rejected. Unknown uncertainty remains deferred for estimation;
its declaration and correlation assumptions remain reachable through source refs.

Acquisition member summaries are indexed once and reused along the bounded
explicit opportunity edges. There is no generated entity/step product or
observation-distance matrix. Clock-declaration consistency checks use at most the
fixed 64-mapping inventory, independently of evidence count. Output diagnostics
are sorted/capped after validation, never used as a reason to stop validation.
Both primary exclusions and additional exclusion facts are retained; only the
primary reason contributes to exclusion denominators.

The authored fixture prints four report SHA-256 hashes, without writing files:

```sh
PYTHONPATH=src python3 -B examples/correspondence_research_fixture.py
```

The acceptance fixture literally supplies oracle labels and external claims for
section 7. Other fixtures cover simultaneous split labels, no observations and
an independently digest-bound impaired view. No hypothesis is synthesized by
reading truth, no ambiguous candidate is selected, and no SF-3 interface is
called or exported. These are software examples, not physical sensor experiments.

Validation commands use the existing `/home/ali/venvs/aegis/bin/python`, pytest,
and `/tmp/node-v24.21.0-linux-x64/bin/node`. The system `python3` has no pytest;
no dependency was installed. Logs, RSS measurements, production output and
repeatability captures are kept under `/tmp/aegis-sf4-*`, outside Git.

Initial implementation validation (2026-11-02; superseded by the independent
review in Appendix G; no test weakening):

| Check | Result | GNU time wall / maximum RSS |
| --- | --- | --- |
| Focused SF-4 | 148 passed | 10.11 s / 55.8 MiB |
| Explicit SF-1/SF-2/SF-3 selection | 256 passed | 72.88 s / 46.7 MiB |
| Complete Python regression | 2,851 passed, 2 existing opt-in skips | 167.33 s / 409.7 MiB |
| Complete frontend, one worker / sequential files | 396 passed, 19 files | 83.20 s / 330.3 MiB |
| TypeScript typecheck | Passed | 1.56 s / 270.7 MiB |
| Production build | Passed; `/tmp/aegis-sf4-dist` | 0.98 s / 194.6 MiB |

GNU time reports maximum resident set size, not aggregate WSL/process-tree RAM.
The two Python skips require explicit real Gazebo/Docker-physics opt-in; neither
was enabled. Heavy validation commands ran sequentially. The sandboxed existing
Starlette API test blocked in AnyIO/asyncio (a 25-second bounded probe captured
its stack); the unchanged complete suite passed with approved unsandboxed
execution. The first sandboxed frontend run had 8 existing CLI-test failures
(`spawnSync` EPERM) and 388 passes; the unchanged approved unsandboxed rerun
passed all 396. These environment failures were not repaired by changing tests,
baselines, application contracts or dependencies.

Independent byte-level prefix oracles, exact population ratios, all reviewed
continuity sequences, all 22 source tags, zero denominators, atomic rejection,
source/byte immutability, resource caps, diagnostic overflow and SF-3/clock/IO
isolation are covered by the five SF-4 test files. Implementation checks corrected
three concrete provenance/canonicalization defects: copied derivation source
objects, freely replaceable artifact hashes/caches, and acquisition digest members
ordered by reference-list order rather than primary occurrence ordinal.

Four full report hashes matched byte-for-byte in three fresh processes with
`PYTHONHASHSEED=0,1,1729` (also tested by the focused suite):

```text
acceptance f84269a630af9100e82c3cb41179b318270862942d1e1de9129bf6036ad1b43e
empty 4d45d17919d7f7665b8b89e2426405d8291e2f7dda9068f4a9c5625e42ff0403
impaired 9f3bbe1d56ebe6e25a94914cecb9521797e6919b6f76562214b4ff2fe540562a
split 520662f5ed9d6460d401574166bbf22d4666d997a498f8045540c4498a867062
```

The four-scenario fixture command took 0.40 s for seed 0; maximum RSS across the
three measured processes was 23.0 MiB. These small-fixture measurements
are not a performance certification at every input cap.

Final scope/whitespace validation checks tracked and untracked files and the
empty index against the exact 15-path Appendix E manifest. Earlier SF-1/SF-2/SF-3
implementations/tests, dependencies and telemetry baselines remain unchanged.
No normative wire, metric, population or lifecycle deviation was introduced.
The loader's explicit policy argument and byte-only Artifact construction are
public API clarifications; neither grants estimator admission. Scientific limits
in section 11 remain: supplied assertions are not authenticated truth, declared
cutoffs do not prove lack of hindsight, partial evidence reduces coverage, and
these proposal-specific scores do not establish physical sensor accuracy or
operational correspondence. No automatic association, SF-3 feedback, actuation,
network service or live transport exists. Ready for independent implementation
review; no staging, commit, push, pull request or merge is authorized here.

## Appendix G. Independent implementation review (2026-11-02)

Checkpoint: `codex/sf4-association-research`, HEAD/base
`8b82fd6b92857374d716705c3b12fa593fafd5a4`, exactly the approved 15 paths and an
empty index. The base contains SF-3. Earlier fusion contracts, legacy behavior,
dependencies, characterization tests and telemetry baselines are unchanged.

The review constructed failing counterexamples before relying on regression
results. Corrections are restricted to the SF-4 manifest:

1. **Object-order uniqueness.** JSON objects with the same EvidenceKey fields in
   different key orders bypassed `repr`-based uniqueness. Canonical JSON value
   equality now rejects duplicate scope/ref objects independently of key order;
   there is no silent set collapse of contradictory/duplicate declarations.
2. **Nested ownership and bounded memory APIs.** Tuple-based scopes and mapping
   proxies could retain caller-owned mutable dictionaries, altering a returned
   report after evaluation. All supported mappings and tuple/list descendants
   are now detached recursively. Cycles, excessive depth and value-node counts
   reject explicitly in both evaluation requests and the in-memory artifact
   factory, before recursive encoding. Already-frozen subtrees still count at
   every serialized position; composing them cannot evade depth/node limits.
   Frozen dataclasses/proxies are an API
   immutability boundary, not protection against hostile Python code deliberately
   invoking low-level mutation mechanisms in the same process.
3. **Parser node accounting.** Preflight counted keys and separators as extra
   nodes: a legal 256-observation input with 47,640 JSON value nodes and less than
   1 MiB was rejected. It now counts each scalar/container value once, excluding
   object keys, while tracking quote escapes and depth before allocation. A
   100,000-value input is within the node cap; 100,001 values is rejected. The
   separate source-graph node cap is still enforced. Byte and record limits also
   remain mandatory; reaching one cap does not waive another.
4. **Report integrity.** Consistent aggregate totals alone allowed evidence-row
   outcomes and continuity summaries to contradict those totals. Validation now
   derives populations/exclusions from unique logical rows, checks occurrence,
   truth/hypothesis and lifecycle references, enforces hypothesis/outcome and
   unknown-uncertainty/admission consistency, validates segment/fragment/link
   ratios and label-support bounds, and checks canonical summary/diagnostic
   ordering. These checks establish internal consistency, not the authenticity
   of a foreign report or its ground truth.
5. **Structural schema/profile discrepancies.** Cutoff/digest null coupling and
   acquisition completeness were runtime-only structural checks; code/stage and
   diagnostic-reference combinations were unconstrained. They are now closed
   schema unions too. Identifier patterns reject blank identifiers and identifiers containing controls;
   canonical ID/scalar/digest regexes cannot match only a prefix before a final
   newline. All four checked-in schemas were regenerated from the registry.

No C/I/A/U formula, lifecycle precedence, supplied alignment, SF-1/SF-2 behavior
or SF-3 interface was changed. Physical resumption still requires a fully
assessed episode block; an observed member before acquisition closure is not
proof of full assessment. Unknown gaps break continuity, and first sightings do
not become resumptions. Mixed assignments retain incorrect rows even when a
correct singleton supports a truth-conditioned resolved step. Same-step splits
and collisions never create an artificial sequential link.

Independent analytical oracles checked N=C+I+A+U before checking ratios. They
cover all-correct/all-incorrect/all-ambiguous/all-unresolved/empty populations,
the section 7 C=2,I=1,A=1,U=1 example, a separate N=7 mixed case, delayed and stale
exclusions, duplicates, unaligned labels, and large bounded inputs. Denominators
remain exact unreduced counts; zero denominators remain null. Independent
SF-1 fingerprint reconstruction and byte-level prefix hash examples matched the
specified preimages. Cross-view artifact bindings reject reuse of raw truth or
hypotheses against an impaired observation digest. A caller explicitly rewriting
all bindings/assertions is not authenticated by hashes.

An already-installed independent Draft 2020-12 validator checked all four schemas
and agreed with runtime shape validation on 64 valid/invalid structural cases.
No dependency was added. The probe is retained under
`/tmp/aegis-sf4-review-schema-probe.*`, not in Git or production imports.
**Standard JSON Schema alone is not full SF-4 acceptance.** UTF-8 byte budgets,
built-in integer/lossless scalar representation, finite binary64 magnitude,
PSD/source validation, graph links, cross-artifact identities, timing and report
arithmetic require the mandatory runtime profile. Four explicit probes show
standard shape acceptance followed by runtime rejection (an over-budget Unicode
ID, version 1.0 instead of literal integer 1, an overflowing scalar and a dangling
graph reference). These are documented validation layers, not interchangeable
acceptance paths or a claim of standalone semantic schema equivalence. The
schemas now state this boundary in `$comment`; no remote resolver is enabled.

Final independent-review validation, run sequentially on the final source:

| Check | Result | GNU time wall / maximum RSS |
| --- | --- | --- |
| Focused SF-4 | 191 passed | 20.36 s / 61.2 MiB |
| Explicit SF-1/SF-2/SF-3 selection | 256 passed | 70.16 s / 46.5 MiB |
| Complete Python regression | 2,894 passed, 2 existing opt-in skips | 180.56 s / 407.6 MiB |
| Complete frontend, sequential files / one worker | 396 passed, 19 files | 85.68 s / 331.2 MiB |
| TypeScript typecheck | Passed | 1.31 s / 282.3 MiB |
| Production build | Passed; `/tmp/aegis-sf4-review-dist` | 1.15 s / 254.8 MiB |

The established approved host environment was used for complete Python/frontend
validation because the sandbox's existing Starlette/Node process restrictions
were reproduced during initial implementation (Appendix F). Tests were not
weakened or moved out of the full suite. No dependency was installed. The two
skips retain their explicit real-physics opt-in requirements. GNU time maximum
RSS is not aggregate WSL/process-tree RAM.

Final resource probes, together: 16.34 s, 60.5 MiB maximum RSS:

| Supplied profile | Observation bytes | Truth bytes | Report bytes | Expected outcome |
| --- | --- | --- | --- | --- |
| 512 position observations / 512 opportunities | 1,509,716 | 126,003 | 495,186 | 512 correct; 256 diagnostics retained, 768 dropped exactly |
| 1,024 completed-empty acquisitions / 1,024 steps | 631,690 | 106,706 | 136,899 | 1,024 explicit missing opportunities; empty accuracy population, null metrics |
| 4,096 explicit opportunities / 8,192 edges / 128 declared entities | 35,160 | 482,940 | 599,131 | 4,096 explicit missing annotations; no inferred opportunities or identities |

Each report round-tripped through bounded report IO. These profiles exercise
selected inclusive caps and a 512-observation input near the 100,000-value budget;
they are not certification of all simultaneous caps, payload shapes, runtimes or
hardware. Benchmarks and their authored schedule remain under
`/tmp/aegis-sf4-review-bounds.*`, outside the implementation manifest.

Fresh processes using `PYTHONHASHSEED=0,1,1729` produced identical report bytes and
hashes; these four valid-fixture hashes also match initial implementation:

```text
acceptance f84269a630af9100e82c3cb41179b318270862942d1e1de9129bf6036ad1b43e
empty 4d45d17919d7f7665b8b89e2426405d8291e2f7dda9068f4a9c5625e42ff0403
impaired 9f3bbe1d56ebe6e25a94914cecb9521797e6919b6f76562214b4ff2fe540562a
split 520662f5ed9d6460d401574166bbf22d4666d997a498f8045540c4498a867062
```

The seed-0 four-scenario run took 0.52 s; maximum RSS across all three fresh
processes was 23.0 MiB. Logs, hashes, probe scripts, resource records and build
artifacts are under `/tmp/aegis-sf4-review-*`, outside Git. The final scope audit
checks exactly the Appendix E 15 paths, HEAD/base, empty index, unchanged earlier
tracked contracts/tests/dependencies/baselines, credential patterns and both
tracked/untracked whitespace. No production module, test or evidence outside
that manifest was changed.

Review verdict: ready for a standalone commit **after separate user approval**;
no known blocking defect remains in the approved runtime-validation pipeline.
No staging, commit, push, PR or merge was performed. Scientific limitations are
unchanged: identities, opportunities, completeness, uncertainty, label alignment
and cutoff provenance remain supplied assertions; hashes do not authenticate
truth or prevent a producer's hindsight. Internal report consistency is not
independent verification of a foreign report's source bindings. Metrics are
conditional, proposal-specific research diagnostics, not physical sensor accuracy,
standard MOT scores, an automatic association algorithm or a validated track
state. No SF-3 state update, candidate selection, optimal alignment, live tracking,
operational control or actuation path was introduced.
