from pathlib import Path
import sys
import time

import cv2

from aegis.perception.object_detector import ObjectDetector
from aegis.sensors.video_file import VideoFileSource


INPUT_VIDEO_PATH = Path("data/videos/test.mp4")
OUTPUT_DIRECTORY = Path("outputs/videos")
OUTPUT_VIDEO_PATH = OUTPUT_DIRECTORY / "aegis_detection_output.mp4"

MODEL_PATH = "yolo11n.pt"
CONFIDENCE_THRESHOLD = 0.35
IMAGE_SIZE = 640


def main() -> int:
    """Detect common objects in a video and save an annotated copy."""

    print("=" * 60)
    print("Aegis Offline Object Detection")
    print("=" * 60)
    print(f"Input:      {INPUT_VIDEO_PATH}")
    print(f"Output:     {OUTPUT_VIDEO_PATH}")
    print(f"Model:      {MODEL_PATH}")
    print(f"Confidence: {CONFIDENCE_THRESHOLD:.2f}")
    print(f"Image size: {IMAGE_SIZE}")
    print()

    if not INPUT_VIDEO_PATH.is_file():
        print(f"ERROR: Input video does not exist: {INPUT_VIDEO_PATH}")
        return 1

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    video = None
    writer = None
    frame_count = 0
    detection_count = 0
    started_at = time.perf_counter()

    try:
        video = VideoFileSource(str(INPUT_VIDEO_PATH))

        width = int(video.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        source_fps = float(video.cap.get(cv2.CAP_PROP_FPS))

        if width <= 0 or height <= 0:
            raise RuntimeError(
                f"Invalid video dimensions: {width} x {height}"
            )

        if source_fps <= 0:
            print("WARNING: Source FPS is unavailable; using 30 FPS.")
            source_fps = 30.0

        print(f"Resolution: {width} x {height}")
        print(f"Source FPS: {source_fps:.2f}")
        print()

        detector = ObjectDetector(
            model_path=MODEL_PATH,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            image_size=IMAGE_SIZE,
        )

        codec = cv2.VideoWriter_fourcc(*"mp4v")

        writer = cv2.VideoWriter(
            str(OUTPUT_VIDEO_PATH),
            codec,
            source_fps,
            (width, height),
        )

        if not writer.isOpened():
            raise RuntimeError(
                f"Could not create output video: {OUTPUT_VIDEO_PATH}"
            )

        print("Processing frames...")

        while True:
            frame = video.get_frame()

            if frame is None:
                break

            frame_count += 1

            result = detector.detect(frame)

            current_detections = (
                0 if result.boxes is None else len(result.boxes)
            )
            detection_count += current_detections

            annotated_frame = result.plot()

            cv2.putText(
                annotated_frame,
                f"Aegis | Frame: {frame_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                annotated_frame,
                f"Objects: {current_detections}",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

            writer.write(annotated_frame)

            if frame_count % 25 == 0:
                elapsed = time.perf_counter() - started_at
                processing_fps = frame_count / elapsed

                print(
                    f"Frames: {frame_count} | "
                    f"Detections: {detection_count} | "
                    f"Processing speed: {processing_fps:.2f} FPS"
                )

        if frame_count == 0:
            raise RuntimeError(
                "The input video opened, but no frames were decoded."
            )

        elapsed = time.perf_counter() - started_at
        average_fps = frame_count / elapsed

        print()
        print("Processing completed successfully.")
        print(f"Frames processed:      {frame_count}")
        print(f"Total detections:      {detection_count}")
        print(f"Processing time:       {elapsed:.2f} seconds")
        print(f"Average processing FPS:{average_fps:.2f}")
        print(f"Output saved to:       {OUTPUT_VIDEO_PATH}")

        return 0

    except (RuntimeError, ValueError, cv2.error) as error:
        print(f"\nERROR: {error}")
        return 1

    except Exception as error:
        print(f"\nUNEXPECTED ERROR: {type(error).__name__}: {error}")
        return 1

    finally:
        if video is not None:
            video.release()

        if writer is not None:
            writer.release()


if __name__ == "__main__":
    sys.exit(main())
