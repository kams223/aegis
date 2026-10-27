/** Offline temporal inspection over validated Phase 75D files. No fusion or clock access. */
import { compareTime, loadInspection, MAX_BYTES, SENSORS, sha256, uint64 } from './model';
import type { Inspection, RecordRow, Sensor, Timestamp } from './model';

export const MAX_REPLAY_ROWS = 1024;
export const MAX_REPLAY_DIAGNOSTICS = 4096;
export type ReplayStatus = 'fresh' | 'stale' | 'missing' | 'invalid';
export interface ReplayDiagnostic {
  code: string; evidence: 'input' | 'limitation'; dataset: number | null;
  index: number | null; sensor: Sensor | null; detail: string;
}
export interface ReplayEntry { dataset: number; index: number; available_ns: string | null; record: RecordRow }
export interface ReplayInput {
  inspection_sha256: string | null; input_sha256: string | null;
  example_kind: 'synthetic_fixture' | null; evidence_attestation: string | null;
}
export interface ReplayHistory {
  inputs: ReplayInput[]; domain: string; timeline: ReplayEntry[]; diagnostics: ReplayDiagnostic[]; diagnostics_dropped: number;
}
export interface ChannelState { history_index: number; timeline_index: number | null; status: ReplayStatus; age_ns: string | null }
export interface SensorState { sensor: Sensor; status: ReplayStatus; channels: ChannelState[] }
export interface ReplayResult {
  schema_version: 1; artifact_kind: 'offline_multisensor_replay'; evaluation: Timestamp;
  inputs: ReplayInput[]; stale_after_ns: string; timeline: ReplayEntry[]; sensors: SensorState[];
  diagnostics: ReplayDiagnostic[]; diagnostics_dropped: number;
}
// Include configuration and full source identity: equal-time raw/impaired and
// different recordings/configurations must never silently overwrite one another.
function channel(r: RecordRow): string {
  const s = r.source;
  return JSON.stringify([r.observation_type, s.session_id, s.vehicle_id, s.component_id,
    s.source_id, s.data_origin, s.clock_domain, r.source_sha256, r.origin, r.config_sha256]);
}
function collector(initial: readonly ReplayDiagnostic[] = [], dropped = 0) {
  const diagnostics = [...initial];
  return {diagnostics, add(d: ReplayDiagnostic) {
    if (diagnostics.length < MAX_REPLAY_DIAGNOSTICS) diagnostics.push(d); else dropped++;
  }, dropped: () => dropped};
}
/** Inputs must come from loadInspection. This does not relax that loader's rules. */
export function buildReplay(docs: readonly Inspection[], inspectionDigests: readonly string[] = []): ReplayHistory {
  if (!docs.length || docs.length > 2 || docs.reduce((n, d) => n + d.observations.length + d.rejected.length, 0) > MAX_REPLAY_ROWS)
    throw new Error('BOUND: replay requires 1–2 inspections and at most 1024 accepted plus rejected rows');
  if (inspectionDigests.length && (inspectionDigests.length !== docs.length || inspectionDigests.some(d => !/^[0-9a-f]{64}$/.test(d))))
    throw new Error('PROVENANCE: invalid inspection byte digests');
  const inputs: ReplayInput[] = docs.map((d, i) => ({inspection_sha256: inspectionDigests[i] ?? null,
    input_sha256: d.input_sha256 ?? null, example_kind: d.example_kind ?? null, evidence_attestation: d.evidence_attestation ?? null}));
  const domain = docs[0]!.evaluation.domain;
  if (docs.some(d => d.evaluation.domain !== domain)) throw new Error('CLOCK_DOMAIN: incompatible inspection domains; no conversion');
  const c = collector(), timeline: ReplayEntry[] = [], seen = new Set<string>();
  const high = new Map<string, bigint>(), provenance = new Map<string, string>();
  docs.forEach((doc, dataset) => {
    doc.observations.forEach(({record: r}, index) => {
      const key = channel(r), acquisition = uint64(r.acquisition.value_ns);
      if ([r.acquisition, r.simulation, r.delivery].some(t => t && t.domain !== domain) || r.source.clock_domain !== domain)
        throw new Error('CLOCK_DOMAIN: incompatible record domain');
      const add = (code: string, detail: string, evidence: ReplayDiagnostic['evidence'] = 'input') => c.add({code, detail, evidence, dataset, index, sensor: r.observation_type});
      const duplicate = JSON.stringify([key, r.acquisition.value_ns]);
      if (seen.has(duplicate)) add('DUPLICATE', 'Repeated channel acquisition retained; stable input order breaks ties.');
      seen.add(duplicate);
      if (r.delivery) {
        const delivery = uint64(r.delivery.value_ns);
        if (delivery < (high.get(key) ?? -1n)) add('DELIVERY_REGRESSION', 'Known delivery regresses in supplied inspection order.');
        high.set(key, delivery > (high.get(key) ?? -1n) ? delivery : high.get(key)!);
      } else add('AVAILABILITY_UNKNOWN', 'Delivery was not recorded; selected-time availability cannot be established.', 'limitation');
      if (r.values === null) add('DROPOUT', 'Explicit unavailable observation; no measurement or zero fill.');
      const identity = JSON.stringify([r.source.session_id, r.source.source_id, r.origin, r.config_sha256]);
      if (provenance.has(identity) && provenance.get(identity) !== r.source_sha256)
        add('SOURCE_PROVENANCE', 'Same session/source/origin/configuration refers to different recording digests; channels remain separate.');
      provenance.set(identity, r.source_sha256);
      // Validate precision here too; all other record semantics are loader-owned.
      if (r.delivery && uint64(r.delivery.value_ns) < acquisition) throw new Error('TIMESTAMP: delivery precedes acquisition');
      timeline.push({dataset, index, available_ns: r.delivery?.value_ns ?? null, record: r});
    });
    doc.rejected.forEach(r => c.add({code: r.diagnostic.code, evidence: 'input', dataset, index: null,
      sensor: SENSORS.includes(r.sensor as Sensor) ? r.sensor as Sensor : null,
      detail: `Rejected original input index ${r.index}, sensor ${r.sensor ?? 'unknown'}, severity ${r.diagnostic.severity ?? 'unspecified'}: ${r.diagnostic.path}: ${r.diagnostic.explanation}`}));
    doc.anomalies.forEach(a => c.add({code: a.code, evidence: 'input', dataset, index: null, sensor: null,
      detail: `Producer diagnostic at original input index ${a.index}; not a replay observation index.`}));
    doc.source_diagnostics?.forEach(d => d.reasons.forEach(code => c.add({code: `SOURCE_${code}`, evidence: 'input', dataset, index: null, sensor: d.sensor,
      detail: `Producer input index ${d.index}, acquisition ${d.acquisition_ns} ns; recorded label, not selected-time freshness.`})));
  });
  timeline.sort((a, b) => compareTime(a.record.acquisition.value_ns, b.record.acquisition.value_ns)
    || SENSORS.indexOf(a.record.observation_type) - SENSORS.indexOf(b.record.observation_type)
    || a.dataset - b.dataset || a.index - b.index);
  for (const sensor of SENSORS) if (!timeline.some(e => e.record.observation_type === sensor))
    c.add({code: 'MISSING_HISTORY', evidence: 'limitation', dataset: null, index: null, sensor, detail: 'No accepted history; expected sampling rate and absent samples are unknown.'});
  return {inputs, domain, timeline, diagnostics: c.diagnostics, diagnostics_dropped: c.dropped()};
}
function validateEvaluation(evaluation: Timestamp, staleAfterNs: string) {
  if (Object.keys(evaluation).some(k => !['schema_version', 'value_ns', 'domain', 'unit'].includes(k))
    || evaluation.schema_version !== 1 || evaluation.unit !== 'ns' || typeof evaluation.domain !== 'string'
    || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(evaluation.domain)
    || typeof evaluation.value_ns !== 'string' || typeof staleAfterNs !== 'string')
    throw new Error('TIMESTAMP: require version 1 ns timestamp with explicit bounded domain');
  uint64(evaluation.value_ns); uint64(staleAfterNs);
}
export function inspectReplay(history: ReplayHistory, evaluation: Timestamp, staleAfterNs: string): ReplayResult {
  const c = collector(history.diagnostics, history.diagnostics_dropped);
  let now = 0n, threshold = 0n, invalid = false;
  try {
    validateEvaluation(evaluation, staleAfterNs);
    now = uint64(evaluation.value_ns); threshold = uint64(staleAfterNs);
    if (evaluation.domain !== history.domain) throw new Error('CLOCK_DOMAIN: unknown evaluation domain; no clock conversion');
  } catch (error) {
    invalid = true;
    c.add({code: evaluation.domain !== history.domain ? 'CLOCK_DOMAIN' : 'TIMESTAMP', evidence: 'input', dataset: null, index: null, sensor: null, detail: String(error)});
  }
  const sensors: SensorState[] = SENSORS.map(sensor => {
    const candidates = new Map<string, {first: number; latest: number | null}>();
    history.timeline.forEach((entry, i) => {
      const r = entry.record;
      if (r.observation_type !== sensor) return;
      const key = channel(r);
      if (!candidates.has(key)) candidates.set(key, {first: i, latest: null});
      if (invalid || entry.available_ns === null || uint64(entry.available_ns) > now || uint64(r.acquisition.value_ns) > now) return;
      const candidate = candidates.get(key)!;
      const previous = candidate.latest;
      // First stable entry wins equal acquisition ties; delayed older arrivals
      // never displace a more recently acquired eligible observation.
      if (previous === null || previous === undefined || compareTime(history.timeline[previous]!.record.acquisition.value_ns, r.acquisition.value_ns) < 0)
        candidate.latest = i;
    });
    const channels: ChannelState[] = [...candidates.values()].map(({first, latest: i}) => {
      if (invalid || i === null) {
        if (!invalid) {
          const entry = history.timeline[first]!;
          c.add({code: 'NO_ELIGIBLE_OBSERVATION', evidence: 'limitation', dataset: entry.dataset, index: entry.index, sensor,
            detail: 'No observation has known delivery at or before evaluation; future and unknown-delivery history is not an available measurement.'});
        }
        return {history_index: first, timeline_index: null, status: invalid ? 'invalid' : 'missing', age_ns: null};
      }
      const entry = history.timeline[i]!, age = now - uint64(entry.record.acquisition.value_ns);
      const status = entry.record.values === null ? 'missing' : age > threshold ? 'stale' : 'fresh';
      if (status === 'stale') c.add({code: 'STALE', evidence: 'input', dataset: entry.dataset, index: entry.index, sensor, detail: `Selected-time age ${age} ns exceeds threshold ${staleAfterNs} ns.`});
      return {history_index: first, timeline_index: i, status, age_ns: String(age)};
    });
    if (channels.length > 1) c.add({code: 'MULTIPLE_CHANNELS', evidence: 'limitation', dataset: null, index: null, sensor, detail: 'Multiple provenance channels; inspect each separately. No single sensor state is inferred.'});
    return {sensor, status: invalid || channels.length > 1 ? 'invalid' : channels[0]?.status ?? 'missing', channels};
  });
  return {schema_version: 1, artifact_kind: 'offline_multisensor_replay', evaluation: {...evaluation}, stale_after_ns: staleAfterNs, inputs: history.inputs,
    timeline: history.timeline, sensors, diagnostics: c.diagnostics, diagnostics_dropped: c.dropped()};
}
/** Bounded offline entry point; strict Phase 75D validation is reused unchanged. */
export async function replayInspections(texts: readonly string[], evaluation: Timestamp, staleAfterNs: string): Promise<ReplayResult> {
  if (!texts.length || texts.length > 2) throw new Error('BOUND: select 1–2 inspection files');
  const docs: Inspection[] = [], digests: string[] = [];
  for (const text of texts) {docs.push(await loadInspection(text)); digests.push(await sha256(text));}
  // Exported JSON has a closed versioned schema; invalid requests fail before export.
  validateEvaluation(evaluation, staleAfterNs);
  const history = buildReplay(docs, digests);
  if (evaluation.domain !== history.domain) throw new Error('CLOCK_DOMAIN: incompatible evaluation domain');
  return inspectReplay(history, evaluation, staleAfterNs);
}
export function encodeReplay(result: ReplayResult): string {
  validateEvaluation(result.evaluation, result.stale_after_ns);
  const text = JSON.stringify(result) + '\n';
  if (new TextEncoder().encode(text).length > MAX_BYTES) throw new Error('BOUND: replay output exceeds 8 MiB');
  return text;
}
