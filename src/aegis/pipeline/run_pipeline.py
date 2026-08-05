import sys
import time
from collections.abc import Callable


PipelineStage = tuple[str, Callable[[], int]]


def build_default_stages() -> list[PipelineStage]:
    """Import and construct the production pipeline stages.

    Imports are intentionally lazy so unit tests do not load
    PyTorch and Ultralytics during test discovery.
    """

    from aegis.perception.process_video import (
        main as process_video,
    )
    from aegis.world_model.evaluate_tracks import (
        main as evaluate_tracks,
    )
    from aegis.world_model.summarize_tracks import (
        main as summarize_tracks,
    )

    return [
        (
            "Video detection and tracking",
            process_video,
        ),
        (
            "Per-track world-model summarization",
            summarize_tracks,
        ),
        (
            "Track-quality evaluation",
            evaluate_tracks,
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
    print(
        "  outputs/videos/"
        "aegis_tracking_output.mp4"
    )
    print(
        "  outputs/data/"
        "aegis_track_observations.csv"
    )
    print(
        "  outputs/data/"
        "aegis_track_summaries.csv"
    )
    print(
        "  outputs/data/"
        "aegis_track_quality.csv"
    )
    print("=" * 65)

    return 0


def main() -> int:
    """Run the default Aegis offline pipeline."""

    return run_stages(build_default_stages())


if __name__ == "__main__":
    sys.exit(main())
