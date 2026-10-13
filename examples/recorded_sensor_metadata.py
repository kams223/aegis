"""Bounded offline recorded metadata checks; recording contents are never opened."""

import argparse
from dataclasses import asdict, dataclass
from fractions import Fraction
import json
from math import isfinite
from pathlib import Path, PurePosixPath
import sys

from examples.synthetic_observation_profiles import read_json, _object, _text, MAX_BYTES
from examples.synthetic_observation_inspector import _document, _text as html_text

MAX_SOURCES = 16
MAX_RECORDS = 4096
MAX_ID = 128
MAX_DESCRIPTION = 1024
MAX_REFERENCE = 256
MAX_NOTE = 256
MAX_SEQUENCE = 2**31 - 1
MAX_TIMESTAMP = 10**18
UNITS = {"s": 1, "ms": 1000, "us": 1000000, "ns": 1000000000}
KINDS = ("camera", "radar", "metadata")


class RecordedInputError(ValueError):
    """Structural or local-reference error; no partial report is produced."""


@dataclass(frozen=True)
class RecordedSource:
    source_id: str
    source_kind: str
    clock_domain: str
    recording_reference: str


@dataclass(frozen=True)
class RecordedMetadata:
    complete: bool | None
    byte_count: int | None
    content_digest: str | None
    note: str | None


@dataclass(frozen=True)
class RecordedRecord:
    record_id: str
    source_id: str
    sequence_index: int
    timestamp_value: int | float
    timestamp_unit: str
    metadata: RecordedMetadata


@dataclass(frozen=True)
class RecordedDataset:
    dataset_id: str
    description: str
    sources: tuple[RecordedSource, ...]
    records: tuple[RecordedRecord, ...]


def _closed(value, fields, location, optional=()):
    _object(value, fields, optional, location, RecordedInputError)


def _string(value, location, limit=MAX_ID):
    _text(value, location, RecordedInputError)
    if len(value) > limit:
        raise RecordedInputError(location + ": string exceeds limit")
    return value


def _integer(value, location, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise RecordedInputError(location + ": expected bounded nonnegative integer, not bool")
    return value


def _array(value, location, maximum):
    if type(value) is not list or len(value) > maximum:
        raise RecordedInputError(location + ": expected bounded array")
    return value


def _reference(value, directory, location):
    _string(value, location, MAX_REFERENCE)
    if (PurePosixPath(value).is_absolute() or any(part in (".", "..") for part in value.split("/"))
            or ":" in value or "\\" in value or "\x00" in value or "//" in value or value.endswith("/")):
        raise RecordedInputError(location + ": unsafe relative recording reference")
    try:
        resolved = (directory / value).resolve(strict=True)
        resolved.relative_to(directory)
        if not resolved.is_file():
            raise RecordedInputError(location + ": recording reference must be a regular file")
    except (OSError, ValueError, RuntimeError) as cause:
        raise RecordedInputError(location + ": missing file or recording reference escapes dataset directory") from cause
    # Existence/type/provenance only: no open, decoding, hashing or stat metadata in reports.
    return value


def dataset_from_document(document, directory):
    """Validate a closed document and local references; return immutable owned values."""
    _closed(document, ("schema_version", "dataset_id", "description", "sources", "records"), "dataset")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise RecordedInputError("schema_version: require integer 1")
    dataset_id = _string(document["dataset_id"], "dataset_id")
    description = _string(document["description"], "description", MAX_DESCRIPTION)
    try:
        directory = Path(directory).resolve(strict=True)
        if not directory.is_dir():
            raise RecordedInputError("dataset directory: require existing local directory")
    except (OSError, ValueError, TypeError, RuntimeError) as cause:
        raise RecordedInputError("dataset directory: unable to resolve local directory") from cause
    sources, identities = [], set()
    for index, value in enumerate(_array(document["sources"], "sources", MAX_SOURCES)):
        location = f"sources[{index}]"
        _closed(value, ("source_id", "source_kind", "clock_domain", "recording_reference"), location)
        identity = _string(value["source_id"], location + ".source_id")
        if identity in identities:
            raise RecordedInputError(location + ": duplicate source_id")
        identities.add(identity)
        if type(value["source_kind"]) is not str or value["source_kind"] not in KINDS:
            raise RecordedInputError(location + ": unsupported source_kind")
        domain = _string(value["clock_domain"], location + ".clock_domain")
        reference = _reference(value["recording_reference"], directory, location + ".recording_reference")
        sources.append(RecordedSource(identity, value["source_kind"], domain, reference))
    records, record_ids = [], set()
    for index, value in enumerate(_array(document["records"], "records", MAX_RECORDS)):
        location = f"records[{index}]"
        _closed(value, ("record_id", "source_id", "sequence_index", "timestamp", "metadata"), location)
        identity = _string(value["record_id"], location + ".record_id")
        if identity in record_ids:
            raise RecordedInputError(location + ": duplicate record_id")
        record_ids.add(identity)
        source_id = _string(value["source_id"], location + ".source_id")
        if source_id not in identities:
            raise RecordedInputError(location + ": unresolved source_id")
        sequence = _integer(value["sequence_index"], location + ".sequence_index", MAX_SEQUENCE)
        timestamp = value["timestamp"]
        _closed(timestamp, ("value", "unit"), location + ".timestamp")
        number = timestamp["value"]
        if (type(number) not in (int, float) or abs(number) > MAX_TIMESTAMP
                or (type(number) is float and not isfinite(number))):
            raise RecordedInputError(location + ": timestamp must be a finite bounded number, not bool")
        if type(timestamp["unit"]) is not str or timestamp["unit"] not in UNITS:
            raise RecordedInputError(location + ": unsupported timestamp unit")
        metadata = value["metadata"]
        _closed(metadata, (), location + ".metadata", ("complete", "byte_count", "content_digest", "note"))
        if "complete" in metadata and type(metadata["complete"]) is not bool:
            raise RecordedInputError(location + ": metadata.complete must be bool")
        if "byte_count" in metadata:
            _integer(metadata["byte_count"], location + ".metadata.byte_count", 2**63 - 1)
        if "content_digest" in metadata:
            digest = metadata["content_digest"]
            if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise RecordedInputError(location + ": content_digest must be lowercase SHA-256 text")
        if "note" in metadata:
            _string(metadata["note"], location + ".metadata.note", MAX_NOTE)
        records.append(RecordedRecord(identity, source_id, sequence, number, timestamp["unit"],
            RecordedMetadata(*(metadata.get(key) for key in ("complete", "byte_count", "content_digest", "note")))))
    return RecordedDataset(dataset_id, description, tuple(sources), tuple(records))


def load_dataset(path):
    try:
        path = Path(path)
        if not path.is_file():
            raise RecordedInputError("dataset: require an existing regular JSON file")
        directory = path.resolve(strict=True).parent
    except (OSError, ValueError, TypeError, RuntimeError) as cause:
        raise RecordedInputError("dataset: unable to resolve local JSON file") from cause
    return dataset_from_document(read_json(path, error=RecordedInputError), directory)


def validate_dataset(dataset):
    """Check declarations in delivery order; never repair or inspect recording contents."""
    if not isinstance(dataset, RecordedDataset):
        raise RecordedInputError("validation requires a loaded RecordedDataset")
    diagnostics, unavailable = [], []
    counts = {source.source_id: 0 for source in dataset.sources}
    sequences = {source.source_id: set() for source in dataset.sources}
    seen_times = {source.source_id: set() for source in dataset.sources}
    previous_sequence, previous_time, supported = {}, {}, {}
    def diagnostic(code, severity, explanation, source_id=None, record=None, index=None):
        diagnostics.append({"code": code, "severity": severity, "source_id": source_id,
            "record_id": None if record is None else record.record_id, "record_index": index,
            "explanation": explanation})
    def pending(check, source_id=None, record=None, index=None):
        unavailable.append({"check": check, "required": True, "source_id": source_id,
            "record_id": None if record is None else record.record_id, "record_index": index,
            "status": "not_evaluated"})
    for source in dataset.sources:
        domain = source.clock_domain
        supported[source.source_id] = domain.startswith("recording:") and bool(domain[len("recording:"):].strip())
        if domain == "unknown":
            diagnostic("UNKNOWN_CLOCK_DOMAIN", "Warning", "Clock origin is explicitly unknown; timestamp checks unavailable.", source.source_id)
            pending("timestamp_integrity", source.source_id)
        elif not supported[source.source_id]:
            diagnostic("UNSUPPORTED_CLOCK_DOMAIN", "Invalid", "Only explicit recording:<timebase-id> domains are supported.", source.source_id)
            pending("timestamp_integrity", source.source_id)
    for index, record in enumerate(dataset.records):
        key, sequence = record.source_id, record.sequence_index
        counts[key] += 1
        if sequence in sequences[key]:
            diagnostic("DUPLICATE_SEQUENCE_INDEX", "Invalid", "Sequence index repeats within this source.", key, record, index)
        if key in previous_sequence and sequence < previous_sequence[key]:
            diagnostic("OUT_OF_ORDER_DELIVERY", "Warning", "Sequence index decreased in source delivery order.", key, record, index)
        sequences[key].add(sequence)
        previous_sequence[key] = sequence
        if supported[key]:
            time = Fraction(str(record.timestamp_value)) / UNITS[record.timestamp_unit]
            if time in seen_times[key]:
                diagnostic("REPEATED_TIMESTAMP", "Warning", "Timestamp repeats within this source clock after exact unit conversion.", key, record, index)
            if key in previous_time and time < previous_time[key]:
                diagnostic("TIMESTAMP_REGRESSION", "Invalid", "Timestamp decreased in delivery order within this source clock.", key, record, index)
            seen_times[key].add(time)
            previous_time[key] = time
        if record.metadata.complete is False:
            diagnostic("INCOMPLETE_RECORD", "Invalid", "Record metadata explicitly declares incomplete data.", key, record, index)
        elif record.metadata.complete is None:
            diagnostic("MISSING_COMPLETENESS", "Warning", "Optional completeness declaration missing; required completeness check unavailable.", key, record, index)
            pending("record_completeness", key, record, index)
    if not dataset.sources:
        diagnostic("NO_SOURCES", "Warning", "No sources are supplied; dataset checks unavailable.")
        pending("source_inventory")
    for source in dataset.sources:
        key = source.source_id
        if counts[key] < 2:
            diagnostic("INSUFFICIENT_RECORDS", "Warning", "At least two source records are needed for temporal and ordering checks.", key)
            pending("record_order_and_timestamps", key)
        expected = 0
        for sequence in sorted(sequences[key]):
            if sequence > expected:
                diagnostic("SEQUENCE_GAP", "Warning", f"Missing sequence range {expected}..{sequence - 1}; zero-based indices are required.", key)
            expected = sequence + 1
    domains = {}
    for source in dataset.sources:
        domains.setdefault(source.clock_domain, []).append(source.source_id)
    status = "failed" if any(d["severity"] == "Invalid" for d in diagnostics) else "not_evaluated" if unavailable else "passed"
    return {"schema_version": 1, "dataset_id": dataset.dataset_id,
        "source_inventory": [asdict(source) for source in dataset.sources],
        "record_count": len(dataset.records), "per_source_counts": counts,
        "timestamp_domains": [{"clock_domain": domain, "source_ids": ids,
            "comparison_scope": "per_source_only; no cross-source clock alignment"} for domain, ids in domains.items()],
        "diagnostics": diagnostics, "status": status,
        "unevaluated_checks": unavailable + [{"check": "recording_content_integrity_and_physical_accuracy",
            "required": False, "status": "not_evaluated",
            "explanation": "Contents, declared digests/byte counts, physical accuracy and operational readiness are outside metadata-only scope."}]}


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_html(report):
    body = "<h1>Recorded Sensor Metadata Validation</h1><p>Dataset: " + html_text(report["dataset_id"])
    body += "</p><p>Status: " + html_text(report["status"]) + "</p><p>Offline metadata declarations only; recording contents are not inspected.</p>"
    body += "<h2>Source inventory and clock domains</h2><pre>" + html_text(render_json({
        key: report[key] for key in ("source_inventory", "record_count", "per_source_counts", "timestamp_domains")})) + "</pre>"
    columns = ("code", "severity", "source_id", "record_id", "record_index", "explanation")
    body += '<h2>Quality diagnostics</h2><table><caption>Diagnostics in stable validation order</caption><thead><tr>'
    body += "".join('<th scope="col">' + html_text(key) + "</th>" for key in columns) + "</tr></thead><tbody>"
    for diagnostic in report["diagnostics"]:
        body += "<tr>" + "".join("<td>" + html_text(diagnostic[key]) + "</td>" for key in columns) + "</tr>"
    body += "</tbody></table><h2>Unevaluated checks and limitations</h2><pre>" + html_text(render_json(report["unevaluated_checks"])) + "</pre>"
    return _document(body, title="Recorded Sensor Metadata Validation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", required=True, metavar="PATH")
    parser.add_argument("--format", choices=("json", "html"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = validate_dataset(load_dataset(args.dataset))
        output = render_html(report) if args.format == "html" else render_json(report)
    except RecordedInputError as cause:
        parser.error(str(cause))
    print(output, end="")
    return {"passed": 0, "failed": 1, "not_evaluated": 2}[report["status"]] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
