"""SF-4 closed research contracts. No correspondence generation or estimator API."""
from collections.abc import Mapping
from dataclasses import dataclass, fields
from math import isfinite
import re
import json
from types import MappingProxyType
from typing import get_args, get_origin, Literal

from aegis.fusion.admission import AdmissionRequest, _CANONICAL_TYPES

MAX_BYTES = {'observations': 4 * 1024**2, 'truth': 1024**2,
             'hypotheses': 1024**2, 'report': 8 * 1024**2}
SOURCE_TYPES = {c.__name__: c for c in (AdmissionRequest,) + _CANONICAL_TYPES}
KINDS = {x: 'offline_correspondence_' + y for x, y in
         [('observations', 'observations'), ('truth', 'truth'),
          ('hypotheses', 'hypotheses'), ('report', 'evaluation')]}
METRICS = ('conditional_resolved_accuracy', 'resolved_coverage', 'strict_correctness',
           'unresolved_fraction', 'ambiguous_fraction', 'eligible_data_coverage', 'known_truth_coverage')
CODE_GROUPS = (
 ('io/schema', 'IO_ERROR UTF8 SCHEMA VERSION BOUND DIGEST_MISMATCH'),
 ('references', 'UNKNOWN_REFERENCE GRAPH_CYCLE GRAPH_TYPE EVIDENCE_CONFLICT REFERENCE_MEMBERSHIP_CONFLICT CONTEXT_POLICY_CONFLICT TRUTH_CONFLICT HYPOTHESIS_CONFLICT TERMINAL_CONFLICT'),
 ('source', 'SOURCE_INVALID CLOCK_MAPPING_INVALID COMPLETION_CONFLICT'),
 ('source notes', 'DUPLICATE_EVIDENCE DUPLICATE_HYPOTHESIS UNCERTAINTY_UNKNOWN SINGULAR_UNCERTAINTY'),
 ('source eligibility', 'SCOPE_EXCLUDED CLOCK_MAPPING_REQUIRED DELIVERY_CLOCK_UNSUPPORTED ACQUISITION_UNKNOWN DELIVERY_UNKNOWN TEMPORAL_ORDER_AMBIGUOUS PENDING_DELIVERY STALE_MEASUREMENT'),
 ('hypothesis', 'MISSING_HYPOTHESIS HYPOTHESIS_UNRESOLVED HYPOTHESIS_PENDING HYPOTHESIS_AVAILABILITY_UNKNOWN HYPOTHESIS_UNALIGNED HYPOTHESIS_CAUSAL_CONFLICT HYPOTHESIS_CLOCK_UNSUPPORTED HYPOTHESIS_CUTOFF_FUTURE'),
 ('hypothesis view', 'INPUT_VIEW_MISMATCH'),
 ('comparison', 'TRUTH_UNAVAILABLE TRUTH_AMBIGUOUS LABEL_MATCH LABEL_MISMATCH CAUSAL_PROVENANCE_UNVERIFIED'),
 ('lifecycle', 'ACQUISITION_UNCONFIRMED ACQUISITION_UNAVAILABLE ACQUISITION_PENDING COMPLETION_UNKNOWN UNKNOWN_MEMBER_TRUTH NOT_SCHEDULED NOT_OBSERVABLE STALE_AT_EVALUATION'),
 ('continuity', 'OPPORTUNITY_UNASSESSED IDENTITY_SPLIT LABEL_COLLISION CONTAMINATED_LABEL MIXED_STEP'),
 ('summary', 'EMPTY_POPULATION OUTPUT_BOUND'))
CODES = tuple(code for _, group in CODE_GROUPS for code in group.split())


class ContractError(ValueError):
    def __init__(self, code, path='', explanation='Invalid research declaration'):
        self.code, self.path, self.explanation = code, path[:256], explanation[:512]
        super().__init__(f'{code}: {self.path}: {self.explanation}')


def require(condition, code='SCHEMA', path='', explanation='Invalid research declaration'):
    if not condition:
        raise ContractError(code, path, explanation)


@dataclass(frozen=True, slots=True, eq=False)
class FrozenMap(Mapping):
    """Recursively immutable validated JSON; lookup table cannot be mutated."""
    _values: Mapping

    def __init__(self, values):
        require(isinstance(values, Mapping), path='immutable_object')
        object.__setattr__(self, '_values', freeze(values)._values)

    def __getitem__(self, key): return self._values[key]
    def __iter__(self): return iter(self._values)
    def __len__(self): return len(self._values)


def freeze(value):
    """Detach every supported mapping/sequence, including caller-owned tuples.

    Parsing bounds do not protect the in-memory request API. Apply the same
    value-node/depth budget here and reject cycles before Python recursion fails.
    """
    active=set(); nodes=0
    def visit(item,depth):
        nonlocal nodes
        nodes+=1
        require(depth<=16 and nodes<=100000,'BOUND','immutable_input')
        if type(item) is FrozenMap:
            # Reusing an immutable subtree must still account for its serialized
            # depth/node cost; otherwise callers can compose over-budget trees.
            identity=id(item)
            require(identity not in active,'SCHEMA','immutable_input','Cyclic JSON value')
            active.add(identity)
            for child in item.values(): visit(child,depth+1)
            active.remove(identity)
            return item
        if isinstance(item,Mapping) or type(item) in (tuple,list):
            identity=id(item)
            require(identity not in active,'SCHEMA','immutable_input','Cyclic JSON value')
            active.add(identity)
            if isinstance(item,Mapping):
                values={k:visit(v,depth+1) for k,v in item.items()}
                result=object.__new__(FrozenMap)
                object.__setattr__(result,'_values',MappingProxyType(values))
            else: result=tuple(visit(v,depth+1) for v in item)
            active.remove(identity)
            return result
        return item
    return visit(value,0)


def thaw(value):
    if isinstance(value, Mapping): return {k: thaw(v) for k, v in value.items()}
    if type(value) is tuple: return [thaw(x) for x in value]
    return value


def scalar(value):
    require(type(value) in (int, float), path='scalar')
    require(type(value) is int or isfinite(value), path='scalar')
    # Existing SF-1 numeric policy also applies to all wire scalar leaves.
    from aegis.fusion.uncertainty import _number
    try: _number(value, 'scalar')
    except ValueError as e: raise ContractError('SCHEMA', 'scalar', 'Outside SF-1 numeric limits') from e
    return {'kind': 'int' if type(value) is int else 'float',
            'value': str(value) if type(value) is int else value.hex()}


def unscalar(value):
    require(isinstance(value, Mapping) and set(value) == {'kind', 'value'}, path='scalar')
    kind, text = value['kind'], value['value']
    require(type(text) is str and len(text) <= 512, path='scalar.value')
    try:
        result = int(text) if kind == 'int' else float.fromhex(text) if kind == 'float' else None
        require(result is not None and scalar(result) == dict(value), path='scalar')
    except (ValueError, OverflowError) as e:
        raise ContractError('SCHEMA', 'scalar', 'Noncanonical or nonfinite scalar') from e
    return result


def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def arr(items, cap=1024, minimum=0, unique=False):
    out = {'type': 'array', 'items': items, 'maxItems': cap, 'minItems': minimum}
    if unique: out['uniqueItems'] = True
    return out


def nullable(schema): return {'anyOf': [schema, {'type': 'null'}]}
def enum(*values): return {'enum': list(values)}
def ref(name): return {'$ref': '#/$defs/' + name}
IDENT = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': r'^(?=.*\S)[^\u0000-\u001f\u007f-\u009f]+(?![\s\S])', 'x-byte-limit': 128, 'x-identifier': True}
TEXT = {'type': 'string', 'maxLength': 512, 'x-byte-limit': 512}
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 100000}
DIGEST = {'type': 'string', 'minLength': 64, 'maxLength': 64, 'pattern': r'^[0-9a-f]{64}(?![\s\S])'}


def _field_schema(annotation):
    """Wire shape from the fixed audited source types, never a wire import name."""
    if annotation is int: return ref('IntScalar')
    if annotation is float: return ref('Scalar')
    if annotation is str: return IDENT
    if annotation is type(None): return {'type': 'null'}
    if annotation in SOURCE_TYPES.values(): return ref('SourceRef')
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Literal: return enum(*args)
    if origin is tuple:
        if args[-1] is Ellipsis: return arr(_field_schema(args[0]), 16)
        return {'type': 'array', 'prefixItems': [_field_schema(a) for a in args], 'items': False, 'minItems': len(args), 'maxItems': len(args)}
    if args: return {'anyOf': [_field_schema(a) for a in args]}
    # SensorObservation's generic measurement is the one explicit audited union.
    return ref('SourceRef')


def schema_definitions():
    d = {}
    d['Scalar'] = {'oneOf': [obj(kind={'const': 'int'}, value={'type': 'string', 'pattern': r'^(0|-?[1-9][0-9]*)(?![\s\S])', 'maxLength': 512}), obj(kind={'const': 'float'}, value={'type': 'string', 'maxLength': 512, 'pattern': r'^-?0x(?:0\.0p\+0|[01]\.[0-9a-f]{13}p[+-](?:0|[1-9][0-9]*))(?![\s\S])'})]}
    d['IntScalar'] = d['Scalar']['oneOf'][0]
    d['Time'] = obj(seconds=ref('Scalar'), clock_domain=IDENT)
    d['Frame'] = obj(frame_id=IDENT)
    d['EvidenceKey'] = obj(sensor_id=IDENT, source_session_id=IDENT, observation_id=IDENT)
    d['Generator'] = obj(generator_id=IDENT, revision=IDENT, configuration_sha256=DIGEST)
    d['AssertionProvenance'] = obj(assertion_id=IDENT, revision=IDENT)
    d['LineageEntry'] = obj(operation_id=IDENT, revision=IDENT, configuration_sha256=DIGEST, input_sha256=DIGEST)
    d['DerivedFrom'] = obj(dataset_sha256=DIGEST, evidence_key=ref('EvidenceKey'))
    d['Provenance'] = obj(generator=ref('Generator'), origin=enum('synthetic_raw', 'synthetic_impaired'), upstream_source_sha256=nullable(DIGEST), derived_from=nullable(ref('DerivedFrom')), lineage=arr(ref('LineageEntry'),16))
    d['SourceRef'] = obj(ref=IDENT)
    nodes = []
    for name, cls in SOURCE_TYPES.items():
        fs = {f.name: TEXT if f.name == 'reason' else _field_schema(f.type) for f in fields(cls)}
        d['Fields' + name] = obj(**fs)
        nodes.append(obj(object_id=IDENT, type={'const': name}, fields=ref('Fields' + name)))
    d['SourceNode'] = {'oneOf': nodes}
    d['SourceGraph'] = obj(root_ref=IDENT, objects=arr(ref('SourceNode'),128,1))
    d['Mapping'] = obj(**{f.name: IDENT if f.type is str else ref('Scalar') for f in fields(SOURCE_TYPES['BoundedClockMapping'])})
    d['ClockMapping'] = obj(mapping_id=IDENT, revision=IDENT, mapping=ref('Mapping'))
    d['Step'] = obj(step_id=IDENT, start=ref('Time'), end=ref('Time'))
    d['Occurrence'] = obj(occurrence_id=IDENT, step_ref=IDENT, acquisition_ref=IDENT, admission_request=ref('SourceGraph'), acquisition_mapping_ref=nullable(IDENT), occurrence_received_at=nullable(ref('Time')), provenance=ref('Provenance'))
    d['AcquisitionEnvelope'] = obj(acquisition_ref=IDENT, step_ref=IDENT, sensor_id=IDENT, source_session_id=IDENT, acquisition_id=IDENT, acquisition_time=nullable(ref('Time')), status=enum('completed','unavailable','unconfirmed'), observation_occurrence_refs=arr(IDENT,1024,unique=True), reason=nullable(TEXT), acquisition_mapping_ref=nullable(IDENT), available_at=nullable(ref('Time')), completeness_provenance=ref('AssertionProvenance'))
    d['Entity'] = obj(truth_entity_id=IDENT, episode_id=IDENT)
    d['TruthLabel'] = {'oneOf': [obj(evidence_key=ref('EvidenceKey'),status={'const': 'known'},truth_entity_id=IDENT),obj(evidence_key=ref('EvidenceKey'),status={'const': 'ambiguous'},candidates=arr(IDENT,8,2,True)),obj(evidence_key=ref('EvidenceKey'),status={'const': 'unavailable'},reason=TEXT)]}
    d['Opportunity'] = {'oneOf':[obj(truth_entity_id=IDENT,step_ref=IDENT,expectation={'const':'expected'},required_acquisition_refs=arr(IDENT,8,1,True)),obj(truth_entity_id=IDENT,step_ref=IDENT,expectation={'const':'not_observable'},required_acquisition_refs=arr(IDENT,0))]}
    d['Terminal'] = obj(truth_entity_id=IDENT,step_ref=IDENT,visible_at=ref('Time'),provenance=ref('AssertionProvenance'))
    acquisition=d['AcquisitionEnvelope']['properties']
    branches=[]
    for status in ('completed','unavailable','unconfirmed'):
        variants=(False,) if status=='completed' else (False,True)
        for unknown_time in variants:
            properties=dict(acquisition)
            properties.update(status={'const':status},
                acquisition_time={'type':'null'} if unknown_time else ref('Time'),
                acquisition_mapping_ref={'type':'null'} if unknown_time else nullable(IDENT),
                reason={'type':'null'} if status=='completed' else {**TEXT,'minLength':1})
            if status!='completed': properties['observation_occurrence_refs']=arr(IDENT,0)
            branches.append(obj(**properties))
    d['AcquisitionEnvelope']={'oneOf':branches}
    d['ProducerProvenance'] = obj(producer_id=IDENT,revision=IDENT,alignment_protocol_id=nullable(IDENT))
    d['Alignment'] = obj(external_label=IDENT,truth_entity_id=IDENT)
    common = dict(evidence_key=ref('EvidenceKey'),decision_available_at=nullable(ref('Time')),information_cutoff=nullable(ref('Time')),input_view_sha256=nullable(DIGEST))
    decisions=[]
    for cutoff_known in (False,True):
        contextual=dict(common,information_cutoff=ref('Time') if cutoff_known else {'type':'null'},
                        input_view_sha256=DIGEST if cutoff_known else {'type':'null'})
        decisions.extend([obj(**contextual,status={'const':'assigned'},external_label=IDENT),
                          obj(**contextual,status={'const':'ambiguous'},candidates=arr(IDENT,8,2,True)),
                          obj(**contextual,status={'const':'unresolved'},reason=TEXT)])
    d['Decision']={'oneOf':decisions}
    d['Policy'] = obj(policy_id=IDENT,revision=IDENT,additional_max_age_seconds=nullable(ref('Scalar')))
    d['OpportunityKey'] = obj(truth_entity_id=IDENT,step_ref=IDENT)
    d['Scope'] = obj(evidence_keys=nullable(arr(ref('EvidenceKey'),1024,unique=True)),opportunity_keys=nullable(arr(ref('OpportunityKey'),4096,unique=True)))
    d['ExpectedDigests'] = obj(dataset_sha256=DIGEST,truth_sha256=DIGEST,hypotheses_sha256=DIGEST)
    d['EvaluationRequest'] = obj(schema_version={'const':1},evaluation=ref('Time'),expected_digests=ref('ExpectedDigests'),policy=ref('Policy'),scope=ref('Scope'))
    d['Ratio'] = obj(numerator=COUNT,denominator={'type':'integer','minimum':1,'maximum':100000})
    d['Metrics'] = obj(**{k:nullable(ref('Ratio')) for k in METRICS})
    d['SourceDiagnostic'] = obj(code=IDENT,path={'type':'string','maxLength':256,'x-byte-limit':256},explanation=TEXT)
    d['DiagnosticReference'] = obj(artifact=enum('observations','truth','hypotheses','request','report'),collection=nullable(enum('steps','clock_mappings','occurrences','acquisitions','entity_catalog','evidence_labels','opportunities','terminal_annotations','external_label_catalog','label_alignment','decisions','evidence_rows','lifecycle_rows','entities','labels','diagnostics')),index=nullable(COUNT))
    reference_branches=[]
    collections={'observations':{'steps':1024,'clock_mappings':64,'occurrences':1024,'acquisitions':1024},
        'truth':{'entity_catalog':128,'evidence_labels':1024,'opportunities':4096,'terminal_annotations':128},
        'hypotheses':{'external_label_catalog':256,'label_alignment':256,'decisions':1024},
        'request':{},'report':{'evidence_rows':1024,'lifecycle_rows':4224,'entities':128,'labels':256,'diagnostics':256}}
    for artifact,arrays in collections.items():
        reference_branches.append(obj(artifact={'const':artifact},collection={'type':'null'},index={'type':'null'}))
        for collection,cap in arrays.items():
            reference_branches.append(obj(artifact={'const':artifact},collection={'const':collection},index={'type':'integer','minimum':0,'maximum':cap-1}))
    d['DiagnosticReference']={'oneOf':reference_branches}
    d['Diagnostic'] = obj(code=enum(*CODES),stage=enum(*(x for x,_ in CODE_GROUPS)),severity=enum('info','limitation','error'),reference=nullable(ref('DiagnosticReference')),path={'type':'string','maxLength':256,'x-byte-limit':256},explanation=TEXT)
    diagnostic=d['Diagnostic']['properties']
    d['Diagnostic']={'oneOf':[obj(**dict(diagnostic,stage={'const':stage},code=enum(*codes.split()))) for stage,codes in CODE_GROUPS]}
    d['Bindings'] = obj(**{k:nullable(DIGEST) for k in ('dataset_sha256','truth_sha256','hypotheses_sha256','policy_sha256')})
    d['EvidenceRow'] = obj(evidence_key=ref('EvidenceKey'),occurrence_refs=arr(IDENT),step_ref=IDENT,acquisition_ref=IDENT,source_ref=obj(primary_occurrence_ref=IDENT),truth_ref=COUNT,hypothesis_refs=arr(COUNT),timing_status=enum('eligible','ineligible'),temporal_reason=nullable(enum(*CODE_GROUPS[4][1].split())),admission_status=enum('admitted','deferred','rejected','not_evaluated'),source_diagnostics=arr(ref('SourceDiagnostic'),8),restrictions=nullable(arr(IDENT,32)),uncertainty_status=enum('known_psd','unknown'),truth_status=enum('known','ambiguous','unavailable'),hypothesis_status=enum('assigned','ambiguous','unresolved','missing','pending','unaligned','invalid_context'),comparison_status=enum('correct','incorrect','ambiguous','unresolved','unscored'),reason_codes=arr(enum(*CODES),len(CODES),unique=True),continuity_eligibility=enum('assessed','unassessed'))
    d['LifecycleRow'] = obj(truth_entity_id=IDENT,step_ref=IDENT,status=enum('observed','temporarily_missing','resumed','ended','unknown','not_observable'),reason_codes=arr(enum(*CODES),len(CODES),unique=True),opportunity_ref=nullable(COUNT),evidence_refs=arr(ref('EvidenceKey')))
    entity = dict(truth_entity_id=IDENT,**{k:COUNT for k in ('assessed_steps','resolved_steps','assessed_gaps','unassessed_opportunities','not_observable_steps','unassessed_breaks','fragment_count','same_label_links','changed_label_links','split_steps','mixed_steps','confirmed_reappearances')},block_segment_counts=arr(COUNT,4096),resolved_step_coverage=nullable(ref('Ratio')),identity_retention=nullable(ref('Ratio')))
    d['EntitySummary'] = obj(**entity)
    d['LabelSummary'] = obj(external_label=IDENT,assigned_known_truth_count=COUNT,truth_support=arr(IDENT,128,unique=True),contaminated={'type':'boolean'},collision_step_count=COUNT,adjacent_step_identity_changes=COUNT,assessed_adjacent_links=COUNT)
    d['Continuity'] = obj(entities=arr(ref('EntitySummary'),128),labels=arr(ref('LabelSummary'),256))
    counts='occurrence_count logical_evidence_count in_scope_count eligible_count known_truth_count duplicate_occurrence_count excluded_scope_count truth_ambiguous_count truth_unavailable_count correct_count incorrect_count ambiguous_count unresolved_count'.split()
    d['Populations'] = obj(**{k:COUNT for k in counts},excluded_by_reason=arr(obj(reason_code=enum(*CODE_GROUPS[4][1].split()),count=COUNT),len(CODES)))
    return d


def build_schemas():
    d=schema_definitions()
    roots={
      'observations':obj(dataset_id=IDENT,revision=IDENT,observation_view_id=IDENT,generator=ref('Generator'),scenario_clock_domain=IDENT,steps=arr(ref('Step')),clock_mappings=arr(ref('ClockMapping'),64),occurrences=arr(ref('Occurrence')),acquisitions=arr(ref('AcquisitionEnvelope')),provenance=ref('Provenance')),
      'truth':obj(dataset_sha256=DIGEST,truth_id=IDENT,revision=IDENT,entity_catalog=arr(ref('Entity'),128),evidence_labels=arr(ref('TruthLabel')),opportunities=arr(ref('Opportunity'),4096),terminal_annotations=arr(ref('Terminal'),128)),
      'hypotheses':obj(dataset_sha256=DIGEST,hypothesis_id=IDENT,revision=IDENT,producer_provenance=ref('ProducerProvenance'),external_label_catalog=arr(IDENT,256,unique=True),label_alignment=arr(ref('Alignment'),256),decisions=arr(ref('Decision'))),
      'report':obj(status=enum('complete','incomplete','rejected'),bindings=ref('Bindings'),evaluation=nullable(ref('Time')),policy=nullable(ref('Policy')),scope=nullable(ref('Scope')),populations=nullable(ref('Populations')),evidence_rows=arr(ref('EvidenceRow')),lifecycle_rows=arr(ref('LifecycleRow'),4224),continuity=ref('Continuity'),metrics=nullable(ref('Metrics')),diagnostics=arr(ref('Diagnostic'),256),diagnostics_dropped=COUNT)}
    result={}
    def external(value):
        if isinstance(value,dict):
            return {k: ('correspondence-observations-v1.schema.json'+v if k=='$ref' else external(v)) for k,v in value.items()}
        if isinstance(value,list): return [external(v) for v in value]
        return value
    for name,root in roots.items():
        root['properties'].update(schema_version={'const':1},artifact_kind={'const':KINDS[name]})
        root['required'] += ['schema_version','artifact_kind']
        if name=='report':
            successful=dict(root['properties'])
            successful.update(status=enum('complete','incomplete'),evaluation=ref('Time'),policy=ref('Policy'),scope=ref('Scope'),populations=ref('Populations'),metrics=ref('Metrics'))
            rejected=dict(root['properties'])
            rejected.update(status={'const':'rejected'},metrics={'type':'null'},evidence_rows=arr(ref('EvidenceRow'),0),lifecycle_rows=arr(ref('LifecycleRow'),0),continuity=obj(entities=arr(ref('EntitySummary'),0),labels=arr(ref('LabelSummary'),0)))
            root['oneOf']=[obj(**successful),obj(**rejected)]
        root.update({'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'correspondence-'+name+'-v1.schema.json',
                     '$comment':'Closed wire shapes; SF-4 runtime validation is also mandatory for UTF-8 byte limits, scalar canonicality, graph/reference integrity, source admissibility, covariance, temporal rules and report consistency. No remote references.'})
        if name=='observations': root['$defs']=d
        else: root=external(root)
        result[name]=root
    return result


SCHEMAS=build_schemas()
DEFINITIONS=SCHEMAS['observations']['$defs']


def validate_shape(value, schema, path=''):
    """Dependency-free validator for the fixed schema vocabulary above only."""
    if '$ref' in schema:
        target=schema['$ref']
        require(target.startswith('#/$defs/') or target.startswith('correspondence-observations-v1.schema.json#/$defs/'),path=path)
        return validate_shape(value,DEFINITIONS[target.split('/')[-1]],path)
    for keyword in ('oneOf','anyOf'):
        if keyword in schema:
            matches=0
            for branch in schema[keyword]:
                try: validate_shape(value,branch,path); matches+=1
                except ContractError: pass
            require(matches==1 if keyword=='oneOf' else matches>=1,path=path)
            return
    if 'const' in schema: require(type(value) is type(schema['const']) and value==schema['const'],path=path)
    if 'enum' in schema: require(any(type(value) is type(x) and value==x for x in schema['enum']),path=path)
    kind=schema.get('type')
    if kind=='object':
        require(isinstance(value,Mapping) and set(value)==set(schema['required']),path=path)
        for k,v in value.items(): validate_shape(v,schema['properties'][k],path+'/'+k)
    elif kind=='array':
        require(type(value) in (tuple,list),path=path)
        require(schema.get('minItems',0)<=len(value)<=schema['maxItems'],'BOUND',path)
        for i,v in enumerate(value):
            rule=schema['prefixItems'][i] if 'prefixItems' in schema else schema['items']
            validate_shape(v,rule,path+'/'+str(i))
        if schema.get('uniqueItems'): require(len({json.dumps(thaw(v),sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False) for v in value})==len(value),path=path)
    elif kind=='string':
        require(type(value) is str,path=path)
        try: size=len(value.encode('utf-8'))
        except UnicodeError: raise ContractError('UTF8',path) from None
        require(schema.get('minLength',0)<=len(value)<=schema.get('maxLength',100000),path=path)
        require(size<=schema.get('x-byte-limit',100000),'BOUND',path)
        if schema.get('x-identifier'): require(value.strip() and not any(ord(c)<32 or 127<=ord(c)<=159 for c in value),path=path)
        if 'pattern' in schema: require(re.fullmatch(schema['pattern'],value) is not None,path=path)
    elif kind=='integer': require(type(value) is int and schema['minimum']<=value<=schema['maximum'],path=path)
    elif kind=='boolean': require(type(value) is bool,path=path)
    elif kind=='null': require(value is None,path=path)


def validate_report(report):
    """Report shape plus independently checkable population/count invariants."""
    validate_shape(report,SCHEMAS['report'])
    if report['status']=='rejected': return
    p=report['populations']; m=report['metrics']
    require(p['occurrence_count']==p['logical_evidence_count']+p['duplicate_occurrence_count'],path='populations.occurrences')
    require(p['logical_evidence_count']==p['in_scope_count']+p['excluded_scope_count'],path='populations.scope')
    require(p['in_scope_count']==p['eligible_count']+sum(x['count'] for x in p['excluded_by_reason']),path='populations.exclusions')
    reasons=[x['reason_code'] for x in p['excluded_by_reason']]
    require(reasons==sorted(set(reasons)) and 'SCOPE_EXCLUDED' not in reasons,path='populations.excluded_by_reason')
    require(p['eligible_count']==p['known_truth_count']+p['truth_ambiguous_count']+p['truth_unavailable_count'],path='populations.truth')
    c,i,a,u=(p[k+'_count'] for k in ('correct','incorrect','ambiguous','unresolved'))
    n=p['known_truth_count']; require(n==c+i+a+u,path='populations.outcomes')
    pairs=((c,c+i),(c+i,n),(c,n),(u,n),(a,n),(p['eligible_count'],p['in_scope_count']),(n,p['eligible_count']))
    for name,(num,den) in zip(METRICS,pairs):
        value=None if den==0 else {'numerator':num,'denominator':den}
        require(m[name]==value,path='metrics.'+name)
    require(len(report['evidence_rows'])==p['logical_evidence_count'],path='evidence_rows')
    require(sum(len(x['occurrence_refs']) for x in report['evidence_rows'])==p['occurrence_count'],'BOUND','occurrence_refs')
    require(sum(len(x['hypothesis_refs']) for x in report['evidence_rows'])<=1024,'BOUND','hypothesis_refs')
    require(sum(len(x['evidence_refs']) for x in report['lifecycle_rows'])<=1024,'BOUND','lifecycle.evidence_refs')
    require(sum(len(x['block_segment_counts']) for x in report['continuity']['entities'])<=4096,'BOUND','blocks')
    require(sum(len(x['truth_support']) for x in report['continuity']['labels'])<=1024,'BOUND','truth_support')
    # Totals are not sufficient: rows must describe the same population.
    rows=report['evidence_rows']; seen_keys=set(); seen_occurrences=set(); hypothesis_refs=[]
    row_counts={k:0 for k in ('eligible_count','known_truth_count','excluded_scope_count','truth_ambiguous_count','truth_unavailable_count','correct_count','incorrect_count','ambiguous_count','unresolved_count')}
    exclusions={}; truth_refs=set()
    def evidence_identity(key):
        return tuple(key[name] for name in ('sensor_id','source_session_id','observation_id'))
    row_index={}
    for row in rows:
        key=evidence_identity(row['evidence_key'])
        require(key not in seen_keys,path='evidence_rows.evidence_key')
        seen_keys.add(key); row_index[key]=row
        require(row['occurrence_refs'] and row['source_ref']['primary_occurrence_ref']==row['occurrence_refs'][0],path='evidence_rows.source_ref')
        for occurrence in row['occurrence_refs']:
            require(occurrence not in seen_occurrences,path='evidence_rows.occurrence_refs')
            seen_occurrences.add(occurrence)
        hypothesis_refs.extend(row['hypothesis_refs']); truth_refs.add(row['truth_ref'])
        outcome=row['comparison_status']; hypothesis=row['hypothesis_status']
        if outcome in ('correct','incorrect'): require(hypothesis=='assigned',path='evidence_rows.hypothesis_status')
        elif outcome=='ambiguous': require(hypothesis=='ambiguous',path='evidence_rows.hypothesis_status')
        elif outcome=='unresolved': require(hypothesis in ('unresolved','missing','pending','unaligned','invalid_context'),path='evidence_rows.hypothesis_status')
        require(('LABEL_MATCH' in row['reason_codes'])==(outcome=='correct') and ('LABEL_MISMATCH' in row['reason_codes'])==(outcome=='incorrect'),path='evidence_rows.reason_codes')
        if row['uncertainty_status']=='unknown': require(row['admission_status']!='admitted',path='evidence_rows.admission_status')
        eligible=row['timing_status']=='eligible'
        require(eligible==(row['temporal_reason'] is None),path='evidence_rows.temporal_reason')
        if eligible:
            row_counts['eligible_count']+=1
            if row['truth_status']=='known':
                row_counts['known_truth_count']+=1
                require(row['comparison_status']!='unscored',path='evidence_rows.comparison_status')
                row_counts[row['comparison_status']+'_count']+=1
            else:
                row_counts['truth_'+row['truth_status']+'_count']+=1
                require(row['comparison_status']=='unscored',path='evidence_rows.comparison_status')
        else:
            require(row['comparison_status']=='unscored',path='evidence_rows.comparison_status')
            reason=row['temporal_reason']
            if reason=='SCOPE_EXCLUDED': row_counts['excluded_scope_count']+=1
            else: exclusions[reason]=exclusions.get(reason,0)+1
    require(truth_refs==set(range(len(rows))),path='evidence_rows.truth_ref')
    require(len(hypothesis_refs)==len(set(hypothesis_refs)) and set(hypothesis_refs)==set(range(len(hypothesis_refs))),path='evidence_rows.hypothesis_refs')
    require(all(p[k]==v for k,v in row_counts.items()),path='populations.rows')
    require(exclusions=={x['reason_code']:x['count'] for x in p['excluded_by_reason']},path='populations.excluded_by_reason')
    lifecycle_keys=set(); lifecycle_evidence=set(); reappearances={}
    for row in report['lifecycle_rows']:
        key=(row['truth_entity_id'],row['step_ref'])
        require(key not in lifecycle_keys,path='lifecycle_rows')
        lifecycle_keys.add(key)
        if row['status']=='resumed': reappearances[row['truth_entity_id']]=reappearances.get(row['truth_entity_id'],0)+1
        require(row['opportunity_ref'] is not None or row['status']=='ended',path='lifecycle_rows.opportunity_ref')
        present=row['status'] in ('observed','resumed')
        require(present==bool(row['evidence_refs']),path='lifecycle_rows.evidence_refs')
        for evidence in row['evidence_refs']:
            identity=evidence_identity(evidence)
            require(identity in row_index and identity not in lifecycle_evidence,path='lifecycle_rows.evidence_refs')
            source=row_index[identity]
            require(source['truth_status']=='known' and source['step_ref']==row['step_ref'],path='lifecycle_rows.evidence_refs')
            lifecycle_evidence.add(identity)
    entity_names=[x['truth_entity_id'] for x in report['continuity']['entities']]
    require(entity_names==sorted(set(entity_names),key=lambda x:x.encode()),path='continuity.entities.order')
    entities=set()
    for entity in report['continuity']['entities']:
        require(entity['truth_entity_id'] not in entities,path='continuity.entities')
        entities.add(entity['truth_entity_id'])
        assessed,resolved=entity['assessed_steps'],entity['resolved_steps']
        require(assessed==resolved+entity['assessed_gaps'],path='continuity.assessed_steps')
        require(sum(entity['block_segment_counts'])<=resolved,path='continuity.block_segment_counts')
        require(entity['fragment_count']==sum(max(0,n-1) for n in entity['block_segment_counts']),path='continuity.fragment_count')
        require(entity['split_steps']<=entity['assessed_gaps'] and entity['mixed_steps']<=assessed,path='continuity.steps')
        same,changed=entity['same_label_links'],entity['changed_label_links']
        require(same+changed<=max(0,resolved-sum(n>0 for n in entity['block_segment_counts'])),path='continuity.links')
        coverage=None if assessed==0 else {'numerator':resolved,'denominator':assessed}
        retention=None if same+changed==0 else {'numerator':same,'denominator':same+changed}
        require(entity['resolved_step_coverage']==coverage and entity['identity_retention']==retention,path='continuity.ratios')
        require(entity['confirmed_reappearances']==reappearances.get(entity['truth_entity_id'],0),path='continuity.confirmed_reappearances')
    label_names=[x['external_label'] for x in report['continuity']['labels']]
    require(label_names==sorted(set(label_names),key=lambda x:x.encode()),path='continuity.labels.order')
    labels=set(); total_claims=0
    for label in report['continuity']['labels']:
        require(label['external_label'] not in labels,path='continuity.labels')
        labels.add(label['external_label'])
        require(tuple(label['truth_support'])==tuple(sorted(set(label['truth_support']),key=lambda x:x.encode())),path='continuity.truth_support')
        count=label['assigned_known_truth_count']; total_claims+=count
        require(1<=len(label['truth_support'])<=count<=n,path='continuity.truth_support.count')
        require(label['collision_step_count']<=count//2 and label['assessed_adjacent_links']<=count-1,path='continuity.label_counts')
        require(label['contaminated']==(len(label['truth_support'])>=2),path='continuity.contaminated')
        require(label['adjacent_step_identity_changes']<=label['assessed_adjacent_links'],path='continuity.label_links')

    require(c+i<=total_claims<=n,path='continuity.assigned_known_truth_count')
    stage_order={stage:i for i,(stage,_) in enumerate(CODE_GROUPS)}
    artifact_order={name:i for i,name in enumerate(('observations','truth','hypotheses','request','report'))}
    diagnostic_order=[]
    for diagnostic in report['diagnostics']:
        reference=diagnostic['reference'] or {}
        collection=reference.get('collection'); index=reference.get('index')
        require((collection is None)==(index is None),path='diagnostics.reference')
        allowed={'observations':('steps','clock_mappings','occurrences','acquisitions'),
                 'truth':('entity_catalog','evidence_labels','opportunities','terminal_annotations'),
                 'hypotheses':('external_label_catalog','label_alignment','decisions'),
                 'request':(), 'report':('evidence_rows','lifecycle_rows','entities','labels','diagnostics')}
        artifact=reference.get('artifact','report')
        require(collection is None or collection in allowed[artifact],path='diagnostics.reference.collection')
        diagnostic_order.append((stage_order[diagnostic['stage']],artifact_order[artifact],-1 if index is None else index,diagnostic['path'].encode(),CODES.index(diagnostic['code'])))
    require(diagnostic_order==sorted(diagnostic_order),path='diagnostics.order')
