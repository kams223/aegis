"""Isolated offline platform contracts, without device drivers or control APIs."""

from aegis.platform.snapshot import PlatformSnapshot, build_snapshot, snapshot_from_document, snapshot_document
from aegis.platform.investigation import investigate

__all__ = ("PlatformSnapshot", "build_snapshot", "snapshot_from_document", "snapshot_document", "investigate")
