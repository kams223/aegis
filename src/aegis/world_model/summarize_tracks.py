from pathlib import Path
import sys

from aegis.world_model.track_summarizer import TrackSummarizer


INPUT_PATH = Path(
    "outputs/data/aegis_track_observations.csv"
)

OUTPUT_PATH = Path(
    "outputs/data/aegis_track_summaries.csv"
)


def main() -> int:
    """Create one summarized world-model record per track."""

    print("=" * 60)
    print("Aegis Track Summarizer")
    print("=" * 60)
    print(f"Input:  {INPUT_PATH}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    try:
        summarizer = TrackSummarizer(INPUT_PATH)
        summary_count = summarizer.write_summaries(OUTPUT_PATH)

        print("Track summarization completed successfully.")
        print(f"Tracks summarized: {summary_count}")
        print(f"Output saved to:   {OUTPUT_PATH}")

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


if __name__ == "__main__":
    sys.exit(main())
