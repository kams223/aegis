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
YOLO Object Detection
      |
      v
ByteTrack Association
      |
      v
Frame-Level Track Observations
      |
      v
Per-Track Summaries
      |
      v
Track Quality Evaluation
      |
      +-------------------------+
      |                         |
      v                         v
Annotated Video          Processing Metrics
                                |
                                v
                         Auditable Run Manifest
                                |
                                v
                         Archived Run History
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
             FastAPI                     Dashboards
                 |
                 v
       Run Performance Comparison
```

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
| GET | `/dashboard/compare.html` | Run-comparison dashboard |
| GET | `/docs` | Interactive OpenAPI documentation |

Example stable-track query:

```text
http://localhost:8000/tracks?quality=stable&minimum_confidence=0.5
```

Example historical stable-track query:

```text
http://localhost:8000/runs/<run-id>/tracks?quality=stable&minimum_confidence=0.5
```

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
python -m pytest tests/test_run_manifest.py -v
python -m pytest tests/test_run_comparison.py -v
python -m pytest tests/test_run_comparison_api.py -v
python -m pytest tests/test_comparison_dashboard.py -v
```

GitHub Actions executes the lightweight test suite on pushes to `main` and on pull requests.

Full model inference is excluded from CI because it requires model weights, larger dependencies, input video, and substantially more processing time.

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
- Both dashboards load correctly.
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
