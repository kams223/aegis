"""Convert combined Ultralytics inference/tracking into Aegis-owned output.

Concurrent/interleaved session isolation is not established: backend tracker
internals may contain process-global state. Use sequential sessions here.
"""

from collections.abc import Callable
from typing import Any

from aegis.core.frames import Frame
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import (
    TrackedObject,
    TrackedObjectBatch,
    TrackingFrameOutput,
)


def _create_model(model_path: str) -> Any:
    """Import inference dependencies only when constructing a real session."""
    from ultralytics import YOLO

    return YOLO(model_path)


def _integer_id(value: Any, name: str) -> int:
    """Reject malformed IDs rather than silently truncating their values."""
    try:
        converted = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid {name} ID: {value!r}") from error
    if converted != value:
        raise ValueError(f"Invalid {name} ID: {value!r}")
    return converted


def _tracked_objects(result: Any, box_count: int) -> tuple[TrackedObject, ...]:
    """Copy assigned rows into plain values, preserving backend row order."""
    boxes = result.boxes
    if boxes is None or box_count == 0 or boxes.id is None:
        return ()

    try:
        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        identities = boxes.id.cpu().tolist()

        if any(len(values) != box_count for values in (
            coordinates, confidences, classes, identities,
        )):
            raise ValueError("Tracking array lengths do not match returned box count")

        objects = []
        for xyxy, confidence, class_value, track_value in zip(
            coordinates, confidences, classes, identities, strict=True,
        ):
            class_id = _integer_id(class_value, "class")
            track_id = _integer_id(track_value, "track")
            try:
                label = str(result.names[class_id])
            except (AttributeError, KeyError, IndexError, TypeError) as error:
                raise ValueError(f"Invalid class label lookup for ID {class_id}") from error

            x1, y1, x2, y2 = xyxy
            objects.append(TrackedObject(
                track_id=track_id,
                detection=ObjectDetection(
                    class_id=class_id,
                    label=label,
                    confidence=float(confidence),
                    x1=float(x1), y1=float(y1),
                    x2=float(x2), y2=float(y2),
                ),
            ))
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid tracking result: {error}") from error

    return tuple(objects)


class UltralyticsTrackingSession:
    """One sequential stream backed by a freshly constructed private model.

    An injected factory must construct an independent model for each session.
    Any failure after inference begins makes the session unusable; close it
    and create a new session rather than attempting rollback or retry.
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.35,
        image_size: int = 640,
        tracker_config: str = "bytetrack.yaml",
        device: str = "cpu",
        *,
        model_factory: Callable[[str], Any] | None = None,
    ):
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        if image_size <= 0:
            raise ValueError("image_size must be positive")
        if not device.strip():
            raise ValueError("device cannot be empty")

        factory = _create_model if model_factory is None else model_factory
        self._model = factory(model_path)
        self._confidence_threshold = confidence_threshold
        self._image_size = image_size
        self._tracker_config = tracker_config
        self._device = device
        self._stream_id: str | None = None
        self._last_frame_number: int | None = None
        self._closed = False
        self._failed = False

    def track(self, frame: Frame) -> TrackingFrameOutput:
        """Track once, returning only Aegis values and the plotted image."""
        if self._closed:
            raise RuntimeError("Tracking session is closed")
        if self._failed:
            raise RuntimeError("Tracking session has failed; close it and create a new session")

        metadata = frame.metadata
        if self._stream_id is not None and metadata.stream_id != self._stream_id:
            raise ValueError("Frame belongs to a different tracking stream")
        if (
            self._last_frame_number is not None
            and metadata.frame_number <= self._last_frame_number
        ):
            raise ValueError("Frame numbers must be strictly increasing")

        self._stream_id = metadata.stream_id
        self._last_frame_number = metadata.frame_number
        try:
            results = self._model.track(
                source=frame.image,
                persist=True,
                tracker=self._tracker_config,
                conf=self._confidence_threshold,
                imgsz=self._image_size,
                device=self._device,
                verbose=False,
            )
            if not results:
                raise RuntimeError("Tracking backend returned no results for the frame")
            result = results[0]
            box_count = 0 if result.boxes is None else len(result.boxes)
            objects = _tracked_objects(result, box_count)
            annotated_image = result.plot()
            return TrackingFrameOutput(
                tracks=TrackedObjectBatch(frame=metadata, objects=objects),
                returned_box_count=box_count,
                annotated_image=annotated_image,
            )
        except BaseException:
            # Even interruption may leave backend state advanced. Never retry it.
            self._failed = True
            raise

    def close(self) -> None:
        """End the session; dropping ownership does not guarantee GPU release."""
        self._closed = True
        self._model = None
