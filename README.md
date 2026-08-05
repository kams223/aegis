# Aegis

[![Aegis Tests](https://github.com/kams223/aegis/actions/workflows/tests.yml/badge.svg)](https://github.com/kams223/aegis/actions/workflows/tests.yml)

Aegis is a software-first, multi-sensor situational-awareness platform for detecting, tracking, analyzing, and visualizing objects in recorded sensor data.

The current prototype processes recorded video with a pretrained object detector, assigns persistent tracking IDs, builds a structured world model, evaluates track stability, and exposes the results through an API and browser dashboard.

## Current Scope

Aegis currently focuses on benign perception and decision support:

- Recorded-video ingestion
- Pretrained object detection
- Persistent multi-object tracking
- Frame-level observation logging
- Per-track history summarization
- Track-stability evaluation
- Read-only REST API
- Browser-based dashboard
- Automated unit and API tests
- Continuous integration with GitHub Actions

Aegis does not implement autonomous engagement, targeting, or physical countermeasures.

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
      +-------------------+
      |                   |
      v                   v
FastAPI              Annotated Video
      |
      v
Situational-Awareness Dashboard
```

## Track Quality Levels

Aegis assigns one of three temporal stability levels:

- `stable`: persistent track with sufficient average confidence
- `tentative`: useful observation requiring more supporting evidence
- `weak`: short-lived or low-confidence observation

Track stability does not prove that the predicted class label is correct.

## Technology Stack

- Python 3.12
- OpenCV
- Ultralytics YOLO
- ByteTrack
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
│   ├── images/
│   └── videos/
├── outputs/
│   ├── data/
│   └── videos/
├── src/
│   └── aegis/
│       ├── api/
│       ├── core/
│       ├── fusion/
│       ├── perception/
│       ├── pipeline/
│       ├── sensors/
│       ├── tracking/
│       ├── visualization/
│       └── world_model/
├── tests/
├── pytest.ini
├── requirements.txt
└── requirements-dev.txt
```

Local videos, generated outputs, and downloaded model weights are excluded from Git.

## Development Environment

The project is currently developed using:

```text
Windows 11
└── WSL2
    └── Ubuntu 24.04
```

The project directory is:

```text
/home/ali/Projects/aegis
```

## Installation

Enter Ubuntu through WSL:

```powershell
wsl
```

Open the project:

```bash
cd ~/Projects/aegis
```

Create a virtual environment if one does not exist:

```bash
python3 -m venv ~/venvs/aegis
```

Activate it:

```bash
source ~/venvs/aegis/bin/activate
```

Install application dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install test dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Configure the Python source path:

```bash
export PYTHONPATH="$(pwd)/src"
```

## Input Video

Place an input video at:

```text
data/videos/test.mp4
```

The input location can be changed in:

```text
configs/pipeline.json
```

Input videos are intentionally excluded from Git.

## Pipeline Configuration

The complete offline workflow is configured through:

```text
configs/pipeline.json
```

Configurable values include:

- Input video path
- Object-detection model
- Tracker configuration
- Confidence threshold
- Inference image size
- Inference device
- Output paths
- Track-stability thresholds

Example:

```json
{
  "model": {
    "model_path": "yolo11n.pt",
    "tracker_config": "bytetrack.yaml",
    "confidence_threshold": 0.35,
    "image_size": 640,
    "device": "cpu"
  }
}
```

## Run the Complete Pipeline

Activate the environment:

```bash
cd ~/Projects/aegis
source ~/venvs/aegis/bin/activate
export PYTHONPATH="$(pwd)/src"
```

Run all processing stages:

```bash
python -m aegis.pipeline.run_pipeline
```

The command executes:

1. Video detection and tracking
2. Per-track world-model summarization
3. Track-quality evaluation

## Generated Artifacts

The pipeline generates:

```text
outputs/videos/aegis_tracking_output.mp4
outputs/data/aegis_track_observations.csv
outputs/data/aegis_track_summaries.csv
outputs/data/aegis_track_quality.csv
```

### Observations

`aegis_track_observations.csv` contains one row per confirmed track per video frame.

### Summaries

`aegis_track_summaries.csv` contains one summarized record per track.

### Quality

`aegis_track_quality.csv` contains track-stability classifications used by the API and dashboard.

## Run the API and Dashboard

Start the composed server:

```bash
python -m uvicorn aegis.api.server:app \
  --host 127.0.0.1 \
  --port 8000
```

Open:

- Dashboard: http://localhost:8000/dashboard/
- API documentation: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Statistics: http://localhost:8000/statistics
- Tracks: http://localhost:8000/tracks

Stop the server with:

```text
Ctrl + C
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Service information |
| GET | `/health` | API and world-model availability |
| GET | `/statistics` | Aggregate track statistics |
| GET | `/tracks` | Filtered list of tracks |
| GET | `/tracks/{track_id}` | One track by ID |
| GET | `/dashboard/` | Situational-awareness dashboard |

Example filtered query:

```text
http://localhost:8000/tracks?quality=stable&minimum_confidence=0.5
```

## Run Tests

Run the complete test suite:

```bash
export PYTHONPATH="$(pwd)/src"
python -m pytest -v
```

GitHub Actions runs the same lightweight test suite automatically on pushes to `main` and on pull requests.

Model inference is intentionally excluded from CI because it requires large dependencies, model downloads, and substantially more processing time.

## Current Limitations

The current prototype has several important limitations:

- It uses a general-purpose pretrained model.
- Predicted labels may be incorrect.
- Confidence does not guarantee semantic accuracy.
- Persistent false detections can appear as stable tracks.
- Movement is measured in image pixels, not real-world distance.
- The camera has not been geometrically calibrated.
- Processing currently runs offline.
- CPU inference is slower than the source video frame rate.
- The current world model is CSV-based rather than database-backed.
- Radar, thermal, RF, acoustic, and Wi-Fi CSI inputs are not yet integrated.

## Responsible Use

Aegis is intended for research, monitoring, infrastructure awareness, robotics education, and human-supervised decision support.

Detection and tracking outputs should be treated as uncertain sensor observations. They must not be treated as verified facts or used as the sole basis for consequential autonomous actions.

## Roadmap

Planned software milestones include:

- Command-line configuration selection
- Pipeline run manifests and reproducibility metadata
- Specialized aerial-object datasets
- Model evaluation and confusion analysis
- Camera calibration
- Trajectory estimation
- Database-backed world model
- Historical replay
- Additional simulated sensor adapters
- Multi-sensor fusion research
- ROS 2 integration
- Deployment packaging

## Status

Aegis is an early-stage research prototype. The current version demonstrates a complete offline perception vertical slice from recorded video to a tested API and dashboard.
