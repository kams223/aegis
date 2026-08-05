import sys
import time

import cv2

from aegis.core.pipeline_config import PipelineConfig
from aegis.perception.object_detector import ObjectDetector
from aegis.sensors.video_file import VideoFileSource
from aegis.world_model.track_logger import TrackLogger


def extract_track_ids(result) -> set[int]:
    """Return persistent track IDs present in one result."""

    if result.boxes is None or result.boxes.id is None:
        return set()

    return {
        int(track_id)
        for track_id in result.boxes.id.cpu().tolist()
    }


def process_video(config: PipelineConfig) -> int:
    """Track objects and save video plus structured observations."""

    print("=" * 60)
    print("Aegis Offline Tracking and World Model")
    print("=" * 60)
    print(f"Input video: {config.input_video_path}")
    print(f"Output video:{config.output_video_path}")
    print(f"Track data:  {config.observations_path}")
    print(f"Model:       {config.model_path}")
    print(f"Tracker:     {config.tracker_config}")
    print(f"Device:      {config.device}")
    print(f"Confidence:  {config.confidence_threshold:.2f}")
    print(f"Image size:  {config.image_size}")
    print()

    if not config.input_video_path.is_file():
        print(
            "ERROR: Input video does not exist: "
            f"{config.input_video_path}"
        )
        return 1

    config.output_video_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    config.observations_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    video = None
    writer = None
    track_logger = None

    frame_count = 0
    total_frame_detections = 0
    observed_track_ids: set[int] = set()
    started_at = time.perf_counter()

    try:
        video = VideoFileSource(
            str(config.input_video_path)
        )

        width = int(
            video.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        height = int(
            video.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )
        source_fps = float(
            video.cap.get(cv2.CAP_PROP_FPS)
        )

        if width <= 0 or height <= 0:
            raise RuntimeError(
                f"Invalid video dimensions: {width} x {height}"
            )

        if source_fps <= 0:
            print(
                "WARNING: Source FPS unavailable; using 30 FPS."
            )
            source_fps = 30.0

        print(f"Resolution: {width} x {height}")
        print(f"Source FPS: {source_fps:.2f}")
        print()

        detector = ObjectDetector(
            model_path=config.model_path,
            confidence_threshold=(
                config.confidence_threshold
            ),
            image_size=config.image_size,
            tracker_config=config.tracker_config,
            device=config.device,
        )

        codec = cv2.VideoWriter_fourcc(*"mp4v")

        writer = cv2.VideoWriter(
            str(config.output_video_path),
            codec,
            source_fps,
            (width, height),
        )

        if not writer.isOpened():
            raise RuntimeError(
                "Could not create output video: "
                f"{config.output_video_path}"
            )

        track_logger = TrackLogger(
            config.observations_path
        )
        track_logger.open()

        print(
            "Tracking objects and recording observations..."
        )

        while True:
            frame = video.get_frame()

            if frame is None:
                break

            frame_count += 1
            timestamp_seconds = (
                frame_count - 1
            ) / source_fps

            result = detector.track(frame)

            frame_detection_count = (
                0
                if result.boxes is None
                else len(result.boxes)
            )

            total_frame_detections += (
                frame_detection_count
            )

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
                (
                    "Unique tracks: "
                    f"{len(observed_track_ids)}"
                ),
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 200, 0),
                2,
                cv2.LINE_AA,
            )

            writer.write(annotated_frame)

            if frame_count % 25 == 0:
                elapsed = (
                    time.perf_counter() - started_at
                )
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
                "The input video opened, "
                "but no frames were decoded."
            )

        elapsed = time.perf_counter() - started_at
        average_fps = frame_count / elapsed

        print()
        print(
            "Tracking and logging completed successfully."
        )
        print(f"Frames processed:       {frame_count}")
        print(
            f"Frame detections:       "
            f"{total_frame_detections}"
        )
        print(
            f"Unique tracks observed: "
            f"{len(observed_track_ids)}"
        )
        print(
            f"Track rows written:     "
            f"{track_logger.row_count}"
        )
        print(f"Processing time:        {elapsed:.2f} seconds")
        print(f"Average processing FPS: {average_fps:.2f}")
        print(f"Output video:           {config.output_video_path}")
        print(f"Track data:             {config.observations_path}")

        return 0

    except (RuntimeError, ValueError, cv2.error) as error:
        print(f"\nERROR: {error}")
        return 1

    except Exception as error:
        print(
            f"\nUNEXPECTED ERROR: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    finally:
        if video is not None:
            video.release()

        if writer is not None:
            writer.release()

        if track_logger is not None:
            track_logger.close()


def main() -> int:
    """Load configuration and process the configured video."""

    try:
        config = PipelineConfig.from_file()

    except (FileNotFoundError, ValueError) as error:
        print(f"CONFIGURATION ERROR: {error}")
        return 1

    return process_video(config)


if __name__ == "__main__":
    sys.exit(main())
