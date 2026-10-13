"""Versioned local software regression snapshots; approval is a human review step."""

from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from examples.synthetic_observation_batch import run_batch, BatchInputError, MAX_ENTRIES
from examples.synthetic_observation_profiles import (
    read_json, _object, _text, MAX_BYTES, SEVERITIES, EXPECTATIONS, profile_from_document,
    ProfileLoadError,
)
from examples.synthetic_observation_inspector import _document, _text as html_text

STATUSES = ("passed", "failed", "not_evaluated")
ENTRY_FIELDS = ("position", "scenario_id", "profile_id", "scenario_loading", "profile_loading",
                "metadata_validation_status", "inventory_integrity_status", "profile_evaluation_status",
                "diagnostic_counts", "profile_checks", "loading_error", "final_status")


class RegressionInputError(ValueError):
    """Malformed local baseline, snapshot or candidate destination."""


def _closed(value, fields, location):
    _object(value, fields, (), location, RegressionInputError)


def _string(value, location):
    return _text(value, location, RegressionInputError)


def _status(value, location):
    if type(value) is not str or value not in STATUSES:
        raise RegressionInputError(location + ": unsupported status")


def canonical_report(report):
    """UTF-8 JSON: sorted object keys, compact separators, literal Unicode, no LF."""
    try:
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as cause:
        raise RegressionInputError("report is not finite UTF-8 JSON") from cause
    if len(encoded) > MAX_BYTES:
        raise RegressionInputError("report exceeds 1 MiB limit")
    return encoded


def report_digest(report):
    return hashlib.sha256(canonical_report(report)).hexdigest()


def _check_value(key, value, *, actual=False):
    if actual and value is None:
        return
    # Reuse the existing closed declarative expectation types, without evaluation.
    try:
        profile_from_document({"schema_version": 1, "profile_id": "snapshot",
            "scenario_id": "snapshot", "description": "Software snapshot value",
            "expectations": {key: value}})
    except ProfileLoadError as cause:
        raise RegressionInputError("profile check value: " + str(cause)) from cause


def validate_snapshot(report):
    """Closed semantic schema; return a detached snapshot in schema field order."""
    _closed(report, ("schema_version", "batch_id", "entries", "overall_status"), "report")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise RegressionInputError("report schema_version: require integer 1")
    _string(report["batch_id"], "batch_id")
    _status(report["overall_status"], "overall_status")
    entries = report["entries"]
    if type(entries) is not list or len(entries) > MAX_ENTRIES:
        raise RegressionInputError("entries: require array of at most 32 entries")
    rows = []
    for position, row in enumerate(entries):
        _closed(row, ENTRY_FIELDS, "entry")
        if type(row["position"]) is not int or row["position"] != position:
            raise RegressionInputError("entry position: must match ordered array index")
        _string(row["scenario_id"], "scenario_id")
        if row["profile_id"] is not None:
            _string(row["profile_id"], "profile_id")
        if row["loading_error"] is not None:
            _string(row["loading_error"], "loading_error")
        for key in ("scenario_loading", "profile_loading", "metadata_validation_status",
                    "inventory_integrity_status", "profile_evaluation_status", "final_status"):
            _status(row[key], key)
        _closed(row["diagnostic_counts"], SEVERITIES, "diagnostic_counts")
        for count in row["diagnostic_counts"].values():
            if type(count) is not int or count < 0:
                raise RegressionInputError("diagnostic counts: require nonnegative integers")
        checks = row["profile_checks"]
        if type(checks) is not list or len(checks) > len(EXPECTATIONS):
            raise RegressionInputError("profile_checks: require bounded array")
        last = -1
        for check in checks:
            _closed(check, ("id", "status", "expected", "actual"), "profile check")
            if type(check["id"]) is not str or check["id"] not in EXPECTATIONS:
                raise RegressionInputError("profile check: unsupported id")
            index = EXPECTATIONS.index(check["id"])
            if index <= last:
                raise RegressionInputError("profile checks: duplicate or out of schema order")
            last = index
            _status(check["status"], "profile check status")
            _check_value(check["id"], check["expected"])
            _check_value(check["id"], check["actual"], actual=True)
        detached = {key: deepcopy(row[key]) for key in ENTRY_FIELDS}
        detached["diagnostic_counts"] = {severity: row["diagnostic_counts"][severity] for severity in SEVERITIES}
        detached["profile_checks"] = []
        for check in checks:
            ordered = {key: deepcopy(check[key]) for key in ("id", "status", "expected", "actual")}
            if check["id"] == "diagnostic_counts":
                for key in ("expected", "actual"):
                    if ordered[key] is not None:
                        ordered[key] = {severity: ordered[key][severity] for severity in SEVERITIES if severity in ordered[key]}
            detached["profile_checks"].append(ordered)
        rows.append(detached)
    result = {"schema_version": 1, "batch_id": report["batch_id"], "entries": rows,
              "overall_status": report["overall_status"]}
    canonical_report(result)
    return result


def semantic_report(batch_report):
    """Select documented outcomes; presentation and nested inspection data excluded."""
    try:
        rows = [{key: deepcopy(row["profile_evaluation"]["checks"] if key == "profile_checks" else row[key])
                 for key in ENTRY_FIELDS} for row in batch_report["entries"]]
        return validate_snapshot({"schema_version": batch_report["schema_version"],
            "batch_id": batch_report["batch_id"], "entries": rows,
            "overall_status": batch_report["overall_status"]})
    except (KeyError, TypeError) as cause:
        raise RegressionInputError("batch report: missing or invalid semantic fields") from cause


def baseline_from_document(document):
    _closed(document, ("schema_version", "baseline_id", "description", "source_batch_id",
                       "approval", "report_digest", "report"), "baseline")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise RegressionInputError("baseline schema_version: require integer 1")
    for key in ("baseline_id", "description", "source_batch_id"):
        _string(document[key], key)
    approval = document["approval"]
    _closed(approval, ("status", "approved_by", "approval_note"), "approval")
    if approval["status"] == "approved" and type(approval["status"]) is str:
        _string(approval["approved_by"], "approved_by")
        _string(approval["approval_note"], "approval_note")
    elif approval["status"] == "candidate" and type(approval["status"]) is str:
        if approval["approved_by"] is not None or approval["approval_note"] is not None:
            raise RegressionInputError("candidate: approval fields must be null")
    else:
        raise RegressionInputError("approval status: require candidate or approved")
    report = validate_snapshot(document["report"])
    if report["batch_id"] != document["source_batch_id"]:
        raise RegressionInputError("source_batch_id: does not match stored report")
    digest = document["report_digest"]
    if type(digest) is not str or digest != report_digest(report):
        raise RegressionInputError("report_digest: SHA-256 mismatch")
    result = {"schema_version": 1, **{key: document[key] for key in
              ("baseline_id", "description", "source_batch_id")}, "approval": deepcopy(approval),
              "report_digest": digest, "report": report}
    if len(render_json(result).encode("utf-8")) > MAX_BYTES:
        raise RegressionInputError("baseline exceeds 1 MiB limit")
    return result


def load_baseline(path):
    return baseline_from_document(read_json(path, error=RegressionInputError))


def candidate_baseline(batch_report, baseline_id, description):
    report = semantic_report(batch_report)
    return baseline_from_document({"schema_version": 1, "baseline_id": baseline_id,
        "description": description, "source_batch_id": report["batch_id"],
        "approval": {"status": "candidate", "approved_by": None, "approval_note": None},
        "report_digest": report_digest(report), "report": report})


def write_candidate(path, candidate):
    """Exclusive creation only; trusted stable parent directories are required."""
    candidate = baseline_from_document(candidate)
    if candidate["approval"]["status"] != "candidate":
        raise RegressionInputError("generation writes candidates only")
    value = str(path)
    _string(value, "output path")
    if (":" in value or "\\" in value or "\x00" in value or "//" in value
            or any(part in (".", "..") for part in value.split("/")) or value.endswith("/")):
        raise RegressionInputError("output path: unsafe local path")
    target = Path(value)
    # Refuse symlinks in every existing parent, including the destination itself.
    try:
        absolute = target.absolute()
        if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
            raise RegressionInputError("output path: symlinks are unsupported")
        if not absolute.parent.is_dir():
            raise RegressionInputError("output path: parent directory must exist")
        contents = render_json(candidate).encode("utf-8")
        fd = os.open(absolute, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
    except (OSError, ValueError) as cause:
        raise RegressionInputError("output path: cannot exclusively create candidate") from cause


def _category(path):
    if path == "/batch_id":
        return "batch_identity"
    if "diagnostic_counts" in path:
        return "diagnostic_counts"
    if "profile_checks" in path:
        return "profile_checks"
    if "metadata_validation_status" in path:
        return "metadata_validity"
    if "profile_evaluation_status" in path:
        return "profile_evaluation"
    if path.endswith("scenario_id"):
        return "scenario_identity"
    if path.endswith("profile_id"):
        return "profile_identity"
    if "loading" in path or "inventory_integrity_status" in path:
        return "evaluation_availability"
    if path.endswith("status"):
        return "validation_status"
    return "entry_order_and_identity"


def _differences(before, after, path=""):
    """Schema-ordered depth-first JSON Pointer differences; list indices are meaningful."""
    changes = []
    def add(location, old, new, classification):
        changes.append({"path": location, "category": _category(location),
                        "baseline_value": deepcopy(old), "current_value": deepcopy(new),
                        "classification": classification})
    if type(before) is dict and type(after) is dict:
        for key in before:
            location = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in after:
                add(location, before[key], None, "removed")
            else:
                changes.extend(_differences(before[key], after[key], location))
        for key in after:
            if key not in before:
                add(path + "/" + key.replace("~", "~0").replace("/", "~1"), None, after[key], "added")
    elif type(before) is list and type(after) is list:
        for index in range(max(len(before), len(after))):
            location = path + "/" + str(index)
            if index >= len(before):
                add(location, None, after[index], "added")
            elif index >= len(after):
                add(location, before[index], None, "removed")
            else:
                changes.extend(_differences(before[index], after[index], location))
    elif type(before) is not type(after) or before != after:
        add(path, before, after, "changed")
    return changes


def compare_reports(batch_report, baseline):
    baseline = baseline_from_document(baseline)
    current = semantic_report(batch_report)
    approved = baseline["approval"]["status"] == "approved"
    differences = _differences(baseline["report"], current) if approved else []
    status = ("changed" if differences else "unchanged") if approved else "not_evaluated"
    def outcomes(report):
        return [{"position": row["position"], "scenario_id": row["scenario_id"],
                 "metadata_validity": row["metadata_validation_status"],
                 "profile_agreement": row["profile_evaluation_status"],
                 "final_status": row["final_status"]} for row in report["entries"]]
    return {"schema_version": 1, "baseline_id": baseline["baseline_id"], "batch_id": current["batch_id"],
        "baseline_approval_status": baseline["approval"]["status"], "comparison_status": status,
        "baseline_report_status": baseline["report"]["overall_status"],
        "current_report_status": current["overall_status"], "difference_count": len(differences),
        "differences": differences, "summary": {
            "reason": "Compared approved semantic snapshot" if approved else "NOT APPROVED: candidate comparison not evaluated",
            "baseline_outcomes": outcomes(baseline["report"]), "current_outcomes": outcomes(current),
            "scope": "Synthetic software reproducibility only; no physical-system performance assessment",
            "limitations": "Approval metadata is a review declaration, not an authenticated signature. Only the documented semantic snapshot is compared."}}


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_html(report):
    body = "<h1>Synthetic Software Regression Report</h1>"
    for key in ("baseline_id", "batch_id", "baseline_approval_status", "comparison_status",
                "baseline_report_status", "current_report_status", "difference_count"):
        body += "<p>" + html_text(key) + ": " + html_text(report[key]) + "</p>"
    columns = ("path", "category", "classification", "baseline_value", "current_value")
    body += '<h2>Semantic differences</h2><table><caption>Ordered semantic changes</caption><thead><tr>'
    body += "".join('<th scope="col">' + html_text(key) + "</th>" for key in columns) + "</tr></thead><tbody>"
    for difference in report["differences"]:
        body += "<tr>" + "".join("<td>" + html_text(json.dumps(difference[key], ensure_ascii=False, allow_nan=False))
                                + "</td>" for key in columns) + "</tr>"
    body += "</tbody></table><h2>Metadata validity and profile agreement</h2><pre>"
    body += html_text(render_json(report["summary"])) + "</pre>"
    return _document(body, title="Synthetic Software Regression Report")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", required=True, metavar="PATH")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", metavar="PATH")
    mode.add_argument("--generate-candidate", action="store_true")
    parser.add_argument("--output", metavar="PATH")
    parser.add_argument("--baseline-id")
    parser.add_argument("--description")
    parser.add_argument("--format", choices=("json", "html"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    if not __debug__:
        parser.error("Run without -O: synthetic validation requires assertion checks")
    if args.generate_candidate:
        if not args.output or not args.baseline_id or not args.description or args.format != "json" or args.strict:
            parser.error("candidate generation requires --output, --baseline-id, --description; JSON only, without --strict")
    elif any(value is not None for value in (args.output, args.baseline_id, args.description)):
        parser.error("candidate options require --generate-candidate")
    try:
        baseline = None if args.generate_candidate else load_baseline(args.baseline)
        batch = run_batch(args.manifest)
        if args.generate_candidate:
            write_candidate(args.output, candidate_baseline(batch, args.baseline_id, args.description))
            return 0
        report = compare_reports(batch, baseline)
        output = render_html(report) if args.format == "html" else render_json(report)
    except (RegressionInputError, BatchInputError) as cause:
        parser.error(str(cause))
    print(output, end="")
    return {"unchanged": 0, "changed": 1, "not_evaluated": 2}[report["comparison_status"]] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
