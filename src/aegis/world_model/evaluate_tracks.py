import sys

from aegis.core.pipeline_config import PipelineConfig
from aegis.world_model.track_quality import TrackQualityEvaluator


def evaluate_tracks(config: PipelineConfig) -> int:
    """Evaluate stability of configured track summaries."""

    print("=" * 60)
    print("Aegis Track Quality Evaluation")
    print("=" * 60)
    print(f"Input:  {config.summaries_path}")
    print(f"Output: {config.quality_path}")
    print()

    try:
        evaluator = TrackQualityEvaluator(
            minimum_stable_observations=(
                config.minimum_stable_observations
            ),
            minimum_stable_duration=(
                config.minimum_stable_duration
            ),
            minimum_stable_confidence=(
                config.minimum_stable_confidence
            ),
        )

        counts = evaluator.process(
            input_path=config.summaries_path,
            output_path=config.quality_path,
        )

        total = sum(counts.values())

        print("Track quality evaluation completed.")
        print(f"Total tracks:     {total}")
        print(f"Stable tracks:    {counts['stable']}")
        print(f"Tentative tracks: {counts['tentative']}")
        print(f"Weak tracks:      {counts['weak']}")
        print(
            f"Output saved to:  {config.quality_path}"
        )

        return 0

    except (FileNotFoundError, KeyError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    except Exception as error:
        print(
            f"UNEXPECTED ERROR: "
            f"{type(error).__name__}: {error}"
        )
        return 1


def main() -> int:
    """Load configuration and evaluate track quality."""

    try:
        config = PipelineConfig.from_file()

    except (FileNotFoundError, ValueError) as error:
        print(f"CONFIGURATION ERROR: {error}")
        return 1

    return evaluate_tracks(config)


if __name__ == "__main__":
    sys.exit(main())
