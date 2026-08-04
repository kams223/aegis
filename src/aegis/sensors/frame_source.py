from abc import ABC, abstractmethod
import numpy as np


class FrameSource(ABC):
    """Base class for all frame sources."""

    @abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """Return the next frame, or None if there are no more frames."""
        pass

    @abstractmethod
    def release(self):
        """Release any resources (camera, video file, etc.)."""
        pass
