"""SF-3 fabricated external-object trajectories; explicit correspondence, no RNG."""
from dataclasses import dataclass
from fractions import Fraction
import json
from math import atan2, hypot, sqrt, ldexp

from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.admission import AdmissionRequest, AdmissionLedger, CorrelationClaim, EvidenceKey
from aegis.fusion.timing import AlignmentRequest, align_batch
from aegis.fusion.acquisition import Acquisition, inspect_acquisitions
from aegis.fusion.uncertainty import MeasurementBasis, CovarianceDeclaration, UncertaintyProvenance, _require, _text
from aegis.fusion.geometry import GeometryRequest
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.fusion.reference_estimator import (
    ReferenceAssumptions, ReferencePrior, ReferenceModel, ReferenceMeasurement,
    Adaptation, adapt_position, state_basis, replay, _solve, _Fault, _model, _exact, _number,
    _covariance,
)

NAMES = ('constant_velocity','acceleration_mismatch','missing','delayed','unequal_intervals','singular_covariance')
FRAME = ReferenceFrame('sf3.synthetic.fixed_cartesian')
CLOCK = 'sf3.synthetic.seconds'
PROVENANCE = UncertaintyProvenance('sf3.fabricated.cartesian.noise','1','synthetic_model')


@dataclass(frozen=True, slots=True)
class ReferenceScenario:
    name: str
    prior: ReferencePrior
    assumptions: ReferenceAssumptions
    acquisitions: tuple[Acquisition, ...]
    adaptations: tuple[Adaptation, ...]
    measurements: tuple[ReferenceMeasurement, ...]
    query_times: tuple[MeasurementTime, ...]
    acceleration: tuple[float, float]


def ground_truth(time, acceleration=(0.,0.)):
    """Fixed analytical initial position (20,10), velocity (2,-1), z=5 metres."""
    t=Fraction(time)
    ax,ay=map(Fraction,acceleration)
    return (20+2*t+ax*t*t/2,10-t+ay*t*t/2,2+ax*t,-1+ay*t)


def scenario(name: str) -> ReferenceScenario:
    _text(name,'scenario')
    _require(name in NAMES,'SCENARIO','name','Unknown bounded fabricated scenario')
    times = (0.,0.5,1.5,2.,4.,5.,7.,8.) if name=='unequal_intervals' else tuple(float(i) for i in range(8))
    acceleration = (0.5,0.25) if name=='acceleration_mismatch' else (0.,0.)
    keys=tuple(EvidenceKey('sf3.synthetic.radar',name,str(i)) for i in range(len(times)))
    assumptions=ReferenceAssumptions(name,'known-synthetic-entity','explicit-prior','sf3.synthetic.independence.v1',keys,True)
    prior=ReferencePrior(assumptions.prior_id,assumptions.correspondence_id,MeasurementTime(0.,CLOCK),FRAME,
        (20.,10.,2.,-1.),CovarianceDeclaration(tuple(tuple(4. if i==j else 0. for j in range(4)) for i in range(4)),state_basis(FRAME),PROVENANCE))
    acquisitions,adaptations,measurements=[],[],[]
    deliveries=tuple(t+(3. if name=='delayed' and i%2==0 else 0.) for i,t in enumerate(times))
    inspection=MeasurementTime(max(deliveries),CLOCK)
    ledger=AdmissionLedger.empty()
    for i,(t,key) in enumerate(zip(times,keys)):
        time=MeasurementTime(t,CLOCK)
        if name=='missing' and i in (2,3,6):
            acquisitions.append(Acquisition(key.sensor_id,key.source_session_id,'scan-'+str(i),time,'completed',()))
            continue
        truth=ground_truth(t,acceleration)
        # Fixed fabricated offsets; they are not random draws or sensor accuracy evidence.
        dx,dy=((0.2,-0.1),(-0.2,0.1),(0.1,0.2),(-0.1,-0.2))[i%4]
        x,y,z=float(truth[0])+dx,float(truth[1])+dy,5.
        polar=RadarPolarDetectionMeasurement(hypot(x,y,z),atan2(y,x),atan2(z,hypot(x,y)))
        obs=SensorObservation(key.observation_id,key.sensor_id,time,FRAME,polar)
        acquisitions.append(Acquisition(key.sensor_id,key.source_session_id,'scan-'+str(i),time,'completed',(obs,)))
        basis=MeasurementBasis('radar_polar',('range_m','azimuth_rad','elevation_rad'),('m','rad','rad'),FRAME)
        raw=CovarianceDeclaration(((1.,0.,0.),(0.,0.001,0.),(0.,0.,0.001)),basis,PROVENANCE)
        correlation=CorrelationClaim('independence_asserted',None,assumptions.assumption_id,keys)
        request=AdmissionRequest(obs,key.source_session_id,'external_object','radar_polar',basis,raw,correlation,
                                 inspection,MeasurementTime(deliveries[i],CLOCK),None)
        admission=align_batch((AlignmentRequest(request,'sf3.synthetic.timing','1'),),ledger)
        _require(admission.results[0].status=='admitted','FIXTURE','admission','Fabricated source must pass SF-1/SF-2')
        ledger=admission.ledger
        cart=MeasurementBasis('cartesian_point',('x_m','y_m','z_m'),('m',)*3,FRAME)
        matrix=((1.,0.,0.),(0.,0. if name=='singular_covariance' else 1.,0.),(0.,0.,1.))
        projected=CovarianceDeclaration(matrix,cart,PROVENANCE)
        geometry=GeometryRequest(admission.results[0].admission.admitted_measurement,'sf3.synthetic.geometry','1',
                                 'radar_cartesian',projected_uncertainty=projected)
        adaptation=adapt_position(geometry,assumptions,None)
        adaptations.append(adaptation)
        if adaptation.measurement is not None:
            measurements.append(adaptation.measurement)
    _require(not inspect_acquisitions(tuple(acquisitions)).diagnostics,'FIXTURE','acquisitions','Bounded acquisition validation failed')
    return ReferenceScenario(name,prior,assumptions,tuple(acquisitions),tuple(adaptations),tuple(measurements),
                             tuple(MeasurementTime(t,CLOCK) for t in times),acceleration)


@dataclass(frozen=True, slots=True)
class ReferenceEvaluation:
    scenario_name: str
    model: ReferenceModel
    position_rmse_m: float
    velocity_rmse_mps: float
    position_errors: tuple[tuple[Fraction, Fraction], ...]
    velocity_errors: tuple[tuple[Fraction, Fraction], ...]
    position_nees: tuple[Fraction | None, ...]
    innovations: tuple[tuple[Fraction, ...], ...]
    nis: tuple[Fraction, ...]
    final_covariance: tuple[tuple[Fraction, ...], ...]
    correction_statuses: tuple[str, ...]
    adaptation_statuses: tuple[str, ...]


def _rmse(vectors):
    """Float approximation of exact vector RMSE without squaring into float.

    Scale the exact mean square by an even binary exponent before conversion;
    Reject a positive root outside the nonzero finite float range explicitly.
    """
    mean = sum(sum(x*x for x in vector) for vector in vectors)/len(vectors)
    if mean == 0:
        return 0.
    exponent = mean.numerator.bit_length()-mean.denominator.bit_length()
    half = exponent//2
    scaled = mean/Fraction(2)**(2*half)
    try:
        result = ldexp(sqrt(float(scaled)),half)
    except OverflowError:
        raise _Fault('REPORT','rmse','RMSE cannot be represented as a finite float') from None
    _require(result>0,'REPORT','rmse','Nonzero RMSE is below the representable float range')
    return result


def evaluate(fixture: ReferenceScenario, model: ReferenceModel) -> ReferenceEvaluation:
    """Fixed finite fixture evaluation; RMSE uses squared 2D vector norm per query."""
    # Reject arbitrary large/custom scenarios; this evaluator is for these six fixtures only.
    _require(type(fixture) is ReferenceScenario and fixture==scenario(fixture.name),'SCENARIO','fixture','Use an unchanged deterministic fixture')
    errors,velocity,nees=[],[],[]
    for time in fixture.query_times:
        result=replay(fixture.prior,fixture.measurements,time,model)
        _require(result.final.status=='predicted','EVALUATION','replay','Reference replay failed')
        state=result.final.state
        truth=ground_truth(time.seconds,fixture.acceleration)
        e=tuple(state.values[i]-truth[i] for i in range(2))
        v=tuple(state.values[i+2]-truth[i+2] for i in range(2))
        errors.append(e); velocity.append(v)
        try:
            s=tuple(tuple(state.covariance[i][j] for j in range(2)) for i in range(2))
            nees.append(sum(x*y for x,y in zip(e,_solve(s,e))))
        except _Fault:
            nees.append(None)  # Singular/ill-conditioned marginal has no claimed normalized score.
    final=replay(fixture.prior,fixture.measurements,fixture.query_times[-1],model)
    accepted=tuple(step for step in final.steps if step.status=='corrected')
    return ReferenceEvaluation(fixture.name,model,_rmse(errors),_rmse(velocity),tuple(errors),tuple(velocity),tuple(nees),
        tuple(s.innovation for s in accepted),tuple(s.nis for s in accepted),final.final.state.covariance,
        tuple(s.status for s in final.steps),tuple(a.status for a in fixture.adaptations))


def evaluation_bytes(result: ReferenceEvaluation) -> bytes:
    """Deterministic fixture report v1, exact rationals and hexadecimal float RMSE."""
    _require(type(result) is ReferenceEvaluation,'REPORT','result','Require bounded reference evaluation')
    _model(result.model); _text(result.scenario_name,'scenario_name')
    _require(result.scenario_name in NAMES,'REPORT','scenario_name','Unknown fixture')
    for name in ('position_errors','velocity_errors'):
        vectors = getattr(result,name)
        _require(type(vectors) is tuple and len(vectors)==8,'REPORT',name,'Eight query errors required')
        for vector in vectors:
            _require(type(vector) is tuple and len(vector)==2 and all(type(x) is Fraction for x in vector),
                     'REPORT',name,'Require exact 2D errors')
            for x in vector:
                _exact(x)
    for name,vectors in (('position_rmse_m',result.position_errors),('velocity_rmse_mps',result.velocity_errors)):
        score = getattr(result,name)
        _require(type(score) is float and score>=0,'REPORT',name,'Require nonnegative finite float RMSE')
        _number(score,name)
        expected = _rmse(vectors)
        _require(score==expected,'REPORT',name,'RMSE contradicts supplied query errors')
    _covariance(result.final_covariance,4)
    _require(all(type(x) is Fraction for row in result.final_covariance for x in row),
             'REPORT','final_covariance','Require exact covariance')
    _require(type(result.position_nees) is tuple and len(result.position_nees)==8,
             'REPORT','position_nees','One consistency score per query required')
    for score in result.position_nees:
        _require(score is None or (type(score) is Fraction and score>=0),
                 'REPORT','position_nees','Require nonnegative exact score or unavailable')
    _require(type(result.correction_statuses) is tuple and len(result.correction_statuses)<=8 and
             all(type(s) is str and s in ('corrected','deferred','rejected','duplicate') for s in result.correction_statuses),
             'REPORT','correction_statuses','Invalid correction outcomes')
    _require(type(result.adaptation_statuses) is tuple and len(result.adaptation_statuses)<=8 and
             all(type(s) is str and s in ('admitted','deferred','rejected') for s in result.adaptation_statuses),
             'REPORT','adaptation_statuses','Invalid adaptation outcomes')
    count = result.correction_statuses.count('corrected')
    _require(type(result.innovations) is tuple and type(result.nis) is tuple and
             len(result.innovations)==len(result.nis)==count,'REPORT','innovations','Correction and innovation counts must agree')
    for vector in result.innovations:
        _require(type(vector) is tuple and len(vector)==2 and all(type(x) is Fraction for x in vector),
                 'REPORT','innovations','Require exact 2D residuals')
    _require(all(type(x) is Fraction and x>=0 for x in result.nis),'REPORT','nis','Require nonnegative exact NIS')
    def encode(value, depth=0):
        _require(depth<=3,'BOUND','report','Report nesting exceeded')
        if type(value) is Fraction:
            _exact(value)
            return {'numerator':str(value.numerator),'denominator':str(value.denominator)}
        if type(value) is float:
            _number(value,'report')
            return value.hex()
        if type(value) is tuple:
            _require(len(value)<=16,'BOUND','report','Report tuple exceeds 16 values')
            return [encode(x,depth+1) for x in value]
        _require(value is None or type(value) is str,'REPORT','value','Unsupported report value')
        if value is not None:
            _text(value,'report')
        return value
    document={name:encode(getattr(result,name)) for name in (
        'scenario_name','position_rmse_m','velocity_rmse_mps','position_errors','velocity_errors','position_nees',
        'innovations','nis','final_covariance','correction_statuses','adaptation_statuses')}
    document.update(schema_version=1,model_revision=result.model.revision,
                    acceleration_spectral_density=encode(Fraction(result.model.acceleration_spectral_density)))
    return (json.dumps(document,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
