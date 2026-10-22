import wireSchema from '../../../../configs/simulation/sensor-telemetry-v1.schema.json';
import { parseJson, validate } from './schema';
import type { Schema } from './schema';

export const MAX_BYTES = 8 * 1024 * 1024;
export const SENSORS = ['imu', 'gnss', 'barometer'] as const;
export type Sensor = typeof SENSORS[number];
export type Freshness = 'missing' | 'future' | 'pending' | 'stale' | 'fresh';
export interface Timestamp { schema_version: 1; value_ns: string; domain: string; unit: 'ns' }
export interface Field { schema_version: 1; name: string; value: number; unit: string }
export interface RecordRow {
  schema_version: 1; observation_type: Sensor;
  source: { schema_version: 1; session_id: string; vehicle_id: string; component_id: Sensor; source_id: string; data_origin: 'recorded'; clock_domain: string };
  acquisition: Timestamp; simulation: Timestamp; delivery: Timestamp | null;
  frame: string; origin: 'raw' | 'impaired'; source_sha256: string;
  config_json: string | null; config_sha256: string | null; seed_identifier: string | null; values: Field[] | null;
}
interface Rejection { index: number; sensor: string | null; diagnostic: { schema_version?: 1; code: string; path: string; explanation: string; severity?: string } }
export interface Inspection {
  schema_version: 1; artifact_kind: 'offline_sensor_telemetry_inspection'; evaluation: Timestamp; stale_after_ns: string;
  observations: { record: RecordRow; freshness: Freshness }[];
  rejected: Rejection[]; anomalies: { index: number; code: string }[];
  source_diagnostics?: { index: number; sensor: Sensor; acquisition_ns: string; reasons: string[] }[];
  input_sha256?: string; example_kind?: 'synthetic_fixture'; evidence_attestation?: string;
  summary: Record<Sensor, { count: number; rejected: number; missing: number; latest_acquisition_ns: string | null; freshness: Freshness; origins: {raw: number; impaired: number}; units: Record<string, string>; frames: string[] }>;
}
const obj = (properties: Record<string, Schema>, optional: string[] = []): Schema => ({ type: 'object', properties, required: Object.keys(properties).filter(k => !optional.includes(k)), additionalProperties: false });
const str: Schema = { type: 'string', minLength: 1, maxLength: 1024 };
const identity: Schema = { type: 'string', maxLength: 128, pattern: '^[A-Za-z0-9][A-Za-z0-9_.:-]*$' };
const ns: Schema = { type: 'string', pattern: '^(0|[1-9][0-9]{0,19})$' };
const nullable = (s: Schema): Schema => ({ anyOf: [s, {type: 'null'}] });
const array = (items: Schema, maxItems = 1024): Schema => ({type: 'array', items, maxItems});
const count: Schema = {type: 'integer', minimum: 0, maximum: 1024};
const sensor: Schema = { enum: SENSORS };
const state: Schema = { enum: ['missing', 'future', 'pending', 'stale', 'fresh'] };
const timestamp = obj({schema_version: {const: 1}, value_ns: ns, domain: identity, unit: {const: 'ns'}});
const summary = obj({count, rejected: count, missing: count, latest_acquisition_ns: nullable(ns), freshness: state,
  origins: obj({raw: count, impaired: count}), units: {type: 'object'}, frames: array(str, 3)});
const diagnostic = obj({schema_version: {const: 1}, code: str, path: str, explanation: str, severity: {enum: ['error', 'unavailable']}}, ['schema_version', 'severity']);
const recordSchema = {oneOf: wireSchema.properties.observations.items.oneOf} as Schema;
const inspectionSchema = obj({schema_version: {const: 1}, artifact_kind: {const: 'offline_sensor_telemetry_inspection'}, evaluation: timestamp,
  stale_after_ns: ns, observations: array(obj({record: recordSchema, freshness: state})),
  rejected: array(obj({index: { ...count, maximum: 1023 }, sensor: nullable(str), diagnostic})),
  anomalies: array(obj({index: {...count, maximum: 1023}, code: {enum: ['OUT_OF_ORDER', 'DELIVERY_REGRESSION']}}), 2048),
  summary: obj(Object.fromEntries(SENSORS.map(s => [s, summary]))),
  source_diagnostics: array(obj({index: {...count, maximum: 1023}, sensor, acquisition_ns: ns, reasons: array({enum: ['MISSING_OBSERVATION', 'OUT_OF_ORDER', 'STALE', 'PRESSURE_DOMAIN', 'GEOGRAPHIC_RANGE', 'QUATERNION_NORM']}, 8)})),
  input_sha256: {type: 'string', pattern: '^[0-9a-f]{64}$'}, example_kind: {const: 'synthetic_fixture'}, evidence_attestation: str,
}, ['source_diagnostics', 'input_sha256', 'example_kind', 'evidence_attestation']);
export function uint64(value: string): bigint {
  if (!/^(0|[1-9][0-9]{0,19})$/.test(value) || BigInt(value) > 18446744073709551615n) throw new Error('Invalid uint64 nanoseconds');
  return BigInt(value);
}
function requireValue(ok: unknown, why: string): asserts ok { if (!ok) throw new Error(why); }
function freeze<T>(v: T): T { if (v && typeof v === 'object') { Object.values(v).forEach(freeze); Object.freeze(v); } return v; }
export function freshness(r: RecordRow, evaluation: Timestamp, threshold: string): Freshness {
  requireValue(r.source.clock_domain === evaluation.domain, 'CLOCK_DOMAIN: selected evaluation domain differs');
  const now = uint64(evaluation.value_ns), acquisition = uint64(r.acquisition.value_ns), stale = uint64(threshold);
  if (r.values === null) return 'missing';
  if (acquisition > now) return 'future';
  if (r.delivery && uint64(r.delivery.value_ns) > now) return 'pending';
  return now - acquisition > stale ? 'stale' : 'fresh';
}
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object') return `{${Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, child]) => `${JSON.stringify(k)}:${canonical(child)}`).join(',')}}`;
  return JSON.stringify(v);
}
export async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function checkConfig(r: RecordRow) {
  if (r.origin === 'raw') { requireValue(r.config_json === null && r.config_sha256 === null && r.seed_identifier === null, 'PROVENANCE: raw impairment metadata'); return; }
  requireValue(r.config_json !== null, 'PROVENANCE: missing configuration');
  const config = parseJson(r.config_json) as {seed: number; reference_ns: number; stale_after_ns: number; rules: {sensor: Sensor; field: string; unit: string; noise_std: number}[]; policies: {sensor: Sensor; dropout_probability: number; latency_ns: number; jitter_ns: number}[]};
  const integer: Schema = {type: 'integer', minimum: 0, maximum: Number.MAX_SAFE_INTEGER};
  const number: Schema = {type: 'number', minimum: -1e6, maximum: 1e6};
  validate(config, obj({schema_version: {const: 1}, seed: integer, reference_ns: integer, stale_after_ns: integer,
    rules: array(obj({schema_version: {const: 1}, sensor, field: str, unit: str, noise_std: {...number, minimum: 0}, bias: number, drift_per_second: number}), 256),
    policies: array(obj({schema_version: {const: 1}, sensor, dropout_probability: {type: 'number', minimum: 0, maximum: 1}, latency_ns: {...integer, maximum: 1e12}, jitter_ns: integer}), 3)}), 'config');
  requireValue(new Set(config.rules.map(x => `${x.sensor}/${x.field}`)).size === config.rules.length && new Set(config.policies.map(x => x.sensor)).size === config.policies.length, 'SCHEMA: duplicate config rule/policy');
  for (const p of config.policies) requireValue(p.jitter_ns <= p.latency_ns, 'BOUND: jitter exceeds latency');
  for (const rule of config.rules) {
    const variant = wireSchema.properties.observations.items.oneOf[SENSORS.indexOf(rule.sensor) === 0 ? 0 : rule.sensor === 'gnss' ? 1 : 2]!;
    const fields = variant.properties.values.anyOf[0]!.items!.oneOf!;
    requireValue(!rule.field.startsWith('orientation.') && rule.field !== 'variance' && rule.field !== 'derived_altitude' && fields.some(f => f.properties.name.const === rule.field && f.properties.unit.const === rule.unit), 'UNITS: unsupported impairment rule');
  }
  requireValue(r.seed_identifier === String(config.seed) && r.config_sha256 === await sha256(r.config_json + '\n'), 'PROVENANCE: configuration digest or seed differs');
}
export async function loadInspection(text: string): Promise<Inspection> {
  requireValue(new TextEncoder().encode(text).length <= MAX_BYTES, 'File exceeds 8 MiB');
  const data = parseJson(text);
  validate(data, inspectionSchema);
  function textBounds(v: unknown): void {
    if (typeof v === 'string') requireValue(v.length > 0 && v.length <= 1024 && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(v), 'Invalid bounded contract string');
    if (v && typeof v === 'object') Object.values(v).forEach(textBounds);
  }
  textBounds(data);
  const doc = data as Inspection;
  uint64(doc.evaluation.value_ns); uint64(doc.stale_after_ns);
  requireValue(doc.observations.length + doc.rejected.length <= 1024, 'Record limit exceeds 1024');
  const seen = new Set<string>(), configs = new Set<string>();
  for (const {record: r, freshness: saved} of doc.observations) {
    requireValue(r.source.component_id === r.observation_type && r.source.source_id === r.frame, 'IDENTITY: sensor/frame differs');
    for (const t of [r.acquisition, r.simulation, r.delivery]) if (t) { uint64(t.value_ns); requireValue(t.domain === r.source.clock_domain, 'CLOCK_DOMAIN: record timestamp differs'); }
    requireValue(uint64(r.acquisition.value_ns) <= uint64(r.simulation.value_ns) && (!r.delivery || uint64(r.simulation.value_ns) <= uint64(r.delivery.value_ns)), 'TIMESTAMP: acquisition/simulation/delivery order');
    requireValue(saved === freshness(r, doc.evaluation, doc.stale_after_ns), 'Freshness disagrees with recorded evaluation');
    const key = canonical([r.source, r.acquisition, r.origin]);
    requireValue(!seen.has(key), 'DUPLICATE: accepted observation'); seen.add(key);
    const names = new Set(r.values?.map(f => f.name));
    requireValue(names.size === (r.values?.length ?? 0), 'UNITS: duplicate fields');
    for (const [group, axes] of [['acceleration', 'xyz'], ['angular_velocity', 'xyz'], ['orientation', 'xyzw']]) {
      const present = [...names].filter(n => n.startsWith(group + '.'));
      requireValue(!present.length || present.length === axes!.length, 'SCHEMA: incomplete vector');
    }
    requireValue(r.values === null || (r.observation_type === 'gnss' ? ['latitude', 'longitude', 'altitude'].every(n => names.has(n)) : r.observation_type !== 'barometer' || names.has('pressure')), 'SCHEMA: required fields missing');
    const configKey = canonical([r.origin, r.config_json, r.config_sha256, r.seed_identifier]);
    if (!configs.has(configKey)) { await checkConfig(r); configs.add(configKey); }
  }
  for (const s of SENSORS) {
    const rows = doc.observations.filter(x => x.record.observation_type === s), sum = doc.summary[s];
    const available = rows.filter(x => ['fresh', 'stale'].includes(x.freshness)).sort((a, b) => compareTime(a.record.acquisition.value_ns, b.record.acquisition.value_ns));
    const last = available.at(-1);
    requireValue(sum.count === rows.length && sum.missing === rows.filter(x => x.record.values === null).length && sum.rejected === doc.rejected.filter(x => x.sensor === s).length && sum.latest_acquisition_ns === (last?.record.acquisition.value_ns ?? null) && sum.freshness === (last?.freshness ?? 'missing'), 'Summary counts/freshness disagree');
    requireValue(['raw', 'impaired'].every(o => sum.origins[o as 'raw' | 'impaired'] === rows.filter(x => x.record.origin === o).length), 'Summary origins disagree');
    const units = Object.fromEntries(rows.flatMap(x => x.record.values ?? []).map(f => [f.name, f.unit]));
    requireValue(canonical(sum.units) === canonical(units) && canonical(sum.frames) === canonical([...new Set(rows.map(x => x.record.frame))].sort()), 'Summary units/frames disagree');
  }
  for (const d of doc.source_diagnostics ?? []) { uint64(d.acquisition_ns); requireValue(new Set(d.reasons).size === d.reasons.length, 'Duplicate source diagnostics'); }
  return freeze(doc);
}
export function compareTime(a: string, b: string) { return BigInt(a) < BigInt(b) ? -1 : BigInt(a) > BigInt(b) ? 1 : 0; }
export function filterRecords(doc: Inspection, sensor: Sensor | 'all') { return doc.observations.map(x => x.record).filter(r => sensor === 'all' || r.observation_type === sensor).sort((a, b) => compareTime(a.acquisition.value_ns, b.acquisition.value_ns)); }
export function chartData(rows: readonly RecordRow[], field: string, limit = 256) {
  requireValue(Number.isInteger(limit) && limit >= 2, 'Invalid chart limit');
  const points = rows.map(r => ({time: r.acquisition.value_ns, value: r.values?.find(f => f.name === field)?.value ?? null}));
  if (points.length <= limit) return points;
  // Retain null gaps in each bucket; downsampling must never bridge a dropout.
  return Array.from({length: limit}, (_, i) => {
    const start = Math.floor(i * points.length / limit), end = Math.floor((i + 1) * points.length / limit);
    return points.slice(start, end).find(p => p.value === null) ?? points[i === limit - 1 ? points.length - 1 : start]!;
  });
}
export function matchOriginal(r: RecordRow, originals: readonly RecordRow[]) {
  return originals.find(o => o.origin === 'raw' && o.source_sha256 === r.source_sha256 && canonical(o.source) === canonical(r.source) && canonical(o.acquisition) === canonical(r.acquisition)) ?? null;
}
