"""Characterize the existing scalar sensor-message prototype."""

from unittest.mock import Mock

from aegis.core import messages
from aegis.core.messages import SensorMessage
from aegis.sensors import simulated_sensor
from aegis.sensors.simulated_sensor import SimulatedSensor


def test_explicit_message_preserves_fields_and_arbitrary_payload():
    payload = {"samples": [1, 2], "metadata": {"unit": "example"}}
    message = SensorMessage("sensor-a", "custom", 123.5, payload)

    assert message.sensor_id == "sensor-a"
    assert message.sensor_type == "custom"
    assert message.timestamp == 123.5
    assert message.data is payload


def test_create_uses_current_clock_and_preserves_payload(monkeypatch):
    clock = Mock(return_value=456.25)
    monkeypatch.setattr(messages.time, "time", clock)
    payload = ["arbitrary", {"nested": True}]

    message = SensorMessage.create("sensor-b", "custom", payload)

    assert message.sensor_id == "sensor-b"
    assert message.sensor_type == "custom"
    assert message.timestamp == 456.25
    assert message.data is payload
    clock.assert_called_once_with()


def test_simulated_reads_currently_emit_camera_messages_with_fresh_values(monkeypatch):
    randomness = Mock(side_effect=[0.125, 0.875])
    clock = Mock(side_effect=[1000.0, 1001.5])
    monkeypatch.setattr(simulated_sensor.random, "random", randomness)
    monkeypatch.setattr(messages.time, "time", clock)
    sensor = SimulatedSensor("thermal_01")

    first = sensor.read()
    second = sensor.read()

    # The name does not select a sensor type in the current simulator.
    assert first == SensorMessage("thermal_01", "camera", 1000.0, {"value": 0.125})
    assert second == SensorMessage("thermal_01", "camera", 1001.5, {"value": 0.875})
    assert first is not second
