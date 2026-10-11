"""Explicit clock relationships and exact conservative numerical containment."""

from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import math
from pathlib import Path
import subprocess
import sys

import pytest

from aegis.fusion.clock_mapping import (
    BoundedClockMapping, MappedTimeInterval, map_measurement_time,
)
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation


def mapping(**changes):
    return replace(BoundedClockMapping("source", "target", 1.0, 0.0,
                                      -sys.float_info.max, sys.float_info.max, 0.0),
                   **changes)


def mapped(seconds, **changes):
    return map_measurement_time(MeasurementTime(seconds, "source"), mapping(**changes))


def assert_contains(result):
    m = result.source_mapping
    center = Fraction(m.scale) * Fraction(result.source_time.seconds) + Fraction(m.offset_seconds)
    error = Fraction(m.error_bound_seconds)
    assert math.isfinite(result.lower_seconds) and math.isfinite(result.upper_seconds)
    assert Fraction(result.lower_seconds) <= center - error
    assert Fraction(result.upper_seconds) >= center + error
    # Each endpoint is the tightest finite float enclosure.
    next_lower = math.nextafter(result.lower_seconds, math.inf)
    next_upper = math.nextafter(result.upper_seconds, -math.inf)
    assert next_lower == math.inf or Fraction(next_lower) > center - error
    assert next_upper == -math.inf or Fraction(next_upper) < center + error


@pytest.mark.parametrize("seconds", [-10.0, -0.0, 0.0, 2.5, sys.float_info.max])
def test_identity_is_singleton(seconds):
    m = mapping(target_clock_domain="source")
    result = map_measurement_time(MeasurementTime(seconds, "source"), m)
    assert result.lower_seconds == result.upper_seconds == seconds


@pytest.mark.parametrize("scale,offset,error,expected", [
    (1, 3, 0, (5, 5)), (1, -3, 0, (-1, -1)),
    (2, 0, 0, (4, 4)), (0.5, 0, 0, (1, 1)),
    (2, -3, 0.25, (0.75, 1.25)),
])
def test_affine_equation_and_target_second_error(scale, offset, error, expected):
    result = mapped(2, scale=scale, offset_seconds=offset, error_bound_seconds=error)
    assert (result.lower_seconds, result.upper_seconds) == expected
    assert_contains(result)


@pytest.mark.parametrize("name", [
    "scale", "offset_seconds", "valid_from_source_seconds",
    "valid_until_source_seconds", "error_bound_seconds",
])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 10 ** 400])
def test_nonfinite_parameters_rejected(name, value):
    with pytest.raises(ValueError):
        mapping(**{name: value})


@pytest.mark.parametrize("name", [
    "scale", "offset_seconds", "valid_from_source_seconds",
    "valid_until_source_seconds", "error_bound_seconds",
])
@pytest.mark.parametrize("value", [True, False, "1", None, Fraction(1)])
def test_numeric_policy(name, value):
    with pytest.raises(TypeError):
        mapping(**{name: value})


@pytest.mark.parametrize("name,value", [
    ("scale", 0), ("scale", -1), ("error_bound_seconds", -0.1),
    ("valid_from_source_seconds", sys.float_info.max),
])
def test_invalid_invariants(name, value):
    changes = {name: value}
    if name == "valid_from_source_seconds":
        changes["valid_until_source_seconds"] = 0
    with pytest.raises(ValueError):
        mapping(**changes)


@pytest.mark.parametrize("name", ["source_clock_domain", "target_clock_domain"])
@pytest.mark.parametrize("value", ["", " \t", True, None, 1])
def test_invalid_domain_identifiers(name, value):
    with pytest.raises(ValueError):
        mapping(**{name: value})


@pytest.mark.parametrize("seconds", [-2, 3])
def test_inclusive_validity_endpoints(seconds):
    assert mapped(seconds, valid_from_source_seconds=-2,
                  valid_until_source_seconds=3).lower_seconds == seconds


def test_singleton_validity():
    assert mapped(2, valid_from_source_seconds=2, valid_until_source_seconds=2).lower_seconds == 2


@pytest.mark.parametrize("seconds", [math.nextafter(-2, -math.inf), math.nextafter(3, math.inf)])
def test_adjacent_outside_values_rejected(seconds):
    with pytest.raises(ValueError, match="outside"):
        mapped(seconds, valid_from_source_seconds=-2, valid_until_source_seconds=3)


@pytest.mark.parametrize("changes", [
    {"scale": math.nextafter(1, 2)}, {"offset_seconds": math.ulp(0.0)},
    {"error_bound_seconds": math.ulp(0.0)},
])
def test_same_domain_requires_exact_identity(changes):
    with pytest.raises(ValueError, match="identity"):
        mapping(target_clock_domain="source", **changes)


def test_signed_zero_identity_parameters():
    m = mapping(target_clock_domain="source", offset_seconds=-0.0, error_bound_seconds=-0.0)
    assert map_measurement_time(MeasurementTime(-0.0, "source"), m).lower_seconds == 0
    assert math.copysign(1, m.offset_seconds) == -1


def test_domain_value_equality_and_no_name_interpretation():
    domain = " utc:invented origin "
    equal_domain = domain.encode().decode()
    m = mapping(source_clock_domain=domain, target_clock_domain="unknown target")
    result = map_measurement_time(MeasurementTime(1, equal_domain), m)
    assert m.source_clock_domain == domain
    assert result.clock_domain == "unknown target"
    with pytest.raises(ValueError, match="mismatch"):
        map_measurement_time(MeasurementTime(1, domain.strip()), m)


@pytest.mark.parametrize("time,m", [(1, mapping()), (MeasurementTime(1, "source"), None)])
def test_wrong_operation_types(time, m):
    with pytest.raises(TypeError):
        map_measurement_time(time, m)


@pytest.mark.parametrize("seconds,error", [(math.nan, ValueError), (math.inf, ValueError),
                                         (-math.inf, ValueError), (True, TypeError),
                                         ("1", TypeError)])
def test_invalid_source_seconds(seconds, error):
    with pytest.raises(error):
        mapped(seconds)


def test_wrong_source_domain():
    with pytest.raises(ValueError, match="mismatch"):
        map_measurement_time(MeasurementTime(1, "other"), mapping())


@pytest.mark.parametrize("seconds,changes", [
    (1e16, {"error_bound_seconds": 0.1}),
    (math.ulp(0.0), {"scale": 0.5}),
    (0.0, {"error_bound_seconds": math.ulp(0.0)}),
    (math.ulp(0.0), {"scale": 0.5, "error_bound_seconds": math.ulp(0.0)}),
    (sys.float_info.max, {}),
    (sys.float_info.max, {"scale": 2, "offset_seconds": -sys.float_info.max}),
    (0.1, {"scale": 0.1, "offset_seconds": -0.01}),
    (-0.1, {"scale": 0.1}),
    (1.0, {"offset_seconds": 2 ** -54}),
    (1.0, {"offset_seconds": -2 ** -54}),
])
def test_exact_containment_for_extremes_and_rounding(seconds, changes):
    assert_contains(mapped(seconds, **changes))


def test_naive_arithmetic_would_narrow_both_endpoints():
    result = mapped(1e16, error_bound_seconds=0.1)
    assert 1e16 - 0.1 == 1e16 + 0.1 == 1e16
    assert result.lower_seconds < 1e16 < result.upper_seconds
    assert_contains(result)


@pytest.mark.parametrize("seconds,changes", [
    (sys.float_info.max, {"scale": 2}),
    (-sys.float_info.max, {"scale": 2}),
    (sys.float_info.max, {"error_bound_seconds": math.ulp(0.0)}),
    (-sys.float_info.max, {"error_bound_seconds": math.ulp(0.0)}),
])
def test_unrepresentable_enclosing_bounds_rejected(seconds, changes):
    with pytest.raises(ValueError, match="unrepresentable"):
        mapped(seconds, **changes)


@pytest.mark.parametrize("changes,error", [
    ({"lower_seconds": math.nan}, ValueError),
    ({"upper_seconds": math.inf}, ValueError),
    ({"lower_seconds": True}, TypeError),
    ({"upper_seconds": -1}, ValueError),
    ({"clock_domain": ""}, ValueError),
    ({"clock_domain": True}, ValueError),
    ({"clock_domain": "wrong"}, ValueError),
    ({"source_time": None}, TypeError),
    ({"source_mapping": None}, TypeError),
    ({"source_time": MeasurementTime(0, "wrong")}, ValueError),
])
def test_interval_constructor_validation(changes, error):
    with pytest.raises(error):
        replace(mapped(0), **changes)


def test_frozen_provenance_determinism_and_observation_unchanged():
    time = MeasurementTime(2, "source")
    m = mapping(error_bound_seconds=0.25)
    observation = SensorObservation("obs", "sensor", time, ReferenceFrame("frame"), (1, 2))
    before = (repr(time), repr(m), repr(observation))
    result = map_measurement_time(time, m)
    assert result.source_time is time and result.source_mapping is m
    assert map_measurement_time(time, m) == result
    assert (repr(time), repr(m), repr(observation)) == before
    assert observation.measurement_time is time
    for obj in (m, result):
        for field in fields(obj):
            with pytest.raises(FrozenInstanceError):
                setattr(obj, field.name, None)


def test_fresh_import_and_operation_without_external_dependencies_or_effects():
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys
baseline = set(sys.modules)
sys.path.insert(0, sys.argv[1])
from aegis.fusion.clock_mapping import BoundedClockMapping, map_measurement_time
from aegis.fusion.contracts import MeasurementTime
assert all(name in sys.stdlib_module_names or name == "aegis"
           for name in {key.split(".")[0] for key in set(sys.modules) - baseline})
import time, random
def prohibit(event, args):
    if event in {"open", "socket.__new__", "subprocess.Popen", "os.system"}:
        raise AssertionError(event)
sys.addaudithook(prohibit)
def forbidden(*args, **kwargs):
    raise AssertionError("implicit clock/randomness")
time.time = time.monotonic = time.perf_counter = time.sleep = forbidden
random.random = forbidden
m = BoundedClockMapping("a", "b", 1, 2, -10, 10, 0.25)
r = map_measurement_time(MeasurementTime(1, "a"), m)
assert (r.lower_seconds, r.upper_seconds) == (2.75, 3.25)
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, str(source)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
