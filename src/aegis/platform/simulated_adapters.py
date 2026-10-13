"""Pure adapters for supplied aerial, ground and third-party fixture values."""

from aegis.platform.contracts import Device, SentinelMonitor, PlatformContractError, from_document


def _sentinel(device, monitor, category):
    if type(device) is not Device or type(monitor) is not SentinelMonitor:
        raise PlatformContractError("adapter: require Device and SentinelMonitor contracts")
    if device.device_type != category or monitor.sentinel_category != category:
        raise PlatformContractError("adapter: wrong synthetic Sentinel category")
    if monitor.device_id != device.device_id or monitor.connectivity != device.connection_status:
        raise PlatformContractError("adapter: inconsistent device or connectivity")
    if {s.source_id for s in monitor.sensors} != {s.source_id for s in device.sources}:
        raise PlatformContractError("adapter: inconsistent source inventory")
    return device, monitor


def aerial_sentinel_from_fixture(device_document, monitor_document):
    """Convert closed supplied documents only; unknown measurements stay unknown."""
    return _sentinel(from_document(Device, device_document), from_document(SentinelMonitor, monitor_document), "aerial")


def ground_sentinel_from_fixture(device_document, monitor_document):
    return _sentinel(from_document(Device, device_document), from_document(SentinelMonitor, monitor_document), "ground")


def third_party_from_fixture(device_document):
    device = from_document(Device, device_document)
    if device.category != "third_party":
        raise PlatformContractError("adapter: require third_party category")
    return device
