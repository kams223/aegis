"""SF-3 bounded synthetic-reference CV estimator; no association or actuation.

Exact rational arithmetic avoids covariance roundoff/repair. Every operation is
conditional on explicit synthetic correspondence and joint-noise assumptions.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json

from aegis.fusion.contracts import MeasurementTime, ReferenceFrame
from aegis.fusion.admission import EvidenceKey, _key, _time, _Budget, _BatchBound
from aegis.fusion.uncertainty import (
    CovarianceDeclaration, UnknownUncertainty, MeasurementBasis, Diagnostic,
    validate_covariance, _Fault, _require, _text, _number, _frame, _determinant,
)
from aegis.fusion.geometry import GeometryRequest, transform_measurement, ExactCovariance
from aegis.spatial.transforms import TransformedPoint

MAX_MEASUREMENTS = 16  # Matches SF-1's maximum explicit independence scope.
MAX_PREDICTIONS = 32
MAX_BITS = 4096
MAX_DT = 86400
MAX_CONDITION = 10**12
H = ((1, 0, 0, 0), (0, 1, 0, 0))
I4 = tuple(tuple(Fraction(int(i == j)) for j in range(4)) for i in range(4))


def position_basis(frame):
    return MeasurementBasis('cartesian_position_2d', ('x_m', 'y_m'), ('m', 'm'), frame)


def state_basis(frame):
    return MeasurementBasis('reference_cv_2d', ('x_m', 'y_m', 'vx_mps', 'vy_mps'), ('m', 'm', 'm/s', 'm/s'), frame)


def _exact(x):
    if type(x) is not Fraction:
        _number(x, 'number')
        x = Fraction(x)
    _require(x.numerator.bit_length() <= MAX_BITS and x.denominator.bit_length() <= MAX_BITS,
             'NUMERIC_BOUND', 'number', 'Reference rational component exceeds 4096 bits')
    return x


def _sum(values):
    total = Fraction(0)
    for x in values:
        total = _exact(total + x)
    return total


def _transpose(a):
    return tuple(zip(*a))


def _mul(a, b):
    return tuple(tuple(_sum(_exact(x*y) for x,y in zip(row,col)) for col in _transpose(b)) for row in a)


def _add(a, b):
    return tuple(tuple(_exact(x+y) for x,y in zip(row,other)) for row,other in zip(a,b))


def _covariance(matrix, n):
    _require(type(matrix) is tuple and len(matrix) == n, 'COVARIANCE_SHAPE', 'matrix', 'Incorrect covariance dimension')
    for row in matrix:
        _require(type(row) is tuple and len(row) == n, 'COVARIANCE_SHAPE', 'matrix', 'Require immutable square matrix')
    a = tuple(tuple(_exact(x) for x in row) for row in matrix)
    _require(all(a[i][j] == a[j][i] for i in range(n) for j in range(i)), 'COVARIANCE_ASYMMETRIC', 'matrix', 'Exact symmetry required')
    rank = 0
    for size in range(1,n+1):
        for ix in combinations(range(n),size):
            d = _determinant(tuple(tuple(a[i][j] for j in ix) for i in ix))
            _require(d >= 0,'COVARIANCE_NOT_PSD','matrix','Negative principal minor; no repair')
            if d > 0:
                rank = size
    return a,rank


def _failure(error):
    return error.diagnostic if isinstance(error,_Fault) else Diagnostic('INPUT','request','Invalid input or numeric resource overflow')


@dataclass(frozen=True, slots=True)
class ReferenceAssumptions:
    scenario_id: str
    correspondence_id: str
    prior_id: str
    assumption_id: str
    evidence_scope: tuple[EvidenceKey, ...]
    independent_of_prior: bool


def _assumptions(a):
    _require(type(a) is ReferenceAssumptions,'ASSUMPTIONS','assumptions','Require explicit synthetic joint model')
    for name in ('scenario_id','correspondence_id','prior_id','assumption_id'):
        _text(getattr(a,name),name)
    _require(a.independent_of_prior is True,'CORRELATION','assumptions','Prior/noise independence must be explicitly asserted')
    _require(type(a.evidence_scope) is tuple and 2 <= len(a.evidence_scope) <= MAX_MEASUREMENTS,
             'BOUND','scope','Require 2–16 explicitly scoped evidence identities')
    for key in a.evidence_scope:
        _key(key)
    _require(len(set(a.evidence_scope)) == len(a.evidence_scope),'CORRELATION','scope','Scope identities must be unique')


@dataclass(frozen=True, slots=True)
class SyntheticPosition:
    """Explicit synthetic-only unit/reference input, never native sensor telemetry."""
    evidence_key: EvidenceKey
    acquisition: MeasurementTime
    delivery: MeasurementTime | None
    evaluation: MeasurementTime
    frame: ReferenceFrame
    position: tuple[int | float, int | float]
    uncertainty: CovarianceDeclaration | UnknownUncertainty
    fixture_revision: str


@dataclass(frozen=True, slots=True)
class ReferenceMeasurement:
    source: SyntheticPosition | GeometryRequest
    assumptions: ReferenceAssumptions
    evidence_key: EvidenceKey
    acquisition: MeasurementTime
    delivery: MeasurementTime
    evaluation: MeasurementTime
    frame: ReferenceFrame
    position: tuple[Fraction, Fraction]
    covariance: tuple[tuple[Fraction, ...], ...]
    max_age_seconds: int | float | None
    fingerprint: str
    restrictions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Adaptation:
    status: str
    measurement: ReferenceMeasurement | None
    diagnostics: tuple[Diagnostic, ...]


def adapt_position(source: SyntheticPosition | GeometryRequest, assumptions: ReferenceAssumptions,
                   max_age_seconds: int | float | None) -> Adaptation:
    """Validate synthetic input or re-run SF-2, then explicitly select measured x/y.

    SF-1 unknown/shared correlation or singular uncertainty always defers. A
    synthetic independence scope must match SF-1 and name the independent prior.
    SF-2 restrictions remain recorded; no general joint-compatibility claim is made.
    """
    try:
        _assumptions(assumptions)
        if max_age_seconds is not None:
            _number(max_age_seconds,'max_age_seconds')
            _require(max_age_seconds>=0,'AGE_POLICY','max_age_seconds','Require explicit nonnegative age or None')
        budget = _Budget()
        restrictions = ('SYNTHETIC_REFERENCE_ONLY','INDEPENDENCE_IS_CALLER_ASSERTED')
        if type(source) is SyntheticPosition:
            _text(source.fixture_revision,'fixture_revision')
            key,acq,delivery,evaluation,frame = source.evidence_key,source.acquisition,source.delivery,source.evaluation,source.frame
            _frame(frame,'frame'); _key(key)
            _time(acq,'acquisition'); _time(evaluation,'evaluation')
            _require(key in assumptions.evidence_scope,'CORRESPONDENCE','key','Evidence outside declared scope')
            if delivery is not None:
                _time(delivery,'delivery')
                _require(acq.clock_domain==delivery.clock_domain==evaluation.clock_domain,'CLOCK_DOMAIN','time','Require explicit common inspection clock')
                _require(Fraction(acq.seconds)<=Fraction(delivery.seconds),'CAUSAL_ORDER','delivery','Delivery precedes acquisition')
            _require(type(source.position) is tuple and len(source.position)==2,'MEASUREMENT','position','Require complete 2D Cartesian position')
            values = tuple(_exact(x) for x in source.position)
            if type(source.uncertainty) is UnknownUncertainty:
                _text(source.uncertainty.reason,'uncertainty.reason')
                return Adaptation('deferred',None,(Diagnostic('UNCERTAINTY_UNKNOWN','uncertainty','No covariance substituted'),))
            check = validate_covariance(source.uncertainty,position_basis(frame))
            if check.diagnostics:
                return Adaptation('rejected',None,check.diagnostics)
            _require(check.covariance.uncertainty_provenance.method=='synthetic_model',
                     'SYNTHETIC_ONLY','uncertainty','Reference inputs require explicit synthetic uncertainty provenance')
            covariance = check.covariance.matrix
            if check.covariance.restrictions:
                return Adaptation('deferred',None,(Diagnostic('SINGULAR_UNCERTAINTY','uncertainty','No singular measurement model is implemented'),))
            source_hash = budget.digest((key,acq,delivery,frame,source.position,source.uncertainty,source.fixture_revision))
        else:
            _require(type(source) is GeometryRequest,'SOURCE','source','Require explicit synthetic input or SF-2 geometry request')
            result = transform_measurement(source)
            if result.status != 'transformed':
                return Adaptation(result.status,None,result.diagnostics)
            _require(source.operation == 'radar_cartesian' and type(result.geometry) is TransformedPoint,
                     'GEOMETRY','source','Only complete measured Cartesian radar geometry supports x/y selection')
            admitted = source.source
            claim = admitted.correlation
            if (claim.mode != 'independence_asserted' or claim.assumption_id != assumptions.assumption_id
                    or claim.scope != assumptions.evidence_scope):
                return Adaptation('deferred',None,(Diagnostic('JOINT_MODEL_REQUIRED','correlation','SF-1 independence scope must match the synthetic reference model'),))
            if 'REQUIRES_SINGULAR_MODEL' in result.restrictions:
                return Adaptation('deferred',None,(Diagnostic('SINGULAR_UNCERTAINTY','uncertainty','SF-1/SF-2 singular restriction is not bypassed'),))
            _require(type(result.propagation.covariance) is ExactCovariance,'UNCERTAINTY','uncertainty','Require validated propagated covariance')
            _require(admitted.uncertainty.uncertainty_provenance.method=='synthetic_model' and
                     result.propagation.covariance.source_uncertainty.uncertainty_provenance.method=='synthetic_model',
                     'SYNTHETIC_ONLY','uncertainty','Reference integration requires synthetic raw and projected uncertainty models')
            lo,hi = admitted.measurement_interval
            if lo != hi:
                return Adaptation('deferred',None,(Diagnostic('TEMPORAL_AMBIGUITY','acquisition','Reference estimator requires singleton acquisition time'),))
            key = admitted.evidence_key
            acq = MeasurementTime(lo,admitted.evaluation.clock_domain)
            delivery,evaluation,frame = admitted.available_at,admitted.evaluation,result.destination_frame
            values = tuple(_exact(x) for x in (result.geometry.x_m,result.geometry.y_m))
            covariance = tuple(tuple(row[j] for j in range(2)) for row in result.propagation.covariance.matrix[:2])
            restrictions += result.restrictions + ('EXPLICIT_XY_SELECTION','CONDITIONAL_SYNTHETIC_JOINT_MODEL')
            source_hash = budget.digest((key,admitted.source_observation,delivery,
                CovarianceDeclaration(admitted.uncertainty.matrix,admitted.uncertainty.measurement_basis,admitted.uncertainty.uncertainty_provenance),
                admitted.correlation,admitted.derivation,source.operation_id,source.revision,source.operation,source.rigid,source.projected_uncertainty))
        _key(key)
        _require(key in assumptions.evidence_scope,'CORRESPONDENCE','key','Evidence must belong to declared synthetic correspondence')
        _frame(frame,'frame')
        for value in (acq,evaluation):
            _time(value,'time')
        if delivery is None:
            return Adaptation('deferred',None,(Diagnostic('AVAILABILITY_UNKNOWN','delivery','No delivery substituted'),))
        _time(delivery,'delivery')
        _require(acq.clock_domain == delivery.clock_domain == evaluation.clock_domain,'CLOCK_DOMAIN','time','Require explicit common inspection clock')
        _require(Fraction(acq.seconds) <= Fraction(delivery.seconds),'CAUSAL_ORDER','delivery','Delivery precedes acquisition')
        if max_age_seconds is not None:
            _number(max_age_seconds,'max_age_seconds')
            _require(max_age_seconds>=0,'AGE_POLICY','max_age_seconds','Require explicit nonnegative age or None')
        if Fraction(delivery.seconds)>Fraction(evaluation.seconds):
            return Adaptation('deferred',None,(Diagnostic('PENDING_DELIVERY','delivery','Not available at selected evaluation'),))
        if max_age_seconds is not None and Fraction(evaluation.seconds)-Fraction(acq.seconds)>Fraction(max_age_seconds):
            return Adaptation('deferred',None,(Diagnostic('STALE_MEASUREMENT','acquisition','Explicit maximum age exceeded'),))
        covariance,rank = _covariance(covariance,2)
        _require(rank==2,'SINGULAR_UNCERTAINTY','covariance','Require positive-definite measurement covariance')
        identity = budget.digest((source_hash,assumptions.scenario_id,assumptions.correspondence_id,
            assumptions.prior_id,assumptions.assumption_id,assumptions.evidence_scope))
        # Evaluation/age policy are eligibility decisions, not source identity.
        fingerprint = sha256(json.dumps([identity,[[x.numerator,x.denominator] for x in values],
            [[[x.numerator,x.denominator] for x in row] for row in covariance]],separators=(',',':')).encode()).hexdigest()
        return Adaptation('admitted',ReferenceMeasurement(source,assumptions,key,acq,delivery,evaluation,frame,
                          values,covariance,max_age_seconds,fingerprint,tuple(dict.fromkeys(restrictions))),())
    except (_Fault,_BatchBound,TypeError,ValueError,OverflowError,AttributeError) as error:
        return Adaptation('rejected',None,(_failure(error),))


@dataclass(frozen=True, slots=True)
class ReferencePrior:
    prior_id: str
    correspondence_id: str
    time: MeasurementTime
    frame: ReferenceFrame
    values: tuple[int | float, ...]  # All four values, including velocity, required.
    uncertainty: CovarianceDeclaration


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    start: MeasurementTime
    end: MeasurementTime
    model: 'ReferenceModel'


@dataclass(frozen=True, slots=True)
class ReferenceState:
    prior: ReferencePrior
    time: MeasurementTime
    values: tuple[Fraction, ...]
    covariance: tuple[tuple[Fraction, ...], ...]
    evaluation: MeasurementTime
    prior_sha256: str
    measurements: tuple[ReferenceMeasurement, ...] = ()
    predictions: tuple[PredictionRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceModel:
    acceleration_spectral_density: int | float  # m²/s³, equal independent axes
    revision: str


@dataclass(frozen=True, slots=True)
class EstimationStep:
    status: str
    state: ReferenceState | None
    diagnostics: tuple[Diagnostic, ...] = ()
    measurement: ReferenceMeasurement | None = None
    innovation: tuple[Fraction, ...] | None = None
    innovation_covariance: tuple[tuple[Fraction, ...], ...] | None = None
    nis: Fraction | None = None
    model: ReferenceModel | None = None


def initialize(prior: ReferencePrior) -> EstimationStep:
    try:
        _require(type(prior) is ReferencePrior,'PRIOR','prior','Require explicit four-component prior')
        _text(prior.prior_id,'prior_id'); _text(prior.correspondence_id,'correspondence_id')
        _time(prior.time,'prior.time'); _frame(prior.frame,'prior.frame')
        _require(type(prior.values) is tuple and len(prior.values)==4,'PRIOR','values','Velocity prior must be supplied, never inferred from one position')
        for x in prior.values:
            _number(x,'prior.values')
        values = tuple(_exact(x) for x in prior.values)
        check = validate_covariance(prior.uncertainty,state_basis(prior.frame))
        if check.diagnostics:
            return EstimationStep('rejected',None,check.diagnostics)
        p,_ = _covariance(check.covariance.matrix,4)
        identity = _Budget().digest((prior.prior_id,prior.correspondence_id,prior.time,prior.frame,prior.values,prior.uncertainty))
        return EstimationStep('initialized',ReferenceState(prior,prior.time,values,p,prior.time,identity))
    except (_Fault,TypeError,ValueError,OverflowError,AttributeError) as error:
        return EstimationStep('rejected',None,(_failure(error),))


def _state(state):
    _require(type(state) is ReferenceState,'STATE','state','Require reference state')
    initial = initialize(state.prior)
    _require(initial.status=='initialized','PRIOR','state.prior','Invalid prior')
    _require(type(state.prior_sha256) is str and state.prior_sha256==initial.state.prior_sha256,
             'PROVENANCE','state.prior','Prior differs from the pinned initial declaration')
    _time(state.time,'state.time')
    _time(state.evaluation,'state.evaluation')
    _require(state.evaluation.clock_domain==state.prior.time.clock_domain and
             Fraction(state.evaluation.seconds)>=Fraction(state.prior.time.seconds),
             'EVALUATION_CONTEXT','state.evaluation','Invalid inspection context')
    _require(state.time.clock_domain==state.prior.time.clock_domain and Fraction(state.time.seconds)>=Fraction(state.prior.time.seconds),
             'CLOCK_DOMAIN','state.time','Invalid state clock/time')
    _require(type(state.values) is tuple and len(state.values)==4,'STATE','values','Four state components required')
    for x in state.values:
        _require(type(x) is Fraction,'NUMERIC_TYPE','state.values','Derived state must remain exact rational')
        _exact(x)
    _covariance(state.covariance,4)
    _require(all(type(x) is Fraction for row in state.covariance for x in row),
             'NUMERIC_TYPE','state.covariance','Derived covariance must remain exact rational')
    _require(type(state.measurements) is tuple and len(state.measurements)<=MAX_MEASUREMENTS,'BOUND','measurements','Reference evidence capacity exceeded')
    _require(type(state.predictions) is tuple and len(state.predictions)<=MAX_PREDICTIONS,
             'BOUND','predictions','At most 32 nonzero prediction transitions')
    previous = state.prior.time
    for record in state.predictions:
        _require(type(record) is PredictionRecord,'PROVENANCE','predictions','Require prediction lineage')
        _time(record.start,'prediction.start'); _time(record.end,'prediction.end'); _model(record.model)
        _require(record.start==previous and record.end.clock_domain==previous.clock_domain and
                 0<Fraction(record.end.seconds)-Fraction(record.start.seconds)<=MAX_DT,
                 'PROVENANCE','predictions','Prediction lineage must be contiguous and ordered')
        previous = record.end
    _require(previous==state.time,'PROVENANCE','state.time','State time must match prediction lineage')
    seen=set()
    for m in state.measurements:
        _measurement(m)
        _key(m.evidence_key)
        _assumptions(m.assumptions)
        _time(m.acquisition,'measurement.acquisition'); _time(m.delivery,'measurement.delivery')
        _require(m.assumptions.prior_id==state.prior.prior_id and
                 m.assumptions.correspondence_id==state.prior.correspondence_id and
                 m.assumptions==state.measurements[0].assumptions and m.frame==state.prior.frame and
                 m.evidence_key in m.assumptions.evidence_scope and
                 m.acquisition.clock_domain==m.delivery.clock_domain==state.time.clock_domain and
                 Fraction(m.acquisition.seconds)<=Fraction(state.time.seconds) and
                 Fraction(m.delivery.seconds)<=Fraction(state.evaluation.seconds),
                 'PROVENANCE','state.measurements','Evidence history contradicts the prior, clock or inspection context')
        _require(m.evidence_key not in seen,'EVIDENCE_CONFLICT','state','Repeated state evidence')
        seen.add(m.evidence_key)


def _model(model):
    _require(type(model) is ReferenceModel,'MODEL','model','Require explicit white-acceleration model')
    _number(model.acceleration_spectral_density,'spectral_density'); _text(model.revision,'revision')
    _require(model.acceleration_spectral_density>=0,'MODEL','spectral_density','Require nonnegative m²/s³')


def predict(state: ReferenceState, time: MeasurementTime, model: ReferenceModel) -> EstimationStep:
    try:
        _state(state); _model(model); _time(time,'prediction.time')
        _require(time.clock_domain==state.time.clock_domain,'CLOCK_DOMAIN','prediction.time','No implicit clock mapping')
        dt = Fraction(time.seconds)-Fraction(state.time.seconds)
        _require(0<=dt<=MAX_DT,'TIME_ORDER','prediction.time','Require nonnegative dt <=86400 seconds')
        if dt==0:
            return EstimationStep('predicted',state,model=model)
        _require(len(state.predictions)<MAX_PREDICTIONS,'BOUND','predictions','Prediction capacity reached')
        f = ((1,0,dt,0),(0,1,0,dt),(0,0,1,0),(0,0,0,1))
        q = Fraction(model.acceleration_spectral_density)
        a,b,c = _exact(q*dt**3/3),_exact(q*dt**2/2),_exact(q*dt)
        noise = ((a,0,b,0),(0,a,0,b),(b,0,c,0),(0,b,0,c))
        values = tuple(row[0] for row in _mul(f,tuple((x,) for x in state.values)))
        p,_ = _covariance(_add(_mul(_mul(f,state.covariance),_transpose(f)),noise),4)
        return EstimationStep('predicted',replace(state,time=time,values=values,covariance=p,
            predictions=state.predictions+(PredictionRecord(state.time,time,model),)),model=model)
    except (_Fault,TypeError,ValueError,OverflowError,AttributeError) as error:
        return EstimationStep('rejected',state,(_failure(error),),model=model)


def _solve(s, rhs):
    """Exact 2x2 solve; condition bound is conservative infinity-norm product."""
    a,b,d = s[0][0],s[0][1],s[1][1]
    determinant = _exact(a*d-b*b)
    _require(a>0 and d>0 and determinant>0,'INNOVATION_SINGULAR','innovation','Positive-definite innovation required')
    norm = max(a+abs(b),d+abs(b))
    _require(norm*norm <= MAX_CONDITION*determinant,'INNOVATION_CONDITION','innovation','Innovation infinity-norm condition exceeds 1e12')
    return (_exact((d*rhs[0]-b*rhs[1])/determinant),_exact((a*rhs[1]-b*rhs[0])/determinant))


def _measurement(measurement):
    _require(type(measurement) is ReferenceMeasurement,'MEASUREMENT','measurement','Require validated reference measurement')
    _key(measurement.evidence_key); _assumptions(measurement.assumptions)
    _frame(measurement.frame,'measurement.frame')
    for value in (measurement.acquisition,measurement.delivery,measurement.evaluation):
        _time(value,'measurement.time')
    _text(measurement.fingerprint,'fingerprint')
    _require(len(measurement.fingerprint)==64 and all(c in '0123456789abcdef' for c in measurement.fingerprint),
             'PROVENANCE','fingerprint','Require exact SHA-256 identity')
    _require(type(measurement.restrictions) is tuple and len(measurement.restrictions)<=32,
             'BOUND','restrictions','Invalid restriction container')
    for flag in measurement.restrictions:
        _text(flag,'restrictions')
    _require(type(measurement.position) is tuple and len(measurement.position)==2 and
             all(type(x) is Fraction for x in measurement.position),'NUMERIC_TYPE','measurement.position','Require exact rational derived position')
    _covariance(measurement.covariance,2)
    _require(all(type(x) is Fraction for row in measurement.covariance for x in row),
             'NUMERIC_TYPE','measurement.covariance','Require exact rational derived covariance')
    checked = adapt_position(measurement.source,measurement.assumptions,measurement.max_age_seconds)
    _require(checked.status=='admitted' and checked.measurement==measurement,'MEASUREMENT','measurement','Revalidation failed; no forged geometry/covariance accepted')


def correct(state: ReferenceState, measurement: ReferenceMeasurement, model: ReferenceModel,
            evaluation: MeasurementTime | None = None) -> EstimationStep:
    """Atomic predict/correct. Failures retain the input state and consume no key."""
    try:
        _state(state); _model(model)
        _measurement(measurement)
        evaluation = measurement.evaluation if evaluation is None else evaluation
        _time(evaluation,'evaluation')
        _require(evaluation.clock_domain==state.evaluation.clock_domain==measurement.evaluation.clock_domain and
                 Fraction(evaluation.seconds)>=Fraction(state.evaluation.seconds),
                 'EVALUATION_CONTEXT','evaluation','Cannot reuse a posterior in an earlier or incompatible inspection context')
        reason = None
        if Fraction(measurement.delivery.seconds)>Fraction(evaluation.seconds):
            reason = ('PENDING_DELIVERY','delivery','Not exposed at selected evaluation')
        elif type(measurement.source) is GeometryRequest and Fraction(evaluation.seconds)>Fraction(measurement.evaluation.seconds):
            reason = ('EVALUATION_CONTEXT','evaluation','SF-1 original age policy is unavailable; require fresh admission for later evaluation')
        elif measurement.max_age_seconds is not None and Fraction(evaluation.seconds)-Fraction(measurement.acquisition.seconds)>Fraction(measurement.max_age_seconds):
            reason = ('STALE_MEASUREMENT','acquisition','Age at selected evaluation exceeds policy')
        if reason:
            return EstimationStep('deferred',state,(Diagnostic(*reason),),measurement=measurement,model=model)
        for previous in state.measurements:
            if previous.evidence_key==measurement.evidence_key:
                _require(previous.fingerprint==measurement.fingerprint,'EVIDENCE_CONFLICT','measurement','Same key, different content or assumptions')
                return EstimationStep('duplicate',state,measurement=measurement,model=model)
        _require(len(state.measurements)<MAX_MEASUREMENTS,'BOUND','measurements','Reference capacity reached')
        a = measurement.assumptions
        _require(a.prior_id==state.prior.prior_id and a.correspondence_id==state.prior.correspondence_id,
                 'CORRESPONDENCE','measurement','Only explicitly associated evidence for this prior')
        if state.measurements:
            _require(a==state.measurements[0].assumptions,'CORRELATION','measurement','Joint model cannot change during a reference trajectory')
        _require(measurement.frame==state.prior.frame,'FRAME_MISMATCH','measurement','Cartesian frames must match exactly')
        prediction = predict(state,measurement.acquisition,model)
        if prediction.status!='predicted':
            return EstimationStep(prediction.status,state,prediction.diagnostics,measurement,model=model)
        predicted = prediction.state
        p,r = predicted.covariance,measurement.covariance
        residual = tuple(_exact(measurement.position[i]-predicted.values[i]) for i in range(2))
        s = _add(tuple(tuple(p[i][j] for j in range(2)) for i in range(2)),r)
        k = tuple(_solve(s,(p[i][0],p[i][1])) for i in range(4))
        values = tuple(_exact(predicted.values[i]+_sum(k[i][j]*residual[j] for j in range(2))) for i in range(4))
        kh = _mul(k,H)
        left = tuple(tuple(_exact(I4[i][j]-kh[i][j]) for j in range(4)) for i in range(4))
        # Joseph form; exact arithmetic requires neither symmetrization nor jitter.
        covariance,_ = _covariance(_add(_mul(_mul(left,p),_transpose(left)),_mul(_mul(k,r),_transpose(k))),4)
        nis = _sum(x*y for x,y in zip(residual,_solve(s,residual)))
        updated = replace(predicted,values=values,covariance=covariance,evaluation=evaluation,
                          measurements=state.measurements+(measurement,))
        return EstimationStep('corrected',updated,measurement=measurement,innovation=residual,innovation_covariance=s,nis=nis,model=model)
    except (_Fault,TypeError,ValueError,OverflowError,AttributeError) as error:
        diagnostic = _failure(error)
        status = 'deferred' if diagnostic.code in ('INNOVATION_SINGULAR','INNOVATION_CONDITION','NUMERIC_BOUND') else 'rejected'
        return EstimationStep(status,state,(diagnostic,),measurement=measurement,model=model)


@dataclass(frozen=True, slots=True)
class ReferenceReplay:
    prior: ReferencePrior
    evaluation: MeasurementTime
    model: ReferenceModel
    steps: tuple[EstimationStep, ...]
    final: EstimationStep


def replay(prior: ReferencePrior, measurements: tuple[ReferenceMeasurement, ...], evaluation: MeasurementTime,
           model: ReferenceModel) -> ReferenceReplay:
    """Offline backtest: eligible deliveries only; acquisition/input-index order.

    No online rewind. At earlier evaluation times future deliveries remain hidden.
    Missing observations cause prediction only, never fabricated corrections.
    """
    initial = initialize(prior)
    try:
        _require(initial.status=='initialized','PRIOR','prior','Invalid explicit prior')
        _model(model); _time(evaluation,'evaluation')
        _require(evaluation.clock_domain==prior.time.clock_domain and Fraction(evaluation.seconds)>=Fraction(prior.time.seconds),
                 'TIME_ORDER','evaluation','Evaluation must be in prior clock and at/after prior')
        _require(type(measurements) is tuple and len(measurements)<=MAX_MEASUREMENTS,'BOUND','measurements','At most 16 observations per replay')
        for m in measurements:
            _measurement(m)
        ordered = sorted(enumerate(measurements),key=lambda item:(Fraction(item[1].acquisition.seconds),item[0]))
        state,steps = initial.state,[]
        for _,m in ordered:
            step = correct(state,m,model,evaluation=evaluation)
            steps.append(step)
            if step.status=='corrected':
                state = step.state
        return ReferenceReplay(prior,evaluation,model,tuple(steps),predict(replace(state,evaluation=evaluation),evaluation,model))
    except (_Fault,TypeError,ValueError,OverflowError,AttributeError) as error:
        return ReferenceReplay(prior,evaluation,model,(),EstimationStep('rejected',initial.state,(_failure(error),),model=model))
