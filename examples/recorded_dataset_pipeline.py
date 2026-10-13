"""Offline coordination of independent metadata quality and recording byte checks."""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys

from examples import recorded_sensor_metadata as metadata
from examples import recorded_sensor_integrity as integrity
from examples.synthetic_observation_profiles import _object
from examples.synthetic_observation_inspector import _document, _text as html_text

REPORT_FIELDS = ("schema_version", "dataset_id", "manifest_id", "metadata_status", "integrity_status",
                 "overall_status", "metadata_summary", "integrity_summary", "source_inventory",
                 "diagnostics", "unevaluated_checks")


class PipelineInputError(ValueError):
    """Rejected explicit input, distinct from reportable stage unavailability."""


def combine_status(metadata_status, integrity_status):
    if metadata_status not in ("passed", "failed", "not_evaluated"):
        raise PipelineInputError("unsupported metadata stage status")
    if integrity_status not in ("verified", "mismatch", "not_evaluated"):
        raise PipelineInputError("unsupported integrity stage status")
    if metadata_status == "failed" or integrity_status == "mismatch":
        return "failed"
    if "not_evaluated" in (metadata_status, integrity_status):
        return "not_evaluated"
    return "passed"


def _unavailable(code, explanation):
    return {"report": None, "unavailable_reason": {"code": code, "explanation": explanation}}


def run_pipeline(dataset_path, manifest_path):
    """Load each input once, run each stage once, retain both complete owned reports.

    NotImplementedError denotes explicit stage unavailability. Recording-stage
    OSError denotes incomplete I/O; other unexpected exceptions remain visible.
    Invalid declarations or associations abort without a partial unified report.
    """
    try:
        path = Path(dataset_path).resolve(strict=True)
    except (OSError, ValueError, TypeError, RuntimeError) as cause:
        raise PipelineInputError("dataset loading: unable to resolve local JSON path") from cause
    try:
        dataset = metadata.load_dataset(path)
    except metadata.RecordedInputError as cause:
        raise PipelineInputError("dataset loading: " + str(cause)) from cause
    try:
        manifest = integrity.load_manifest(manifest_path)
    except integrity.IntegrityInputError as cause:
        raise PipelineInputError("manifest loading: " + str(cause)) from cause
    try:
        metadata_summary = {"report": metadata.validate_dataset(dataset), "unavailable_reason": None}
    except metadata.RecordedInputError as cause:
        raise PipelineInputError("metadata validation: " + str(cause)) from cause
    except NotImplementedError:
        metadata_summary = _unavailable("STAGE_UNAVAILABLE", "Metadata validation implementation is unavailable.")
    try:
        integrity_summary = {"report": integrity.verify_dataset(dataset, manifest, path.parent, path), "unavailable_reason": None}
    except integrity.IntegrityInputError as cause:
        raise PipelineInputError("integrity input: " + str(cause)) from cause
    except NotImplementedError:
        integrity_summary = _unavailable("STAGE_UNAVAILABLE", "Recording integrity implementation is unavailable.")
    except OSError:
        integrity_summary = _unavailable("STAGE_IO_UNAVAILABLE", "Recording integrity I/O did not complete.")
    metadata_summary, integrity_summary = deepcopy(metadata_summary), deepcopy(integrity_summary)
    meta, files = metadata_summary["report"], integrity_summary["report"]
    metadata_status = "not_evaluated" if meta is None else meta["status"]
    integrity_status = "not_evaluated" if files is None else files["verification_status"]
    overall = combine_status(metadata_status, integrity_status)
    references = {source.source_id: source.recording_reference for source in dataset.sources}
    diagnostics, pending = [], []
    def diagnostic(stage, code, severity, source_id=None, record_id=None, record_index=None,
                   entry_index=None, explanation=None):
        diagnostics.append({"stage": stage, "code": code, "severity": severity, "source_id": source_id,
            "record_id": record_id, "record_index": record_index, "entry_index": entry_index,
            "recording_reference": references.get(source_id), "explanation": explanation})
    for stage, summary in (("metadata", metadata_summary), ("integrity", integrity_summary)):
        unavailable = summary["unavailable_reason"]
        if unavailable is not None:
            diagnostic(stage, unavailable["code"], "Warning", explanation=unavailable["explanation"])
            pending.append({"stage": stage, "check": "stage_execution", "required": True,
                "status": "not_evaluated", "reason": deepcopy(unavailable)})
        elif stage == "metadata":
            for item in meta["diagnostics"]:
                diagnostic(stage, item["code"], item["severity"], item["source_id"], item["record_id"],
                           item["record_index"], explanation=item["explanation"])
            pending.extend({"stage": stage, **deepcopy(item)} for item in meta["unevaluated_checks"])
        else:
            for item in files["diagnostics"]:
                index = item["entry_index"]
                severity = "Invalid" if index is not None and files["entries"][index]["integrity_status"] == "mismatch" else "Warning"
                diagnostic(stage, item["code"], severity, item["source_id"], entry_index=index,
                           explanation="Phase 59 integrity diagnostic: " + item["code"])
            for index, row in enumerate(files["entries"]):
                if row["integrity_status"] == "not_evaluated":
                    pending.append({"stage": stage, "check": "recording_integrity", "required": True,
                        "source_id": row["source_id"], "entry_index": index, "status": "not_evaluated",
                        "diagnostic_codes": deepcopy(row["diagnostic_codes"])})
            if not files["entries"]:
                pending.append({"stage": stage, "check": "recording_inventory", "required": True,
                    "status": "not_evaluated", "diagnostic_codes": ["NO_FILES"]})
    file_rows = {} if files is None else {row["source_id"]: row for row in files["entries"]}
    inventory = []
    for source in dataset.sources:
        key = source.source_id
        row = file_rows.get(key)
        inventory.append({**asdict(source), "record_count": None if meta is None else meta["per_source_counts"][key],
            "metadata_diagnostic_codes": [] if meta is None else [d["code"] for d in meta["diagnostics"] if d["source_id"] == key],
            "metadata_stage_available": meta is not None,
            "integrity_status": "not_evaluated" if row is None else row["integrity_status"],
            "integrity_diagnostic_codes": [] if row is None else deepcopy(row["diagnostic_codes"])})
    return {"schema_version": 1, "dataset_id": dataset.dataset_id, "manifest_id": manifest.manifest_id,
        "metadata_status": metadata_status, "integrity_status": integrity_status, "overall_status": overall,
        "metadata_summary": metadata_summary, "integrity_summary": integrity_summary,
        "source_inventory": inventory, "diagnostics": diagnostics, "unevaluated_checks": pending}


def _report_shape(report):
    _object(report, REPORT_FIELDS, (), "pipeline report", PipelineInputError)
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise PipelineInputError("pipeline report: require schema_version integer 1")
    if report["overall_status"] != combine_status(report["metadata_status"], report["integrity_status"]):
        raise PipelineInputError("pipeline report: inconsistent overall status")
    for key in ("metadata_summary", "integrity_summary"):
        _object(report[key], ("report", "unavailable_reason"), (), key, PipelineInputError)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def render_json(report):
    """Canonical document: UTF-8-compatible sorted keys, compact JSON, one final LF."""
    _report_shape(report)
    return _json(report)


def render_html(report):
    _report_shape(report)
    body = "<h1>Unified Recorded Dataset Validation</h1>"
    for key in ("dataset_id", "manifest_id", "overall_status", "metadata_status", "integrity_status"):
        body += "<p>" + html_text(key) + ": " + html_text(report[key]) + "</p>"
    body += "<p>Metadata quality and byte integrity remain independent. Matching checksums do not authenticate origin or establish physical accuracy.</p>"
    columns = ("source_id", "source_kind", "clock_domain", "recording_reference", "record_count",
               "metadata_stage_available", "metadata_diagnostic_codes", "integrity_status", "integrity_diagnostic_codes")
    body += '<h2>Source outcomes</h2><table><caption>Dataset source order; metadata diagnostics and file outcomes</caption><thead><tr>'
    body += "".join('<th scope="col">' + html_text(key) + "</th>" for key in columns) + "</tr></thead><tbody>"
    for row in report["source_inventory"]:
        body += "<tr>" + "".join("<td>" + html_text(row[key]) + "</td>" for key in columns) + "</tr>"
    body += "</tbody></table><h2>Stage diagnostics</h2><pre>" + html_text(_json(report["diagnostics"])) + "</pre>"
    body += "<h2>Checks not evaluated</h2><pre>" + html_text(_json(report["unevaluated_checks"])) + "</pre>"
    body += "<h2>Independent stage reports</h2>"
    for key in ("metadata_summary", "integrity_summary"):
        body += "<details><summary>" + html_text(key) + "</summary><pre>" + html_text(_json(report[key])) + "</pre></details>"
    return _document(body, title="Unified Recorded Dataset Validation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dataset", required=True, metavar="PATH")
    parser.add_argument("--manifest", required=True, metavar="PATH")
    parser.add_argument("--format", choices=("json", "html"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_pipeline(args.dataset, args.manifest)
        output = render_html(report) if args.format == "html" else render_json(report)
    except PipelineInputError as cause:
        parser.error(str(cause))
    print(output, end="")
    return {"passed": 0, "failed": 1, "not_evaluated": 2}[report["overall_status"]] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
