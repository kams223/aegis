from aegis.sensors.simulated_sensor import SimulatedSensor
from aegis.fusion.fusion_engine import FusionEngine


camera = SimulatedSensor("camera_01")
thermal = SimulatedSensor("thermal_01")


fusion = FusionEngine()


fusion.add_measurement(
    camera.read(),
    weight=0.8
)

fusion.add_measurement(
    thermal.read(),
    weight=0.4
)

result = fusion.fuse()


print(result)
