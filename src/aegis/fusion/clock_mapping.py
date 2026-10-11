"""Explicit, bounded clock relationships without synchronization or clock reads.

Numeric inputs accept built-in int and float values (not bool); they must be
finite and within the finite float range. Values are retained without coercion.
The error bound is a caller assertion in target seconds over the entire source
validity interval, not independently verified physical synchronization. It must
cover any relevant acquisition or calibration uncertainty supplied by the caller.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, nextafter

from aegis.fusion.contracts import MeasurementTime


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _number(value: float, name: str) -> None:
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a built-in int or float, not bool")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite and within finite float range")


@dataclass(frozen=True)
class BoundedClockMapping:
    """t_target = scale * t_source + offset_seconds, within inclusive bounds.

Both clocks use seconds; scale is a positive dimensionless rate ratio. Offset
and the symmetric error bound use target seconds. No parameters are estimated,
normalized, or rewritten. Equal domain identifiers require exact identity.
"""

    source_clock_domain: str
    target_clock_domain: str
    scale: float
    offset_seconds: float
    valid_from_source_seconds: float
    valid_until_source_seconds: float
    error_bound_seconds: float

    def __post_init__(self) -> None:
        _identifier(self.source_clock_domain, "source_clock_domain")
        _identifier(self.target_clock_domain, "target_clock_domain")
        for name in (
            "scale", "offset_seconds", "valid_from_source_seconds",
            "valid_until_source_seconds", "error_bound_seconds",
        ):
            _number(getattr(self, name), name)
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if self.error_bound_seconds < 0:
            raise ValueError("error_bound_seconds must be nonnegative")
        if self.valid_from_source_seconds > self.valid_until_source_seconds:
            raise ValueError("source validity interval must be ordered")
        if self.source_clock_domain == self.target_clock_domain and (
            self.scale != 1 or self.offset_seconds != 0
            or self.error_bound_seconds != 0
        ):
            raise ValueError("same-domain mapping must be exact identity")


@dataclass(frozen=True)
class MappedTimeInterval:
    """Closed target-domain interval with original time and mapping provenance.

This is conditional on the caller's mapping/error assertion. The endpoints do
not assert physical synchronization or object association. Direct construction
validates structure and domains, not that endpoints were derived by mapping.
"""

    lower_seconds: float
    upper_seconds: float
    clock_domain: str
    source_time: MeasurementTime
    source_mapping: BoundedClockMapping

    def __post_init__(self) -> None:
        _number(self.lower_seconds, "lower_seconds")
        _number(self.upper_seconds, "upper_seconds")
        if self.lower_seconds > self.upper_seconds:
            raise ValueError("interval endpoints must be ordered")
        _identifier(self.clock_domain, "clock_domain")
        if not isinstance(self.source_time, MeasurementTime):
            raise TypeError("source_time must be MeasurementTime")
        if not isinstance(self.source_mapping, BoundedClockMapping):
            raise TypeError("source_mapping must be BoundedClockMapping")
        if self.clock_domain != self.source_mapping.target_clock_domain:
            raise ValueError("target clock-domain mismatch")
        if self.source_time.clock_domain != self.source_mapping.source_clock_domain:
            raise ValueError("source clock-domain mismatch")


def _outward_float(endpoint: Fraction, *, lower: bool) -> float:
    try:
        result = float(endpoint)
    except OverflowError as exc:
        raise ValueError("finite enclosing interval endpoint is unrepresentable") from exc
    if not isfinite(result):
        raise ValueError("finite enclosing interval endpoint is unrepresentable")
    represented = Fraction(result)
    if (lower and represented > endpoint) or (not lower and represented < endpoint):
        result = nextafter(result, float("-inf") if lower else float("inf"))
    if not isfinite(result):
        raise ValueError("finite enclosing interval endpoint is unrepresentable")
    return result


def map_measurement_time(
    measurement_time: MeasurementTime,
    mapping: BoundedClockMapping,
) -> MappedTimeInterval:
    """Map one timestamp without extrapolation, mutation, I/O, or current time.

Fraction evaluates supplied numeric values exactly. Float endpoints round
outward only when necessary, enclosing that mathematical interval. This can
widen representational bounds, but does not change the physical error model or
recover precision lost before input. No implicit conversion graph is used.
"""
    if not isinstance(measurement_time, MeasurementTime):
        raise TypeError("measurement_time must be MeasurementTime")
    if not isinstance(mapping, BoundedClockMapping):
        raise TypeError("mapping must be BoundedClockMapping")
    _number(measurement_time.seconds, "measurement_time.seconds")
    if measurement_time.clock_domain != mapping.source_clock_domain:
        raise ValueError("source clock-domain mismatch")
    if not (mapping.valid_from_source_seconds <= measurement_time.seconds
            <= mapping.valid_until_source_seconds):
        raise ValueError("timestamp outside source validity interval")
    center = (Fraction(mapping.scale) * Fraction(measurement_time.seconds)
              + Fraction(mapping.offset_seconds))
    error = Fraction(mapping.error_bound_seconds)
    return MappedTimeInterval(
        _outward_float(center - error, lower=True),
        _outward_float(center + error, lower=False),
        mapping.target_clock_domain, measurement_time, mapping,
    )
