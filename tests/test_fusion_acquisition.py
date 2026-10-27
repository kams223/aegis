from dataclasses import replace
import pytest
from aegis.fusion.acquisition import Acquisition, inspect_acquisitions
from aegis.fusion.contracts import MeasurementTime
from test_fusion_admission import make_request


def event(**changes):
    obs = make_request().observation
    return replace(Acquisition('camera','session','scan',obs.measurement_time,'completed',(obs,)), **changes)


def test_completeness_and_source_identity():
    a = event(); before = repr(a)
    events = (a, event(acquisition_id='empty',observations=()),
              event(acquisition_id='unavailable',status='unavailable',observations=(),reason='recording unavailable'),
              event(acquisition_id='unknown',status='unconfirmed',acquisition_time=None,observations=(),reason='callback not confirmed'))
    out = inspect_acquisitions(events)
    assert [r.completeness for r in out.results] == ['completed_with_observations','completed_empty','unavailable','unconfirmed']
    assert out.results[0].source is a and repr(a) == before and out == inspect_acquisitions(events)
    assert not inspect_acquisitions(()).results


def test_duplicate_conflict_and_invalid_do_not_reserve():
    a = event()
    out = inspect_acquisitions((replace(a, acquisition_time=None),a,a,replace(a, observations=())))
    assert [r.status for r in out.results] == ['rejected','accepted','duplicate','rejected']


@pytest.mark.parametrize('changes', [dict(status='unknown'),dict(status='unavailable'),dict(sensor_id='other'),
    dict(acquisition_time=MeasurementTime(10,'other')),dict(observations=[]),dict(reason='unexpected')])
def test_invalid_completeness(changes):
    out = inspect_acquisitions((event(**changes),))
    assert out.diagnostics or out.results[0].status == 'rejected'


def test_aggregate_bounds():
    assert inspect_acquisitions((event(),) * 1025).diagnostics
    assert inspect_acquisitions((event(observations=(make_request().observation,) * 1025),)).diagnostics


def test_observation_times_need_not_be_equal():
    a = event(acquisition_time=MeasurementTime(9,'video:a'))
    assert inspect_acquisitions((a,)).results[0].status == 'accepted'


def test_canonical_text_budget_rolls_back_batch():
    a = event(observations=())
    events = tuple(replace(a,acquisition_id=str(i),sensor_id='s'*1024,source_session_id='x'*1024) for i in range(1024))
    out = inspect_acquisitions(events)
    assert not out.results and out.diagnostics[0].code == 'BOUND'


@pytest.mark.parametrize('invalid', [None, False, 'bad acquisition', event(observations=[])])
def test_malformed_record_does_not_discard_unrelated_valid_acquisition(invalid):
    a = event()
    out = inspect_acquisitions((invalid,a))
    assert not out.diagnostics
    assert [r.status for r in out.results] == ['rejected','accepted']
    assert out.results[1].source is a
