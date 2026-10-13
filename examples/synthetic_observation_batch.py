"""Explicit, bounded local batch reports; no discovery, writes or services."""

import argparse
import json
from pathlib import Path, PurePosixPath
import sys

from examples.synthetic_observation_profiles import (
    _object, _text, read_json, load_profile, evaluate_profile, metadata_status, combine_status, ProfileLoadError,
)
from examples.synthetic_observation_scenarios import load_scenario, ScenarioLoadError
from examples.synthetic_observation_validation import build_validation_manifest, ValidationInputError
from examples.synthetic_observation_inspector import _document, _text as html_text

MAX_ENTRIES = 32


class BatchInputError(ValueError):
    """Invalid manifest or entry input; entire batch is rejected before output."""


def _relative_path(value, directory):
    _text(value, "entry path", BatchInputError)
    parts = PurePosixPath(value)
    if (parts.is_absolute() or any(part in (".", "..") for part in value.split("/"))
            or value.endswith("/") or ":" in value or "\\" in value or "\x00" in value or "//" in value):
        raise BatchInputError("entry path: require relative path without traversal, URLs or backslashes")
    try:
        resolved = (directory / value).resolve(strict=True)
        resolved.relative_to(directory)
        if not resolved.is_file():
            raise BatchInputError("entry path: require a regular file")
    except (OSError, ValueError, RuntimeError) as cause:
        raise BatchInputError("entry path: missing file or symlink escapes manifest directory") from cause
    return resolved


def load_batch_manifest(path):
    document = read_json(path, error=BatchInputError)
    _object(document, ("schema_version", "batch_id", "description", "entries"), (), "batch", BatchInputError)
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise BatchInputError("schema_version: only version 1 is supported")
    for name in ("batch_id", "description"):
        _text(document[name], name, BatchInputError)
    if type(document["entries"]) is not list or len(document["entries"]) > MAX_ENTRIES:
        raise BatchInputError("entries: require array with at most 32 entries")
    # Validate every entry shape before executing any one entry.
    for index, entry in enumerate(document["entries"]):
        _object(entry, ("scenario",), ("profile",), f"entry {index}", BatchInputError)
        for name, value in entry.items():
            _text(value, f"entry {index}: {name}", BatchInputError)
    return document


def run_batch(path):
    """Prepare the complete batch in memory or raise an indexed input error.

    Status covers inventory/lineage/metadata and declared profile expectations.
    Original schema-v1 manifests remain intact, including unevaluated capabilities.
    """
    document = load_batch_manifest(path)
    try:
        directory = Path(path).resolve(strict=True).parent
    except (OSError, RuntimeError) as cause:
        raise BatchInputError("unable to resolve manifest directory") from cause
    results = []
    for index, entry in enumerate(document["entries"]):
        stage = "scenario_loading"
        try:
            scenario = load_scenario(_relative_path(entry["scenario"], directory))
            stage = "profile_loading"
            profile = None if "profile" not in entry else load_profile(_relative_path(entry["profile"], directory))
            if profile is not None and profile["scenario_id"] != scenario.label:
                raise ProfileLoadError("scenario_id: profile does not match scenario")
            stage = "metadata_validation"
            manifest = build_validation_manifest(scenario)
            stage = "profile_evaluation"
            evaluation = ({"profile_id": None, "scenario_id": scenario.label, "status": "not_evaluated",
                           "checks": [], "failed_expectations": []} if profile is None else
                          evaluate_profile(scenario, profile, manifest=manifest))
        except (ScenarioLoadError, ProfileLoadError, BatchInputError, ValidationInputError) as cause:
            raise BatchInputError(f"entry {index}: {stage}: {cause}") from cause
        integrity = combine_status(check["status"] for check in manifest["invariants"][:3])
        results.append({"position": index, "scenario_id": scenario.label,
                        "profile_id": evaluation["profile_id"], "scenario_loading": "passed",
                        "profile_loading": "not_evaluated" if profile is None else "passed",
                        "metadata_validation_status": metadata_status(manifest),
                        "inventory_integrity_status": integrity,
                        "profile_evaluation_status": evaluation["status"],
                        "diagnostic_counts": manifest["diagnostics"]["severity_counts"],
                        "profile_evaluation": evaluation, "loading_error": None,
                        "final_status": combine_status((integrity, evaluation["status"])),
                        "scenario_validation": manifest})
    return {"schema_version": 1, "batch_id": document["batch_id"], "description": document["description"],
            "scope": "Declared synthetic software expectations and existing inventory/metadata checks only",
            "entries": results, "overall_status": combine_status(row["final_status"] for row in results),
            "limitations": ["Profile agreement does not establish metadata validity or physical-system readiness.",
                            "Independent reconstruction and built-in checks remain as reported in each original manifest.",
                            "Clock domains are not aligned; repeated references are not independent acquisitions."]}


def render_batch_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_batch_html(report):
    columns = ("position", "scenario_id", "profile_id", "metadata_validation_status",
               "profile_evaluation_status", "final_status")
    body = ("<h1>Synthetic Software Batch Validation</h1><p>Batch: " + html_text(report["batch_id"])
            + "</p><p>" + html_text(report["description"]) + "</p><p>Overall status: "
            + html_text(report["overall_status"]) + "</p><p>" + html_text(report["scope"]) + "</p>"
            + "<table><caption>Metadata validity and profile agreement are separate results</caption><thead><tr>"
            + "".join('<th scope="col">' + html_text(name) + "</th>" for name in columns) + "</tr></thead><tbody>")
    for row in report["entries"]:
        body += "<tr>" + "".join("<td>" + html_text(row[name]) + "</td>" for name in columns) + "</tr>"
    body += "</tbody></table>"
    for row in report["entries"]:
        body += "<h2>Entry " + html_text(row["position"]) + ": " + html_text(row["scenario_id"]) + "</h2>"
        body += "<h3>Diagnostic counts</h3><pre>" + html_text(json.dumps(row["diagnostic_counts"], indent=2)) + "</pre>"
        body += "<h3>Declared expectations and failures</h3><pre>" + html_text(
            json.dumps(row["profile_evaluation"], indent=2, ensure_ascii=False, allow_nan=False)) + "</pre>"
        body += "<details><summary>Original scenario validation manifest</summary><pre>" + html_text(
            json.dumps(row["scenario_validation"], indent=2, ensure_ascii=False, allow_nan=False)) + "</pre></details>"
    body += "<h2>Limitations</h2><ul>" + "".join("<li>" + html_text(item) + "</li>" for item in report["limitations"]) + "</ul>"
    return _document(body, title="Synthetic Software Batch Validation")


def main(argv=None):
    if not __debug__:
        raise RuntimeError("Run without -O: synthetic validation requires assertion checks")
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", required=True, metavar="PATH")
    parser.add_argument("--format", choices=("json", "html"), default="json")
    parser.add_argument("--strict", action="store_true", help="exit 0 passed, 1 failed, 2 not_evaluated")
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.manifest)
        output = render_batch_html(report) if args.format == "html" else render_batch_json(report)
    except BatchInputError as cause:
        parser.error(str(cause))
    print(output, end="")
    return {"passed": 0, "failed": 1, "not_evaluated": 2}[report["overall_status"]] if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
