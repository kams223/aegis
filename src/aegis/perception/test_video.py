from pathlib import Path
import sys

import cv2

from aegis.sensors.video_file import VideoFileSource


INPUT_VIDEO_PATH = Path("data/videos/test.mp4")
OUTPUT_DIRECTORY = Path("outputs/videos")
OUTPUT_VIDEO_PATH = OUTPUT_DIRECTORY / "aegis_test_output.mp4"


def main() -> int:
    """Process a video, annotate its frames, and save the result."""

    print("=" * 55)
    print("Aegis Vision Processing Test")
    print("=" * 55)
    print(f"Input:  {INPUT_VIDEO_PATH}")
    print(f"Output: {OUTPUT_VIDEO_PATH}\n")

    if not INPUT_VIDEO_PATH.exists():
        print(f"ERROR: Input video does not exist: {INPUT_VIDEO_PATH}")
        return 1

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    video = None
    writer = None
    frame_count = 0

    try:
        video = VideoFileSource(str(INPUT_VIDEO_PATH))

        width = int(video.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = video.cap.get(cv2.CAP_PROP_FPS)

        if width <= 0 or height <= 0:
            raise RuntimeError(
                f"Invalid video dimensions: width={width}, height={height}"
            )

        if fps <= 0:
            print("WARNING: Could not read the original FPS. Using 30 FPS.")
            fps = 30.0

        print(f"Resolution: {width} x {height}")
        print(f"FPS:        {fps:.2f}")
        print("Processing frames...\n")

        codec = cv2.VideoWriter_fourcc(*"mp4v")

        writer = cv2.VideoWriter(
            str(OUTPUT_VIDEO_PATH),
            codec,
            fps,
            (width, height),
        )

        if not writer.isOpened():
            raise RuntimeError(
                f"Could not create output video: {OUTPUT_VIDEO_PATH}"
            )

        while True:
            frame = video.get_frame()

            if frame is None:
                break

            frame_count += 1

            cv2.putText(
                frame,
                f"Aegis | Frame: {frame_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            writer.write(frame)

            if frame_count % 100 == 0:
                print(f"Processed {frame_count} frames...")

        if frame_count == 0:
            raise RuntimeError("The video opened, but no frames were decoded.")

        print("\nProcessing completed successfully.")
        print(f"Total frames processed: {frame_count}")
        print(f"Saved output video to: {OUTPUT_VIDEO_PATH}")

        return 0

    except (RuntimeError, cv2.error) as error:
        print(f"\nERROR: {error}")
        return 1

    finally:
        if video is not None:
            video.release()

        if writer is not None:
            writer.release()


if __name__ == "__main__":
    sys.exit(main())
