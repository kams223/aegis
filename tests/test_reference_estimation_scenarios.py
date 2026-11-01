from dataclasses import replace
from hashlib import sha256
from fractions import Fraction
import json
import pytest
from aegis.simulation.reference_estimation import scenario,evaluate,evaluation_bytes,NAMES
from aegis.fusion.reference_estimator import ReferenceModel,replay
from aegis.fusion.acquisition import inspect_acquisitions


@pytest.mark.parametrize('name',NAMES)
def test_scenarios_are_bounded_repeatable_and_preserve_sources(name):
    fixture=scenario(name); before=repr(fixture)
    result=evaluate(fixture,ReferenceModel(.25,'white-acceleration-v1'))
    assert result.position_rmse_m>=0 and result.velocity_rmse_mps>=0
    assert len(result.position_errors)==8 and len(result.velocity_errors)==8
    assert all(value is None or value>=0 for value in result.position_nees)
    assert all(value>=0 for value in result.nis)
    assert result.final_covariance==tuple(zip(*result.final_covariance))
    assert repr(fixture)==before and fixture==scenario(name)
    hashes=tuple(sha256(evaluation_bytes(evaluate(fixture,ReferenceModel(.25,'white-acceleration-v1')))).hexdigest() for _ in range(3))
    assert len(set(hashes))==1
    assert json.loads(evaluation_bytes(result))['schema_version']==1


def test_missing_is_explicit_empty_and_singular_measurements_remain_deferred():
    missing=scenario('missing')
    inspected=inspect_acquisitions(missing.acquisitions)
    assert sum(x.completeness=='completed_empty' for x in inspected.results)==3
    singular=scenario('singular_covariance')
    assert not singular.measurements and len(singular.adaptations)==8
    assert all(x.status=='deferred' for x in singular.adaptations)
    result=evaluate(singular,ReferenceModel(0,'1'))
    assert not result.innovations and not result.correction_statuses


def test_acceleration_mismatch_is_sensitive_to_declared_process_noise():
    fixture=scenario('acceleration_mismatch')
    rigid=evaluate(fixture,ReferenceModel(0,'q-zero'))
    flexible=evaluate(fixture,ReferenceModel(1,'q-one'))
    assert flexible.position_rmse_m<rigid.position_rmse_m
    assert flexible.velocity_rmse_mps<rigid.velocity_rmse_mps
    assert flexible.final_covariance!=rigid.final_covariance


def test_delayed_data_not_visible_at_earlier_queries():
    fixture=scenario('delayed')
    result=replay(fixture.prior,fixture.measurements,fixture.query_times[0],ReferenceModel(0,'1'))
    assert all(s.status=='deferred' for s in result.steps)
    assert not result.final.state.measurements
    final=replay(fixture.prior,fixture.measurements,fixture.query_times[-1],ReferenceModel(0,'1'))
    assert len(final.final.state.measurements)==7


def test_fixture_evaluator_rejects_modified_scenarios():
    from aegis.fusion.reference_estimator import _Fault
    with pytest.raises(_Fault):
        evaluate(replace(scenario('constant_velocity'),measurements=()),ReferenceModel(0,'1'))


@pytest.mark.parametrize('changes', [dict(position_rmse_m=-1.),dict(position_rmse_m='not-numeric'),
    dict(final_covariance=((Fraction(1),),)),dict(position_errors=())])
def test_serializer_rejects_semantically_invalid_scientific_reports(changes):
    from aegis.fusion.reference_estimator import _Fault
    result=evaluate(scenario('constant_velocity'),ReferenceModel(.25,'1'))
    with pytest.raises(_Fault):
        evaluation_bytes(replace(result,**changes))


def test_rmse_denominators_and_nees_match_independent_constant_error_oracle(monkeypatch):
    from types import SimpleNamespace
    import aegis.simulation.reference_estimation as module
    fixture=scenario('constant_velocity')
    def reference_replay(prior,measurements,time,model):
        truth=module.ground_truth(time.seconds)
        values=tuple(x+e for x,e in zip(truth,(3,4,0,12)))
        identity=tuple(tuple(Fraction(int(i==j)) for j in range(4)) for i in range(4))
        state=SimpleNamespace(values=values,covariance=identity)
        return SimpleNamespace(final=SimpleNamespace(status='predicted',state=state),steps=())
    monkeypatch.setattr(module,'replay',reference_replay)
    result=module.evaluate(fixture,ReferenceModel(0,'metric-oracle'))
    assert result.position_rmse_m==5.0  # sqrt(8*(3²+4²)/8), not per-axis RMSE.
    assert result.velocity_rmse_mps==12.0
    assert result.position_nees==(Fraction(25),)*8


def test_estimator_replay_never_queries_ground_truth(monkeypatch):
    import aegis.simulation.reference_estimation as module
    fixture=scenario('acceleration_mismatch')
    def forbidden(*args,**kwargs):
        raise AssertionError('Estimator accessed ground truth')
    monkeypatch.setattr(module,'ground_truth',forbidden)
    result=replay(fixture.prior,fixture.measurements,fixture.query_times[-1],ReferenceModel(.25,'1'))
    assert result.final.status=='predicted'


@pytest.mark.parametrize('magnitude', [Fraction(1,10**200),Fraction(10**200)])
def test_rmse_extreme_representable_magnitudes_do_not_square_into_float_underflow_or_overflow(magnitude):
    # sqrt(mean of eight identical squared vector norms) is exactly magnitude.
    result=evaluate(scenario('constant_velocity'),ReferenceModel(0,'rmse-range-oracle'))
    errors=((magnitude,Fraction(0)),)*8
    report=replace(result,position_errors=errors,position_rmse_m=float(magnitude))
    document=json.loads(evaluation_bytes(report))
    assert document['position_rmse_m']==float(magnitude).hex()


def test_rmse_nonzero_representable_errors_cannot_be_published_as_zero():
    from aegis.fusion.reference_estimator import _Fault
    result=evaluate(scenario('constant_velocity'),ReferenceModel(0,'rmse-range-oracle'))
    errors=((Fraction(1,10**200),Fraction(0)),)*8
    with pytest.raises(_Fault):
        evaluation_bytes(replace(result,position_errors=errors,position_rmse_m=0.))


@pytest.mark.parametrize('magnitude,score', [(Fraction(1,10**400),0.),(Fraction(10**400),1e308)])
def test_unrepresentable_rmse_is_rejected_without_zero_or_finite_substitution(magnitude,score):
    from aegis.fusion.reference_estimator import _Fault
    result=evaluate(scenario('constant_velocity'),ReferenceModel(0,'rmse-range-oracle'))
    with pytest.raises(_Fault):
        evaluation_bytes(replace(result,position_errors=((magnitude,Fraction(0)),)*8,position_rmse_m=score))
