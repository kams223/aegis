from pathlib import Path
import sys

from aegis.world_model.track_quality import TrackQualityEvaluator


INPUT_PATH = Path(
    "outputs/data/aegis_track_summaries.csv"
)

OUTPUT_PATH = Path(
    "outputs/data/aegis_track_quality.csv"
)


def main() -> int:
    """Evaluate the stability of summarized tracks."""

    print("=" * 60)
    print("Aegis Track Quality Evaluation")
    print("=" * 60)
    print(f"Input:  {INPUT_PATH}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    try:
        evaluator = TrackQualityEvaluator(
            minimum_stable_observations=5,
            minimum_stable_duration=0.2,
            minimum_stable_confidence=0.50,
        )

        counts = evaluator.process(
            input_path=INPUT_PATH,
            output_path=OUTPUT_PATH,
        )

        total = sum(counts.values())

        print("Track quality evaluation completed.")
        print(f"Total tracks:     {total}")
        print(f"Stable tracks:    {counts['stable']}")
        print(f"Tentative tracks: {counts['tentative']}")
        print(f"Weak tracks:      {counts['weak']}")
        print(f"Output saved to:  {OUTPUT_PATH}")

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
