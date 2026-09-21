"""Aegis tracking values and an isolated sequential-session interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from aegis.core.frames import Frame, FrameMetadata
from aegis.perception.contracts import ObjectDetection

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True)
class TrackedObject:
    """A detection with an assigned identity local to its tracking session."""

    track_id: int
    detection: ObjectDetection


@dataclass(frozen=True)
class TrackedObjectBatch:
    """Ordered objects with assigned IDs for one frame; empty is valid."""

    frame: FrameMetadata
    objects: tuple[TrackedObject, ...]


@dataclass(frozen=True)
class TrackingFrameOutput:
    """Tracking data and an annotated H x W x 3 BGR uint8 image.

    returned_box_count is the number of boxes returned by the tracking backend
    for the frame. It is not necessarily the number of assigned tracks or raw
    detector candidates. All fields describe the same input frame.

    The image is retained by reference; freezing this wrapper does not make
    the array immutable. No copying or runtime image validation is performed.
    """

    tracks: TrackedObjectBatch
    returned_box_count: int
    annotated_image: NDArray[np.uint8]


class TrackingSession(Protocol):
    """One isolated sequential tracking stream.

    Tracking state must not leak between sessions. Frames belong to the same
    stream and frame numbers must increase strictly monotonically; gaps are
    allowed. close() ends the session, after which track() must reject calls.
    Implementations choose how to isolate state and enforce these obligations;
    this interface prescribes no model ownership or lifecycle machinery.
    """

    def track(self, frame: Frame) -> TrackingFrameOutput:
        """Process the next frame and return Aegis-owned tracking output."""
        ...

    def close(self) -> None:
        """End the session and release implementation-owned resources."""
        ...
