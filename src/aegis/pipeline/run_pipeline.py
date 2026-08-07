import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

from aegis.core.pipeline_config import (
    DEFAULT_CONFIG_PATH,
    PipelineConfig,
)
from aegis.pipeline.run_manifest import RunManifest


PipelineStage = tuple[str, Callable[[], int]]


def parse_arguments(
    arguments: list[str] | None = None,
) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        prog="aegis-pipeline",
        description=(
            "Run the Aegis offline situational-awareness "
            "pipeline."
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "Path to a pipeline JSON configuration "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )

    return parser.parse_args(arguments)


def build_default_stages(
    config: PipelineConfig,
) -> list[PipelineStage]:
    """Construct production stages using one configuration."""

    from aegis.perception.process_video import process_video
    from aegis.world_model.evaluate_tracks import evaluate_tracks
    from aegis.world_model.summarize_tracks import summarize_tracks

    return [
        (
            "Video detection and tracking",
            lambda: process_video(config),
        ),
        (
            "Per-track world-model summarization",
            lambda: summarize_tracks(config),
        ),
        (
            "Track-quality evaluation",
            lambda: evaluate_tracks(config),
        ),
    ]


def record_failed_stage(
    manifest: RunManifest | None,
    stage_name: str,
    duration_seconds: float,
    exit_code: int,
    status: str = "failed",
) -> None:
    """Record a failed or interrupted stage if enabled."""

    if manifest is None:
        return

    manifest.record_stage(
        name=stage_name,
        status=status,
        duration_seconds=duration_seconds,
        exit_code=exit_code,
    )

    manifest.finish(
        status=status,
        exit_code=exit_code,
        monotonic_time=time.perf_counter(),
    )


def run_stages(
    stages: list[PipelineStage],
    manifest: RunManifest | None = None,
) -> int:
    """Run stages sequentially and stop on failure."""

    pipeline_started_at = time.perf_counter()

    print("=" * 65)
    print("Aegis Offline Situational-Awareness Pipeline")
    print("=" * 65)
    print(f"Stages: {len(stages)}")
    print()

    for stage_number, (stage_name, stage_function) in enumerate(
        stages,
        start=1,
    ):
        stage_started_at = time.perf_counter()

        print("-" * 65)
        print(
            f"Stage {stage_number}/{len(stages)}: "
            f"{stage_name}"
        )
        print("-" * 65)

        try:
            result = stage_function()

        except KeyboardInterrupt:
            stage_elapsed = (
                time.perf_counter() - stage_started_at
            )

            record_failed_stage(
                manifest=manifest,
                stage_name=stage_name,
                duration_seconds=stage_elapsed,
                exit_code=130,
                status="interrupted",
            )

            print()
            print(
                f"Pipeline interrupted during: {stage_name}"
            )
            return 130

        except Exception as error:
            stage_elapsed = (
                time.perf_counter() - stage_started_at
            )

            record_failed_stage(
                manifest=manifest,
                stage_name=stage_name,
                duration_seconds=stage_elapsed,
                exit_code=1,
            )

            print()
            print(
                f"UNEXPECTED PIPELINE ERROR during "
                f"'{stage_name}': "
                f"{type(error).__name__}: {error}"
            )
            return 1

        stage_elapsed = (
            time.perf_counter() - stage_started_at
        )

        if result != 0:
            record_failed_stage(
                manifest=manifest,
                stage_name=stage_name,
                duration_seconds=stage_elapsed,
                exit_code=result,
            )

            print()
            print(
                f"Pipeline stopped because '{stage_name}' "
                f"returned exit code {result}."
            )
            return result

        if manifest is not None:
            manifest.record_stage(
                name=stage_name,
                status="completed",
                duration_seconds=stage_elapsed,
                exit_code=0,
            )

        print()
        print(
            f"Stage completed in {stage_elapsed:.2f} seconds."
        )
        print()

    pipeline_elapsed = (
        time.perf_counter() - pipeline_started_at
    )

    if manifest is not None:
        manifest.finish(
            status="completed",
            exit_code=0,
            monotonic_time=time.perf_counter(),
        )

    print("=" * 65)
    print("Aegis pipeline completed successfully.")
    print(f"Total processing time: {pipeline_elapsed:.2f} seconds")
    print()
    print("Generated artifacts:")
    print("  Annotated tracking video")
    print("  Frame-level track observations")
    print("  Per-track summaries")
    print("  Track-quality evaluations")

    if manifest is not None:
        print(
            f"  Latest run manifest: "
            f"{manifest.output_path}"
        )
        print(
            f"  Archived run manifest: "
            f"{manifest.archive_path}"
        )

    print("=" * 65)

    return 0


def main(
    arguments: list[str] | None = None,
) -> int:
    """Load configuration and execute a recorded run."""

    parsed_arguments = parse_arguments(arguments)

    try:
        config = PipelineConfig.from_file(
            parsed_arguments.config
        )

    except (FileNotFoundError, ValueError) as error:
        print(f"CONFIGURATION ERROR: {error}")
        return 1

    print(
        f"Using configuration: "
        f"{parsed_arguments.config}"
    )
    print()

    manifest = RunManifest(
        config=config,
        config_path=parsed_arguments.config,
    )

    try:
        manifest.start(
            monotonic_time=time.perf_counter()
        )

    except (OSError, ValueError) as error:
        print(f"MANIFEST ERROR: {error}")
        return 1

    return run_stages(
        stages=build_default_stages(config),
        manifest=manifest,
    )


if __name__ == "__main__":
    sys.exit(main())
