"""Bounded local research IO, closed source graph codec and canonical digests."""
from collections.abc import Mapping
from dataclasses import dataclass, fields
from fractions import Fraction
from hashlib import sha256
import json
import os
import stat
from typing import get_args, get_origin, Literal

from aegis.fusion.admission import AdmissionRequest, EvidenceKey, _Budget
from aegis.fusion.contracts import MeasurementTime
from .correspondence_contracts import (ContractError, FrozenMap, MAX_BYTES, SOURCE_TYPES,
    SCHEMAS, DEFINITIONS, require, scalar, unscalar, freeze, thaw, validate_shape, validate_report)


def canonical_bytes(value):
    return (json.dumps(thaw(value), ensure_ascii=True,sort_keys=True,separators=(',', ':'),allow_nan=False)+'\n').encode('ascii')


def digest(value): return sha256(canonical_bytes(value)).hexdigest()


def time_wire(value):
    return {'seconds':scalar(value.seconds),'clock_domain':value.clock_domain}


def time_value(value):
    validate_shape(value,DEFINITIONS['Time'])
    return MeasurementTime(unscalar(value['seconds']),value['clock_domain'])


def key_wire(key): return {f.name:getattr(key,f.name) for f in fields(EvidenceKey)}
def key_value(value):
    validate_shape(value,DEFINITIONS['EvidenceKey'])
    return EvidenceKey(**value)


def _matches(value,annotation):
    if annotation in (float,int): return type(value) in ((int,float) if annotation is float else (int,))
    if annotation is str: return type(value) is str
    if annotation is type(None): return value is None
    if annotation in SOURCE_TYPES.values(): return type(value) is annotation
    origin,args=get_origin(annotation),get_args(annotation)
    if origin is Literal: return value in args and type(value) is str
    if origin is tuple:
        if type(value) is not tuple: return False
        if args[-1] is Ellipsis: return all(_matches(x,args[0]) for x in value)
        return len(value)==len(args) and all(_matches(x,t) for x,t in zip(value,args))
    if args: return any(_matches(value,a) for a in args)
    return type(value).__name__ in ('ImagePoint','ImageTrackMeasurement','RadarPolarDetectionMeasurement')


def encode_source(request):
    """Encode only audited types, preserving shared Python object identity."""
    seen,nodes,active={},[],set()
    def encode(value,depth=0):
        require(depth<=16,'BOUND','source')
        if value is None or type(value) is str: return value
        if type(value) in (int,float): return scalar(value)
        if type(value) is tuple:
            require(len(value)<=16,'BOUND','source.tuple')
            return [encode(x,depth+1) for x in value]
        require(type(value).__name__ in SOURCE_TYPES and SOURCE_TYPES[type(value).__name__] is type(value),'GRAPH_TYPE','source')
        identity=id(value)
        require(identity not in active,'GRAPH_CYCLE','source')
        if identity in seen: return {'ref':seen[identity]}
        require(len(nodes)<128,'BOUND','source.objects')
        name='n'+str(len(nodes)); seen[identity]=name
        node={'object_id':name,'type':type(value).__name__,'fields':{}}; nodes.append(node)
        active.add(identity)
        node['fields']={f.name:encode(getattr(value,f.name),depth+1) for f in fields(value)}
        active.remove(identity)
        return {'ref':name}
    root=encode(request)
    result={'root_ref':root['ref'],'objects':nodes}
    decode_source(result)
    return result


def decode_source(graph):
    validate_shape(graph,DEFINITIONS['SourceGraph'])
    nodes={}
    for node in graph['objects']:
        require(node['object_id'] not in nodes,'GRAPH_TYPE','objects','Repeated graph node ID')
        nodes[node['object_id']]=node
    active=set(); decoded={}; maximum_depth={}
    def build(name,depth):
        require(depth<=16,'BOUND','source.depth')
        require(name in nodes,'UNKNOWN_REFERENCE','source.ref')
        require(name not in active,'GRAPH_CYCLE','source.ref')
        # Revisited shared nodes must still obey the longest reference path bound.
        if name in decoded:
            require(depth+maximum_depth[name]<=16,'BOUND','source.depth')
            return decoded[name],maximum_depth[name]
        node=nodes[name]; cls=SOURCE_TYPES[node['type']]; active.add(name)
        def leaf(value,level):
            require(level<=16,'BOUND','source.depth')
            if isinstance(value,Mapping):
                if set(value)=={'ref'}:
                    result,height=build(value['ref'],level)
                    return result, height
                if set(value)=={'kind','value'}: return unscalar(value),0
                raise ContractError('GRAPH_TYPE','source.field')
            if type(value) in (tuple,list):
                parts=[leaf(x,level+1) for x in value]
                return tuple(x for x,_ in parts),1+max((h for _,h in parts),default=0)
            require(value is None or type(value) is str,'GRAPH_TYPE','source.field')
            return value,0
        values={}; height=0
        for f in fields(cls):
            v,h=leaf(node['fields'][f.name],depth+1)
            require(_matches(v,f.type),'GRAPH_TYPE','source.'+f.name)
            values[f.name]=v; height=max(height,1+h)
        try: value=cls(**values)
        except (ValueError,TypeError,OverflowError) as e:
            raise ContractError('SOURCE_INVALID','source', 'Existing source constructor rejected declaration') from e
        active.remove(name); decoded[name]=value; maximum_depth[name]=height
        return value,height
    root,_=build(graph['root_ref'],0)
    require(type(root) is AdmissionRequest,'GRAPH_TYPE','root_ref')
    if root.derivation is not None:
        require(root.derivation.source_observation is root.observation,'SOURCE_INVALID','derivation.source_observation','Derivation must share the original observation object')
    require(len(decoded)==len(nodes),'GRAPH_TYPE','objects','Unused source nodes forbidden')
    return root


@dataclass(frozen=True,slots=True,init=False)
class Artifact:
    kind: str
    sha256: str
    data: FrozenMap
    sources: tuple[AdmissionRequest,...]=()
    byte_count: int=0

    def __init__(self, raw, kind):
        # No public cache/digest constructor: every ordinary construction validates
        # exact bounded bytes. dataclasses.replace cannot forge a binding or cache.
        values=_parse_artifact_fields(raw,kind)
        for name,value in zip(('kind','sha256','data','sources','byte_count'),values):
            object.__setattr__(self,name,value)


def _pairs(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'SCHEMA','json','Duplicate JSON key')
        out[key]=value
    return out


def _preflight(text):
    """Count JSON value starts, not object keys or separators, before allocation.

    Exact syntax is still checked by json.loads. Quotes/escapes are tracked so
    brackets in strings cannot change depth; each scalar/container counts once.
    """
    stack=[]; nodes=0; quoted=escaped=False; previous=None
    for c in text:
        if quoted:
            if escaped: escaped=False
            elif c=='\\': escaped=True
            elif c=='"': quoted=False; previous='"'
            continue
        if c.isspace(): continue
        if c=='"':
            is_key=bool(stack and stack[-1]=='{' and previous in ('{',','))
            if not is_key: nodes+=1
            quoted=True
        elif c in '[{': stack.append(c); nodes+=1
        elif c in ']}':
            require(bool(stack),'SCHEMA','json')
            stack.pop()
        elif c not in ',:':
            if previous in (None,'[',':',',') and not (stack and stack[-1]=='{' and previous!= ':'):
                nodes+=1
        require(len(stack)<=16 and nodes<=100000,'BOUND','json')
        previous=c


def _parse_artifact_fields(raw,kind):
    require(type(kind) is str and kind in MAX_BYTES,'SCHEMA','kind')
    require(type(raw) is bytes and len(raw)<=MAX_BYTES[kind],'BOUND','input')
    bound=sha256(raw).hexdigest()
    try: text=raw.decode('utf-8','strict')
    except UnicodeError: raise ContractError('UTF8','input') from None
    _preflight(text)
    try:
        data=json.loads(text,object_pairs_hook=_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ContractError('SCHEMA','json','Nonfinite constant')))
    except (json.JSONDecodeError,RecursionError,ValueError) as e:
        if isinstance(e,ContractError): raise
        raise ContractError('SCHEMA','json','Invalid JSON') from e
    require(isinstance(data,dict),'SCHEMA','root')
    require(type(data.get('schema_version')) is int and data['schema_version']==1,'VERSION','schema_version')
    validate_shape(data,SCHEMAS[kind])
    # Validate canonical scalars even in fields not used by the selected evaluation.
    def scalars(value):
        if type(value) is dict:
            if set(value)=={'kind','value'}: unscalar(value)
            else:
                for v in value.values(): scalars(v)
        elif type(value) is list:
            for v in value: scalars(v)
    scalars(data)
    if kind=='report': validate_report(data)
    sources=()
    if kind=='observations':
        require(sum(len(o['admission_request']['objects']) for o in data['occurrences'])<=100000,'BOUND','objects')
        sources=tuple(decode_source(o['admission_request']) for o in data['occurrences'])
        # Aggregate original source text, rather than a separate budget per source.
        budget=_Budget()
        try:
            for source in sources: budget.canonical((source.observation,source.source_session_id,source.entity_kind,source.quantity,source.basis,source.uncertainty,source.correlation,source.evaluation,source.available_at,source.max_age_seconds,source.derivation))
        except ValueError as e: raise ContractError('SOURCE_INVALID','source') from e
        except Exception as e:
            from aegis.fusion.admission import _BatchBound
            if isinstance(e,_BatchBound): raise ContractError('BOUND','source') from e
            raise
    return kind,bound,freeze(data),sources,len(raw)


def parse_artifact(raw,kind):
    return Artifact(raw,kind)


def artifact_from_data(data,kind):
    # The in-memory entry point needs the same pre-allocation safeguards as bytes.
    require(type(kind) is str and kind in SCHEMAS,'SCHEMA','kind')
    immutable=freeze(data)
    validate_shape(immutable,SCHEMAS[kind])
    return parse_artifact(canonical_bytes(immutable),kind)


def read_artifact(path,kind):
    """Regular explicit local file, bounded read, no symlink traversal anywhere."""
    require(type(kind) is str and kind in MAX_BYTES,'SCHEMA','kind')
    try:
        path=os.fspath(path)
        require(type(path) is str and '://' not in path,'IO_ERROR','input')
        # Walk components with directory descriptors, never follow intermediate links.
        parts=path.split('/')
        directory=os.open('/' if path.startswith('/') else '.',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                if not part: continue
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                os.close(directory); directory=next_fd
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        finally: os.close(directory)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode),'IO_ERROR','input')
            require(info.st_size<=MAX_BYTES[kind],'BOUND','input')
            raw=stream.read(MAX_BYTES[kind]+1)
    except ContractError:
        raise
    except (OSError, ValueError, TypeError) as e:
        raise ContractError('IO_ERROR','input','Cannot read regular local input') from e
    return parse_artifact(raw,kind)


def source_facts(occurrence,source):
    key=EvidenceKey(source.observation.sensor_id,source.source_session_id,source.observation.observation_id)
    budget=_Budget()
    return {'profile':'sf4-source-facts-v1',
      'sf1_evidence_sha256':budget.digest((key,source.observation,source.available_at)),
      'sf1_assumptions_sha256':budget.digest((source.entity_kind,source.quantity,source.basis,source.uncertainty,source.correlation,source.derivation,source.evaluation.clock_domain)),
      'source_max_age_seconds':None if source.max_age_seconds is None else scalar(source.max_age_seconds),
      'step_ref':occurrence['step_ref'],'acquisition_ref':occurrence['acquisition_ref'],
      'acquisition_mapping_ref':occurrence['acquisition_mapping_ref'],'provenance':thaw(occurrence['provenance'])}


def view_digests(dataset,cutoffs):
    """Prefix hash per declared cutoff; no truth, age filtering or identity choice."""
    require(dataset.kind=='observations','SCHEMA','view')
    require(len(cutoffs)<=1024,'BOUND','cutoffs')
    data=dataset.data; domain=data['scenario_clock_domain']; events=[]; seen=set()
    occurrences={o['occurrence_id']:s for o,s in zip(data['occurrences'],dataset.sources)}
    primary_ordinals={}
    for ordinal,source in enumerate(dataset.sources):
        key=(source.observation.sensor_id,source.source_session_id,source.observation.observation_id)
        primary_ordinals.setdefault(key,ordinal)
    for ordinal,(o,s) in enumerate(zip(data['occurrences'],dataset.sources)):
        k=(s.observation.sensor_id,s.source_session_id,s.observation.observation_id)
        if k in seen: continue
        seen.add(k)
        if s.available_at is not None and s.available_at.clock_domain==domain:
            events.append((Fraction(s.available_at.seconds),0,ordinal,{'kind':'evidence','evidence_key':key_wire(EvidenceKey(*k)),'source_sha256':digest(source_facts(o,s))}))
    for ordinal,a in enumerate(data['acquisitions']):
        at=a['available_at']
        if at is None or at['clock_domain']!=domain: continue
        keys=[]; key_set=set()
        for occurrence in a['observation_occurrence_refs']:
            require(occurrence in occurrences,'UNKNOWN_REFERENCE','acquisition')
            s=occurrences[occurrence]; key=key_wire(EvidenceKey(s.observation.sensor_id,s.source_session_id,s.observation.observation_id))
            identity=tuple(key.values())
            if identity not in key_set: keys.append(key); key_set.add(identity)
        keys.sort(key=lambda key:primary_ordinals[(key['sensor_id'],key['source_session_id'],key['observation_id'])])
        facts={'profile':'sf4-acquisition-facts-v1',**{k:thaw(v) for k,v in a.items() if k!='observation_occurrence_refs'},'logical_evidence_keys':keys}
        events.append((Fraction(unscalar(at['seconds'])),1,ordinal,{'kind':'acquisition','acquisition_ref':a['acquisition_ref'],'envelope_sha256':digest(facts)}))
    events.sort(key=lambda x:x[:3]); state=sha256()
    def add(h,value):
        blob=canonical_bytes(value); h.update(len(blob).to_bytes(4,'big')); h.update(blob)
    add(state,{'profile':'sf4-observation-view-v1','dataset_sha256':dataset.sha256})
    ordered=[]
    for c in cutoffs:
        t=time_value(c); require(t.clock_domain==domain,'SCHEMA','cutoff')
        ordered.append((Fraction(t.seconds),canonical_bytes(c),c))
    ordered.sort(key=lambda x:(x[0],x[1])); index=0; result={}
    for now,key,c in ordered:
        while index<len(events) and events[index][0]<=now:
            add(state,events[index][3]); index+=1
        copy=state.copy(); add(copy,{'kind':'cutoff','time':thaw(c)})
        result[key]=copy.hexdigest()
    return result
