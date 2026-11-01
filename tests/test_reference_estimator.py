"""Independent analytical SF-3 prediction, conditioning and Joseph-form checks."""
from dataclasses import replace, FrozenInstanceError
from fractions import Fraction as F
import pytest
from aegis.fusion.contracts import MeasurementTime, ReferenceFrame
from aegis.fusion.admission import EvidenceKey
from aegis.fusion.uncertainty import CovarianceDeclaration, UncertaintyProvenance, UnknownUncertainty
from aegis.fusion.reference_estimator import (
    ReferencePrior, ReferenceModel, ReferenceAssumptions, SyntheticPosition,
    state_basis, position_basis, initialize, predict, correct, adapt_position, replay,
    MAX_MEASUREMENTS, MAX_PREDICTIONS, _solve, _Fault,
)

FRAME=ReferenceFrame('synthetic.fixed')
PROV=UncertaintyProvenance('analytical','1','synthetic_model')
MODEL=ReferenceModel(0,'1')
KEYS=tuple(EvidenceKey('synthetic','fixture',str(i)) for i in range(MAX_MEASUREMENTS))
ASSUMPTIONS=ReferenceAssumptions('fixture','known','prior','independent',KEYS,True)


def diagonal(values):
    return tuple(tuple(value if i==j else 0 for j in range(len(values))) for i,value in enumerate(values))


def prior(**changes):
    r=ReferencePrior('prior','known',MeasurementTime(0,'fixture.clock'),FRAME,(0,0,1,2),
                     CovarianceDeclaration(diagonal((1,1,1,1)),state_basis(FRAME),PROV))
    return replace(r,**changes)


def measurement(index=0,time=0,position=(2,4),r=None,**changes):
    source=SyntheticPosition(KEYS[index],MeasurementTime(time,'fixture.clock'),MeasurementTime(time,'fixture.clock'),
        MeasurementTime(time,'fixture.clock'),FRAME,position,
        CovarianceDeclaration(r or diagonal((1,1)),position_basis(FRAME),PROV),'1')
    source=replace(source,**changes)
    outcome=adapt_position(source,ASSUMPTIONS,None)
    assert outcome.status=='admitted',outcome
    return outcome.measurement


def test_prediction_independent_analytical_integrated_white_acceleration():
    initial=initialize(prior()).state
    out=predict(initial,MeasurementTime(2,'fixture.clock'),ReferenceModel(3,'white-acceleration-v1'))
    assert out.status=='predicted' and out.state.values==(2,4,1,2)
    # FP Fᵀ gives diag(5,5,1,1), cross=2. Q gives pos8, cross6, vel6.
    assert out.state.covariance==((13,0,8,0),(0,13,0,8),(8,0,7,0),(0,8,0,7))
    assert out.state.predictions[0].model is out.model
    assert initial.time.seconds==0 and initial.covariance==diagonal((1,1,1,1))


def test_prediction_semigroup_for_continuous_white_acceleration():
    s=initialize(prior()).state; model=ReferenceModel(.5,'1')
    direct=predict(s,MeasurementTime(3,'fixture.clock'),model).state
    a=predict(s,MeasurementTime(1,'fixture.clock'),model).state
    split=predict(a,MeasurementTime(3,'fixture.clock'),model).state
    assert direct.values==split.values and direct.covariance==split.covariance
    assert len(split.predictions)==2


def test_scalar_gaussian_oracle_no_velocity_from_single_same_time_position():
    s=initialize(prior()).state; m=measurement()
    out=correct(s,m,MODEL)
    assert out.status=='corrected' and out.state.values==(1,2,1,2)
    assert out.state.covariance==diagonal((F(1,2),F(1,2),1,1))
    assert out.innovation==(2,4) and out.innovation_covariance==diagonal((2,2)) and out.nis==10
    assert out.measurement is m and out.state.measurements==(m,)


def test_nontrivial_correlated_measurement_analytical_gaussian_oracle():
    s=initialize(prior()).state
    m=measurement(position=(3,3),r=((2,1),(1,2)))
    out=correct(s,m,MODEL)
    # S=[[3,1],[1,3]], S^-1=1/8[[3,-1],[-1,3]].
    assert out.state.values==(F(3,4),F(3,4),1,2)
    assert tuple(row[:2] for row in out.state.covariance[:2])==((F(5,8),F(1,8)),(F(1,8),F(5,8)))
    assert out.nis==F(9,2)


def test_zero_and_singular_prior_are_supported_without_inverting_prior():
    for p in (diagonal((0,0,0,0)),diagonal((1,0,0,0))):
        pr=prior(uncertainty=CovarianceDeclaration(p,state_basis(FRAME),PROV))
        out=correct(initialize(pr).state,measurement(),MODEL)
        assert out.status=='corrected'
        assert out.state.values[2:]==(1,2)


@pytest.mark.parametrize('dt', [-1,86401])
def test_invalid_prediction_time_does_not_advance(dt):
    s=initialize(prior()).state
    out=predict(s,MeasurementTime(dt,'fixture.clock'),MODEL)
    assert out.status=='rejected' and out.state is s


def test_zero_duration_identity_and_clock_isolation():
    s=initialize(prior()).state
    assert predict(s,s.time,ReferenceModel(100,'1')).state is s
    assert predict(s,MeasurementTime(1,'other'),MODEL).status=='rejected'


@pytest.mark.parametrize('value', [float('nan'),float('inf'),True,-1])
def test_invalid_process_density(value):
    assert predict(initialize(prior()).state,MeasurementTime(1,'fixture.clock'),ReferenceModel(value,'1')).status=='rejected'


@pytest.mark.parametrize('values', [(1,2),(1,2,float('inf'),0),(1,2,True,0),(1,2,float('nan'),0)])
def test_velocity_prior_must_be_complete_and_finite(values):
    assert initialize(prior(values=values)).status=='rejected'


@pytest.mark.parametrize('matrix', [((1,2),(0,1)),((1,2),(2,1)),((1,float('nan')),(float('nan'),1)),((1,float('inf')),(float('inf'),1))])
def test_invalid_measurement_covariance_rejected(matrix):
    m=measurement()
    source=replace(m.source,uncertainty=replace(m.source.uncertainty,matrix=matrix))
    assert adapt_position(source,ASSUMPTIONS,None).status=='rejected'


@pytest.mark.parametrize('uncertainty', [UnknownUncertainty('not known'),CovarianceDeclaration(((1,0),(0,0)),position_basis(FRAME),PROV),CovarianceDeclaration(((0,0),(0,0)),position_basis(FRAME),PROV)])
def test_unknown_and_singular_measurement_never_become_identity_noise(uncertainty):
    m=measurement()
    out=adapt_position(replace(m.source,uncertainty=uncertainty),ASSUMPTIONS,None)
    assert out.status=='deferred' and out.measurement is None


def test_condition_guard_is_transactional_and_later_valid_evidence_can_succeed():
    s=initialize(prior(uncertainty=CovarianceDeclaration(diagonal((0,0,0,0)),state_basis(FRAME),PROV))).state
    ill=measurement(r=diagonal((1e-20,1)))
    out=correct(s,ill,MODEL)
    assert out.status=='deferred' and out.diagnostics[0].code=='INNOVATION_CONDITION' and out.state is s
    assert correct(s,measurement(),MODEL).status=='corrected'
    with pytest.raises(_Fault):
        _solve(((F(0),F(0)),(F(0),F(0))),(F(0),F(0)))


def test_duplicates_conflicts_and_equal_time_tie_breaking():
    s=initialize(prior()).state; m=measurement()
    first=correct(s,m,MODEL)
    assert correct(first.state,m,MODEL).status=='duplicate'
    assert correct(first.state,measurement(position=(3,4)),MODEL).diagnostics[0].code=='EVIDENCE_CONFLICT'
    a,b=measurement(1),measurement(0)
    result=replay(prior(),(a,b,a),MeasurementTime(0,'fixture.clock'),MODEL)
    assert [step.status for step in result.steps]==['corrected','corrected','duplicate']
    assert tuple(x.evidence_key for x in result.final.state.measurements)==(KEYS[1],KEYS[0])


def test_delayed_delivery_selected_time_and_no_online_rewind():
    m=measurement(time=0,delivery=MeasurementTime(2,'fixture.clock'),evaluation=MeasurementTime(2,'fixture.clock'))
    assert replay(prior(),(m,),MeasurementTime(1,'fixture.clock'),MODEL).steps[0].status=='deferred'
    assert replay(prior(),(m,),MeasurementTime(2,'fixture.clock'),MODEL).steps[0].status=='corrected'
    future=predict(initialize(prior()).state,MeasurementTime(1,'fixture.clock'),MODEL).state
    assert correct(future,m,MODEL).diagnostics[0].code=='TIME_ORDER'


def test_replay_orders_unequal_acquisitions_without_mutating_input():
    inputs=(measurement(1,2,(2,4)),measurement(0,0,(0,0)))
    before=repr(inputs)
    out=replay(prior(),inputs,MeasurementTime(3,'fixture.clock'),MODEL)
    assert [step.measurement.evidence_key for step in out.steps]==[KEYS[0],KEYS[1]]
    assert out==replay(prior(),inputs,MeasurementTime(3,'fixture.clock'),MODEL) and repr(inputs)==before
    with pytest.raises(FrozenInstanceError):
        out.final.state.values=(0,0,0,0)


def test_resource_bounds_and_exact_numeric_deferral():
    m=measurement()
    assert replay(prior(),(m,)*17,MeasurementTime(0,'fixture.clock'),MODEL).final.status=='rejected'
    state=initialize(prior()).state
    for i in range(MAX_PREDICTIONS):
        state=predict(state,MeasurementTime(i+1,'fixture.clock'),MODEL).state
    assert predict(state,MeasurementTime(MAX_PREDICTIONS+1,'fixture.clock'),MODEL).diagnostics[0].code=='BOUND'
    huge=prior(values=(2**4000,0,0,0))
    assert initialize(huge).status=='rejected'  # SF-1 finite numeric input range.


def test_forged_measurement_frame_and_correspondence_reject():
    m=measurement(); s=initialize(prior()).state
    assert correct(s,replace(m,position=(F(999),F(999))),MODEL).status=='rejected'
    other=ReferenceFrame('other')
    source=replace(m.source,frame=other,uncertainty=replace(m.source.uncertainty,measurement_basis=position_basis(other)))
    valid_other=adapt_position(source,ASSUMPTIONS,None).measurement
    assert correct(s,valid_other,MODEL).diagnostics[0].code=='FRAME_MISMATCH'
    assert correct(initialize(prior(correspondence_id='different')).state,m,MODEL).diagnostics[0].code=='CORRESPONDENCE'


def test_derived_numeric_types_cannot_silently_reenter_float_arithmetic():
    s=initialize(prior()).state; m=measurement()
    assert predict(replace(s,values=tuple(float(x) for x in s.values)),s.time,MODEL).status=='rejected'
    assert predict(replace(s,covariance=diagonal((1.,1.,1.,1.))),s.time,MODEL).status=='rejected'
    assert correct(s,replace(m,covariance=diagonal((1.,1.))),MODEL).status=='rejected'
    assert correct(s,replace(m,position=(2.,4.)),MODEL).status=='rejected'


@pytest.mark.parametrize('changes', [dict(independent_of_prior=False),dict(assumption_id=''),dict(evidence_scope=KEYS[:1])])
def test_missing_joint_model_is_not_assumed(changes):
    m=measurement()
    assert adapt_position(m.source,replace(ASSUMPTIONS,**changes),None).status=='rejected'


def test_selected_time_staleness_uses_explicit_policy_and_inclusive_boundary():
    m=measurement()
    m=adapt_position(m.source,ASSUMPTIONS,2).measurement
    assert replay(prior(),(m,),MeasurementTime(2,'fixture.clock'),MODEL).steps[0].status=='corrected'
    assert replay(prior(),(m,),MeasurementTime(3,'fixture.clock'),MODEL).steps[0].diagnostics[0].code=='STALE_MEASUREMENT'


def test_extreme_finite_prediction_is_exact_and_bounded():
    from sys import float_info
    s=initialize(prior()).state
    out=predict(s,MeasurementTime(1,'fixture.clock'),ReferenceModel(float_info.max,'extreme'))
    assert out.status=='predicted'
    assert all(type(x) is F for row in out.state.covariance for x in row)
    assert out.state.covariance[0][0]==F(2)+F(float_info.max)/3


def test_prior_and_measurement_units_and_frames_are_strict():
    p=prior()
    assert initialize(replace(p,uncertainty=replace(p.uncertainty,measurement_basis=replace(state_basis(FRAME),units=('m',)*4)))).status=='rejected'
    m=measurement()
    bad=replace(m.source,uncertainty=replace(m.source.uncertainty,measurement_basis=replace(position_basis(FRAME),units=('px','px'))))
    assert adapt_position(bad,ASSUMPTIONS,None).status=='rejected'
    assert adapt_position(replace(m.source,frame=None),ASSUMPTIONS,None).status=='rejected'


def test_prediction_history_preserves_model_changes_without_hidden_reset():
    s=initialize(prior()).state
    s=predict(s,MeasurementTime(1,'fixture.clock'),ReferenceModel(0,'first')).state
    s=predict(s,MeasurementTime(2,'fixture.clock'),ReferenceModel(1,'second')).state
    assert [r.model.revision for r in s.predictions]==['first','second']
    assert predict(replace(s,predictions=()),s.time,MODEL).status=='rejected'


@pytest.mark.parametrize('changes', [dict(evidence_key=None),dict(acquisition=MeasurementTime(float('nan'),'fixture.clock')),dict(delivery=MeasurementTime(0,'other'))])
def test_unknown_uncertainty_does_not_mask_invalid_source_metadata(changes):
    source=replace(measurement().source,uncertainty=UnknownUncertainty('unknown'),**changes)
    assert adapt_position(source,ASSUMPTIONS,None).status=='rejected'


def test_state_retains_inspection_context_separately_from_acquisition_epoch():
    m=measurement(delivery=MeasurementTime(2,'fixture.clock'),evaluation=MeasurementTime(2,'fixture.clock'))
    updated=correct(initialize(prior()).state,m,MODEL).state
    assert updated.time.seconds==0 and updated.evaluation.seconds==2
    forecast=predict(updated,MeasurementTime(1,'fixture.clock'),MODEL).state
    assert forecast.evaluation.seconds==2  # Retrospective epoch, not information known at t=1.
    earlier=measurement(1,time=1)
    out=correct(forecast,earlier,MODEL)
    assert out.status=='rejected' and out.diagnostics[0].code=='EVALUATION_CONTEXT'


def test_existing_posterior_cannot_be_reused_with_altered_prior_identity():
    m=measurement()
    updated=correct(initialize(prior()).state,m,MODEL).state
    altered=replace(updated,prior=replace(updated.prior,prior_id='other-prior'))
    out=correct(altered,m,MODEL)
    assert out.status=='rejected'


def test_resumed_state_cannot_claim_unadmitted_history_as_duplicate():
    m=measurement()
    forged=replace(m,source={'observation_type':'gnss'})
    state=replace(initialize(prior()).state,measurements=(forged,))
    assert correct(state,m,MODEL).status=='rejected'
    assert predict(state,state.time,MODEL).status=='rejected'


def test_joseph_posterior_matches_independent_four_dimensional_information_form():
    # Independent Gauss-Jordan oracle; no estimator matrix/solve helpers used.
    def inverse(a):
        n=len(a)
        rows=[[F(x) for x in row]+[F(int(i==j)) for j in range(n)] for i,row in enumerate(a)]
        for col in range(n):
            pivot=next(i for i in range(col,n) if rows[i][col])
            rows[col],rows[pivot]=rows[pivot],rows[col]
            scale=rows[col][col]
            rows[col]=[x/scale for x in rows[col]]
            for i in range(n):
                if i!=col:
                    factor=rows[i][col]
                    rows[i]=[x-factor*y for x,y in zip(rows[i],rows[col])]
        return tuple(tuple(row[n:]) for row in rows)
    b=((2,0,0,0),(1,2,0,0),(1,-1,1,0),(0,1,2,1))
    p=tuple(tuple(sum(b[i][k]*b[j][k] for k in range(4)) for j in range(4)) for i in range(4))
    pr=prior(values=(1,-1,2,0),uncertainty=CovarianceDeclaration(p,state_basis(FRAME),PROV))
    m=measurement(position=(3,4),r=((4,3),(3,4)))
    ip,ir=inverse(p),inverse(m.covariance)
    information=tuple(tuple(ip[i][j]+(ir[i][j] if i<2 and j<2 else 0) for j in range(4)) for i in range(4))
    expected_p=inverse(information)
    rhs=tuple(sum(ip[i][j]*pr.values[j] for j in range(4))+(sum(ir[i][j]*m.position[j] for j in range(2)) if i<2 else 0) for i in range(4))
    expected_mean=tuple(sum(expected_p[i][j]*rhs[j] for j in range(4)) for i in range(4))
    result=correct(initialize(pr).state,m,MODEL)
    assert result.status=='corrected'
    assert result.state.covariance==expected_p and result.state.values==expected_mean


def test_process_covariance_matches_independent_impulse_response_quadrature():
    # Simpson integration is exact for the degree-two GGᵀ integrand.
    dt=F(1,2); q=6
    def integrand(s,i,j):
        g=((dt-s,0),(0,dt-s),(1,0),(0,1))
        return sum(g[i][k]*g[j][k] for k in range(2))
    expected=tuple(tuple(q*dt/6*(integrand(0,i,j)+4*integrand(dt/2,i,j)+integrand(dt,i,j)) for j in range(4)) for i in range(4))
    pr=prior(uncertainty=CovarianceDeclaration(diagonal((0,0,0,0)),state_basis(FRAME),PROV))
    result=predict(initialize(pr).state,MeasurementTime(.5,'fixture.clock'),ReferenceModel(q,'impulse-oracle'))
    assert result.state.covariance==expected


@pytest.mark.parametrize('diagonal_max,status', [(10**12,'corrected'),(10**12+1,'deferred')])
def test_innovation_condition_limit_is_exact_and_inclusive(diagonal_max,status):
    pr=prior(uncertainty=CovarianceDeclaration(diagonal((0,0,0,0)),state_basis(FRAME),PROV))
    result=correct(initialize(pr).state,measurement(r=diagonal((1,diagonal_max))),MODEL)
    assert result.status==status


@pytest.mark.parametrize('epsilon,status', [(2**-30,'corrected'),(2**-45,'deferred')])
def test_strongly_correlated_and_near_degenerate_innovation(epsilon,status):
    pr=prior(uncertainty=CovarianceDeclaration(diagonal((0,0,0,0)),state_basis(FRAME),PROV))
    result=correct(initialize(pr).state,measurement(r=((1,1-epsilon),(1-epsilon,1))),MODEL)
    assert result.status==status
    if status=='deferred':
        assert result.diagnostics[0].code=='INNOVATION_CONDITION'


def test_actual_rational_growth_limit_is_transactional():
    tiny=5e-324
    pr=prior(uncertainty=CovarianceDeclaration(diagonal((0,0,0,0)),state_basis(FRAME),PROV))
    state=initialize(pr).state
    assert predict(state,MeasurementTime(tiny,'fixture.clock'),MODEL).status=='predicted'
    rejected=predict(state,MeasurementTime(tiny,'fixture.clock'),ReferenceModel(tiny,'tiny-density'))
    assert rejected.status=='rejected' and rejected.diagnostics[0].code=='NUMERIC_BOUND'
    assert rejected.state is state and not state.predictions
    m=measurement(time=tiny)
    deferred=correct(state,m,ReferenceModel(1,'white-acceleration'))
    assert deferred.status=='deferred' and deferred.diagnostics[0].code=='NUMERIC_BOUND'
    assert deferred.state is state and not state.measurements
    assert correct(state,m,MODEL).status=='corrected'


def test_future_measurement_values_do_not_affect_an_earlier_selected_estimate():
    early=measurement(0,position=(1,1))
    a=measurement(1,time=1,position=(100,100),delivery=MeasurementTime(5,'fixture.clock'),evaluation=MeasurementTime(5,'fixture.clock'))
    b=measurement(1,time=1,position=(-100,-100),delivery=MeasurementTime(5,'fixture.clock'),evaluation=MeasurementTime(5,'fixture.clock'))
    left=replay(prior(),(early,a),MeasurementTime(2,'fixture.clock'),MODEL)
    right=replay(prior(),(early,b),MeasurementTime(2,'fixture.clock'),MODEL)
    assert left.final.state==right.final.state
    assert left.steps[1].status==right.steps[1].status=='deferred'


def test_value_equal_foreign_frame_cannot_bypass_measurement_validation():
    class ForeignFrame:
        def __eq__(self,other):
            return True
    forged=replace(measurement(),frame=ForeignFrame())
    out=correct(initialize(prior()).state,forged,MODEL)
    assert out.status=='rejected'


def test_value_equal_boolean_delivery_is_not_a_valid_timestamp():
    forged=replace(measurement(),delivery=MeasurementTime(False,'fixture.clock'))
    out=correct(initialize(prior()).state,forged,MODEL)
    assert out.status=='rejected'
