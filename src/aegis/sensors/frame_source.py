from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from aegis.core.frames import Frame, SourceMetadata

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class FrameSource(ABC):
    """Base class for all frame sources."""

    @property
    @abstractmethod
    def metadata(self) -> SourceMetadata:
        """Return source dimensions, effective FPS, and stream identity."""
        pass

    @abstractmethod
    def read_frame(self) -> Frame | None:
        """Return a numbered, timed frame, or None when no frame is read."""
        pass

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Compatibility image-only read; advances the same frame sequence."""
        frame = self.read_frame()
        return None if frame is None else frame.image

    @abstractmethod
    def release(self) -> None:
        """Release any resources (camera, video file, etc.)."""
        pass
