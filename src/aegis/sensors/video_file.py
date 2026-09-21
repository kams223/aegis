import math
from uuid import uuid4

import cv2

from aegis.core.frames import Frame, FrameMetadata, SourceMetadata
from aegis.sensors.frame_source import FrameSource


class VideoFileSource(FrameSource):

    def __init__(self, path: str):
        self._capture = cv2.VideoCapture(path)
        self._frame_number = 0

        if not self._capture.isOpened():
            print(f"ERROR: Could not open video: {path}")

        try:
            width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(self._capture.get(cv2.CAP_PROP_FPS))

            if not math.isfinite(fps) or fps <= 0:
                print("WARNING: Source FPS unavailable; using 30 FPS.")
                fps = 30.0

            self._metadata = SourceMetadata(
                stream_id=uuid4().hex,
                width=width,
                height=height,
                fps=fps,
            )
        except Exception:
            # Construction failed before the caller could own cleanup.
            self._capture.release()
            raise

    @property
    def metadata(self) -> SourceMetadata:
        return self._metadata

    def read_frame(self) -> Frame | None:
        success, image = self._capture.read()

        if not success:
            return None

        self._frame_number += 1
        return Frame(
            image=image,
            metadata=FrameMetadata(
                stream_id=self.metadata.stream_id,
                frame_number=self._frame_number,
                timestamp_seconds=(self._frame_number - 1) / self.metadata.fps,
                width=self.metadata.width,
                height=self.metadata.height,
            ),
        )

    def release(self) -> None:
        self._capture.release()
