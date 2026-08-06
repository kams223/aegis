import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

from aegis.core.pipeline_config import (
    DEFAULT_CONFIG_PATH,
    PipelineConfig,
)


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
    """Construct production stages using one configuration.

    Imports are lazy so unit tests do not load PyTorch and
    Ultralytics during test discovery.
    """

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


def run_stages(
    stages: list[PipelineStage],
) -> int:
    """Run pipeline stages sequentially and stop on failure."""

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
            print()
            print(
                f"Pipeline interrupted during: {stage_name}"
            )
            return 130

        except Exception as error:
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
            print()
            print(
                f"Pipeline stopped because '{stage_name}' "
                f"returned exit code {result}."
            )
            return result

        print()
        print(
            f"Stage completed in {stage_elapsed:.2f} seconds."
        )
        print()

    pipeline_elapsed = (
        time.perf_counter() - pipeline_started_at
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
    print("=" * 65)

    return 0


def main(
    arguments: list[str] | None = None,
) -> int:
    """Load a selected configuration and run the pipeline."""

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

    return run_stages(
        build_default_stages(config)
    )


if __name__ == "__main__":
    sys.exit(main())
