"""Classify available representations, never physical correspondence.

Same-frame geometry permits a mathematical comparison, not a matching decision.
Overlapping supplied time bounds do not prove simultaneous acquisition; disjoint
bounds do not prove different objects. No conversion, scoring, or gating occurs.
"""

from dataclasses import dataclass
from enum import Enum

from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.spatial.camera import CameraRay
from aegis.spatial.radar import RadarPoint
from aegis.spatial.transforms import RotatedDirection, TransformedPoint


class SpatialStatus(Enum):
    COMPARABLE = "comparable"
    INCOMPARABLE = "incomparable"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class SpatialReason(Enum):
    SAME_FRAME_METRIC_POINTS = "same_frame_metric_points"
    SAME_FRAME_DIRECTIONS = "same_frame_directions"
    MISSING_SPATIAL_GEOMETRY = "missing_spatial_geometry"
    DIFFERENT_SPATIAL_FRAMES = "different_spatial_frames"
    INCOMPATIBLE_GEOMETRY_TYPES = "incompatible_geometry_types"


class TemporalRelationship(Enum):
    OVERLAPPING = "overlapping"
    DISJOINT = "disjoint"
    INDETERMINATE = "indeterminate"


class TemporalReason(Enum):
    SAME_DOMAIN_BOUNDED_INTERVALS = "same_domain_bounded_intervals"
    MISSING_MAPPED_TIME = "missing_mapped_time"
    DIFFERENT_CLOCK_DOMAINS = "different_clock_domains"


def _require_evidence(value: DerivedSensorEvidence) -> None:
    if not isinstance(value, DerivedSensorEvidence):
        raise TypeError("inputs must be DerivedSensorEvidence")
    # Existing frozen evidence owns validation of derivation and provenance.
    # Classification trusts that contract; it does not rebuild or rederive it.


def _geometry(evidence: DerivedSensorEvidence):
    return (evidence.transformed_geometry if evidence.transformed_geometry is not None
            else evidence.spatial_projection)


def _kind_and_frame(geometry):
    if isinstance(geometry, (RadarPoint, TransformedPoint)):
        return "point", geometry.reference_frame
    if isinstance(geometry, CameraRay):
        return "direction", geometry.optical_frame
    if isinstance(geometry, RotatedDirection):
        return "direction", geometry.reference_frame
    raise TypeError("unsupported spatial representation")


def _spatial(left: DerivedSensorEvidence, right: DerivedSensorEvidence):
    first, second = _geometry(left), _geometry(right)
    if first is None or second is None:
        return SpatialStatus.INSUFFICIENT_INFORMATION, SpatialReason.MISSING_SPATIAL_GEOMETRY
    first_kind, first_frame = _kind_and_frame(first)
    second_kind, second_frame = _kind_and_frame(second)
    if first_kind != second_kind:
        return SpatialStatus.INCOMPARABLE, SpatialReason.INCOMPATIBLE_GEOMETRY_TYPES
    if first_frame != second_frame:
        return SpatialStatus.INSUFFICIENT_INFORMATION, SpatialReason.DIFFERENT_SPATIAL_FRAMES
    reason = (SpatialReason.SAME_FRAME_METRIC_POINTS if first_kind == "point"
              else SpatialReason.SAME_FRAME_DIRECTIONS)
    return SpatialStatus.COMPARABLE, reason


def _temporal(left: DerivedSensorEvidence, right: DerivedSensorEvidence):
    first, second = left.mapped_time, right.mapped_time
    if first is None or second is None:
        return TemporalRelationship.INDETERMINATE, TemporalReason.MISSING_MAPPED_TIME
    if first.clock_domain != second.clock_domain:
        return TemporalRelationship.INDETERMINATE, TemporalReason.DIFFERENT_CLOCK_DOMAINS
    disjoint = (first.upper_seconds < second.lower_seconds
                or second.upper_seconds < first.lower_seconds)
    relationship = TemporalRelationship.DISJOINT if disjoint else TemporalRelationship.OVERLAPPING
    return relationship, TemporalReason.SAME_DOMAIN_BOUNDED_INTERVALS


@dataclass(frozen=True)
class EvidenceComparability:
    """Independent classifications with ordered original evidence references.

Transformed geometry takes precedence over local projection, without searching
alternatives or falling back. Time uses only retained mapped intervals, never
raw timestamps fabricated into exact intervals. Direct construction recomputes
all four classification fields and rejects inconsistent conclusions.
"""

    left: DerivedSensorEvidence
    right: DerivedSensorEvidence
    spatial_status: SpatialStatus
    spatial_reason: SpatialReason
    temporal_relationship: TemporalRelationship
    temporal_reason: TemporalReason

    def __post_init__(self) -> None:
        _require_evidence(self.left)
        _require_evidence(self.right)
        for name, expected in (
            ("spatial_status", SpatialStatus), ("spatial_reason", SpatialReason),
            ("temporal_relationship", TemporalRelationship), ("temporal_reason", TemporalReason),
        ):
            if type(getattr(self, name)) is not expected:
                raise TypeError(f"{name} must be {expected.__name__}")
        if (self.spatial_status, self.spatial_reason) != _spatial(self.left, self.right):
            raise ValueError("inconsistent spatial classification")
        if (self.temporal_relationship, self.temporal_reason) != _temporal(self.left, self.right):
            raise ValueError("inconsistent temporal classification")


def assess_evidence_comparability(
    left: DerivedSensorEvidence, right: DerivedSensorEvidence,
) -> EvidenceComparability:
    """Classify compatible information without scores or an eligibility gate.

Direction compatibility needs neither depth nor a shared ray origin. It does
not establish target positions. Frame/domain equality uses declared identifiers
by value, conditional on producer conventions and caller-supplied time bounds.
"""
    _require_evidence(left)
    _require_evidence(right)
    return EvidenceComparability(left, right, *_spatial(left, right), *_temporal(left, right))
