"""Deterministic local scenario loading and content identity, without assets or physics."""
from hashlib import sha256
from pathlib import Path
from .contracts import MAX_BYTES, Scenario, canonical_bytes, load_contract


def load_scenario(data: bytes) -> Scenario:
    return load_contract(Scenario, data)


def read_scenario(path: str | Path) -> Scenario:
    with Path(path).open('rb') as stream:
        return load_scenario(stream.read(MAX_BYTES + 1))


def scenario_digest(scenario: Scenario) -> str:
    return sha256(canonical_bytes(scenario)).hexdigest()
