"""Frame values independent of capture and inference implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True)
class FrameMetadata:
    """One-based frame position and dimensions for a single stream.

    timestamp_seconds is relative to the start of the stream, not wall time.
    stream_id identifies a processing stream, including a distinct reopening
    of the same video. Dimensions describe the original image in pixels.
    """

    stream_id: str
    frame_number: int
    timestamp_seconds: float
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    """An H x W x 3 BGR uint8 image and its metadata.

    The image is retained by reference, without copying or runtime validation.
    Freezing this wrapper does not freeze the array; consumers should treat
    input pixels as read-only. NumPy is needed only by image implementations.
    """

    image: NDArray[np.uint8]
    metadata: FrameMetadata
