"""Caller-ordered derived evidence, without tracking or temporal reconstruction."""

from dataclasses import dataclass

from aegis.fusion.derived_evidence import DerivedSensorEvidence


@dataclass(frozen=True)
class ObservationHistory:
    """An ordered collection, not a track or shared physical-object assertion.

    Caller order does not guarantee measurement-time order. Duplicate occurrences
    are preserved and do not establish independent acquisitions. The supplied
    tuple and evidence objects are retained by identity, without revalidation.
    Frozen tuple storage does not recursively freeze arbitrary nested payloads.
    """

    records: tuple[DerivedSensorEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            raise TypeError("records must be a tuple")
        for record in self.records:
            if not isinstance(record, DerivedSensorEvidence):
                raise TypeError("records must contain DerivedSensorEvidence instances")
