"""Pure offline evaluation of supplied correspondence assertions, never matching."""
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction

from aegis.fusion.admission import AdmissionLedger, EvidenceKey, _correlation, _time
from aegis.fusion.acquisition import Acquisition, inspect_acquisitions
from aegis.fusion.contracts import MeasurementTime
from aegis.fusion.timing import AlignmentRequest, TimingRequest, align_batch, align_time, _mapped
from aegis.fusion.uncertainty import UnknownUncertainty
from .correspondence_contracts import (ContractError, FrozenMap, CODE_GROUPS, CODES,
    DEFINITIONS, MAX_BYTES, SCHEMAS, freeze, thaw, require, validate_shape, unscalar, validate_report)
from .correspondence_io import (Artifact, canonical_bytes, digest, key_value, key_wire,
    time_value, source_facts, read_artifact, view_digests)


def _unique(rows,identity,code='UNKNOWN_REFERENCE'):
    result={}
    for i,row in enumerate(rows):
        key=identity(row)
        require(key not in result,code,'references','Repeated identity declaration')
        result[key]=(i,row)
    return result


def _number(time): return Fraction(time_value(time).seconds)
def _key(source): return EvidenceKey(source.observation.sensor_id,source.source_session_id,source.observation.observation_id)
def _opp(row): return row['truth_entity_id'],row['step_ref']
def ratio(n,d): return None if d==0 else {'numerator':n,'denominator':d}


def _diagnostic(code,artifact='report',collection=None,index=None,path='',explanation=None):
    stage=next(s for s,group in CODE_GROUPS if code in group.split())
    severity='error' if stage in ('io/schema','references','source','hypothesis view') or code=='OUTPUT_BOUND' else 'info' if code in ('LABEL_MATCH','DUPLICATE_EVIDENCE','DUPLICATE_HYPOTHESIS') else 'limitation'
    return dict(code=code,stage=stage,severity=severity,
                reference=dict(artifact=artifact,collection=collection,index=index),path=path,
                explanation=explanation or code.replace('_',' ').capitalize())


def _ordered_diagnostics(rows):
    stages={s:i for i,(s,_) in enumerate(CODE_GROUPS)}
    artifacts={a:i for i,a in enumerate(('observations','truth','hypotheses','request','report'))}
    def order(d):
        r=d['reference'] or {}
        return (stages[d['stage']],artifacts.get(r.get('artifact'),4),-1 if r.get('index') is None else r['index'],d['path'].encode(),CODES.index(d['code']))
    return sorted(rows,key=order)


def _reject(error,bindings=None):
    bindings=bindings or dict.fromkeys(('dataset_sha256','truth_sha256','hypotheses_sha256','policy_sha256'))
    return freeze(dict(schema_version=1,artifact_kind='offline_correspondence_evaluation',status='rejected',
        bindings=bindings,evaluation=None,policy=None,scope=None,populations=None,evidence_rows=[],lifecycle_rows=[],
        continuity={'entities':[],'labels':[]},metrics=None,diagnostics=[_diagnostic(error.code,path=error.path,explanation=error.explanation)],diagnostics_dropped=0))


@dataclass(frozen=True,slots=True)
class ResearchBundle:
    observations: Artifact
    truth: Artifact
    hypotheses: Artifact


@dataclass(frozen=True,slots=True)
class BundleValidation:
    bundle: ResearchBundle | None
    diagnostics: tuple[FrozenMap,...]


BundleLoadResult=BundleValidation


def _inventory(bundle):
    """Validate complete bounded context before any favorable metric is emitted."""
    require(all(type(a) is Artifact for a in (bundle.observations,bundle.truth,bundle.hypotheses)),'SCHEMA','bundle')
    d,t,h=bundle.observations.data,bundle.truth.data,bundle.hypotheses.data
    for artifact,kind in ((bundle.observations,'observations'),(bundle.truth,'truth'),(bundle.hypotheses,'hypotheses')):
        require(type(artifact) is Artifact and artifact.kind==kind,'SCHEMA','artifact')
        require(type(artifact.data) is FrozenMap,'SCHEMA','artifact.data')
        require(type(artifact.byte_count) is int and 0<=artifact.byte_count<=MAX_BYTES[kind],'BOUND','artifact.bytes')
        validate_shape(artifact.sha256,{'type':'string','pattern':'^[0-9a-f]{64}$'})
        validate_shape(artifact.data,SCHEMAS[kind])
    require(sum(a.byte_count for a in (bundle.observations,bundle.truth,bundle.hypotheses))<=6*1024**2,'BOUND','inputs')
    require(t['dataset_sha256']==h['dataset_sha256']==bundle.observations.sha256,'DIGEST_MISMATCH','dataset_sha256')
    require(d['generator']==d['provenance']['generator'],'SOURCE_INVALID','generator')
    def provenance(p):
        require(p['generator']==d['generator'] and p['origin']==d['provenance']['origin'],'SOURCE_INVALID','provenance')
        if p['origin']=='synthetic_impaired':
            require(p['upstream_source_sha256'] is not None and p['derived_from'] is not None and p['lineage'],'SOURCE_INVALID','provenance','Impaired evidence needs upstream lineage')
    # Root impaired views can bind upstream via hash/lineage without one EvidenceKey.
    root=d['provenance']
    if root['origin']=='synthetic_impaired': require(root['upstream_source_sha256'] is not None and root['lineage'],'SOURCE_INVALID','provenance')
    domain=d['scenario_clock_domain']
    steps=_unique(d['steps'],lambda r:r['step_id'])
    last=None
    for step in d['steps']:
        require(step['start']['clock_domain']==step['end']['clock_domain']==domain,'SCHEMA','steps.clock_domain')
        lo,hi=_number(step['start']),_number(step['end'])
        require(lo<hi and (last is None or lo>=last),'SCHEMA','steps','Require ordered nonoverlapping positive windows')
        last=hi
    mappings=_unique(d['clock_mappings'],lambda r:r['mapping_id'])
    from aegis.fusion.clock_mapping import BoundedClockMapping
    typed_mappings={}
    for name,(_,m) in mappings.items():
        try:
            values={k:v if type(v) is str else unscalar(v) for k,v in m['mapping'].items()}
            mapping=BoundedClockMapping(**values)
            require(mapping.target_clock_domain==domain,'CLOCK_MAPPING_INVALID','mapping')
            typed_mappings[name]=mapping
        except (ValueError,TypeError,OverflowError) as e: raise ContractError('CLOCK_MAPPING_INVALID','mapping') from e
    # SF-2's overlapping declarations must not assert disjoint clock bounds.
    grouped=defaultdict(list)
    for m in typed_mappings.values(): grouped[(m.source_clock_domain,m.target_clock_domain)].append(m)
    for values in grouped.values():
        for i,a in enumerate(values):
            for b in values[i+1:]:
                lo=max(Fraction(a.valid_from_source_seconds),Fraction(b.valid_from_source_seconds)); hi=min(Fraction(a.valid_until_source_seconds),Fraction(b.valid_until_source_seconds))
                if lo<=hi:
                    err=Fraction(a.error_bound_seconds)+Fraction(b.error_bound_seconds)
                    require(all(abs((Fraction(a.scale)-Fraction(b.scale))*x+Fraction(a.offset_seconds)-Fraction(b.offset_seconds))<=err for x in (lo,hi)),'CLOCK_MAPPING_INVALID','mapping','Inconsistent overlapping clock declarations')
    occurrences=_unique(d['occurrences'],lambda r:r['occurrence_id'])
    acquisitions=_unique(d['acquisitions'],lambda r:r['acquisition_ref'])
    require(len(bundle.observations.sources)==len(d['occurrences']),'GRAPH_TYPE','sources')
    from .correspondence_io import decode_source
    for o,s in zip(d['occurrences'],bundle.observations.sources):
        decoded=decode_source(o['admission_request'])
        require(type(s) is type(decoded) and s==decoded,'GRAPH_TYPE','sources','Source cache disagrees with bound graph')
    source_by_occurrence={o['occurrence_id']:s for o,s in zip(d['occurrences'],bundle.observations.sources)}
    logical={}; members=defaultdict(list); fingerprints={}
    for i,(o,s) in enumerate(zip(d['occurrences'],bundle.observations.sources)):
        require(o['step_ref'] in steps and o['acquisition_ref'] in acquisitions,'UNKNOWN_REFERENCE','occurrence')
        require(o['acquisition_mapping_ref'] is None or o['acquisition_mapping_ref'] in mappings,'UNKNOWN_REFERENCE','mapping')
        provenance(o['provenance'])
        if o['occurrence_received_at'] is not None: time_value(o['occurrence_received_at'])
        key=_key(s); facts=source_facts(o,s); fingerprint=digest(facts)
        if key in logical:
            old=logical[key][1]
            require((old['step_ref'],old['acquisition_ref'])==(o['step_ref'],o['acquisition_ref']),'REFERENCE_MEMBERSHIP_CONFLICT','occurrence')
            old_s=logical[key][2]
            require(old_s.max_age_seconds==s.max_age_seconds and type(old_s.max_age_seconds) is type(s.max_age_seconds),'CONTEXT_POLICY_CONFLICT','source.max_age_seconds')
            require(fingerprints[key]==fingerprint,'EVIDENCE_CONFLICT','source')
        else: logical[key]=(i,o,s); fingerprints[key]=fingerprint
        members[key].append(o['occurrence_id'])
    seen_members=set(); events=[]; acquisition_bounds={}
    for a in d['acquisitions']:
        require(a['step_ref'] in steps,'UNKNOWN_REFERENCE','acquisition.step_ref')
        mapping_ref=a['acquisition_mapping_ref']
        require(mapping_ref is None or mapping_ref in mappings,'UNKNOWN_REFERENCE','mapping')
        obs=[]
        for name in a['observation_occurrence_refs']:
            require(name in occurrences and name not in seen_members,'REFERENCE_MEMBERSHIP_CONFLICT','acquisition.members')
            seen_members.add(name); _,o=occurrences[name]; s=source_by_occurrence[name]
            require(o['acquisition_ref']==a['acquisition_ref'] and o['step_ref']==a['step_ref'] and o['acquisition_mapping_ref']==mapping_ref,'REFERENCE_MEMBERSHIP_CONFLICT','acquisition')
            require(s.observation.sensor_id==a['sensor_id'] and s.source_session_id==a['source_session_id'],'REFERENCE_MEMBERSHIP_CONFLICT','acquisition.source')
            obs.append(s.observation)
        at=None if a['acquisition_time'] is None else time_value(a['acquisition_time'])
        event=Acquisition(a['sensor_id'],a['source_session_id'],a['acquisition_id'],at,a['status'],tuple(obs),a['reason'])
        events.append(event)
        mapping=typed_mappings.get(mapping_ref)
        require(at is not None or mapping is None,'CLOCK_MAPPING_INVALID','acquisition.mapping')
        try: bounds,_=_mapped(at,mapping,domain,'acquisition') if at is not None else (None,None)
        except ValueError as e: raise ContractError('CLOCK_MAPPING_INVALID','acquisition') from e
        acquisition_bounds[a['acquisition_ref']]=bounds
        av=a['available_at']
        if av is not None:
            time_value(av)
            if bounds is not None and av['clock_domain']==domain and a['status']=='completed':
                require(Fraction(bounds[1])<=_number(av),'COMPLETION_CONFLICT','available_at','Completion precedes acquisition bounds')
            if a['status']=='completed':
                for name in a['observation_occurrence_refs']:
                    source=source_by_occurrence[name]
                    delivery=source.available_at
                    if delivery is not None and delivery.clock_domain==av['clock_domain']:
                        require(Fraction(delivery.seconds)<=_number(av),'COMPLETION_CONFLICT','available_at','Completion precedes member delivery')
    require(len(seen_members)==len(occurrences),'REFERENCE_MEMBERSHIP_CONFLICT','acquisitions','Every occurrence must belong to one acquisition')
    result=inspect_acquisitions(tuple(events))
    require(not result.diagnostics,'SOURCE_INVALID','acquisitions')
    for r in result.results:
        require(r.status!='rejected','COMPLETION_CONFLICT','acquisitions')
    # Repeated acquisition identities may not change envelope metadata either.
    identities={}
    for a in d['acquisitions']:
        identity=(a['sensor_id'],a['source_session_id'],a['acquisition_id'])
        fact={k:thaw(v) for k,v in a.items() if k not in ('acquisition_ref','observation_occurrence_refs')}
        keys=tuple(_key(source_by_occurrence[x]) for x in a['observation_occurrence_refs'])
        value=(digest(fact),keys)
        require(identity not in identities or identities[identity]==value,'COMPLETION_CONFLICT','acquisitions')
        identities[identity]=value
    entities=_unique(t['entity_catalog'],lambda r:r['truth_entity_id'],'TRUTH_CONFLICT')
    truth=_unique(t['evidence_labels'],lambda r:key_value(r['evidence_key']),'TRUTH_CONFLICT')
    require(set(truth)==set(logical),'TRUTH_CONFLICT','evidence_labels','Truth must cover every logical key exactly once')
    opportunities=_unique(t['opportunities'],_opp,'TRUTH_CONFLICT')
    require(sum(len(o['required_acquisition_refs']) for o in t['opportunities'])<=8192,'BOUND','opportunities')
    terminals=_unique(t['terminal_annotations'],lambda r:r['truth_entity_id'],'TERMINAL_CONFLICT')
    for entity,(_,end) in terminals.items():
        require(entity in entities and end['step_ref'] in steps,'UNKNOWN_REFERENCE','terminal')
        require(end['visible_at']['clock_domain']==domain and _number(end['visible_at'])>=_number(steps[end['step_ref']][1]['start']),'TERMINAL_CONFLICT','visible_at')
    for (entity,step),(ordinal,o) in opportunities.items():
        require(entity in entities and step in steps,'UNKNOWN_REFERENCE','opportunity')
        for name in o['required_acquisition_refs']:
            require(name in acquisitions,'UNKNOWN_REFERENCE','required_acquisition_refs')
            require(acquisitions[name][1]['step_ref']==step,'TRUTH_CONFLICT','opportunity.step')
        if entity in terminals and steps[step][0]>=steps[terminals[entity][1]['step_ref']][0]:
            require(o['expectation']!='expected','TERMINAL_CONFLICT','opportunity')
    for key,(_,label) in truth.items():
        _,o,s=logical[key]
        candidates=[label['truth_entity_id']] if label['status']=='known' else label.get('candidates',())
        for entity in candidates:
            require(entity in entities,'UNKNOWN_REFERENCE','truth.entity')
            require((entity,o['step_ref']) in opportunities,'TRUTH_CONFLICT','truth.opportunity')
            opportunity=opportunities[(entity,o['step_ref'])][1]
            require(opportunity['expectation']=='expected' and o['acquisition_ref'] in opportunity['required_acquisition_refs'],'TRUTH_CONFLICT','truth.opportunity')
            if entity in terminals:
                require(steps[o['step_ref']][0]<steps[terminals[entity][1]['step_ref']][0],'TERMINAL_CONFLICT','truth.label')
    labels=set(h['external_label_catalog'])
    alignments=_unique(h['label_alignment'],lambda r:r['external_label'],'HYPOTHESIS_CONFLICT')
    for name,(_,a) in alignments.items():
        require(name in labels and a['truth_entity_id'] in entities,'UNKNOWN_REFERENCE','label_alignment')
    decisions={}; decision_refs=defaultdict(list)
    for i,decision in enumerate(h['decisions']):
        key=key_value(decision['evidence_key'])
        require(key in logical,'UNKNOWN_REFERENCE','decision.key')
        if key in decisions: require(decision==decisions[key],'HYPOTHESIS_CONFLICT','decision')
        else: decisions[key]=decision
        decision_refs[key].append(i)
        uses=[decision['external_label']] if decision['status']=='assigned' else decision.get('candidates',())
        require(all(label in labels for label in uses),'UNKNOWN_REFERENCE','decision.label')
        cutoff=decision['information_cutoff']
        require((cutoff is None)==(decision['input_view_sha256'] is None),'SCHEMA','input_view_sha256')
    return dict(steps=steps,mappings=typed_mappings,occurrences=occurrences,acquisitions=acquisitions,
        acquisition_bounds=acquisition_bounds,source_by_occurrence=source_by_occurrence,logical=logical,members=members,
        entities=entities,truth=truth,opportunities=opportunities,terminals=terminals,alignments=alignments,
        decisions=decisions,decision_refs=decision_refs)


def validate_research_bundle(observations,truth,hypotheses,policy):
    """No evaluator-ready bundle on structural/source rejection."""
    try:
        validate_shape(policy,DEFINITIONS['Policy'])
        limit=policy['additional_max_age_seconds']
        require(limit is None or unscalar(limit)>=0,'SCHEMA','policy.age')
        bundle=ResearchBundle(observations,truth,hypotheses)
        context=_inventory(bundle)
        # Source/time checks are independent of the report's later scope.
        _sources(bundle,context,MeasurementTime(0,observations.data['scenario_clock_domain']),policy)
        cutoffs=[x['information_cutoff'] for x in context['decisions'].values() if x['information_cutoff'] is not None and x['information_cutoff']['clock_domain']==observations.data['scenario_clock_domain']]
        views=view_digests(observations,cutoffs)
        for decision in context['decisions'].values():
            cutoff=decision['information_cutoff']
            if cutoff is not None and cutoff['clock_domain']==observations.data['scenario_clock_domain']:
                require(views[canonical_bytes(cutoff)]==decision['input_view_sha256'],'INPUT_VIEW_MISMATCH','input_view_sha256')
        return BundleValidation(bundle,())
    except ContractError as e: return BundleValidation(None,(freeze(_diagnostic(e.code,path=e.path,explanation=e.explanation)),))
    except (ValueError,TypeError,OverflowError) as e:
        return BundleValidation(None,(freeze(_diagnostic('SOURCE_INVALID')),))


def load_research_bundle(paths,expected_digests,policy):
    """Read only explicit local inputs. No output files, network or implicit clock."""
    try:
        require(set(paths)=={'observations','truth','hypotheses'},path='paths')
        validate_shape(expected_digests,DEFINITIONS['ExpectedDigests'])
        artifacts=[read_artifact(paths[k],k) for k in ('observations','truth','hypotheses')]
        for a,name in zip(artifacts,('dataset_sha256','truth_sha256','hypotheses_sha256')):
            require(a.sha256==expected_digests[name],'DIGEST_MISMATCH',name)
        return validate_research_bundle(*artifacts,policy)
    except ContractError as e: return BundleValidation(None,(freeze(_diagnostic(e.code,path=e.path,explanation=e.explanation)),))


def _sources(bundle,c,evaluation,policy):
    domain=bundle.observations.data['scenario_clock_domain']; result={}
    limit=policy['additional_max_age_seconds']; limit=None if limit is None else unscalar(limit)
    require(limit is None or limit>=0,'SCHEMA','policy.age')
    for key,(i,o,s) in c['logical'].items():
        mapping=c['mappings'].get(o['acquisition_mapping_ref'])
        _time(s.evaluation,'source.evaluation')
        if s.available_at is not None: _time(s.available_at,'source.available_at')
        age=s.max_age_seconds
        effective=age if limit is None else limit if age is None else min(age,limit)
        # Validate the original policy even when the additional policy is stricter.
        require(age is None or type(age) in (int,float) and age>=0,'SOURCE_INVALID','source.max_age_seconds')
        if age is not None:
            from aegis.fusion.uncertainty import _number as validate_number
            validate_number(age,'source.max_age_seconds')
        available=s.available_at
        supported_delivery=available is None or available.clock_domain==domain
        prepared=replace(s,evaluation=evaluation,max_age_seconds=effective,available_at=available if supported_delivery else None)
        aligned=align_batch((AlignmentRequest(prepared,'sf4-source','1',mapping),),AdmissionLedger.empty())
        require(not aligned.diagnostics and len(aligned.results)==1,'SOURCE_INVALID','source')
        a=aligned.results[0]
        if a.status=='rejected' or a.admission is None:
            ds=a.diagnostics or (() if a.admission is None else a.admission.diagnostics)
            detail=ds[0].code+': '+ds[0].explanation if ds else 'SF-1/SF-2 source validation rejected declaration'
            raise ContractError('SOURCE_INVALID','source',detail)
        if s.derivation is not None and s.derivation.mapped_time is not None:
            require(mapping is not None and a.mapped_time==s.derivation.mapped_time,'CLOCK_MAPPING_INVALID','source.mapped_time')
        timing=align_time(TimingRequest(key,s.observation.measurement_time,available,evaluation,effective,'sf4-time','1',mapping))
        if timing.status=='rejected':
            detail=timing.diagnostics[0]
            raise ContractError('SOURCE_INVALID','source.timing',detail.code+': '+detail.explanation)
        bounds=timing.acquisition_interval; reasons=[]
        if bounds is None: reasons.append('CLOCK_MAPPING_REQUIRED')
        if not supported_delivery: reasons.append('DELIVERY_CLOCK_UNSUPPORTED')
        if available is None: reasons.append('DELIVERY_UNKNOWN')
        if bounds is not None:
            lo,hi=map(Fraction,bounds); step=c['steps'][o['step_ref']][1]
            if lo<_number(step['start']) or hi>=_number(step['end']) or (available is not None and supported_delivery and hi>Fraction(available.seconds)):
                reasons.append('TEMPORAL_ORDER_AMBIGUOUS')
        if available is not None and supported_delivery and Fraction(available.seconds)>Fraction(evaluation.seconds): reasons.append('PENDING_DELIVERY')
        if bounds is not None and effective is not None and Fraction(evaluation.seconds)-Fraction(bounds[0])>Fraction(effective): reasons.append('STALE_MEASUREMENT')
        reason=reasons[0] if reasons else None
        admission=a.admission
        restrictions=admission.admitted_measurement.restrictions if admission.admitted_measurement is not None else None
        if not supported_delivery:
            # Validation with unavailable delivery is not an admission of the original.
            admission=replace(admission,status='deferred')
        result[key]=dict(reason=reason,reasons=reasons,bounds=bounds,admission=admission,restrictions=restrictions)
    return result


def _hypothesis(key,s,decision,alignment,evaluation,domain,views):
    if decision is None: return 'missing','unresolved',['MISSING_HYPOTHESIS'],False
    at,cutoff=decision['decision_available_at'],decision['information_cutoff']
    if (at is not None and at['clock_domain']!=domain) or (cutoff is not None and cutoff['clock_domain']!=domain):
        return 'invalid_context','unresolved',['HYPOTHESIS_CLOCK_UNSUPPORTED'],False
    now=Fraction(evaluation.seconds)
    if cutoff is not None:
        require(views[canonical_bytes(cutoff)]==decision['input_view_sha256'],'INPUT_VIEW_MISMATCH','input_view_sha256')
    if at is None: return 'invalid_context','unresolved',['HYPOTHESIS_AVAILABILITY_UNKNOWN'],False
    delivery=s.available_at
    if (delivery is not None and delivery.clock_domain==domain and
        (_number(at)<Fraction(delivery.seconds) or cutoff is not None and _number(cutoff)<Fraction(delivery.seconds))) or (cutoff is not None and _number(cutoff)>_number(at)):
        return 'invalid_context','unresolved',['HYPOTHESIS_CAUSAL_CONFLICT'],False
    if _number(at)>now: return 'pending','unresolved',['HYPOTHESIS_PENDING'],False
    if cutoff is not None and _number(cutoff)>now: return 'invalid_context','unresolved',['HYPOTHESIS_CUTOFF_FUTURE'],False
    notes=['CAUSAL_PROVENANCE_UNVERIFIED'] if cutoff is None else []
    if decision['status']=='unresolved': return 'unresolved','unresolved',notes+['HYPOTHESIS_UNRESOLVED'],False
    if decision['status']=='ambiguous': return 'ambiguous','ambiguous',notes,False
    if decision['external_label'] not in alignment: return 'unaligned','unresolved',notes+['HYPOTHESIS_UNALIGNED'],True
    return 'assigned',None,notes,True


def evaluate_supplied_hypotheses(validated_bundle,evaluation_request):
    """Immutable count/diagnostic report. Never selects a candidate or label map."""
    bindings=dict.fromkeys(('dataset_sha256','truth_sha256','hypotheses_sha256','policy_sha256'))
    try:
        require(type(validated_bundle) is ResearchBundle,'SCHEMA','bundle')
        bundle=validated_bundle
        require(all(type(a) is Artifact for a in (bundle.observations,bundle.truth,bundle.hypotheses)),'SCHEMA','bundle')
        bindings.update(dataset_sha256=bundle.observations.sha256,truth_sha256=bundle.truth.sha256,hypotheses_sha256=bundle.hypotheses.sha256)
        request=freeze(evaluation_request)
        validate_shape(request,DEFINITIONS['EvaluationRequest'])
        for name in ('dataset_sha256','truth_sha256','hypotheses_sha256'):
            require(request['expected_digests'][name]==bindings[name],'DIGEST_MISMATCH',name)
        bindings['policy_sha256']=digest({'policy':request['policy'],'scope':request['scope']})
        c=_inventory(bundle); d=bundle.observations.data
        evaluation=time_value(request['evaluation']); domain=d['scenario_clock_domain']
        require(evaluation.clock_domain==domain,'SCHEMA','evaluation.clock_domain')
        sources=_sources(bundle,c,evaluation,request['policy'])
        scope=request['scope']; evidence_scope=set(c['logical']) if scope['evidence_keys'] is None else {key_value(k) for k in scope['evidence_keys']}
        opportunity_scope=set(c['opportunities']) if scope['opportunity_keys'] is None else {_opp(k) for k in scope['opportunity_keys']}
        require(evidence_scope<=set(c['logical']) and opportunity_scope<=set(c['opportunities']),'UNKNOWN_REFERENCE','scope')
        cutoffs=[x['information_cutoff'] for x in c['decisions'].values() if x['information_cutoff'] is not None and x['information_cutoff']['clock_domain']==domain]
        views=view_digests(bundle.observations,cutoffs)
        # Digest claims are checked even on currently excluded source rows.
        for decision in c['decisions'].values():
            cutoff=decision['information_cutoff']
            if cutoff is not None and cutoff['clock_domain']==domain:
                require(views[canonical_bytes(cutoff)]==decision['input_view_sha256'],'INPUT_VIEW_MISMATCH','input_view_sha256')
        diagnostics=[]; rows=[]; outcomes={}; token_claims=[]
        excluded=Counter(); counts=Counter(); counts['in_scope_count']=len(evidence_scope)
        for key,(ordinal,o,s) in sorted(c['logical'].items(),key=lambda kv:(c['steps'][kv[1][1]['step_ref']][0],kv[1][0])):
            source=sources[key]; reason=source['reason']; label_index,truth=c['truth'][key]
            decision=c['decisions'].get(key)
            hs,outcome,notes,available_claim=_hypothesis(key,s,decision,c['alignments'],evaluation,domain,views)
            codes=list(source['reasons'])+list(notes)
            if key not in evidence_scope: reason='SCOPE_EXCLUDED'
            elif reason: excluded[reason]+=1
            if reason is None:
                counts['eligible_count']+=1
                if truth['status']=='known':
                    counts['known_truth_count']+=1
                    if outcome is None:
                        aligned=c['alignments'][decision['external_label']][1]['truth_entity_id']
                        outcome='correct' if aligned==truth['truth_entity_id'] else 'incorrect'
                        codes.append('LABEL_MATCH' if outcome=='correct' else 'LABEL_MISMATCH')
                    counts[outcome+'_count']+=1
                    if available_claim:
                        token_claims.append((decision['external_label'],truth['truth_entity_id'],o['step_ref']))
                else:
                    counts['truth_'+truth['status']+'_count']+=1
                    codes.append('TRUTH_'+truth['status'].upper()); outcome='unscored'
            else: codes.append(reason); outcome='unscored'
            uncertainty='unknown' if type(s.uncertainty) is UnknownUncertainty else 'known_psd'
            if uncertainty=='unknown': codes.append('UNCERTAINTY_UNKNOWN')
            admission=source['admission']
            if getattr(admission.uncertainty,'rank',None) is not None and admission.uncertainty.rank<len(s.basis.axes): codes.append('SINGULAR_UNCERTAINTY')
            occurrence_refs=c['members'][key]; hypothesis_refs=c['decision_refs'].get(key,[])
            if len(occurrence_refs)>1: codes.append('DUPLICATE_EVIDENCE')
            if len(hypothesis_refs)>1: codes.append('DUPLICATE_HYPOTHESIS')
            codes=list(dict.fromkeys(codes))
            row=dict(evidence_key=key_wire(key),occurrence_refs=occurrence_refs,step_ref=o['step_ref'],acquisition_ref=o['acquisition_ref'],source_ref={'primary_occurrence_ref':o['occurrence_id']},truth_ref=label_index,hypothesis_refs=hypothesis_refs,timing_status='eligible' if reason is None else 'ineligible',temporal_reason=reason,admission_status=admission.status,source_diagnostics=[dict(code=x.code,path=x.path,explanation=x.explanation) for x in admission.diagnostics],restrictions=None if source['restrictions'] is None else list(source['restrictions']),uncertainty_status=uncertainty,truth_status=truth['status'],hypothesis_status=hs,comparison_status=outcome,reason_codes=codes,continuity_eligibility='unassessed')
            rows.append(row); outcomes[key]=row
            for code in codes: diagnostics.append(_diagnostic(code,'observations','occurrences',ordinal))
        lifecycle,entities,assessed=_lifecycle(bundle,c,sources,outcomes,evidence_scope,opportunity_scope,evaluation)
        labels=_labels(token_claims,assessed,c)
        for row in rows:
            key=key_value(row['evidence_key']); truth=c['truth'][key][1]
            if truth['status']=='known' and (truth['truth_entity_id'],row['step_ref']) in assessed:
                row['continuity_eligibility']='assessed'
        for i,row in enumerate(lifecycle):
            for code in row['reason_codes']: diagnostics.append(_diagnostic(code,'report','lifecycle_rows',i))
        for i,label in enumerate(labels):
            if label['contaminated']: diagnostics.append(_diagnostic('CONTAMINATED_LABEL','report','labels',i))
            if label['collision_step_count']: diagnostics.append(_diagnostic('LABEL_COLLISION','report','labels',i))
        n=counts['known_truth_count']; correct=counts['correct_count']; incorrect=counts['incorrect_count']
        metrics=dict(zip(('conditional_resolved_accuracy','resolved_coverage','strict_correctness','unresolved_fraction','ambiguous_fraction','eligible_data_coverage','known_truth_coverage'),
             (ratio(correct,correct+incorrect),ratio(correct+incorrect,n),ratio(correct,n),ratio(counts['unresolved_count'],n),ratio(counts['ambiguous_count'],n),ratio(counts['eligible_count'],len(evidence_scope)),ratio(n,counts['eligible_count']))))
        if any(v is None for v in metrics.values()): diagnostics.append(_diagnostic('EMPTY_POPULATION'))
        populations={name:counts[name] for name in DEFINITIONS['Populations']['required'] if name!='excluded_by_reason'}
        populations.update(occurrence_count=len(d['occurrences']),logical_evidence_count=len(c['logical']),duplicate_occurrence_count=len(d['occurrences'])-len(c['logical']),excluded_scope_count=len(c['logical'])-len(evidence_scope),excluded_by_reason=[{'reason_code':k,'count':excluded[k]} for k in sorted(excluded)])
        incomplete=bool(excluded or counts['truth_ambiguous_count'] or counts['truth_unavailable_count'] or any(r['status']=='unknown' or 'OPPORTUNITY_UNASSESSED' in r['reason_codes'] for r in lifecycle))
        ordered=_ordered_diagnostics(diagnostics)
        report=dict(schema_version=1,artifact_kind='offline_correspondence_evaluation',status='incomplete' if incomplete else 'complete',bindings=bindings,evaluation=request['evaluation'],policy=request['policy'],scope=request['scope'],populations=populations,evidence_rows=rows,lifecycle_rows=lifecycle,continuity={'entities':entities,'labels':labels},metrics=metrics,diagnostics=ordered[:256],diagnostics_dropped=max(0,len(ordered)-256))
        validate_report(report)
        if len(canonical_bytes(report))>MAX_BYTES['report']:
            rejected=thaw(_reject(ContractError('OUTPUT_BOUND'),bindings)); rejected['diagnostics_dropped']=len(ordered)
            require(len(canonical_bytes(rejected))<=4096,'BOUND','rejection')
            return freeze(rejected)
        return freeze(report)
    except ContractError as e: return _reject(e,bindings)
    except (ValueError,TypeError,OverflowError) as e:
        return _reject(ContractError('SOURCE_INVALID',explanation='Existing source validation rejected declaration'),bindings)


def _lifecycle(bundle,c,sources,outcomes,evidence_scope,opportunity_scope,evaluation):
    now=Fraction(evaluation.seconds); domain=evaluation.clock_domain
    # Index each acquisition's distinct evidence once; no entity x evidence product.
    acquisition_members=defaultdict(list)
    for key,(_,o,_) in c['logical'].items(): acquisition_members[o['acquisition_ref']].append(key)
    closure={}; closure_reasons={}
    for name,(_,a) in c['acquisitions'].items():
        reasons=[]; bounds=c['acquisition_bounds'][name]; step=c['steps'][a['step_ref']][1]
        if a['status']!='completed': reasons.append('ACQUISITION_'+a['status'].upper())
        if bounds is None: reasons.append('ACQUISITION_UNKNOWN')
        elif Fraction(bounds[0])<_number(step['start']) or Fraction(bounds[1])>=_number(step['end']): reasons.append('TEMPORAL_ORDER_AMBIGUOUS')
        at=a['available_at']
        if at is None: reasons.append('COMPLETION_UNKNOWN')
        elif at['clock_domain']!=domain: reasons.append('DELIVERY_CLOCK_UNSUPPORTED')
        elif _number(at)>now: reasons.append('ACQUISITION_PENDING')
        for key in acquisition_members[name]:
            source=sources[key]
            # A stale delivered fact can still establish physical presence/absence.
            if source['reason'] not in (None,'STALE_MEASUREMENT'): reasons.append(source['reason'])
        closure[name]=not reasons; closure_reasons[name]=list(dict.fromkeys(reasons))
    member_summaries={}
    for name,keys in acquisition_members.items():
        observed=defaultdict(list)
        for evidence in keys:
            truth=c['truth'][evidence][1]
            if truth['status']=='known' and sources[evidence]['reason'] in (None,'STALE_MEASUREMENT'):
                observed[truth['truth_entity_id']].append(evidence)
        member_summaries[name]=(all(c['truth'][k][1]['status']=='known' for k in keys),
            all(k in evidence_scope and sources[k]['reason'] is None for k in keys),
            any(k not in evidence_scope for k in keys),observed)
    by_entity=defaultdict(list)
    for key,(ordinal,o) in c['opportunities'].items(): by_entity[key[0]].append((c['steps'][key[1]][0],ordinal,o))
    # Add only visible terminal rows, not every later dataset step.
    for entity,(_,end) in c['terminals'].items():
        if _number(end['visible_at'])<=now and (entity,end['step_ref']) not in opportunity_scope:
            by_entity[entity].append((c['steps'][end['step_ref']][0],None,end))
    lifecycle=[]; summaries=[]; assessed=set()
    for entity in sorted(by_entity,key=lambda x:x.encode()):
        opportunities=sorted(by_entity[entity],key=lambda x:(x[0],-1 if x[1] is None else x[1]))
        summary=dict(truth_entity_id=entity,**{k:0 for k in ('assessed_steps','resolved_steps','assessed_gaps','unassessed_opportunities','not_observable_steps','unassessed_breaks','fragment_count','same_label_links','changed_label_links','split_steps','mixed_steps','confirmed_reappearances')},block_segment_counts=[],resolved_step_coverage=None,identity_retention=None)
        block=False; segments=0; last_label=None; adjacent_label=None; previous_step=None
        seen_observed=False; missing=False; barrier=False
        def end_block():
            nonlocal block,segments,last_label,adjacent_label
            if block: summary['block_segment_counts'].append(segments)
            block=False; segments=0; last_label=None; adjacent_label=None
        for step_ordinal,ordinal,o in opportunities:
            step=o['step_ref']; key=(entity,step)
            if ordinal is not None and key not in opportunity_scope:
                end_block(); seen_observed=missing=False; barrier=True; previous_step=step_ordinal
                continue
            if previous_step is not None and step_ordinal>previous_step+1:
                end_block(); seen_observed=missing=False; barrier=True
            previous_step=step_ordinal
            reasons=[]; refs=[]; member_keys=[]; is_assessed=False
            terminal=c['terminals'].get(entity)
            ended=terminal is not None and _number(terminal[1]['visible_at'])<=now and step_ordinal>=c['steps'][terminal[1]['step_ref']][0]
            if ended: status='ended'
            else:
                summaries_for_op=[member_summaries.get(name,(True,True,False,{})) for name in o['required_acquisition_refs']]
                for _,_,_,observed in summaries_for_op: refs.extend(observed.get(entity,()))
                refs=list(dict.fromkeys(refs))
                if any(sources[k]['reason']=='STALE_MEASUREMENT' for k in refs): reasons.append('STALE_AT_EVALUATION')
                closed=all(closure[name] for name in o['required_acquisition_refs'])
                known=all(x[0] for x in summaries_for_op)
                if refs: status='observed'
                elif o['expectation']=='not_observable': status='not_observable'; reasons.append('NOT_OBSERVABLE')
                elif closed and known: status='temporarily_missing'
                else: status='unknown'
                for name in o['required_acquisition_refs']: reasons.extend(closure_reasons[name])
                if not known: reasons.append('UNKNOWN_MEMBER_TRUTH')
                is_assessed=(o['expectation']=='expected' and closed and known and all(x[1] for x in summaries_for_op))
                if any(x[2] for x in summaries_for_op): reasons.append('SCOPE_EXCLUDED')
            if status=='observed' and seen_observed and missing and is_assessed:
                status='resumed'; summary['confirmed_reappearances']+=1
            if is_assessed:
                assessed.add(key); summary['assessed_steps']+=1
                if not block:
                    if barrier: summary['unassessed_breaks']+=1
                    barrier=False; block=True
                correct={c['decisions'][k]['external_label'] for k in refs if outcomes[k]['comparison_status']=='correct'}
                mixed=bool(correct) and any(outcomes[k]['comparison_status'] in ('incorrect','ambiguous','unresolved') for k in refs)
                if mixed: summary['mixed_steps']+=1; reasons.append('MIXED_STEP')
                if len(correct)>1: summary['split_steps']+=1; reasons.append('IDENTITY_SPLIT')
                resolved=next(iter(correct)) if len(correct)==1 else None
                if resolved is not None:
                    summary['resolved_steps']+=1
                    if last_label is not None:
                        summary['same_label_links' if last_label==resolved else 'changed_label_links']+=1
                    if adjacent_label!=resolved: segments+=1
                    last_label=resolved
                else: summary['assessed_gaps']+=1
                adjacent_label=resolved
                if status in ('observed','resumed'): seen_observed=True; missing=False
                elif status=='temporarily_missing' and seen_observed: missing=True
            else:
                end_block(); seen_observed=missing=False; barrier=True
                if status=='not_observable': summary['not_observable_steps']+=1
                elif status!='ended': summary['unassessed_opportunities']+=1; reasons.append('OPPORTUNITY_UNASSESSED')
            lifecycle.append(dict(truth_entity_id=entity,step_ref=step,status=status,reason_codes=list(dict.fromkeys(reasons)),opportunity_ref=ordinal,evidence_refs=[key_wire(k) for k in refs] if status in ('observed','resumed') else []))
        end_block()
        summary['fragment_count']=sum(max(0,n-1) for n in summary['block_segment_counts'])
        summary['resolved_step_coverage']=ratio(summary['resolved_steps'],summary['assessed_steps'])
        summary['identity_retention']=ratio(summary['same_label_links'],summary['same_label_links']+summary['changed_label_links'])
        summaries.append(summary)
    lifecycle.sort(key=lambda r:(c['steps'][r['step_ref']][0],r['truth_entity_id'].encode(),-1 if r['opportunity_ref'] is None else r['opportunity_ref']))
    # A terminal step may also have a declared not-observable opportunity. Emit a
    # single terminal row when that explicit opportunity already represents end.
    unique=[]; seen=set()
    for row in lifecycle:
        k=(row['truth_entity_id'],row['step_ref'])
        if k not in seen: unique.append(row); seen.add(k)
    require(sum(len(r['evidence_refs']) for r in unique)<=1024,'BOUND','lifecycle.evidence_refs')
    return unique,summaries,assessed


def _labels(claims,assessed,c):
    groups=defaultdict(list)
    for label,truth,step in claims: groups[label].append((truth,step))
    rows=[]
    for label in sorted(groups,key=lambda x:x.encode()):
        group=groups[label]; support=sorted({truth for truth,_ in group},key=lambda x:x.encode()); steps=defaultdict(set)
        for truth,step in group: steps[step].add(truth)
        ordered=sorted(steps,key=lambda x:c['steps'][x][0]); links=changes=0
        for left,right in zip(ordered,ordered[1:]):
            if c['steps'][right][0]!=c['steps'][left][0]+1 or len(steps[left])!=1 or len(steps[right])!=1: continue
            a=next(iter(steps[left])); b=next(iter(steps[right]))
            if (a,left) in assessed and (b,right) in assessed:
                links+=1; changes+=a!=b
        rows.append(dict(external_label=label,assigned_known_truth_count=len(group),truth_support=support,contaminated=len(support)>1,collision_step_count=sum(len(v)>1 for v in steps.values()),adjacent_step_identity_changes=changes,assessed_adjacent_links=links))
    return rows


def report_bytes(report):
    """Canonical bounded report bytes; never writes a file or changes a result."""
    validate_report(report)
    raw=canonical_bytes(report)
    require(len(raw)<=MAX_BYTES['report'],'BOUND','report')
    return raw
