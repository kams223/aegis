"""Strict immutable platform schemas across every contract group."""

from dataclasses import FrozenInstanceError, fields, replace
import json

import pytest

from aegis.platform import contracts as c
from aegis.platform.snapshot import PlatformSnapshot
from examples.platform_snapshot_demo import demo_snapshot


def samples():
    snapshot = demo_snapshot()
    found = {}
    def visit(value):
        if isinstance(value, c.Contract):
            found[type(value)] = value
            for field in fields(value):
                visit(getattr(value, field.name))
        elif type(value) is tuple:
            for item in value:
                visit(item)
    visit(snapshot)
    found[c.ValidationEvidence] = c.ValidationEvidence(evidence_id="validation", dataset_id="dataset",
        metadata_status="failed", integrity_status="verified")
    return tuple(found.values())


SAMPLES = samples()


@pytest.mark.parametrize('value', SAMPLES, ids=lambda v:type(v).__name__)
def test_every_contract_closed_roundtrip_immutable_and_owned(value):
    doc = c.to_document(value)
    assert c.from_document(type(value), doc) == value
    assert c.parse_json(type(value), json.dumps(doc).encode()) == value
    with pytest.raises(FrozenInstanceError):
        value.schema_version = 2
    doc['schema_version'] = 99
    assert value.schema_version == 1


@pytest.mark.parametrize('value', SAMPLES, ids=lambda v:type(v).__name__)
@pytest.mark.parametrize('case', ['missing', 'extra', 'version', 'bool_version', 'float_version', 'wrong_type'])
def test_every_contract_rejects_malformed_document(value, case):
    doc = c.to_document(value)
    if case == 'missing':
        del doc[next(k for k in doc if k != 'schema_version')]
    elif case == 'extra':
        doc['unexpected'] = None
    elif case == 'wrong_type':
        doc[next(k for k in doc if k != 'schema_version')] = {}
    else:
        doc['schema_version'] = {'version':2,'bool_version':True,'float_version':1.0}[case]
    with pytest.raises(c.PlatformContractError):
        c.from_document(type(value), doc)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), True, '1', None, 10**19])
def test_timestamp_numeric_integrity(value):
    with pytest.raises(c.PlatformContractError):
        c.Timestamp(value=value, unit='s', clock_domain='demo:clock')


@pytest.mark.parametrize('unit', ['seconds', '', None, True])
def test_timestamp_requires_explicit_supported_unit(unit):
    with pytest.raises(c.PlatformContractError):
        c.Timestamp(value=1, unit=unit, clock_domain='demo:clock')


def test_timestamp_values_are_not_aligned_or_converted():
    a = c.Timestamp(value=-1.5, unit='ms', clock_domain='clock:a')
    b = c.Timestamp(value=-1.5, unit='s', clock_domain='clock:b')
    assert a != b and c.to_document(a)['value'] == -1.5


@pytest.mark.parametrize('path', ['/tmp/a', '../a', 'a/../b', './a', 'https://example.com/x',
    'file://a', 'C:/a', 'a\\b', 'a//b', 'a/', '', 'a\x00b', 'a%2fb', 'a?b', 'a#b', 'x'*257])
def test_safe_lexical_evidence_references(path):
    with pytest.raises(c.PlatformContractError):
        c.EvidenceReference(evidence_id='ev', source_id='source', kind='camera_recording', local_path=path, dataset_id=None)


def test_lexical_reference_does_not_require_or_open_file():
    value = c.EvidenceReference(evidence_id='ev', source_id='source', kind='camera_recording',
                              local_path='not-created/recording.txt', dataset_id=None)
    assert value.local_path == 'not-created/recording.txt'
    with pytest.raises(c.PlatformContractError):
        replace(value, kind='dataset_report')


@pytest.mark.parametrize('category', ['aegis_native', 'third_party', 'simulated'])
@pytest.mark.parametrize('device_type', ['aerial', 'ground', 'other'])
def test_device_categories_independent_of_device_type(category, device_type):
    device = demo_snapshot().registry.devices[0]
    assert replace(device, category=category, device_type=device_type).category == category


def test_device_registry_preserves_order_and_rejects_duplicate_and_wrong_owned_sources():
    devices = demo_snapshot().registry.devices
    assert c.build_registry(tuple(reversed(devices))).devices == tuple(reversed(devices))
    with pytest.raises(c.PlatformContractError):
        c.build_registry((devices[0], devices[0]))
    with pytest.raises(c.PlatformContractError):
        replace(devices[0], sources=(replace(devices[0].sources[0], device_id='other'),))
    with pytest.raises(c.PlatformContractError):
        replace(devices[0], sources=devices[0].sources * 2)
    with pytest.raises(c.PlatformContractError):
        c.build_registry(list(devices))
    with pytest.raises(c.PlatformContractError):
        c.build_registry(({},))
    shared = replace(devices[1].sources[0], source_id=devices[0].sources[0].source_id)
    with pytest.raises(c.PlatformContractError):
        c.build_registry((devices[0], replace(devices[1], sources=(shared,))))


@pytest.mark.parametrize('name', ['dispatch', 'flight_control', 'lock_target', 'network_probe', 'unknown'])
def test_only_declarative_read_only_capabilities(name):
    with pytest.raises(c.PlatformContractError):
        c.Capability(name=name, support='supported')


def test_unsupported_capability_explicit_and_duplicate_rejected():
    declared = c.Capability(name='camera_evidence', support='unsupported')
    assert declared.support == 'unsupported'
    device = demo_snapshot().registry.devices[0]
    with pytest.raises(c.PlatformContractError):
        replace(device, capabilities=(declared, declared))
    with pytest.raises(c.PlatformContractError):
        replace(declared, support=True)


@pytest.mark.parametrize('value', ['connected', 'live', True, None])
def test_no_live_connectivity_contract(value):
    with pytest.raises(c.PlatformContractError):
        replace(demo_snapshot().registry.devices[0], connection_status=value)


def test_observation_requires_explicit_uncertainty_without_geometry_or_threat_fields():
    obs = demo_snapshot().observations[0]
    for quality in ('missing', 'uncertain'):
        with pytest.raises(c.PlatformContractError):
            replace(obs, quality=quality, uncertainty_note=None)
        assert replace(obs, quality=quality, uncertainty_note='Not measured.').quality == quality
    doc = c.to_document(obs)
    for field in ('coordinates', 'target_id', 'threat_score', 'trajectory'):
        with pytest.raises(c.PlatformContractError):
            c.from_document(c.Observation, {**doc, field:0})


@pytest.mark.parametrize('battery', [True, -1, 101, float('nan'), float('inf'), '50'])
def test_sentinel_battery_strict_bounds(battery):
    with pytest.raises(c.PlatformContractError):
        replace(demo_snapshot().sentinels[0], battery_percent=battery)


@pytest.mark.parametrize('battery', [None, 0, 100, 0.5])
def test_sentinel_missing_and_declared_battery(battery):
    assert replace(demo_snapshot().sentinels[0], battery_percent=battery).battery_percent == battery


def test_sentinel_sensor_duplicate_rejected():
    monitor = demo_snapshot().sentinels[0]
    with pytest.raises(c.PlatformContractError):
        replace(monitor, sensors=monitor.sensors * 2)


@pytest.mark.parametrize('action', ['send_drone_command', 'dispatch_sentinel', 'lock_target', 'allocate_interceptor',
    'transmit_coordinates', 'initiate_engagement', 'change_settings', 'exec', 'fetch_url', 'delete_file'])
def test_mutating_or_unsupported_copilot_actions_rejected(action):
    with pytest.raises(c.PlatformContractError):
        replace(demo_snapshot().investigation_requests[0], action=action)


@pytest.mark.parametrize('previous,new', [('reviewed','under_review'),('dismissed','reviewed'),
    ('under_review','unreviewed'),('unreviewed','unreviewed'),('under_review','under_review')])
def test_review_transition_rejection(previous, new):
    with pytest.raises(c.PlatformContractError):
        replace(demo_snapshot().review_history[0], previous_status=previous, new_status=new)


def test_request_reference_counts_and_ids():
    request = demo_snapshot().investigation_requests[0]
    for refs in ((), ('a','b'), ('bad/id',)):
        with pytest.raises(c.PlatformContractError):
            replace(request, reference_ids=refs)
    for refs in (('a',), ('a','a')):
        with pytest.raises(c.PlatformContractError):
            replace(request, action='compare_validation_results', reference_ids=refs)


@pytest.mark.parametrize('text', ['', ' ', 'x'*129, 'bad/id', 'bad\x00id', '\ud800'])
def test_identifier_bounds_and_encoding(text):
    with pytest.raises(c.PlatformContractError):
        replace(demo_snapshot().registry.devices[0], device_id=text)


def test_text_collection_and_nested_type_bounds():
    snap = demo_snapshot()
    with pytest.raises(c.PlatformContractError):
        replace(snap.observations[0], annotation='x'*1025)
    with pytest.raises(c.PlatformContractError):
        replace(snap.registry.devices[0], capabilities=({},))
    with pytest.raises(c.PlatformContractError):
        replace(snap.registry.devices[0], capabilities=(snap.registry.devices[0].capabilities[0],)*257)
    with pytest.raises(c.PlatformContractError):
        replace(snap.observations[0], timestamp={'value':0})


@pytest.mark.parametrize('payload', [b'\xff', b'{', b'{"schema_version":1,"schema_version":1}',
    b'{"schema_version":NaN}', b'{"schema_version":Infinity}', b'['*1500+b']'*1500, b' '* (c.MAX_JSON_BYTES+1)])
def test_bounded_strict_json(payload):
    with pytest.raises(c.PlatformContractError):
        c.parse_json(PlatformSnapshot, payload)


def test_parse_requires_bytes_and_document_requires_registered_type():
    with pytest.raises(c.PlatformContractError):
        c.parse_json(c.Timestamp, '{}')
    with pytest.raises(c.PlatformContractError):
        c.from_document(dict, {})
    with pytest.raises(c.PlatformContractError):
        c.to_document({})
