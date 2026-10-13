"""Declarative profile schema, explicit ordering and metadata integrity semantics."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from examples import synthetic_observation_profiles as profiles
from examples.synthetic_observation_scenarios import load_scenario
from examples.synthetic_observation_validation import build_validation_manifest

ROOT = Path(__file__).resolve().parents[1]


def fixture(name='baseline'):
    return load_scenario(ROOT / 'examples/scenarios' / (name + '.json'))


def profile(name='baseline'):
    return profiles.load_profile(ROOT / 'examples/profiles' / (name + '.json'))


@pytest.mark.parametrize('name,metadata', [('baseline','passed'), ('repeated_delivery','passed'), ('metadata_edge_cases','failed')])
def test_reviewed_profiles_match_without_concealing_invalid_metadata(name, metadata):
    scenario, declared = fixture(name), profile(name)
    before, source_refs = asdict(scenario), scenario.history.records
    original = deepcopy(declared)
    a = profiles.evaluate_profile(scenario, declared)
    b = profiles.evaluate_profile(scenario, profile(name))
    assert a == b and a['status'] == 'passed' and a['failed_expectations'] == []
    assert [check['id'] for check in a['checks']] == list(profiles.EXPECTATIONS)
    assert a['checks'][-1]['actual'] == metadata
    assert profiles.metadata_status(build_validation_manifest(scenario)) == metadata
    assert asdict(scenario) == before and scenario.history.records is source_refs and declared == original


def test_order_is_schema_order_not_json_member_order_and_partial_severities():
    declared = profile()
    declared['expectations'] = dict(reversed(list(declared['expectations'].items())))
    declared['expectations']['diagnostic_counts'] = {'Invalid': 0, 'Informational': 6}
    results = profiles.evaluate_profile(fixture(), declared)
    assert [check['id'] for check in results['checks']] == list(profiles.EXPECTATIONS)
    assert list(results['checks'][-2]['expected']) == ['Informational', 'Invalid']


def test_only_declared_expectations_and_no_implicit_builtin_profile():
    scenario = fixture()
    declared = profile()
    declared['expectations'] = {'delivery_count': 99}
    result = profiles.evaluate_profile(scenario, declared)
    assert result['status'] == 'failed'
    assert result['checks'] == result['failed_expectations'] == [
        {'id': 'delivery_count', 'status': 'failed', 'expected': 99, 'actual': 2}]
    declared['expectations'] = {}
    assert profiles.evaluate_profile(scenario, declared)['status'] == 'not_evaluated'
    declared['expectations'] = {'diagnostic_counts': {}}
    assert profiles.evaluate_profile(scenario, declared)['status'] == 'not_evaluated'


def test_missing_inventory_and_empty_expected_domains_are_distinct():
    scenario = replace(fixture(), source_batches=None)
    declared = profile()
    declared['expectations'] = {'source_count': 2, 'source_clock_domains': []}
    result = profiles.evaluate_profile(scenario, declared)
    assert result['status'] == 'not_evaluated'
    assert all(check['actual'] is None for check in result['checks'])


def test_profile_and_supplied_manifest_mismatch_is_input_error():
    declared = profile()
    declared['scenario_id'] = 'unrelated'
    with pytest.raises(profiles.ProfileLoadError, match='does not match'):
        profiles.evaluate_profile(fixture(), declared)
    manifest = build_validation_manifest(fixture())
    manifest['scenario_label'] = 'unrelated'
    with pytest.raises(profiles.ProfileLoadError, match='label mismatch'):
        profiles.evaluate_profile(fixture(), profile(), manifest=manifest)


@pytest.mark.parametrize('field,value', [
    ('schema_version',2), ('schema_version',True), ('schema_version',1.0),
    ('profile_id',''), ('scenario_id',None), ('description',[]), ('description',chr(0xD800)),
    ('expectations',[]), ('expectations',{'unknown':0}),
    ('expectations',{'source_count':True}), ('expectations',{'observation_count':-1}),
    ('expectations',{'delivery_count':1.0}), ('expectations',{'repeated_reference_count':float('inf')}),
    ('expectations',{'source_clock_domains':'clock'}), ('expectations',{'source_clock_domains':['a','a']}),
    ('expectations',{'source_clock_domains':['']}), ('expectations',{'source_clock_domains':[0]}),
    ('expectations',{'source_clock_domains':['a']*257}),
    ('expectations',{'diagnostic_counts':{'Error':1}}), ('expectations',{'diagnostic_counts':{'Invalid':True}}),
    ('expectations',{'diagnostic_counts':{'Warning':float('nan')}}),
    ('expectations',{'metadata_validity':'valid'}), ('expectations',{'metadata_validity':[]}),
])
def test_profile_rejects_bad_structure_without_mutating_document(field,value):
    declared = profile()
    declared[field] = value
    before = deepcopy(declared)
    with pytest.raises(profiles.ProfileLoadError):
        profiles.profile_from_document(declared)
    # NaN does not equal itself; compare stable repr for this intentionally invalid tree.
    assert repr(declared) == repr(before)


@pytest.mark.parametrize('raw', [b'{', b'[]', b'"\xff"', b'{"a":1,"a":2}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e309}',
    b'['*2000, b'1'*5000, b' '*(profiles.MAX_BYTES+1)])
def test_profile_json_failures_are_deterministic(tmp_path,raw):
    path = tmp_path/'profile.json'
    path.write_bytes(raw)
    messages = []
    for _ in range(2):
        with pytest.raises(profiles.ProfileLoadError) as error:
            profiles.load_profile(path)
        messages.append(str(error.value))
    assert messages[0] == messages[1]


def test_nested_duplicate_expectation_unknown_fields_and_missing_files(tmp_path):
    raw = json.dumps(profile()).replace('"source_count": 2','"source_count": 2, "source_count": 2')
    path = tmp_path/'profile.json'
    path.write_text(raw)
    with pytest.raises(profiles.ProfileLoadError,match='duplicate'):
        profiles.load_profile(path)
    for declared in ({}, {**profile(), 'extra': 0}):
        with pytest.raises(profiles.ProfileLoadError):
            profiles.profile_from_document(declared)
    with pytest.raises(profiles.ProfileLoadError,match='unable to read'):
        profiles.load_profile(tmp_path/'absent')


def test_profile_result_detaches_expected_values():
    declared = profile()
    result = profiles.evaluate_profile(fixture(), declared)
    result['checks'][4]['expected'].append('changed')
    assert declared['expectations']['source_clock_domains'] == ['fixture:camera','fixture:radar']
