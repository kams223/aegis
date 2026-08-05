import sys

from aegis.core.pipeline_config import PipelineConfig
from aegis.world_model.track_summarizer import TrackSummarizer


def summarize_tracks(config: PipelineConfig) -> int:
    """Create one summarized record per configured track."""

    print("=" * 60)
    print("Aegis Track Summarizer")
    print("=" * 60)
    print(f"Input:  {config.observations_path}")
    print(f"Output: {config.summaries_path}")
    print()

    try:
        summarizer = TrackSummarizer(
            config.observations_path
        )

        summary_count = summarizer.write_summaries(
            config.summaries_path
        )

        print(
            "Track summarization completed successfully."
        )
        print(f"Tracks summarized: {summary_count}")
        print(
            f"Output saved to:   {config.summaries_path}"
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
    """Load configuration and summarize track observations."""

    try:
        config = PipelineConfig.from_file()

    except (FileNotFoundError, ValueError) as error:
        print(f"CONFIGURATION ERROR: {error}")
        return 1

    return summarize_tracks(config)


if __name__ == "__main__":
    sys.exit(main())
