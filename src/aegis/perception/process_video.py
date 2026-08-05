from pathlib import Path
import sys
import time

import cv2

from aegis.perception.object_detector import ObjectDetector
from aegis.sensors.video_file import VideoFileSource
from aegis.world_model.track_logger import TrackLogger


INPUT_VIDEO_PATH = Path("data/videos/test.mp4")

OUTPUT_VIDEO_DIRECTORY = Path("outputs/videos")
OUTPUT_VIDEO_PATH = (
    OUTPUT_VIDEO_DIRECTORY / "aegis_tracking_output.mp4"
)

OUTPUT_DATA_DIRECTORY = Path("outputs/data")
OUTPUT_TRACKS_PATH = (
    OUTPUT_DATA_DIRECTORY / "aegis_track_observations.csv"
)

MODEL_PATH = "yolo11n.pt"
TRACKER_CONFIG = "bytetrack.yaml"
CONFIDENCE_THRESHOLD = 0.35
IMAGE_SIZE = 640


def extract_track_ids(result) -> set[int]:
    """Return the persistent track IDs present in one result."""

    if result.boxes is None or result.boxes.id is None:
        return set()

    return {
        int(track_id)
        for track_id in result.boxes.id.cpu().tolist()
    }


def main() -> int:
    """Track objects and save video plus structured observations."""

    print("=" * 60)
    print("Aegis Offline Tracking and World Model")
    print("=" * 60)
    print(f"Input video: {INPUT_VIDEO_PATH}")
    print(f"Output video:{OUTPUT_VIDEO_PATH}")
    print(f"Track data:  {OUTPUT_TRACKS_PATH}")
    print(f"Model:       {MODEL_PATH}")
    print(f"Tracker:     {TRACKER_CONFIG}")
    print(f"Confidence:  {CONFIDENCE_THRESHOLD:.2f}")
    print(f"Image size:  {IMAGE_SIZE}")
    print()

    if not INPUT_VIDEO_PATH.is_file():
        print(f"ERROR: Input video does not exist: {INPUT_VIDEO_PATH}")
        return 1

    OUTPUT_VIDEO_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    video = None
    writer = None
    track_logger = None

    frame_count = 0
    total_frame_detections = 0
    observed_track_ids: set[int] = set()
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
            print("WARNING: Source FPS unavailable; using 30 FPS.")
            source_fps = 30.0

        print(f"Resolution: {width} x {height}")
        print(f"Source FPS: {source_fps:.2f}")
        print()

        detector = ObjectDetector(
            model_path=MODEL_PATH,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            image_size=IMAGE_SIZE,
            tracker_config=TRACKER_CONFIG,
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

        track_logger = TrackLogger(OUTPUT_TRACKS_PATH)
        track_logger.open()

        print("Tracking objects and recording observations...")

        while True:
            frame = video.get_frame()

            if frame is None:
                break

            frame_count += 1
            timestamp_seconds = (frame_count - 1) / source_fps

            result = detector.track(frame)

            frame_detection_count = (
                0 if result.boxes is None else len(result.boxes)
            )

            total_frame_detections += frame_detection_count

            frame_track_ids = extract_track_ids(result)
            observed_track_ids.update(frame_track_ids)

            track_logger.write_result(
                result=result,
                frame_number=frame_count,
                timestamp_seconds=timestamp_seconds,
            )

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
                f"Active tracks: {len(frame_track_ids)}",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                annotated_frame,
                f"Unique tracks: {len(observed_track_ids)}",
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 200, 0),
                2,
                cv2.LINE_AA,
            )

            writer.write(annotated_frame)

            if frame_count % 25 == 0:
                elapsed = time.perf_counter() - started_at
                processing_fps = frame_count / elapsed

                print(
                    f"Frames: {frame_count} | "
                    f"Active: {len(frame_track_ids)} | "
                    f"Unique: {len(observed_track_ids)} | "
                    f"Rows: {track_logger.row_count} | "
                    f"Speed: {processing_fps:.2f} FPS"
                )

        if frame_count == 0:
            raise RuntimeError(
                "The input video opened, but no frames were decoded."
            )

        elapsed = time.perf_counter() - started_at
        average_fps = frame_count / elapsed

        print()
        print("Tracking and logging completed successfully.")
        print(f"Frames processed:       {frame_count}")
        print(f"Frame detections:       {total_frame_detections}")
        print(f"Unique tracks observed: {len(observed_track_ids)}")
        print(f"Track rows written:     {track_logger.row_count}")
        print(f"Processing time:        {elapsed:.2f} seconds")
        print(f"Average processing FPS: {average_fps:.2f}")
        print(f"Output video:           {OUTPUT_VIDEO_PATH}")
        print(f"Track data:             {OUTPUT_TRACKS_PATH}")

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

        if track_logger is not None:
            track_logger.close()


if __name__ == "__main__":
    sys.exit(main())
