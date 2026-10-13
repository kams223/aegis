"""Version-1 read-only platform values; no acquisition, execution, or geometry.

All nested collections are tuples and all contracts are frozen. Every document
field, including explicit nulls and schema_version, is required on decoding.
Paths are lexical local references only: this layer never opens or resolves them.
"""

from dataclasses import asdict, dataclass, fields
import json
from math import isfinite
import re
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

MAX_ITEMS = 256
MAX_ID = 128
MAX_TEXT = 1024
MAX_PATH = 256
MAX_JSON_BYTES = 4 * 1024 * 1024
_TYPES = set()
_HINTS = {}


class PlatformContractError(ValueError):
    """A closed schema or relationship was rejected without modifying inputs."""


def _error(location, message):
    raise PlatformContractError(location + ": " + message)


def _text(value, name):
    maximum = MAX_TEXT if name in ("annotation", "explanation", "summary", "note", "description") else MAX_ID
    if name == "local_path":
        maximum = MAX_PATH
    if type(value) is not str or not value.strip() or len(value) > maximum:
        _error(name, "require nonempty bounded string")
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        _error(name, "control characters and invalid Unicode are unsupported")
    if name.endswith("_id") and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
        _error(name, "require opaque ASCII identifier")


def safe_reference(value):
    _text(value, "local_path")
    if (value.startswith("/") or ":" in value or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
            or any(c in value for c in ("?", "#", "%"))):
        _error("local_path", "require unambiguous relative local reference")
    return value


def _check(value, hint, name):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return
        choices = tuple(h for h in args if h is not type(None))
        if type(value) in choices:
            _check(value, type(value), name)
            return
        _error(name, "unsupported union value type")
    if origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
            _error(name, "unsupported declared value")
    elif origin is tuple:
        if type(value) is not tuple or len(value) > MAX_ITEMS:
            _error(name, "require tuple of at most 256 values")
        for item in value:
            _check(item, args[0], name)
    elif hint is str:
        _text(value, name)
    elif hint in (int, float):
        if type(value) is not hint or abs(value) > 10**18 or (hint is float and not isfinite(value)):
            _error(name, "require bounded finite number with exact type; bool is unsupported")
    elif hint is bool:
        if type(value) is not bool:
            _error(name, "require bool")
    elif hint in _TYPES:
        if type(value) is not hint:
            _error(name, "require " + hint.__name__)
    else:
        _error(name, "unsupported contract type")


@dataclass(frozen=True, slots=True, kw_only=True)
class Contract:
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            _error("schema_version", "require integer 1")
        for name, hint in _HINTS[type(self)].items():
            _check(getattr(self, name), hint, name)
        self.validate()

    def validate(self):
        """Subclass-specific consistency checks; no effects."""


def contract(cls):
    result = dataclass(frozen=True, slots=True, kw_only=True)(cls)
    _TYPES.add(result)
    _HINTS[result] = get_type_hints(result)
    return result


def unique(values, attribute, name):
    if len(values) > MAX_ITEMS:
        _error(name, "collection exceeds 256 values")
    identities = [getattr(item, attribute) for item in values]
    if len(set(identities)) != len(identities):
        _error(name, "duplicate " + attribute)


@contract
class Timestamp(Contract):
    value: int | float
    unit: Literal["s", "ms", "us", "ns"]
    clock_domain: str


@contract
class AdapterIdentity(Contract):
    adapter_id: str
    version: str


@contract
class Capability(Contract):
    name: Literal["recorded_metadata", "recorded_integrity", "health_snapshot", "observation_display", "camera_evidence"]
    support: Literal["supported", "unsupported", "unknown"]


@contract
class HealthSnapshot(Contract):
    status: Literal["healthy", "degraded", "unavailable", "unknown"]
    timestamp: Timestamp
    note: str


@contract
class SourceReference(Contract):
    source_id: str
    device_id: str
    clock_domain: str
    evidence_id: str


@contract
class Device(Contract):
    device_id: str
    category: Literal["aegis_native", "third_party", "simulated"]
    device_type: Literal["aerial", "ground", "other"]
    adapter: AdapterIdentity
    capabilities: tuple[Capability, ...]
    connection_status: Literal["offline", "recorded", "unknown"]
    health: HealthSnapshot
    sources: tuple[SourceReference, ...]

    def validate(self):
        unique(self.capabilities, "name", "capabilities")
        unique(self.sources, "source_id", "sources")
        if any(source.device_id != self.device_id for source in self.sources):
            _error("sources", "device identity differs")


@contract
class DeviceRegistry(Contract):
    devices: tuple[Device, ...]

    def validate(self):
        unique(self.devices, "device_id", "devices")
        unique(tuple(source for device in self.devices for source in device.sources), "source_id", "sources")


def build_registry(devices):
    """Accept supplied immutable records only; preserve caller order."""
    return DeviceRegistry(devices=devices)


@contract
class EvidenceReference(Contract):
    evidence_id: str
    source_id: str
    kind: Literal["camera_recording", "dataset_report", "validation_result", "observation_note", "health_snapshot"]
    local_path: str
    dataset_id: str | None

    def validate(self):
        safe_reference(self.local_path)
        if self.kind in ("dataset_report", "validation_result") and self.dataset_id is None:
            _error("dataset_id", "required for report evidence")


@contract
class Observation(Contract):
    observation_id: str
    source_id: str
    timestamp: Timestamp
    category: Literal["synthetic", "recorded_metadata"]
    quality: Literal["declared", "uncertain", "missing"]
    uncertainty_note: str | None
    annotation: str
    review_status: Literal["unreviewed", "under_review", "reviewed", "dismissed"]
    evidence_id: str

    def validate(self):
        if self.quality in ("uncertain", "missing") and self.uncertainty_note is None:
            _error("uncertainty_note", "required for uncertain or missing measurements")


@contract
class SensorAvailability(Contract):
    source_id: str
    status: Literal["available", "unavailable", "unknown"]


@contract
class SentinelMonitor(Contract):
    device_id: str
    sentinel_category: Literal["aerial", "ground"]
    connectivity: Literal["offline", "recorded", "unknown"]
    sensors: tuple[SensorAvailability, ...]
    battery_percent: int | float | None
    maintenance_status: Literal["nominal", "due", "unknown"]
    camera_evidence_id: str | None
    review_status: Literal["unreviewed", "under_review", "reviewed", "dismissed"]

    def validate(self):
        unique(self.sensors, "source_id", "sensors")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            _error("battery_percent", "require 0..100 or explicit null")


@contract
class AlertExplanation(Contract):
    code: Literal["unusual_metadata", "quality_warning", "review_requested"]
    explanation: str
    evidence_ids: tuple[str, ...]

    def validate(self):
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            _error("evidence_ids", "require nonempty unique references")
        for key in self.evidence_ids:
            _text(key, "evidence_id")


@contract
class Alert(Contract):
    alert_id: str
    observation_id: str
    status: Literal["unreviewed", "under_review", "reviewed", "dismissed"]
    explanation: AlertExplanation


InvestigationAction = Literal["inspect_dataset_report", "retrieve_evidence", "summarize_device_health", "explain_observation", "compare_validation_results"]


@contract
class InvestigationRequest(Contract):
    request_id: str
    alert_id: str
    action: InvestigationAction
    reference_ids: tuple[str, ...]

    def validate(self):
        count = 2 if self.action == "compare_validation_results" else 1
        if len(self.reference_ids) != count or len(set(self.reference_ids)) != count:
            _error("reference_ids", "incorrect count or duplicate investigation references")
        for key in self.reference_ids:
            _text(key, "reference_id")


@contract
class InvestigationResult(Contract):
    result_id: str
    request_id: str
    status: Literal["completed", "not_evaluated"]
    summary: str
    evidence_ids: tuple[str, ...]

    def validate(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            _error("evidence_ids", "duplicate reference")
        for key in self.evidence_ids:
            _text(key, "evidence_id")


@contract
class HumanReviewDecision(Contract):
    decision_id: str
    subject_kind: Literal["observation", "sentinel", "alert"]
    subject_id: str
    reviewer_id: str
    previous_status: Literal["unreviewed", "under_review", "reviewed", "dismissed"]
    new_status: Literal["unreviewed", "under_review", "reviewed", "dismissed"]
    timestamp: Timestamp
    note: str

    def validate(self):
        allowed = {"unreviewed": ("under_review", "reviewed", "dismissed"),
                   "under_review": ("reviewed", "dismissed"), "reviewed": (), "dismissed": ()}
        if self.new_status not in allowed[self.previous_status]:
            _error("new_status", "invalid review status transition")


@contract
class AuditEntry(Contract):
    audit_id: str
    actor_id: str
    event: Literal["investigation_completed", "investigation_not_evaluated", "human_review"]
    reference_id: str
    timestamp: Timestamp
    note: str


@contract
class ValidationEvidence(Contract):
    """Supplied offline outcome only; no automatic report loading or trust claim."""
    evidence_id: str
    dataset_id: str
    metadata_status: Literal["passed", "failed", "not_evaluated"]
    integrity_status: Literal["verified", "mismatch", "not_evaluated"]


def to_document(value):
    if type(value) not in _TYPES:
        _error("document", "require registered platform contract")
    # JSON-compatible lists are fresh; immutable inputs are never mutated.
    return json.loads(json.dumps(asdict(value), allow_nan=False, ensure_ascii=False))


def _decode(value, hint, location):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        if type(value) not in args:
            _error(location, "wrong union type")
        return value
    if origin is tuple:
        if type(value) is not list or len(value) > MAX_ITEMS:
            _error(location, "require bounded JSON array")
        return tuple(_decode(item, args[0], location) for item in value)
    if hint in _TYPES:
        return from_document(hint, value)
    return value


def from_document(cls, document):
    if cls not in _TYPES:
        _error("document", "unsupported contract class")
    names = tuple(field.name for field in fields(cls))
    if type(document) is not dict or set(document) != set(names):
        _error(cls.__name__, "missing or unexpected fields")
    values = {name: _decode(document[name], hint, name) for name, hint in _HINTS[cls].items()}
    return cls(**values)


def parse_json(cls, data):
    """Bounded in-memory UTF-8 JSON; no files, discovery, or implicit writes."""
    if type(data) is not bytes or len(data) > MAX_JSON_BYTES:
        _error("JSON", "require bytes of at most 4 MiB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _error("JSON", "duplicate key")
            result[key] = value
        return result
    def constant(value):
        _error("JSON", "non-finite number")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as cause:
        if isinstance(cause, PlatformContractError):
            raise
        raise PlatformContractError("JSON: invalid UTF-8 or JSON") from cause
    return from_document(cls, document)
