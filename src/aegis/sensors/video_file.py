import cv2

from aegis.sensors.frame_source import FrameSource


class VideoFileSource(FrameSource):

    def __init__(self, path: str):
        self.cap = cv2.VideoCapture(path)

        if not self.cap.isOpened():
            print(f"ERROR: Could not open video: {path}")

    def get_frame(self):

        success, frame = self.cap.read()

        if not success:
            return None

        return frame

    def release(self):
        self.cap.release()
