"""Execute the example independently of pytest fixtures and working directory."""

import json
from pathlib import Path
import subprocess
import sys


def test_standalone_synthetic_demo_is_deterministic(tmp_path):
    root = Path(__file__).resolve().parents[1]
    # Isolated mode ignores PYTHONPATH and user configuration; -S excludes site
    # packages. Only the repository source path is added before execution.
    bootstrap = (
        "import runpy, sys; sys.path.insert(0, sys.argv[1]); "
        "runpy.run_path(sys.argv[2], run_name='__main__')"
    )
    command = [sys.executable, "-I", "-S", "-B", "-c", bootstrap,
               str(root / "src"), str(root / "examples/synthetic_observation_demo.py")]
    runs = [subprocess.run(command, cwd=tmp_path, env={}, capture_output=True,
                           timeout=30, check=True) for _ in range(2)]
    assert runs[0].stdout == runs[1].stdout
    assert runs[0].stderr == runs[1].stderr == b""
    output = runs[0].stdout.decode("utf-8")
    payload, message = output.rsplit("\n", 2)[:2]
    assert message == "DETERMINISTIC SYNTHETIC DEMO: PASS"
    radar_key = '["scripted-radar-detection",1,"0",0]'
    assert json.loads(payload) == {
        "camera_observation_count": 1, "radar_observation_count": 1,
        "evidence_count": 2, "history_record_count": 2,
        "records": [
            {"position": 0, "modality": "radar", "sensor_id": "fixture:radar-sensor",
             "observation_id": json.dumps(["radar-detection", 1, "fixture:radar-sensor",
                                           "fixture:session", radar_key], separators=(",", ":")),
             "source_local_id": None, "measurement_seconds": 5., "clock_domain": "fixture:radar",
             "reference_frame_id": "fixture:radar:local", "has_projection": True,
             "has_transformation": True, "has_mapped_time": True},
            {"position": 1, "modality": "camera", "sensor_id": "fixture:camera-sensor",
             "observation_id": '["camera-track","fixture:camera-sensor","fixture:opening",51,7,0]',
             "source_local_id": '["fixture:opening",7]', "measurement_seconds": 2.,
             "clock_domain": "fixture:camera", "reference_frame_id": "fixture:camera:image",
             "has_projection": True, "has_transformation": False, "has_mapped_time": True},
        ],
        "camera_direction": [0., 0., 1.], "radar_point_m": [10., 0., 0.],
        "radar_transformed_point_m": [11., 2., 3.],
        "camera_mapped_interval_seconds": [101.75, 102.25],
        "radar_mapped_interval_seconds": [204.75, 205.25],
    }


def test_standalone_synthetic_demo_rejects_optimized_python(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bootstrap = (
        "import runpy, sys; sys.path.insert(0, sys.argv[1]); "
        "runpy.run_path(sys.argv[2], run_name='__main__')"
    )
    command = [sys.executable, "-I", "-S", "-B", "-O", "-c", bootstrap,
               str(root / "src"), str(root / "examples/synthetic_observation_demo.py")]
    result = subprocess.run(command, cwd=tmp_path, env={}, capture_output=True,
                            timeout=30)
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"DETERMINISTIC SYNTHETIC DEMO: PASS" not in result.stdout
    assert b"DETERMINISTIC SYNTHETIC DEMO: PASS" not in result.stderr
    assert b"Run without -O: this demonstration requires assertion checks" in result.stderr
