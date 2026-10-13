"""Bounded local byte verification; declarations and hashes do not authenticate origin."""

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

from examples.recorded_sensor_metadata import load_dataset, RecordedInputError, MAX_SOURCES, MAX_ID, MAX_REFERENCE
from examples.synthetic_observation_profiles import read_json, _object, _text
from examples.synthetic_observation_inspector import _document, _text as html_text

CHUNK_BYTES = 64 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_AGGREGATE_BYTES = 64 * 1024 * 1024
_DESCRIPTORS_SUPPORTED = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks)


class IntegrityInputError(ValueError):
    """Invalid manifest or source association, distinct from unavailable verification."""


class _Unavailable(Exception):
    def __init__(self, code):
        self.code = code


@dataclass(frozen=True)
class IntegrityEntry:
    source_id: str
    recording_reference: str
    expected_size_bytes: int
    expected_sha256: str


@dataclass(frozen=True)
class IntegrityManifest:
    manifest_id: str
    dataset_reference: str
    entries: tuple[IntegrityEntry, ...]


def _string(value, location, limit):
    _text(value, location, IntegrityInputError)
    if len(value) > limit:
        raise IntegrityInputError(location + ": string exceeds limit")
    return value


def _parts(value, location):
    _string(value, location, MAX_REFERENCE)
    if (PurePosixPath(value).is_absolute() or any(part in (".", "..", "") for part in value.split("/"))
            or ":" in value or "\\" in value or "\x00" in value):
        raise IntegrityInputError(location + ": require a safe relative local path")
    return tuple(value.split("/"))


def manifest_from_document(document):
    _object(document, ("schema_version", "manifest_id", "dataset_reference", "entries"), (), "manifest", IntegrityInputError)
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise IntegrityInputError("schema_version: require integer 1")
    identity = _string(document["manifest_id"], "manifest_id", MAX_ID)
    _parts(document["dataset_reference"], "dataset_reference")
    if type(document["entries"]) is not list or len(document["entries"]) > MAX_SOURCES:
        raise IntegrityInputError("entries: require array of at most 16 entries")
    entries, sources, references = [], set(), set()
    for index, row in enumerate(document["entries"]):
        location = f"entries[{index}]"
        _object(row, ("source_id", "recording_reference", "expected_size_bytes", "expected_sha256"), (), location, IntegrityInputError)
        source = _string(row["source_id"], location + ".source_id", MAX_ID)
        _parts(row["recording_reference"], location + ".recording_reference")
        if source in sources or row["recording_reference"] in references:
            raise IntegrityInputError(location + ": duplicate source_id or recording_reference")
        sources.add(source); references.add(row["recording_reference"])
        size = row["expected_size_bytes"]
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise IntegrityInputError(location + ": expected_size_bytes must be a bounded nonnegative integer, not bool")
        digest = row["expected_sha256"]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise IntegrityInputError(location + ": expected_sha256 must be 64 lowercase hex characters")
        entries.append(IntegrityEntry(source, row["recording_reference"], size, digest))
    if sum(entry.expected_size_bytes for entry in entries) > MAX_AGGREGATE_BYTES:
        raise IntegrityInputError("entries: declared aggregate size exceeds 64 MiB limit")
    return IntegrityManifest(identity, document["dataset_reference"], tuple(entries))


def load_manifest(path):
    try:
        if not Path(path).is_file():
            raise IntegrityInputError("manifest: require a regular local JSON file")
    except (OSError, ValueError, TypeError) as cause:
        raise IntegrityInputError("manifest: unable to inspect local JSON file") from cause
    return manifest_from_document(read_json(path, error=IntegrityInputError))


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_relative(root_fd, parts):
    """Walk pinned directories with no-follow flags; refuse special nodes before open."""
    directory = os.dup(root_fd)
    result = None
    try:
        for name in parts[:-1]:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise _Unavailable("UNSAFE_REFERENCE")
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                opened = os.fstat(child)
            except BaseException:
                os.close(child)
                raise
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                os.close(child)
                raise _Unavailable("FILE_CHANGED")
            os.close(directory)
            directory = child
        info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise _Unavailable("UNSAFE_REFERENCE")
        if not stat.S_ISREG(info.st_mode):
            raise _Unavailable("UNSUPPORTED_FILE_TYPE")
        result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=directory)
        opened = os.fstat(result)
        if not stat.S_ISREG(opened.st_mode):
            raise _Unavailable("UNSUPPORTED_FILE_TYPE")
        if _fingerprint(info) != _fingerprint(opened):
            raise _Unavailable("FILE_CHANGED")
        return result, opened
    except BaseException:
        if result is not None:
            os.close(result)
        raise
    finally:
        os.close(directory)


def _code(error):
    if isinstance(error, _Unavailable):
        return error.code
    if isinstance(error, PermissionError):
        return "PERMISSION_DENIED"
    if isinstance(error, FileNotFoundError):
        return "FILE_UNAVAILABLE"
    return "FILE_IO_ERROR"


def _stream(fd, initial, row, budget):
    """At most 64 KiB per read; all consumed bytes, including probes, count toward caps."""
    digest = hashlib.sha256()
    while row["bytes_read"] < initial.st_size:
        remaining = MAX_AGGREGATE_BYTES - budget[0]
        if remaining <= 0:
            raise _Unavailable("AGGREGATE_SIZE_LIMIT")
        chunk = os.read(fd, min(CHUNK_BYTES, initial.st_size - row["bytes_read"], remaining))
        if not chunk:
            raise _Unavailable("SHORT_READ")
        row["bytes_read"] += len(chunk)
        budget[0] += len(chunk)
        digest.update(chunk)
    # Where a byte of budget remains, probe EOF without exceeding either cap.
    if row["bytes_read"] < MAX_FILE_BYTES and budget[0] < MAX_AGGREGATE_BYTES:
        extra = os.read(fd, 1)
        row["bytes_read"] += len(extra)
        budget[0] += len(extra)
        if extra:
            raise _Unavailable("FILE_GROWTH")
    after = os.fstat(fd)
    if after.st_size > initial.st_size:
        raise _Unavailable("FILE_GROWTH")
    if _fingerprint(after) != _fingerprint(initial):
        raise _Unavailable("FILE_CHANGED")
    return digest.hexdigest()


def _associations(dataset, manifest, directory, dataset_path):
    expected_path = directory.joinpath(*_parts(manifest.dataset_reference, "dataset_reference"))
    # Canonical explicit JSON path must be named by the manifest, not just equal bytes.
    if expected_path != dataset_path:
        raise IntegrityInputError("dataset_reference: does not name the supplied dataset")
    expected = {source.source_id: source.recording_reference for source in dataset.sources}
    actual = {entry.source_id: entry.recording_reference for entry in manifest.entries}
    if actual != expected:
        raise IntegrityInputError("entries: require exact dataset source/reference associations")


def verify_dataset(dataset, manifest, directory, dataset_path):
    """Verify a loaded Phase 58 dataset; file failures are reportable, associations are input errors."""
    if not isinstance(manifest, IntegrityManifest):
        raise IntegrityInputError("verification requires a loaded IntegrityManifest")
    directory, dataset_path = Path(directory), Path(dataset_path)
    _associations(dataset, manifest, directory, dataset_path)
    rows = [{"source_id": entry.source_id, "recording_reference": entry.recording_reference,
        "expected_size_bytes": entry.expected_size_bytes, "actual_size_bytes": None,
        "expected_sha256": entry.expected_sha256, "actual_sha256": None,
        "bytes_read": 0, "integrity_status": "not_evaluated", "diagnostic_codes": []} for entry in manifest.entries]
    diagnostics = []
    def fail(index, code):
        rows[index]["diagnostic_codes"].append(code)
        diagnostics.append({"entry_index": index, "source_id": rows[index]["source_id"], "code": code})
    with ExitStack() as stack:
        descriptors = {}
        try:
            if not _DESCRIPTORS_SUPPORTED:
                raise _Unavailable("DESCRIPTOR_VERIFICATION_UNAVAILABLE")
            root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root_fd)
            dataset_fd, _ = _open_relative(root_fd, _parts(manifest.dataset_reference, "dataset_reference"))
            os.close(dataset_fd)
        except (OSError, _Unavailable) as cause:
            for index in range(len(rows)):
                fail(index, _code(cause))
        else:
            for index, row in enumerate(rows):
                try:
                    fd, info = _open_relative(root_fd, _parts(row["recording_reference"], "recording_reference"))
                    stack.callback(os.close, fd)
                    row["actual_size_bytes"] = info.st_size
                    if info.st_size > MAX_FILE_BYTES:
                        raise _Unavailable("FILE_SIZE_LIMIT")
                    descriptors[index] = (fd, info)
                except (OSError, _Unavailable) as cause:
                    fail(index, _code(cause))
            total_size = sum(info.st_size for fd, info in descriptors.values())
            if total_size > MAX_AGGREGATE_BYTES:
                for index in descriptors:
                    fail(index, "AGGREGATE_SIZE_LIMIT")
            else:
                budget = [0]
                for index, (fd, info) in descriptors.items():
                    row = rows[index]
                    try:
                        digest = _stream(fd, info, row, budget)
                        current_fd, current = _open_relative(root_fd, _parts(row["recording_reference"], "recording_reference"))
                        os.close(current_fd)
                        if _fingerprint(current) != _fingerprint(info):
                            raise _Unavailable("FILE_CHANGED")
                        row["actual_sha256"] = digest
                        if row["bytes_read"] != row["expected_size_bytes"]:
                            fail(index, "SIZE_MISMATCH")
                        if digest != row["expected_sha256"]:
                            fail(index, "DIGEST_MISMATCH")
                        row["integrity_status"] = "mismatch" if row["diagnostic_codes"] else "verified"
                    except (OSError, _Unavailable) as cause:
                        fail(index, _code(cause))
    counts = {status: sum(row["integrity_status"] == status for row in rows)
              for status in ("verified", "mismatch", "not_evaluated")}
    status = "mismatch" if counts["mismatch"] else "not_evaluated" if not rows or counts["not_evaluated"] else "verified"
    if not rows:
        diagnostics.append({"entry_index": None, "source_id": None, "code": "NO_FILES"})
    # Stable report ordering is manifest index, then each entry's detection order.
    diagnostics.sort(key=lambda item: -1 if item["entry_index"] is None else item["entry_index"])
    return {"schema_version": 1, "manifest_id": manifest.manifest_id, "dataset_id": dataset.dataset_id,
        "verification_status": status, "file_count": len(rows), "verified_count": counts["verified"],
        "mismatch_count": counts["mismatch"], "not_evaluated_count": counts["not_evaluated"],
        "entries": rows, "diagnostics": diagnostics,
        "limitations": ["Byte equality and declared source associations do not authenticate recording origin, physical accuracy or trusted provenance.",
            "Metadata quality is evaluated separately by the Phase 58 CLI.",
            "Stable trusted dataset directories are required; observable descriptor/path changes are detected, not every possible concurrent mutation."]}


def run_verification(dataset_path, manifest_path):
    manifest = load_manifest(manifest_path)
    dataset = load_dataset(dataset_path)
    path = Path(dataset_path).resolve(strict=True)
    return verify_dataset(dataset, manifest, path.parent, path)


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_html(report):
    body = "<h1>Recorded Dataset Byte Integrity</h1>"
    for key in ("manifest_id", "dataset_id", "verification_status", "file_count", "verified_count", "mismatch_count", "not_evaluated_count"):
        body += "<p>" + html_text(key) + ": " + html_text(report[key]) + "</p>"
    columns = ("source_id", "recording_reference", "expected_size_bytes", "actual_size_bytes",
               "expected_sha256", "actual_sha256", "bytes_read", "integrity_status", "diagnostic_codes")
    body += '<h2>File comparisons</h2><table><caption>Manifest-order byte verification</caption><thead><tr>'
    body += "".join('<th scope="col">' + html_text(key) + "</th>" for key in columns) + "</tr></thead><tbody>"
    for row in report["entries"]:
        body += "<tr>" + "".join("<td>" + html_text(row[key]) + "</td>" for key in columns) + "</tr>"
    body += "</tbody></table><h2>Diagnostics</h2><pre>" + html_text(render_json(report["diagnostics"])) + "</pre>"
    body += "<h2>Scope and limitations</h2><ul>" + "".join("<li>" + html_text(value) + "</li>" for value in report["limitations"]) + "</ul>"
    return _document(body, title="Recorded Dataset Byte Integrity")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", required=True, metavar="PATH")
    parser.add_argument("--manifest", required=True, metavar="PATH")
    parser.add_argument("--format", choices=("json", "html"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_verification(args.dataset, args.manifest)
        output = render_html(report) if args.format == "html" else render_json(report)
    except (IntegrityInputError, RecordedInputError, OSError, ValueError) as cause:
        # Do not include host-dependent filesystem exception strings in diagnostics.
        parser.error(str(cause) if isinstance(cause, (IntegrityInputError, RecordedInputError)) else "unable to prepare local integrity input")
    print(output, end="")
    return {"verified": 0, "mismatch": 1, "not_evaluated": 2}[report["verification_status"]] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
