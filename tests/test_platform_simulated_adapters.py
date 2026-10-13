"""Supplied fixture adapters remain immutable and offline."""
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from aegis.platform import contracts as c
from aegis.platform import simulated_adapters as a
from examples.platform_snapshot_demo import demo_snapshot
from aegis.platform.snapshot import snapshot_document


@pytest.mark.parametrize('index,adapter',[(0,a.aerial_sentinel_from_fixture),(1,a.ground_sentinel_from_fixture)])
def test_sentinel_adapter_roundtrip_no_mutation(index,adapter):
    doc=snapshot_document(demo_snapshot());device=doc['registry']['devices'][index];monitor=doc['sentinels'][index]
    before=deepcopy((device,monitor));result=adapter(device,monitor)
    assert c.to_document(result[0])==device and c.to_document(result[1])==monitor
    assert (device,monitor)==before and result[1].battery_percent is None
    assert all(s.status=='unknown' for s in result[1].sensors)
    device['device_id']='modified'
    assert result[0].device_id!='modified'
    with pytest.raises(FrozenInstanceError):result[1].battery_percent=100


def test_third_party_device_has_no_implicit_monitor_or_acquisition():
    doc=snapshot_document(demo_snapshot())['registry']['devices'][2]
    result=a.third_party_from_fixture(doc)
    assert result.category=='third_party' and result.connection_status=='offline'
    assert any(c.name=='camera_evidence' and c.support=='unsupported' for c in result.capabilities)
    with pytest.raises(c.PlatformContractError):a.third_party_from_fixture({**doc,'category':'simulated'})


@pytest.mark.parametrize('case',['wrong_category','identity','connectivity','inventory','unknown_field','version','wrong_type'])
def test_adapter_rejects_inconsistent_or_malformed_fixtures(case):
    doc=snapshot_document(demo_snapshot());device=doc['registry']['devices'][0];monitor=doc['sentinels'][0]
    if case=='wrong_category':monitor['sentinel_category']='ground'
    elif case=='identity':monitor['device_id']='other'
    elif case=='connectivity':monitor['connectivity']='recorded'
    elif case=='inventory':monitor['sensors']=[]
    elif case=='unknown_field':device['command']='connect'
    elif case=='version':device['schema_version']=2
    else:monitor['battery_percent']=True
    with pytest.raises(c.PlatformContractError):a.aerial_sentinel_from_fixture(device,monitor)


def test_wrong_ground_category_and_bounds():
    doc=snapshot_document(demo_snapshot())
    with pytest.raises(c.PlatformContractError):a.ground_sentinel_from_fixture(doc['registry']['devices'][0],doc['sentinels'][0])
    third=doc['registry']['devices'][2]
    with pytest.raises(c.PlatformContractError):a.third_party_from_fixture({**third,'device_id':'x'*129})
    with pytest.raises(c.PlatformContractError):a.third_party_from_fixture({**third,'capabilities':third['capabilities']*257})
