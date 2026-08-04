import cv2

from aegis.perception.camera_service import CameraService


camera = CameraService()

while True:

    frame = camera.get_frame()

    if frame is None:
        break

    cv2.imshow("Aegis Camera", frame)

    if cv2.waitKey(1) == ord("q"):
        break


camera.release()

cv2.destroyAllWindows()
