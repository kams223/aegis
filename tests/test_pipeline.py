from pathlib import Path

from aegis.pipeline.run_pipeline import (
    main,
    parse_arguments,
    run_stages,
)


class FakeManifest:
    """Minimal test replacement for RunManifest."""

    def __init__(self):
        self.output_path = Path(
            "outputs/data/test_run_manifest.json"
        )
        self.recorded_stages = []
        self.finished = []

    def record_stage(
        self,
        name,
        status,
        duration_seconds,
        exit_code,
    ):
        self.recorded_stages.append(
            {
                "name": name,
                "status": status,
                "duration_seconds": duration_seconds,
                "exit_code": exit_code,
            }
        )

    def finish(
        self,
        status,
        exit_code,
        monotonic_time,
    ):
        self.finished = {
            "status": status,
            "exit_code": exit_code,
            "monotonic_time": monotonic_time,
        }


def test_pipeline_runs_all_successful_stages():
    executed_stages = []

    def first_stage():
        executed_stages.append("first")
        return 0

    def second_stage():
        executed_stages.append("second")
        return 0

    result = run_stages(
        [
            ("First stage", first_stage),
            ("Second stage", second_stage),
        ]
    )

    assert result == 0
    assert executed_stages == [
        "first",
        "second",
    ]


def test_pipeline_stops_after_failed_stage():
    executed_stages = []

    def successful_stage():
        executed_stages.append("successful")
        return 0

    def failed_stage():
        executed_stages.append("failed")
        return 7

    def forbidden_stage():
        executed_stages.append("forbidden")
        return 0

    result = run_stages(
        [
            ("Successful stage", successful_stage),
            ("Failed stage", failed_stage),
            ("Forbidden stage", forbidden_stage),
        ]
    )

    assert result == 7
    assert executed_stages == [
        "successful",
        "failed",
    ]


def test_pipeline_records_successful_manifest():
    manifest = FakeManifest()

    result = run_stages(
        stages=[
            ("First stage", lambda: 0),
            ("Second stage", lambda: 0),
        ],
        manifest=manifest,
    )

    assert result == 0
    assert len(manifest.recorded_stages) == 2

    assert manifest.recorded_stages[0]["status"] == (
        "completed"
    )
    assert manifest.recorded_stages[1]["status"] == (
        "completed"
    )

    assert manifest.finished["status"] == "completed"
    assert manifest.finished["exit_code"] == 0


def test_parse_arguments_accepts_custom_config():
    arguments = parse_arguments(
        [
            "--config",
            "configs/custom.json",
        ]
    )

    assert arguments.config == Path(
        "configs/custom.json"
    )


def test_main_rejects_missing_config(tmp_path):
    missing_path = tmp_path / "missing.json"

    result = main(
        [
            "--config",
            str(missing_path),
        ]
    )

    assert result == 1
