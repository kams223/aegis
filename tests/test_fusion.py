"""Characterize current scalar averaging, not future object-fusion requirements."""

from aegis.core.messages import SensorMessage
from aegis.fusion.fusion_engine import FusionEngine


def measurement(value, sensor_id="sensor-a", timestamp=0.0, sensor_type="camera"):
    return SensorMessage(sensor_id, sensor_type, timestamp, {"value": value})


def test_empty_scalar_fusion_returns_none():
    assert FusionEngine().fuse() is None


def test_default_weights_average_values_without_sensor_registration():
    engine = FusionEngine()
    engine.add_measurement(measurement(2.0, "unregistered-a"))
    engine.add_measurement(measurement(6.0, "unregistered-b"))

    assert engine.fuse() == {
        "fused_value": (2.0 + 6.0) / 2.0,
        "confidence": 2.0,
        "sensor_count": 2,
    }


def test_custom_positive_weights_use_weighted_mean_and_summed_weight_confidence():
    engine = FusionEngine()
    engine.add_measurement(measurement(2.0, "a"), weight=1.0)
    engine.add_measurement(measurement(10.0, "b"), weight=3.0)

    result = engine.fuse()
    assert result["fused_value"] == (2.0 * 1.0 + 10.0 * 3.0) / (1.0 + 3.0)
    # Current confidence is total weight, not a probability.
    assert result["confidence"] == 4.0
    assert result["sensor_count"] == 2


def test_current_scalar_fusion_counts_repeated_sensor_ids_independently():
    engine = FusionEngine()
    engine.add_measurement(measurement(2.0, "same-sensor"))
    engine.add_measurement(measurement(8.0, "same-sensor"))

    assert engine.fuse() == {
        "fused_value": 5.0, "confidence": 2.0, "sensor_count": 2,
    }


def test_current_scalar_fusion_retains_measurements_after_fuse():
    engine = FusionEngine()
    engine.add_measurement(measurement(2.0, "a"))
    engine.add_measurement(measurement(4.0, "b"))
    assert engine.fuse() == {
        "fused_value": 3.0, "confidence": 2.0, "sensor_count": 2,
    }

    engine.add_measurement(measurement(12.0, "c"))
    assert engine.fuse() == {
        "fused_value": (2.0 + 4.0 + 12.0) / 3.0,
        "confidence": 3.0,
        "sensor_count": 3,
    }


def test_current_scalar_fusion_does_not_synchronize_or_filter_by_timestamp():
    results = []
    for timestamps in ((100.0, 100.0), (-1_000_000.0, 1_000_000_000.0)):
        engine = FusionEngine()
        engine.add_measurement(measurement(2.0, "a", timestamps[0]))
        engine.add_measurement(measurement(6.0, "b", timestamps[1]))
        results.append(engine.fuse())

    assert results[0] == results[1] == {
        "fused_value": 4.0, "confidence": 2.0, "sensor_count": 2,
    }


def test_current_scalar_fusion_ignores_sensor_type():
    results = []
    for types in (("camera", "camera"), ("radar", "custom")):
        engine = FusionEngine()
        engine.add_measurement(measurement(2.0, "a", sensor_type=types[0]))
        engine.add_measurement(measurement(6.0, "b", sensor_type=types[1]))
        results.append(engine.fuse())

    assert results[0] == results[1] == {
        "fused_value": 4.0, "confidence": 2.0, "sensor_count": 2,
    }
