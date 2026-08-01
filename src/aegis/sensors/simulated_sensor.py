import random
import time

from aegis.core.messages import SensorMessage


class SimulatedSensor:

    def __init__(self, name):
        self.name = name


    def read(self):

        raw_data = {
            "value": random.random()
        }

        return SensorMessage.create(
            sensor_id=self.name,
            sensor_type="camera",
            data=raw_data
        )


if __name__ == "__main__":

    sensor = SimulatedSensor("camera_01")

    for _ in range(5):

        message = sensor.read()

        print(message)

        time.sleep(1)
