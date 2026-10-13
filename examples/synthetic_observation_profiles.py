"""Closed declarative profiles for synthetic software metadata checks only."""

from copy import deepcopy
import json
from math import isfinite
from pathlib import Path

from examples.synthetic_observation_validation import build_validation_manifest

MAX_BYTES = 1024 * 1024
SEVERITIES = ("Informational", "Warning", "Invalid")
EXPECTATIONS = ("source_count", "observation_count", "delivery_count", "repeated_reference_count",
                "source_clock_domains", "diagnostic_counts", "metadata_validity")


class ProfileLoadError(ValueError):
    """Invalid profile input, distinct from an evaluated expectation mismatch."""


def _object(value, required, optional, location, error=ProfileLoadError):
    if type(value) is not dict:
        raise error(location + ": expected object")
    if set(required) - value.keys():
        raise error(location + ": missing required fields")
    if value.keys() - set(required) - set(optional):
        raise error(location + ": unsupported fields")


def _text(value, location, error=ProfileLoadError):
    if type(value) is not str or not value.strip():
        raise error(location + ": expected nonblank string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as cause:
        raise error(location + ": invalid UTF-8 text") from cause
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileLoadError("JSON: duplicate object member")
        result[key] = value
    return result


def _constant(value):
    raise ProfileLoadError("JSON: non-finite number")


def _finite_tree(value):
    if type(value) is float and not isfinite(value):
        raise ProfileLoadError("JSON: non-finite number")
    if type(value) is dict:
        for child in value.values():
            _finite_tree(child)
    elif type(value) is list:
        for child in value:
            _finite_tree(child)


def read_json(path, *, error=ProfileLoadError):
    """Bounded UTF-8 input, closed duplicate/finite rules; no writes."""
    try:
        with Path(path).open("rb") as stream:
            contents = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError) as cause:
        raise error("unable to read local JSON file") from cause
    if len(contents) > MAX_BYTES:
        raise error("JSON file exceeds 1 MiB limit")
    try:
        value = json.loads(contents.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        _finite_tree(value)
    except ProfileLoadError as cause:
        raise error(str(cause)) from cause
    except (ValueError, RecursionError) as cause:
        raise error("invalid UTF-8 JSON") from cause
    return value


def profile_from_document(document):
    """Validate and detach a closed profile; expectation order is schema order."""
    _object(document, ("schema_version", "profile_id", "scenario_id", "description", "expectations"), (), "profile")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ProfileLoadError("schema_version: only version 1 is supported")
    for name in ("profile_id", "scenario_id", "description"):
        _text(document[name], name)
    values = document["expectations"]
    _object(values, (), EXPECTATIONS, "expectations")
    for key, value in values.items():
        if key in EXPECTATIONS[:4]:
            if type(value) is not int or value < 0:
                raise ProfileLoadError(key + ": expected nonnegative integer, not bool")
        elif key == "source_clock_domains":
            if type(value) is not list or len(value) > 256:
                raise ProfileLoadError(key + ": expected bounded array")
            for domain in value:
                _text(domain, key)
            if len(set(value)) != len(value):
                raise ProfileLoadError(key + ": duplicate clock domain")
        elif key == "diagnostic_counts":
            _object(value, (), SEVERITIES, key)
            for count in value.values():
                if type(count) is not int or count < 0:
                    raise ProfileLoadError(key + ": expected nonnegative integer counts")
        elif type(value) is not str or value not in ("passed", "failed", "not_evaluated"):
            raise ProfileLoadError(key + ": unsupported metadata status")
    return {"schema_version": 1, **{name: document[name] for name in ("profile_id", "scenario_id", "description")},
            "expectations": {key: deepcopy(values[key]) for key in EXPECTATIONS if key in values}}


def load_profile(path):
    return profile_from_document(read_json(path))


def combine_status(statuses):
    values = tuple(statuses)
    return "failed" if "failed" in values else "not_evaluated" if not values or "not_evaluated" in values else "passed"


def metadata_status(manifest):
    """Status of the existing explicitly scoped metadata diagnostic check."""
    return next(check["status"] for check in manifest["invariants"] if check["id"] == "checked_metadata_contracts")


def evaluate_profile(scenario, profile, *, manifest=None):
    """Only supplied expectations are evaluated; no fixed-fixture profile applies.

    A passed profile is agreement with declared data, never metadata validity.
    The caller may reuse the existing validation manifest for this same scenario.
    """
    profile = profile_from_document(profile)
    if profile["scenario_id"] != scenario.label:
        raise ProfileLoadError("scenario_id: profile does not match scenario")
    if manifest is None:
        manifest = build_validation_manifest(scenario)
    if manifest["scenario_label"] != scenario.label:
        raise ProfileLoadError("manifest: scenario label mismatch")
    inventory = manifest["source_inventory"]["batches"]
    domains = None if inventory is None else list(dict.fromkeys(
        observation["clock_domain"] for batch in inventory for observation in batch["observations"]
        if type(observation["clock_domain"]) is str and observation["clock_domain"].strip()))
    actual = {"source_count": None if inventory is None else len(inventory),
              "observation_count": None if inventory is None else sum(len(batch["observations"]) for batch in inventory),
              "delivery_count": manifest["counts"]["history_occurrences"],
              "repeated_reference_count": manifest["counts"]["repeated_reference_occurrences"],
              "source_clock_domains": domains, "diagnostic_counts": manifest["diagnostics"]["severity_counts"],
              "metadata_validity": metadata_status(manifest)}
    checks = []
    for key in EXPECTATIONS:
        if key not in profile["expectations"]:
            continue
        expected = profile["expectations"][key]
        value = actual[key]
        if key == "diagnostic_counts":
            # A partial severity declaration checks only those explicitly present.
            expected = {severity: expected[severity] for severity in SEVERITIES if severity in expected}
            value = {severity: value[severity] for severity in expected}
        status = "not_evaluated" if value is None or (key == "diagnostic_counts" and not expected) else (
            "passed" if value == expected else "failed")
        checks.append({"id": key, "status": status, "expected": deepcopy(expected), "actual": deepcopy(value)})
    return {"profile_id": profile["profile_id"], "scenario_id": profile["scenario_id"],
            "status": combine_status(check["status"] for check in checks), "checks": checks,
            "failed_expectations": [deepcopy(check) for check in checks if check["status"] == "failed"]}
