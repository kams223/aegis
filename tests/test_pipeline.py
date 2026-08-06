from pathlib import Path

from aegis.pipeline.run_pipeline import (
    main,
    parse_arguments,
    run_stages,
)


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
