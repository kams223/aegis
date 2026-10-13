# Aegis

[![Aegis Tests](https://github.com/kams223/aegis/actions/workflows/tests.yml/badge.svg)](https://github.com/kams223/aegis/actions/workflows/tests.yml)

Aegis is a software-first situational-awareness research platform for detecting, tracking, analyzing, auditing, and visualizing objects in recorded video.

The current offline MVP processes a video with a pretrained object detector, assigns persistent tracking IDs, builds a structured world model, evaluates track stability, records reproducibility and performance metadata, exposes read-only API endpoints, and provides browser dashboards for inspection and run comparison.

## Responsible Scope

Aegis currently supports benign perception, research, monitoring, robotics education, and human-supervised decision support.

It does not implement:

- Autonomous engagement
- Weapon control
- Target selection
- Physical countermeasures
- Consequential autonomous decisions

Detection and tracking outputs are uncertain model predictions. They must not be treated as verified facts.

## Current Features

- Recorded MP4 ingestion
- Pretrained YOLO object detection
- ByteTrack persistent multi-object tracking
- Backend-independent frame, detection, and tracking contracts
- Ultralytics tracking isolated behind an Aegis adapter
- Annotated output video
- Frame-level observation logging
- Per-track temporal summaries
- Stable, tentative, and weak quality classifications
- Validated JSON pipeline configuration
- Unified command-line pipeline
- Atomic processing-metrics reports
- Auditable latest-run manifest
- Persistent archived run history
- SQLite-backed pipeline run and evaluated-track storage
- Automatic evaluated-track persistence after successful runs
- Idempotent JSON-manifest and evaluated-track import tools
- Historical per-run track and statistics API
- SHA-256 input-video fingerprints
- Run-to-run performance comparison
- Read-only FastAPI service
- Interactive situational-awareness dashboard
- Historical world-model dashboard with per-run track inspection
- Dedicated run-comparison dashboard
- Automated unit, API, pipeline, and dashboard tests
- GitHub Actions continuous integration

## Architecture

```text
Recorded Video
      |
      v
VideoFileSource
      |
      v
Frame (image + FrameMetadata)
      |
      v
TrackingSession (Aegis-owned interface)
      |
      v
+-------------------------------------------------------+
| UltralyticsTrackingSession (vendor implementation)     |
|                                                       |
| YOLO + ByteTrack -> convert tracking data + plot image |
+-------------------------------------------------------+
      |
      v
TrackingFrameOutput
      |
      +--------------------------+---------------------------+
      |                          |                           |
      v                          v                           v
returned_box_count         annotated_image             TrackedObjectBatch
      |                          |                           |
      v                          v                           v
Processing Metrics        Aegis overlays                 TrackLogger
                                 |                           |
                                 v                           v
                           Annotated MP4          Frame-Level Observation CSV
                                                             |
                                                             v
                                                       TrackSummarizer
                                                             |
                                                             v
                                                     Per-Track Summaries
                                                             |
                                                             v
                                                    TrackQualityEvaluator
                                                             |
                                                             v
                                                      Evaluated Tracks
                                                             |
                                                             v
                                                     SQLite World Model
                                                             |
                                                             v
                                                          FastAPI
                                                             |
                                                             v
                                                         Dashboards
```

### Perception and Tracking Boundary

Aegis owns backend-independent data contracts. `VideoFileSource` returns
`Frame` objects containing an image and `FrameMetadata`. `TrackingSession`
defines the Aegis tracking interface; `UltralyticsTrackingSession` is its
current concrete backend, combining YOLO inference and ByteTrack tracking.

Ultralytics-native Results, Boxes, tensors, and plotting stay inside that
adapter. Downstream processing receives `TrackingFrameOutput`, containing
`returned_box_count`, `annotated_image`, and a `TrackedObjectBatch` of
`TrackedObject` values composed with `ObjectDetection`. The backend-box
count can exceed the number of assigned tracks; an empty tracked batch is
valid. Processing adds Aegis overlays to the annotated image before writing
the MP4. Processing metrics also include processed-frame, written-observation,
unique-track, and timing statistics.

`TrackLogger` consumes Aegis batches. World-model summarization, persistence,
the API, and dashboards do not depend on Ultralytics result types. Successful
pipeline runs attempt to persist evaluated tracks to SQLite and record whether
publication succeeded; dashboards access published tracks through FastAPI. CSV outputs, processing metrics, and run manifests remain
available alongside SQLite persistence.

The `Detector` protocol remains available for backend-independent
detection-only operations returning `DetectionBatch` values, but no standalone
detection backend is currently used by the production pipeline.

**Aegis owns the contracts; inference libraries are replaceable implementation
details.** A future backend must implement those contracts and preserve their
expected coordinate, metadata, counting, and tracking-session semantics.

## Track Quality Levels

Aegis assigns one temporal quality level to every summarized track:

- `stable`: persistent track with sufficient average confidence
- `tentative`: potentially useful track requiring more evidence
- `weak`: short-lived or low-confidence track

Track stability measures temporal persistence. It does not prove that the predicted object label is correct.

## Technology Stack

- Python 3.12
- OpenCV
- Ultralytics YOLO
- ByteTrack
- SQLite
- FastAPI
- Uvicorn
- HTML, CSS, and JavaScript
- pytest
- GitHub Actions

## Project Structure

```text
aegis/
├── .github/
│   └── workflows/
│       └── tests.yml
├── configs/
│   └── pipeline.json
├── data/
│   └── videos/
├── outputs/
│   ├── data/
│   │   └── runs/
│   └── videos/
├── src/
│   └── aegis/
│       ├── api/
│       │   └── static/
│       ├── core/
│       ├── perception/
│       ├── pipeline/
│       ├── sensors/
│       ├── storage/
│       ├── tracking/
│       └── world_model/
├── tests/
├── pytest.ini
├── requirements.txt
└── requirements-dev.txt
```

Input videos, generated artifacts, downloaded model weights, cache directories, and local runtime data are excluded from Git.

## Development Environment

The current development environment is:

```text
Windows 11
└── WSL2
    └── Ubuntu 24.04
```

Project directory:

```text
/home/ali/Projects/aegis
```

Virtual environment:

```text
/home/ali/venvs/aegis
```

## Installation

Enter WSL:

```powershell
wsl
```

Open the project:

```bash
cd /home/ali/Projects/aegis
```

Create the virtual environment if necessary:

```bash
python3 -m venv /home/ali/venvs/aegis
```

Activate it:

```bash
source /home/ali/venvs/aegis/bin/activate
```

Upgrade pip and install application dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install development and test dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Configure the source path:

```bash
export PYTHONPATH="/home/ali/Projects/aegis/src"
```

Confirm the environment:

```bash
python -c "import cv2, torch, ultralytics; print('OpenCV:', cv2.__version__); print('PyTorch:', torch.__version__); print('Ultralytics:', ultralytics.__version__); print('CUDA:', torch.cuda.is_available())"
```

## Input Video

Place the input video at:

```text
data/videos/test.mp4
```

The configured input path can be changed in:

```text
configs/pipeline.json
```

Input videos are not stored in Git.

## Pipeline Configuration

The offline workflow is configured through:

```text
configs/pipeline.json
```

The configuration includes:

- Input-video path
- Detection model
- Tracker configuration
- Confidence threshold
- Inference image size
- Inference device
- Annotated-video output
- Observation output
- Summary output
- Quality output
- Processing-metrics output
- Stable-track thresholds

Current example:

```json
{
  "input": {
    "video_path": "data/videos/test.mp4"
  },
  "model": {
    "model_path": "yolo11n.pt",
    "tracker_config": "bytetrack.yaml",
    "confidence_threshold": 0.35,
    "image_size": 640,
    "device": "cpu"
  },
  "output": {
    "video_path": "outputs/videos/aegis_tracking_output.mp4",
    "observations_path": "outputs/data/aegis_track_observations.csv",
    "summaries_path": "outputs/data/aegis_track_summaries.csv",
    "quality_path": "outputs/data/aegis_track_quality.csv",
    "processing_metrics_path": "outputs/data/aegis_processing_metrics.json"
  },
  "quality": {
    "minimum_stable_observations": 5,
    "minimum_stable_duration": 0.2,
    "minimum_stable_confidence": 0.5
  }
}
```

All configured output paths must be unique.

## Run the Complete Pipeline

Activate the environment:

```bash
cd /home/ali/Projects/aegis

source /home/ali/venvs/aegis/bin/activate

export PYTHONPATH="/home/ali/Projects/aegis/src"
```

Run the configured pipeline:

```bash
python -m aegis.pipeline.run_pipeline \
  --config configs/pipeline.json
```

Display command-line help:

```bash
python -m aegis.pipeline.run_pipeline --help
```

The pipeline executes three stages:

1. Video detection, tracking, annotation, and observation logging
2. Per-track world-model summarization
3. Track-quality evaluation

The pipeline stops if any stage fails.

## Generated Artifacts

A successful run creates:

```text
outputs/videos/aegis_tracking_output.mp4
outputs/data/aegis_track_observations.csv
outputs/data/aegis_track_summaries.csv
outputs/data/aegis_track_quality.csv
outputs/data/aegis_processing_metrics.json
outputs/data/aegis_run_manifest.json
outputs/data/aegis_world_model.sqlite3
outputs/data/runs/<run-id>.json
```

### Annotated video

`aegis_tracking_output.mp4` contains bounding boxes, labels, persistent IDs, frame numbers, active-track counts, and unique-track counts.

### Frame-level observations

`aegis_track_observations.csv` contains one row per confirmed tracked object per frame.

Recorded fields include:

- Frame number
- Timestamp
- Track ID
- Predicted label
- Confidence
- Bounding-box coordinates
- Center position
- Width and height

### Per-track summaries

`aegis_track_summaries.csv` contains one record per persistent track, including duration, observation count, average confidence, start and end position, and image-space displacement.

### Track-quality results

`aegis_track_quality.csv` contains stable, tentative, or weak classifications and human-readable quality reasons.

### Processing metrics

`aegis_processing_metrics.json` records:

- Processing status
- Video dimensions
- Source FPS
- Frames processed
- Frame detections
- Tracked observations
- Unique tracks
- Processing duration
- Average processing FPS
- Failure information when applicable

### Run manifest

`aegis_run_manifest.json` represents the latest run.

It records:

- Unique run ID
- Schema version
- Start and finish timestamps
- Configuration path
- Input metadata
- Input SHA-256 fingerprint
- Model and tracker settings
- Output paths
- Stage results
- Quality thresholds
- Performance metrics
- Quality counts
- Exit status

### Archived run history

Every run is also preserved under:

```text
outputs/data/runs/
```

Archived manifests allow historical inspection and performance comparison without overwriting prior run records.

The SQLite world model is stored at:

```text
outputs/data/aegis_world_model.sqlite3
```

It persists run manifests, stage records, and evaluated tracks. Successful pipeline runs update both the JSON manifests and SQLite storage. The API prefers SQLite when it is available and retains JSON and CSV fallbacks for compatibility.

Existing archived JSON manifests can be imported idempotently:

```bash
python -m aegis.storage.import_run_history \
  --config configs/pipeline.json
```

The latest evaluated-track CSV can also be imported idempotently:

```bash
python -m aegis.storage.import_evaluated_tracks \
  --config configs/pipeline.json
```

## Run the API and Dashboards

Activate the environment and start the composed server:

```bash
cd /home/ali/Projects/aegis

source /home/ali/venvs/aegis/bin/activate

export PYTHONPATH="/home/ali/Projects/aegis/src"

python -m uvicorn aegis.api.server:app \
  --host 127.0.0.1 \
  --port 8000
```

Keep the terminal open while using the API.

Open these addresses:

- Main dashboard: <http://localhost:8000/dashboard/>
- Historical world model: <http://localhost:8000/dashboard/history.html>
- Run comparison: <http://localhost:8000/dashboard/compare.html>
- API documentation: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Statistics: <http://localhost:8000/statistics>
- Tracks: <http://localhost:8000/tracks>
- Run history: <http://localhost:8000/runs>
- Latest run: <http://localhost:8000/runs/latest>

Stop the server with:

```text
Ctrl+C
```

The server binds to `127.0.0.1`, so it is intended for local development access.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Service information |
| GET | `/health` | Data and manifest availability |
| GET | `/statistics` | Aggregate world-model statistics |
| GET | `/tracks` | Filtered track list |
| GET | `/tracks/{track_id}` | One track by persistent ID |
| GET | `/runs` | Compact archived-run history |
| GET | `/runs/latest` | Complete latest-run manifest |
| GET | `/runs/{run_id}` | Complete archived manifest |
| GET | `/runs/{run_id}/statistics` | Aggregate evaluated-track statistics for one run |
| GET | `/runs/{run_id}/tracks` | Filtered evaluated tracks for one run |
| GET | `/runs/{run_id}/tracks/{track_id}` | One evaluated track from one run |
| GET | `/run-comparisons` | Compare two archived runs |
| GET | `/dashboard/` | Main situational-awareness dashboard |
| GET | `/dashboard/history.html` | Historical world-model dashboard |
| GET | `/dashboard/compare.html` | Run-comparison dashboard |
| GET | `/docs` | Interactive OpenAPI documentation |

Example stable-track query:

```text
http://localhost:8000/tracks?quality=stable&minimum_confidence=0.5
```

Example historical track query with filtering and pagination:

```text
http://localhost:8000/runs/<run-id>/tracks?quality=stable&dominant_label=airplane&minimum_confidence=0.5&limit=25&offset=0
```

Historical track queries support:

- `quality`: `stable`, `tentative`, or `weak`
- `dominant_label`: exact predicted-label match
- `minimum_confidence`: value from `0.0` through `1.0`
- `limit`: results returned per page
- `offset`: number of matching tracks skipped

Responses include `total_matching`, `returned`, `offset`, `limit`, `has_previous`, and `has_next`.

Example comparison request:

```bash
curl -sS \
  --get \
  --data-urlencode "baseline=<baseline-run-id>" \
  --data-urlencode "candidate=<candidate-run-id>" \
  "http://127.0.0.1:8000/run-comparisons" \
  | python -m json.tool
```

Run identifiers are validated before archived files are accessed.

## Performance Comparison

The comparison engine evaluates:

- Average processing FPS
- Video-processing duration
- Complete pipeline duration
- Initialization overhead
- Frames processed
- Frame detections
- Tracked observations
- Unique tracks

For each metric, it reports:

- Baseline value
- Candidate value
- Absolute change
- Percentage change
- `improved`, `regressed`, `unchanged`, `changed`, or `unavailable`

Higher FPS is considered better. Lower duration and overhead are considered better. Detection and tracking counts are reported as changed or unchanged without assuming that a higher count is necessarily better.

At least two schema-version 3 runs with processing metrics are required for a complete comparison.

## Run Tests

Activate the environment:

```bash
cd /home/ali/Projects/aegis

source /home/ali/venvs/aegis/bin/activate

export PYTHONPATH="/home/ali/Projects/aegis/src"
```

Run the complete suite:

```bash
python -m pytest -v
```

Run selected test areas:

```bash
python -m pytest tests/test_pipeline.py -v
python -m pytest tests/test_api.py -v
python -m pytest tests/test_dashboard.py -v
python -m pytest tests/test_historical_dashboard.py -v
python -m pytest tests/test_run_manifest.py -v
python -m pytest tests/test_run_comparison.py -v
python -m pytest tests/test_run_comparison_api.py -v
python -m pytest tests/test_comparison_dashboard.py -v
```

GitHub Actions executes the lightweight test suite on pushes to `main` and on pull requests.

Full model inference is excluded from CI because it requires model weights, larger dependencies, input video, and substantially more processing time.

### Deterministic synthetic observation tests

The existing tests exercise public camera and radar observation contracts with
explicit synthetic inputs and no physical devices. Run this focused command from
the repository root using the existing development environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m pytest -p no:cacheprovider -q \
tests/test_synthetic_observation_replay.py \
tests/test_observation_delivery_replay.py \
tests/test_observation_history.py \
tests/test_derived_evidence.py
```

In the representative replay fixture, camera tracking input at timestamp `2`
uses an explicitly selected image point `(320, 240)` in a 640×480 image to derive
direction `(0, 0, 1)`. A scripted radar observation at timestamp `5`, with range
`10` metres and zero azimuth and elevation, yields point `(10, 0, 0)`. An explicit
identity rotation and translation `(1, 2, 3)` metres yield `(11, 2, 3)`. Supplied
clock mappings produce camera interval `[101.75, 102.25]` and radar interval
`[204.75, 205.25]`. Caller-controlled history order is radar first, camera second;
raw timestamp order remains `(5, 2)`.

Inspect `_inputs`, `_replay`, and the assertions in
`tests/test_synthetic_observation_replay.py` for these values. The other listed
files cover delivery order and failures, history retention, and derivation
consistency. These are deterministic software-processing tests: they establish
no physical sensor accuracy or physical synchronization. Spatial transforms and
clock mappings are supplied explicitly, camera depth is not inferred, and no
automatic cross-sensor association occurs. Passing tests do not demonstrate
operational tracking or deployment readiness.

For inspection in your own Python session, the following assumes `history`
already contains a validated `ObservationHistory`. The pytest command above
runs tests; it does not create a reusable `history` variable in your shell.

```python
print({"record_count": len(history.records)})
for position, evidence in enumerate(history.records):
    source = evidence.source_observation
    print({
        "position": position,
        "sensor_id": source.sensor_id,
        "observation_id": source.observation_id,
        "source_local_id": source.source_local_id,
        "measurement_seconds": source.measurement_time.seconds,
        "clock_domain": source.measurement_time.clock_domain,
        "reference_frame_id": source.reference_frame.frame_id,
        "measurement_type": type(source.measurement).__name__,
        "has_projection": evidence.spatial_projection is not None,
        "has_transformation": evidence.spatial_transform is not None,
        "has_mapped_time": evidence.mapped_time is not None,
    })
```

Rows follow caller-controlled history order, and repeated records remain repeated
occurrences. Equal observation IDs do not establish identical sources, and absent
optional fields do not automatically indicate failure. This read-only inspection
view is not a lossless provenance serialization; it performs no sensor fusion,
object association, clock synchronization, or physical localization.

Run the fixed standalone demonstration from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B examples/synthetic_observation_demo.py
```

It constructs the scenario twice using existing observation and evidence
contracts, checks deterministic values and source references, and prints source
metadata, derived values, and `DETERMINISTIC SYNTHETIC DEMO: PASS`. No physical
camera or radar devices are required. This software demonstration is not a
physics simulator; it performs no sensor association, automatic synchronization,
physical localization, or operational tracking.

### Synthetic Observation Inspector

Generate an offline HTML report from the fixed software-only demonstration:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --html \
> /tmp/aegis-synthetic-observations.html
```

Open the saved HTML file in a browser using its **Open File** action. No server,
JavaScript, network connection or additional packages are required. The default
invocation still prints the existing JSON and PASS line; `--html` prints only HTML.

The report shows source observation counts, evidence/history occurrence counts,
sensor and observation IDs, optional source-local IDs, raw timestamps and clock
domains, reference frames, measurement values with units, stored geometry and its
frames, and explicitly mapped intervals with their target clock domains. Expand
an entry's details to inspect selected image points, calibration, transform and
clock-mapping inputs. Provenance begins at the normalized observation.

Rows retain caller-selected history order, including repeated evidence references
as separate occurrences. Counts of occurrences do not imply independent
acquisitions. Explicit source counts describe input collections, not unique IDs
or inferred missing observations. Optional values show `Unavailable (not supplied)`;
modality-specific inapplicable fields show `Not applicable`. Zero remains a value.

Raw times from different clocks are not automatically aligned. Displayed mapped
intervals are conditional on supplied mappings. This is synthetic software data,
not a physical sensor simulation or accuracy claim; the report performs no object
association, clock synchronization, physical localization or geometry derivation.
Rendering reads existing objects without mutation and escapes dynamic HTML text.

### Synthetic scenario analysis workspace

The HTML inspector also includes a delivery-order timeline, separate visual axes
for each raw clock domain, separate conditional mapped-interval axes, and
informational/warning diagnostics. Entries in every lane retain delivery order;
no timestamp sorting, deduplication or clock alignment occurs. Single-value axes
show a centered mark, and the original numeric values remain visible.

Compare the fixed demonstration with an explicitly constructed reordered,
repeated, partial-evidence variant:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --html --compare \
> /tmp/aegis-synthetic-comparison.html
```

Open the saved file in a browser. Both scenarios appear side by side, with
positional differences in IDs, metadata, measurement values, order, geometry,
clock mappings and repeated-reference patterns. Equal IDs never imply shared
physical objects. `--compare` requires `--html`; the original default JSON output
is unchanged. All visuals are static HTML/CSS/SVG, without scripts or network assets.

For explicit scenarios built using public contracts, use the example-local API
from the repository root (`PYTHONPATH=src`):

```python
from examples.synthetic_observation_analysis import SyntheticScenario, diagnose_scenario
from examples.synthetic_observation_inspector import render_synthetic_workspace_html

# history and batches are caller-constructed ObservationHistory/ObservationBatch values.
scenario = SyntheticScenario("Explicit synthetic input", history, 1, 1, batches)
findings = diagnose_scenario(scenario)
document = render_synthetic_workspace_html(scenario, comparison=another_scenario)
```

The two integers are explicit camera/radar source counts, validated against batch
contents when batches are supplied. `source_batches=None` means unavailable;
`source_batches=()` supplies an empty collection and requires zero source counts.
An empty batch finding identifies its batch position; no scan cadence or missing
observations are inferred. Source inventories and delivery occurrences are separate.

Diagnostics identify source batch/observation positions or history occurrences.
They report repeated IDs as warnings, repeated evidence references as informational
(not independent acquisitions), optional metadata/geometry/mappings as informational,
and decreasing raw times within one clock domain as warnings rather than invalidity.
Different clock domains require explicit interpretation. `Invalid` is reserved for
checked existing public-contract violations; this is not a complete revalidator
or a reliability score. Rendering rejects checked invalid histories before returning
HTML. Missing measurement timestamps are not supported by existing derived-evidence
contracts; no new missing-time format is introduced. Scenarios are supplied as
constructed values: there is no input deserializer, code loader, registry or plugin.

### Deterministic replay inspection (Phases 46–48)

Generate a self-contained replay report:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --html --replay \
> /tmp/aegis-synthetic-replay.html
```

Open the saved file in a browser. Previous, Next, Reset and numbered Jump links
navigate pre-rendered states using local URL fragments; the selected card is
highlighted. No JavaScript, server, network access or persistent browser state is
required. All cards, observation details, timelines and diagnostics stay readable.
Supported modes are the unchanged default JSON/PASS output, `--html`,
`--html --compare`, `--html --replay`, and `--html --compare --replay`.
Both optional flags require `--html`; comparison has separate left/right replay
cards.

The immutable example-local `ReplayState` starts before the first occurrence.
Forward selects the next record; backward from zero returns to the initial state.
Previous at initial and Next at the last occurrence do nothing. Empty histories
remain initial. Jump accepts only existing zero-based integer positions; invalid
indices raise `IndexError`, and non-integer indices raise `TypeError`. Reset
returns to initial. The visited prefix includes the selected occurrence, so
backward/reset shorten it; this represents a cursor frontier, not accumulated
click history or independent acquisitions.

Selected cards display original metadata, measurements, optional geometry and
mapped intervals, derivation inputs, and applicable occurrence/source diagnostics.
Source inventory references use object identity, never matching IDs. Unavailable
optional values remain explicit. Earlier and future occurrences are separate,
and repeated evidence retains each delivery position. Raw clock domains remain
separate; no association, synchronization, tracking or physical accuracy is
inferred. This is only synthetic software inspection. Pre-rendering all states
uses quadratic report space, appropriate for small developer fixtures; automatic
playback, live acquisition and persistence are outside scope.

### Reproducible synthetic validation (Phases 49–51)

Generate either opt-in report from the fixed synthetic demonstration:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --validate-json \
> /tmp/aegis-synthetic-validation.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --validate-html \
> /tmp/aegis-synthetic-validation.html
```

Open the HTML file with the browser's Open File action. The dashboard shows the
schema-v1 manifest, source inventory, separate raw/mapped clock domains, counts,
checks and diagnostic severity summary, followed by the existing timeline,
provenance details and replay controls. Everything works offline without
JavaScript. The two validation modes are mutually exclusive and cannot be combined
with `--html`, `--compare` or `--replay`. All five existing output modes are unchanged.

Reports check source counts and source-reference retention, the metadata invariants
covered by existing diagnostics, equality against a second constructed scenario,
and the fixed fixture's explicit delivery, stored geometry and mapped-interval
expectations. Informational diagnostics and warnings do not cause failure.
Every check says `passed`, `failed` or `not_evaluated`; any failure makes the scoped
overall result `failed`, otherwise any unevaluated check makes it `not_evaluated`.
Only all evaluated checks passing yields `passed`. Empty history has no source
lineage to evaluate. Missing inventory/reference is never reported as a pass.

The example-local `build_validation_manifest(scenario, reference=second_scenario,
builtin_expectations=True)` accepts constructed values only. Omit the fixed profile
for other scenarios; its checks then remain explicitly unevaluated. Source batch
and observation order, history occurrences and repeated-reference positions are
retained. `null` represents absent metadata; non-finite source timestamps use
`null` with an explicit representation status. No clocks are aligned or sources
associated by matching IDs. JSON uses fixed field insertion order, UTF-8 text,
strict finite JSON numbers and no current timestamps, paths or environment data.
The CLI emits only the requested document after scenario assertions, with no PASS
marker; failed software checks are recorded in the report rather than hidden.

Physical accuracy, detection precision/recall, false-positive rates, latency,
real-world performance and operational readiness remain explicitly unevaluated.
The diagnostic check is not complete production-contract revalidation. Reports
neither run pytest nor embed test totals, and deterministic software validation
must not be interpreted as physical-system validation. HTML escapes dynamic text
and retains a failed manifest even if the existing inspector rejects its input.


### Strict validation runs (Phase 53)

Add `--strict` to either validation command above, for example
`examples/synthetic_observation_demo.py --validate-json --strict` or
`examples/synthetic_observation_demo.py --validate-html --strict`, using the same
Python environment and redirection. The complete report is emitted before exit:
0 means the listed checks passed, 1 means at least one failed, and 2 means checks
remain unevaluated. Invalid CLI usage also exits 2 and emits no report.
`--strict` requires a validation mode. Non-strict modes retain their original exit
behavior and report bytes; these codes do not establish physical-system readiness.

Missing or malformed scalar timestamp/frame metadata produces a failed manifest
with existing Invalid diagnostics. Missing timestamps use `null` and
`invalid_measurement_time`; no timestamp or clock domain is fabricated. Invalid
clock identifiers are excluded from the clock summary but retained in observation
metadata. The example-local `ValidationInputError` intentionally rejects opaque
objects and mutable containers in metadata identifiers or time/frame wrappers,
because they cannot be represented meaningfully as scalar report metadata.
This is not a complete validator for deliberately corrupted production objects.

Python bytecode is ignored and untracked. CI sets `PYTHONDONTWRITEBYTECODE=1`,
runs tests with `-B`, and checks the Git index for tracked `.pyc` or `__pycache__`
paths without modifying files.

### Report preparation (Phase 54)

Each scenario's diagnostics are computed once per report and shared by its
summary and replay cards. Report-local indexes preserve finding order and source
references by identity; no mutable global cache is used. Comparison sides retain
separate replay controls. HTML sections are composed as escaped body fragments
inside a shared document wrapper. CLI output bytes and validation schema/exit
semantics remain unchanged. Pre-rendered replay still uses quadratic report space
for earlier/future occurrence lists and is intended for small synthetic fixtures.


### Local JSON synthetic scenarios (Phase 55)

Select a deterministic local fixture without changing any no-scenario CLI mode:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --scenario examples/scenarios/baseline.json --html --replay \
> /tmp/aegis-json-scenario.html

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B \
examples/synthetic_observation_demo.py --scenario examples/scenarios/metadata_edge_cases.json --validate-json --strict \
> /tmp/aegis-metadata-validation.json
```

Open saved HTML with the browser's Open File action. `--scenario PATH` alone emits
schema-v1 validation JSON without a PASS marker. `--html` optionally accepts
`--replay`; validation modes and `--strict` retain their existing rules.
`--scenario --compare` is rejected before reading the file: the current comparison
variant is defined only for the built-in fixture. Files are read/parsed once;
no second construction or fixed-fixture validation profile is inferred. Thus valid
loaded fixtures report `not_evaluated` and strict exit 2; diagnosed invalid metadata
reports `failed` and strict exit 1. The unchanged built-in strict pass exits 0.
Non-strict reports exit 0; file/schema failures exit 2 with empty stdout.

The closed JSON schema requires these top-level fields (unknown fields fail):

- `schema_version`: integer 1; `scenario_id`: nonblank label; `description`: explanatory text.
- `sources`: ordered objects with unique `source_id` and `sensor_id`, `kind` (`camera` or
  `radar`), explicit `clock_domain` and `reference_frame` strings. Every source becomes
  one batch, including sources with no observations.
- `observations`: ordered objects with unique `observation_id`, resolved `source_id`,
  finite `measurement_seconds`, `measurement`, and optional nonblank `source_local_id`
  (or null). Per-source batch order follows this array.
- `deliveries`: ordered observation-ID strings; repeats reuse the exact same evidence
  and source objects. IDs are evidence references, never physical associations.

Radar measurements require `range_m` and `azimuth_rad`; `elevation_rad` and
`radial_velocity_mps` may be omitted or null. Camera measurements require `class_id`,
`label`, `confidence`, `x1`, `y1`, `x2`, `y2`, `image_width`, `image_height`, using the
existing `ImageTrackMeasurement` contract and pixel units. Numbers exclude booleans
and non-finite values; dimensions are positive integers. Raw negative timestamps
remain legal. Existing public constructor checks remain authoritative.

Optional `derivation` explicitly requests existing public geometry/time helpers.
Radar `project_spatial` defaults to false. Camera `image_point` ([u,v] pixels) and
`intrinsics` appear together; intrinsics specify `fx_px`, `fy_px`, `cx_px`, `cy_px`,
`optical_frame`, `calibration_id`, using the source's explicit frame and dimensions.
Optional `transform` specifies `source_frame`, `target_frame`, a 3×3
`rotation_target_from_source`, and `translation_target_from_source_m`.
Optional `clock_mapping` uses the seven `BoundedClockMapping` field names:
`source_clock_domain`, `target_clock_domain`, `scale`, `offset_seconds`,
`valid_from_source_seconds`, `valid_until_source_seconds`, `error_bound_seconds`.
No geometry or mapping is inferred when omitted.

For intentional negative fixtures only, `metadata_overrides` accepts null for
`measurement_time`/`reference_frame`, or blank strings for `clock_domain`, `frame_id`,
`sensor_id`, `source_local_id`. Base metadata must still be explicit and valid.
The loader first constructs normal public objects, then applies these closed faults
only to its newly owned fixture objects; the resulting envelopes are deliberately
invalid diagnostic inputs. Overrides cannot accompany derivations or conflicting
missing-wrapper/inner-field overrides. They do not change IDs or measurements.
Use validation reports for these fixtures; ordinary inspection rejects them.

`examples/scenarios/baseline.json` reproduces built-in measurement, geometry,
mapping and radar-before-camera semantics with explicit JSON IDs.
`repeated_delivery.json` adds six ordered deliveries, repeats, multiple clocks,
a decreasing radar timestamp and an explicitly empty batch.
`metadata_edge_cases.json` exercises absent and blank metadata, including repeats.
Descriptions remain in the fixture files; reports use `scenario_id` as their label.

The example-local `load_scenario(path)` returns a `SyntheticScenario`;
`scenario_from_document(document)` constructs one from an already parsed JSON tree
without I/O or input mutation. `ScenarioLoadError` identifies loading failures,
distinct from Invalid diagnostic findings. Duplicate JSON members, unresolved
references, unsupported versions/kinds, unknown fields and invalid UTF-8 fail.
Input is limited to 1 MiB and 256 entries per source/observation/delivery array.
No executable configuration, dynamic imports, network access or automatic file
writes are supported. This remains synthetic software inspection, not a physics
simulator or physical-system readiness assessment.

### Explicit profiles and batch reports (Phase 56)

Run a bounded, explicitly supplied local batch; no discovery or output file writes
occur unless your shell redirects stdout:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.synthetic_observation_batch \
--manifest examples/synthetic_validation_batch.json --format json --strict

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.synthetic_observation_batch \
--manifest examples/synthetic_validation_fault_batch.json --format html --strict \
> /tmp/aegis-batch-validation.html
```

Open saved HTML with the browser's Open File action. Reports are static and usable
without JavaScript or networks. The fault batch exits 1 after its complete report,
even though its negative-test profile agrees with the expected Invalid diagnostics.

Profile schema v1 is a closed object: `schema_version` (integer 1), `profile_id`,
`scenario_id` (the scenario's exact label), `description`, and `expectations`.
The supported expectation keys, evaluated in this fixed order, are `source_count`,
`observation_count`, `delivery_count`, `repeated_reference_count`,
`source_clock_domains`, `diagnostic_counts`, `metadata_validity`. Counts are
nonnegative integers, excluding booleans. Domains are unique nonblank strings,
compared in first source-inventory observation order; an empty batch has no raw
observation clock to report. Diagnostic counts optionally declare any of
`Informational`, `Warning`, `Invalid`, checked in that order. Metadata validity is
`passed`, `failed` or `not_evaluated`, from the existing diagnostic metadata check.
Only declared expectations are checked. An empty profile or unavailable requested
inventory yields `not_evaluated`; a mismatch yields `failed`. Matching an expected
`failed` metadata status establishes profile agreement only. Three reviewed
profiles live in `examples/profiles/`, corresponding to the three existing scenarios.

Batch manifest schema v1 requires `schema_version` (integer 1), `batch_id`,
`description`, and ordered `entries`, each with `scenario` and optional `profile`
relative file paths. Duplicate members, unknown fields, unsupported versions,
non-finite values and invalid types fail. Manifest/profile inputs are limited to
1 MiB, batches to 32 entries, domain lists to 256 items; scenario limits remain
unchanged. Paths resolve against the manifest directory. Absolute paths, URLs,
backslashes, dot/parent traversal and symlink escapes are rejected; symlinks staying
inside that directory are allowed. Use trusted local files that do not change
while loading; concurrent replacement of files is outside this example's scope.

Each entry reports successful scenario/profile loading, metadata validity,
inventory integrity, diagnostic counts, profile checks and failed expectations,
and retains the unchanged original schema-v1 validation manifest. Batch scope is
only the existing source-count/source-lineage/metadata checks and explicitly
supplied profile assertions. Original unevaluated reconstruction, built-in and
physical capabilities remain visible; they are not claimed as evaluated by a
profile. Missing profiles remain `not_evaluated`. An invalid metadata result always
fails the entry regardless of profile agreement. Any failed entry fails the batch;
otherwise any unevaluated entry (or an empty batch) makes it `not_evaluated`;
only fully evaluated scoped entries pass.

`--strict` is optional: exit 0 passed, 1 failed, 2 not_evaluated. Non-strict reports
exit 0. Invalid invocation, malformed manifest/scenario/profile, missing files or
profile/scenario ID mismatch exits 2 with a deterministic indexed error on stderr
and no partial stdout report. All entries are prepared before output. Input errors
are distinct from reportable expectation mismatches. No single-scenario CLI output
or exit code changes. No fixed built-in profile is applied to file-loaded scenarios.
The example-local APIs are `load_profile`, `evaluate_profile`, `run_batch`,
`render_batch_json`, and `render_batch_html`. They introduce no production API or
runtime dependencies and make no physical-performance or operational-readiness
claims.

### Synthetic regression baselines (Phase 57)

Compare an explicitly supplied approved baseline with a fresh Phase 56 batch:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.synthetic_observation_regression \
--manifest examples/synthetic_validation_batch.json --baseline /tmp/reviewed-baseline.json \
--format json --strict
```

Use `--format html` for a static, escaped offline difference table with no
JavaScript or external assets. Reports go to stdout; comparison never writes files,
scans directories or retrieves baselines from a network. Existing demonstration,
scenario and batch commands remain unchanged.

Generate a candidate only with an explicit new destination:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.synthetic_observation_regression \
--manifest examples/synthetic_validation_batch.json --generate-candidate \
--baseline-id local-software-v1 --description "Candidate for human review" \
--output /tmp/candidate-baseline.json
```

Generation emits no stdout and writes only a candidate, using exclusive creation
(`O_CREAT | O_EXCL`, mode 0600). Existing files are never overwritten. The parent
directory must exist; URLs, backslashes, null bytes, dot/parent traversal, repeated
slashes and symlinks in the destination or its parents are rejected. Use trusted
local directories that remain stable during generation. Atomic name creation does
not promise crash-safe publication of complete contents; review the resulting file
before approval. No directories are created automatically.

Baseline schema v1 is a closed object with `schema_version` (integer 1),
`baseline_id`, `description`, `source_batch_id`, `approval`, `report_digest`, and
`report`. IDs and descriptions are nonblank UTF-8 strings. `approval` has exactly
`status`, `approved_by`, and `approval_note`. Generated candidates have status
`candidate` and null approval fields: **NOT APPROVED**. Candidates may be inspected
and loaded, but comparison reports `not_evaluated` without authoritative differences.
A reviewer must inspect the scenario/profile inputs, semantic snapshot, digest,
and any failed or unavailable validation outcomes. If they approve that reference,
they explicitly edit approval status to `approved` and supply their own nonblank
`approved_by` and `approval_note`. No approver or timestamp is generated and no
automatic promotion command exists. Approval is a human-authored declaration,
not a verified identity, cryptographic signature or physical-system authorization.
Test approval identities in tests are labeled `TEST-FIXTURE-ONLY`.

`report` is the closed semantic snapshot, not the entire presentation report:
`schema_version`, `batch_id`, ordered `entries`, and `overall_status`. Each entry
contains `position`, `scenario_id`, `profile_id`, `scenario_loading`,
`profile_loading`, `metadata_validation_status`, `inventory_integrity_status`,
`profile_evaluation_status`, `diagnostic_counts`, `profile_checks`, `loading_error`,
and `final_status`. The three diagnostic severity counts are nonnegative integers,
excluding booleans. Profile checks preserve the existing fixed expectation order
and contain exactly `id`, `status`, `expected`, and `actual`, with existing profile
value types; unavailable actual values are null. Entries retain array order and
positions; no sorting, identity deduplication or physical association is inferred.
Descriptions, HTML formatting, redundant failed-expectation lists and nested
scenario inspection manifests are outside this comparison scope. There are no
generated timestamps, absolute paths or host-specific fields in the snapshot.

The digest is lowercase SHA-256 of the snapshot's UTF-8 bytes from
`json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False)`, with **no trailing newline**, BOM or Unicode normalization.
Object member order and whitespace are immaterial; array order and exact text
remain significant. The loader validates the closed snapshot before hashing.
`source_batch_id` must equal the stored snapshot's `batch_id`. Inputs and generated
artifacts are limited to 1 MiB, entries to 32, checks to the seven existing keys,
and domain values to the existing 256-item limit. Unsupported versions, unknown or
missing fields, wrong types, duplicate members, non-finite numbers, invalid UTF-8,
incorrect digests and malformed local files are rejected.

Comparison uses stable JSON Pointer paths and schema-ordered depth-first traversal.
Differences report category, baseline/current values, and `added`, `removed` or
`changed`. Arrays compare by index, so an insertion or reorder can produce several
field changes; added/removed tail items have explicit classifications. Null remains
a real value; classification distinguishes it from an absent item. A different
current batch ID is a reported `batch_identity` change, not silently accepted as
the same batch. Object member order does not alter difference ordering.

Regression schema v1 reports baseline and batch IDs, approval status,
`comparison_status`, underlying baseline/current report statuses, difference count,
differences, and a summary showing each side's metadata validity, profile agreement
and entry result. `unchanged` means the scoped approved snapshot reproduced;
`changed` means semantic differences; `not_evaluated` means the candidate was not
approved. Failed validation remains visible even when comparison is unchanged.
An approved negative-test reference may contain failed metadata: reproducing it
does not make that metadata valid. Unavailable validation also remains visible
independently of whether the available snapshot changed.

Strict comparison exits 0 for unchanged, 1 for changed, and 2 for not evaluated.
These are regression comparison codes, not validation success codes. Non-strict
successfully rendered reports exit 0. Invalid input or invocation exits 2 with an
error on stderr and no partial report. Generation requires output, ID and description,
supports JSON only, and cannot use `--strict`. Optimized Python is rejected because
the existing synthetic validation requires assertion checks.

The example-local APIs are `semantic_report`, `canonical_report`, `report_digest`,
`candidate_baseline`, `write_candidate`, `load_baseline`, `compare_reports`,
`render_json`, and `render_html`. Inputs are defensively copied. This is scoped
synthetic software reproducibility, not complete production-contract validation,
physical sensor-performance assessment or operational readiness.

### Recorded sensor metadata datasets (Phase 58)

Validate explicit local JSON metadata without opening or decoding recordings:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.recorded_sensor_metadata \
--dataset examples/recorded_datasets/valid.json --format json --strict

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
/home/ali/venvs/aegis/bin/python -B -m examples.recorded_sensor_metadata \
--dataset examples/recorded_datasets/quality_failures.json --format html --strict
```

Reports go to stdout, with no automatic writes, network access, external processes,
live acquisition, video decoding or pixel inspection. JSON and static escaped HTML
contain no generated timestamps, absolute paths, random IDs or external assets.
The existing video processing, synthetic scenario, batch and regression commands
are unchanged. This example introduces no production sensor/fusion contracts.

Dataset schema v1 is closed: `schema_version` (integer 1, excluding bool),
`dataset_id`, `description`, `sources`, and `records`. Each source has exactly
`source_id`, `source_kind` (`camera`, `radar`, or `metadata`), `clock_domain`, and
`recording_reference`. Each record has exactly `record_id`, `source_id`,
`sequence_index`, `timestamp`, and `metadata`. Source and record IDs are unique
within the dataset; every record refers to a declared source. Array order is the
supplied delivery order and is preserved without sorting, repair or deduplication.

`timestamp` has exactly `value` (finite signed int/float, excluding bool) and `unit`
(`s`, `ms`, `us`, or `ns`). Values are numeric offsets within the source's explicit
timebase; calendar strings and implicit units are unsupported. Absolute numeric
value is limited to 10^18 in the declared unit. Comparison uses exact rational
conversion of the parsed number's decimal string, without float unit-rounding or
clock alignment. Original numeric values and units remain unchanged in loaded data.
Negative offsets are valid. Comparisons are within each source in delivery order,
even when several sources declare the same domain; cross-source arrival ordering
is not a temporal association. Supported clock labels are `recording:<timebase-id>`
with a nonblank suffix. `unknown` explicitly makes required timestamp checks
unavailable; other labels produce an unsupported-domain failure. These names are
declarations, not evidence of synchronized clocks or known physical accuracy.

Metadata supports only four optional keys: `complete` (bool), `byte_count`
(nonnegative integer up to 2^63-1), `content_digest` (64 lowercase SHA-256 hex
characters), and `note` (nonblank UTF-8 text). These are declarations only: content
digests and byte counts are not verified against recording bytes. Missing `complete`
leaves the required completeness check unevaluated; false explicitly fails it.
Malformed optional fields are structural loading errors. Coordinates, object
classes, confidence, tracks, trajectories and assessment fields are unsupported.

Limits: JSON input 1 MiB; at most 16 sources and 4096 records. IDs and clock-domain
strings allow at most 128 Unicode characters, descriptions 1024, recording
references 256, and notes 256. Sequence indices are zero-based nonnegative integers
up to 2^31-1. Duplicate JSON keys, unknown fields, unsupported versions, invalid
UTF-8, non-finite numbers, wrong types, duplicate IDs and unresolved sources fail
loading. Empty arrays are structurally valid but cannot establish a validation pass.

References resolve relative to the resolved dataset JSON directory, which is the
authorized dataset directory for that invocation. They must identify existing
regular local files inside that directory. Absolute paths, URLs, drive paths,
backslashes, null bytes, dot/parent traversal, repeated slashes and symlink escapes
are rejected. Internal symlinks are allowed. Only path resolution and file-type
checks occur: referenced contents are never opened. Dataset inputs and directories
must remain trusted and stable while loading; concurrent replacement is outside
this example's guarantees. The explicit JSON path itself selects the dataset root.

Quality diagnostics use deterministic order: source-clock checks in source array
order, record checks in global delivery order, then source summaries/gaps in source
order and ascending sequence ranges. Each has `code`, `severity`, `source_id`,
`record_id`, `record_index`, and `explanation`; IDs/index are null for checks without
a specific record. Duplicate sequence indices are Invalid. Decreasing sequence
indices, missing zero-based sequence ranges and repeated source timestamps are
Warnings. Timestamp regressions and incomplete declarations are Invalid. Missing
completeness, unknown clocks and fewer than two records for a source leave required
checks unavailable. Gap detection reports bounded ranges rather than enumerating
potentially billions of missing indices; no trailing gap after the maximum declared
index can be inferred. Mixed units are compared exactly within each source only.

Report schema v1 contains `schema_version`, `dataset_id`, `source_inventory`,
`record_count`, `per_source_counts`, `timestamp_domains`, `diagnostics`, `status`,
and `unevaluated_checks`. Domain inventory follows first source occurrence and
explicitly states per-source comparison scope. Status precedence is `failed`,
then `not_evaluated`, then `passed`; warnings alone do not fail evaluated checks.
Required unavailable checks prevent passing. Recording-content verification and
physical accuracy are listed separately as unevaluated and outside the required
metadata-only scope. Strict exits are 0 passed, 1 failed, 2 not evaluated. Non-strict
successfully rendered reports exit 0. Structural/input/CLI errors exit 2 with clear
stderr and empty stdout, including when a later record or reference is invalid.

The three small fixtures in `examples/recorded_datasets/` are entirely synthetic,
metadata-only and contain no personal, target or operational recording data.
`valid.json` passes; `quality_warnings.json` passes with declared ordering/time
warnings; `quality_failures.json` fails declared quality checks. `placeholder.txt`
is harmless explanatory text shared only for reference-existence checks.
The example-local APIs are `load_dataset`, `dataset_from_document`,
`validate_dataset`, `render_json`, and `render_html`. Loaded dataclasses and their
tuples contain immutable scalars and never retain caller-owned mutable structures.
Metadata consistency does not establish physical measurement accuracy or readiness.

## Troubleshooting

### `ModuleNotFoundError: No module named 'aegis'`

Set the Python source path:

```bash
export PYTHONPATH="/home/ali/Projects/aegis/src"
```

### API or dashboard does not load

Confirm the composed server is running:

```bash
python -m uvicorn aegis.api.server:app \
  --host 127.0.0.1 \
  --port 8000
```

Use `aegis.api.server:app`, not `aegis.api.app:app`, when the dashboard and comparison routes are required.

### `curl: Failed to connect`

The server is not running, was stopped with `Ctrl+C`, or is listening on another port.

### Dashboard displays stale JavaScript

Perform a hard refresh in the browser:

```text
Ctrl+Shift+R
```

### CUDA is unavailable

Check:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

The pipeline can run with:

```json
"device": "cpu"
```

CPU inference is expected to be slower than the source video frame rate.

### GitHub rejects authentication

Use the GitHub username when prompted:

```text
kams223
```

Use a valid personal access token as the password. GitHub does not accept an account password for Git operations over HTTPS.

### GitHub rejects workflow updates

The personal access token must include permission to update GitHub Actions workflow files.

### Comparison metrics are unavailable

Generate at least two new pipeline runs using the current manifest schema. Older archived manifests remain readable but may not contain processing metrics.

## Current Limitations

- The detector uses a general-purpose pretrained model.
- Predicted labels may be incorrect.
- Confidence does not guarantee semantic accuracy.
- Persistent false detections can become stable tracks.
- Tracking IDs can fragment or change after occlusion.
- Movement is measured in image pixels.
- The camera is not geometrically calibrated.
- Processing is offline rather than real time.
- CPU inference is slower than the source video frame rate.
- Initialization time varies with system state.
- Raw frame observations and per-track summaries remain CSV artifacts.
- Archived run data has no retention policy.
- The development API has no authentication.
- Radar, thermal, RF, acoustic, and Wi-Fi CSI inputs are not integrated.
- No cross-sensor fusion is implemented in the current MVP.

## Safety and Interpretation

Aegis outputs should be interpreted as model-generated sensor observations.

Human operators should consider:

- Model uncertainty
- False positives
- Missed detections
- Track fragmentation
- Class-label instability
- Camera perspective
- Environmental conditions
- Dataset bias
- System-load effects on performance

Track stability, confidence, and repeated observations do not independently establish identity, intent, threat, or ground truth.

## MVP Release Criteria

The offline MVP is ready for release when:

- The complete test suite passes.
- GitHub Actions passes on `main`.
- A configured video pipeline completes successfully.
- All generated artifacts are valid.
- The latest manifest is schema version 3.
- Archived manifests are preserved.
- Health, statistics, tracks, and run endpoints respond.
- Real run comparison succeeds.
- The latest, historical, and comparison dashboards load correctly.
- The repository is clean and synchronized.
- The database-world-model release commit is tagged `v0.2.0`.

## Future Roadmap

Potential post-MVP work includes:

- Specialized aerial-object datasets
- Detection accuracy evaluation
- Confusion matrices and labeled validation data
- Camera calibration
- Real-world trajectory estimation.
- Run-retention policies
- Live-camera ingestion
- GPU optimization
- Historical video replay
- Additional simulated sensor adapters
- Multi-sensor fusion research
- ROS 2 integration
- Authentication and authorization
- Deployment packaging
- Observability and structured logging

## Status

The current version demonstrates a complete offline vertical slice from recorded video through detection, persistent tracking, SQLite-backed world-model persistence, quality evaluation, auditable run history, historical track queries, performance comparison, tested APIs, and browser dashboards.
