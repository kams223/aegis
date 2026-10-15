// Offline normalized records only. No wire protocol, I/O, clock reads or commands.
export const MAX_TELEMETRY_BYTES = 1024 * 1024;
export const FIELD_NAMES = ['altitude', 'ground_speed', 'battery', 'flight_mode', 'link_status', 'reception'] as const;
export type FieldName = typeof FIELD_NAMES[number];
export interface Stamp { readonly value: string; readonly unit: 'ms' | 'us' | 'ns'; readonly clock_domain: string }
export interface Identity { readonly vehicle_id: string; readonly autopilot_family: 'PX4' | 'ArduPilot'; readonly environment: 'SITL'; readonly source_id: string; readonly session_id: string; readonly system_id: number; readonly component_id: number }
export interface Source extends Identity { readonly source_clock_domain: string; readonly receipt_clock_domain: string }
export type FieldValue = Readonly<{ value: number; unit: 'm'; reference: 'home_relative' | 'mean_sea_level' | 'local_origin' | 'unknown'; reference_id: string | null }> | Readonly<{ value: number; unit: 'm/s' }> | Readonly<{ battery_id: string; percentage: number; unit: '%' }> | Readonly<{ base_mode: number; custom_mode: string }> | Readonly<{ status: string; note: string }>;
export interface RecordEntry extends Identity { readonly record_id: string; readonly field: FieldName; readonly value: FieldValue | null; readonly source_timestamp: Stamp | null; readonly receipt_timestamp: Stamp; readonly validation: 'valid' | 'invalid'; readonly diagnostic_codes: readonly string[]; readonly provenance: Readonly<{ kind: 'fictional_normalized' | 'recorded_normalized'; record_reference: string; note: string }> }
export interface Replay { readonly schema_version: 1; readonly normalization_policy_version: 1; readonly document_type: 'sitl_replay'; readonly description: string; readonly sources: readonly Source[]; readonly records: readonly RecordEntry[]; readonly evaluation_timestamp: Stamp; readonly policy: Readonly<{ fresh_for_ms: Readonly<Record<FieldName, number>>; reception_timeout_ms: number }> }
export interface Diagnostic { readonly record_index: number; readonly record_id: string; readonly code: string; readonly field: FieldName; readonly source_id: string; readonly session_id: string }
export interface FieldResult { readonly state: 'available' | 'stale' | 'missing' | 'invalid'; readonly validation: 'valid' | 'invalid' | 'not_evaluated'; readonly value: FieldValue | null; readonly age_ms: string | null; readonly record_id: string | null; readonly source_timestamp: Stamp | null; readonly receipt_timestamp: Stamp | null; readonly provenance: RecordEntry['provenance'] | null; readonly diagnostic_codes: readonly string[] }
export interface VehicleResult { readonly identity_key: string; readonly source: Source; readonly reception_state: 'records_received' | 'open' | 'silent' | 'closed' | 'unknown' | 'stale' | 'missing' | 'unsupported'; readonly last_receipt_timestamp: Stamp | null; readonly fields: Readonly<Record<FieldName, FieldResult>> }
export interface TelemetrySnapshot { readonly schema_version: 1; readonly normalization_policy_version: 1; readonly document_type: 'sitl_snapshot'; readonly recorded_only: true; readonly replay: Replay; readonly vehicles: readonly VehicleResult[]; readonly diagnostics: readonly Diagnostic[]; readonly summary: Readonly<{ accepted_count: number; rejected_count: number; validation: 'valid' | 'with_rejections' }> }
export class TelemetryError extends Error { constructor(message: string) { super(message); this.name = 'TelemetryError'; } }
const requireValue: (condition: unknown, message: string) => asserts condition = (condition, message) => { if (!condition) throw new TelemetryError(message); };
type Row = Record<string, unknown>;
function object(value: unknown, keys: readonly string[], name: string): Row {
  requireValue(typeof value === 'object' && value !== null && !Array.isArray(value), `${name}: expected object`);
  const row = value as Row;
  requireValue(Object.keys(row).length === keys.length && keys.every(k => Object.hasOwn(row, k)), `${name}: missing or unknown fields`); return row;
}
function text(value: unknown, name: string, id = false): asserts value is string {
  requireValue(typeof value === 'string' && value.length > 0 && value.length <= (id ? 128 : 1024) && value.trim().length > 0 && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value), `${name}: invalid bounded text`);
  if (id) requireValue(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(value), `${name}: invalid identifier`);
}
function integer(value: unknown, name: string, max: number, min = 0): void { requireValue(typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max, `${name}: invalid integer`); }
function finite(value: unknown): void { requireValue(typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1e12, 'Telemetry value: finite bounded number required'); }
function decimal(value: unknown, name: string, max = 18446744073709551615n): void { requireValue(typeof value === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(value) && BigInt(value) <= max, `${name}: require lossless unsigned decimal string`); }
function stamp(value: unknown, receipt = false): void {
  const row = object(value, ['value', 'unit', 'clock_domain'], 'Timestamp'); decimal(row.value, 'Timestamp'); text(row.clock_domain, 'Clock domain', true);
  requireValue(receipt ? row.unit === 'ms' : ['ms', 'us', 'ns'].includes(row.unit as string), 'Timestamp: unsupported unit');
}
const identityKeys = ['vehicle_id', 'autopilot_family', 'environment', 'source_id', 'session_id', 'system_id', 'component_id'];
function identity(row: Row): void {
  for (const k of ['vehicle_id', 'source_id', 'session_id']) text(row[k], k, true);
  requireValue(['PX4', 'ArduPilot'].includes(row.autopilot_family as string), 'Unsupported autopilot family'); requireValue(row.environment === 'SITL', 'Environment must be SITL');
  integer(row.system_id, 'System ID', 255, 1); integer(row.component_id, 'Component ID', 255, 1);
}
function valueShape(field: FieldName, value: unknown): void {
  if (value === null) return;
  if (field === 'altitude') {
    const row = object(value, ['value', 'unit', 'reference', 'reference_id'], 'Altitude'); finite(row.value);
    requireValue(row.unit === 'm' && ['home_relative', 'mean_sea_level', 'local_origin', 'unknown'].includes(row.reference as string), 'Altitude: unsupported units or reference');
    if (row.reference_id !== null) text(row.reference_id, 'Altitude reference ID', true);
  } else if (field === 'ground_speed') { const row = object(value, ['value', 'unit'], 'Ground speed'); finite(row.value); requireValue(row.unit === 'm/s', 'Ground speed: unsupported unit'); }
  else if (field === 'battery') { const row = object(value, ['battery_id', 'percentage', 'unit'], 'Battery'); text(row.battery_id, 'Battery ID', true); finite(row.percentage); requireValue(row.unit === '%', 'Battery: unsupported unit'); }
  else if (field === 'flight_mode') { const row = object(value, ['base_mode', 'custom_mode'], 'Flight mode'); integer(row.base_mode, 'Base mode', 255); decimal(row.custom_mode, 'Custom mode', 4294967295n); }
  else { const row = object(value, ['status', 'note'], 'Reception/link status'); if (field === 'reception') text(row.status, 'Reception declaration', true); else requireValue(['receiving', 'silent', 'closed', 'unknown'].includes(row.status as string), 'Unsupported reception/link status'); text(row.note, 'Status note'); }
}
function freeze<T>(value: T): T { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }
export function canonicalTelemetry(value: unknown): string {
  function ordered(x: unknown, depth = 0): unknown {
    requireValue(depth <= 24, 'Telemetry nesting exceeds 24 levels');
    if (typeof x === 'number') requireValue(Number.isFinite(x), 'Non-finite telemetry number');
    if (Array.isArray(x)) return x.map(v => ordered(v, depth + 1));
    if (x && typeof x === 'object') return Object.fromEntries(Object.entries(x).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => [k, ordered(v, depth + 1)]));
    requireValue(x === null || ['string', 'number', 'boolean'].includes(typeof x), 'Unsupported JSON value'); return x;
  }
  const result = JSON.stringify(ordered(value)); requireValue(typeof result === 'string' && new TextEncoder().encode(result).length + 1 <= MAX_TELEMETRY_BYTES, 'Telemetry output exceeds 1 MiB'); return result;
}
function parse(textValue: string): unknown {
  requireValue(typeof textValue === 'string' && new TextEncoder().encode(textValue).length <= MAX_TELEMETRY_BYTES, 'Telemetry input exceeds 1 MiB');
  let result: unknown; try { result = JSON.parse(textValue); } catch { throw new TelemetryError('Malformed telemetry JSON'); }
  const stack: ({ keys: Set<string>; keyExpected: boolean } | null)[] = [];
  for (const match of textValue.matchAll(/"(?:[^"\\]|\\.)*"|[{}\[\],:]/g)) {
    const token = match[0], top = stack.at(-1);
    if (token === '{') stack.push({ keys: new Set(), keyExpected: true }); else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop(); else if (token === ',' && top) top.keyExpected = true; else if (token === ':' && top) top.keyExpected = false;
    else if (token.startsWith('"') && top?.keyExpected) { const key = JSON.parse(token) as string; requireValue(!top.keys.has(key), 'Duplicate telemetry JSON key'); top.keys.add(key); top.keyExpected = false; }
    requireValue(stack.length <= 24, 'Telemetry nesting exceeds 24 levels');
  }
  return result;
}
function sourceKey(s: Identity): string { return `${s.source_id}/${s.session_id}/${s.system_id}/${s.component_id}`; }
function validateReplay(value: unknown): Replay {
  const row = object(value, ['schema_version', 'normalization_policy_version', 'document_type', 'description', 'sources', 'records', 'evaluation_timestamp', 'policy'], 'Replay');
  requireValue(row.schema_version === 1 && row.normalization_policy_version === 1 && row.document_type === 'sitl_replay', 'Unsupported replay schema or policy version'); text(row.description, 'Description'); stamp(row.evaluation_timestamp, true);
  const policy = object(row.policy, ['fresh_for_ms', 'reception_timeout_ms'], 'Policy'); const freshness = object(policy.fresh_for_ms, FIELD_NAMES, 'Freshness policy');
  for (const f of FIELD_NAMES) integer(freshness[f], 'Freshness interval', 3600000, 1); integer(policy.reception_timeout_ms, 'Reception timeout', 3600000, 1);
  requireValue(Array.isArray(row.sources) && row.sources.length <= 8, 'At most eight source/session identities allowed');
  const seen = new Set<string>();
  for (const value of row.sources) {
    const s = object(value, [...identityKeys, 'source_clock_domain', 'receipt_clock_domain'], 'Source'); identity(s); text(s.source_clock_domain, 'Source clock', true); text(s.receipt_clock_domain, 'Receipt clock', true);
    requireValue(s.receipt_clock_domain === (row.evaluation_timestamp as Stamp).clock_domain, 'Evaluation and receipt clocks must match');
    const key = sourceKey(s as unknown as Source); requireValue(!seen.has(key), 'Duplicate configured source/session identity'); seen.add(key);
  }
  requireValue(Array.isArray(row.records) && row.records.length <= 256, 'At most 256 normalized records allowed'); const ids = new Set<string>();
  for (const value of row.records) {
    const rec = object(value, [...identityKeys, 'record_id', 'field', 'value', 'source_timestamp', 'receipt_timestamp', 'validation', 'diagnostic_codes', 'provenance'], 'Record'); identity(rec); text(rec.record_id, 'Record ID', true);
    requireValue(!ids.has(rec.record_id as string), 'Duplicate record ID'); ids.add(rec.record_id as string);
    requireValue(FIELD_NAMES.includes(rec.field as FieldName), 'Unsupported telemetry field'); valueShape(rec.field as FieldName, rec.value);
    if (rec.source_timestamp !== null) stamp(rec.source_timestamp); stamp(rec.receipt_timestamp, true);
    requireValue(['valid', 'invalid'].includes(rec.validation as string), 'Unsupported validation status');
    requireValue(Array.isArray(rec.diagnostic_codes) && rec.diagnostic_codes.length <= 8, 'Invalid diagnostic code count');
    for (const code of rec.diagnostic_codes) requireValue(typeof code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(code), 'Invalid diagnostic code');
    const provenance = object(rec.provenance, ['kind', 'record_reference', 'note'], 'Provenance');
    requireValue(['fictional_normalized', 'recorded_normalized'].includes(provenance.kind as string), 'Unsupported provenance kind'); text(provenance.record_reference, 'Record reference', true); text(provenance.note, 'Provenance note');
  }
  // Own all records and nested values; never freeze or share the caller's input.
  return freeze(JSON.parse(canonicalTelemetry(value)) as Replay);
}
export function loadTelemetryReplay(textValue: string): Replay { return validateReplay(parse(textValue)); }
const nano = (s: Stamp) => BigInt(s.value) * (s.unit === 'ms' ? 1000000n : s.unit === 'us' ? 1000n : 1n);
export function replayTelemetry(input: Replay): TelemetrySnapshot {
  const replay = validateReplay(input), diagnostics: Diagnostic[] = [];
  const samples = replay.sources.map(() => new Map<FieldName, RecordEntry>()), errors = replay.sources.map(() => new Map<FieldName, string[]>());
  const last = replay.sources.map(() => null as Stamp | null), sourceTimes = replay.sources.map(() => null as Stamp | null);
  const unsupportedReception = replay.sources.map(() => false);
  let accepted = 0;
  replay.records.forEach((rec, index) => {
    const at = replay.sources.findIndex(s => sourceKey(s) === sourceKey(rec)); const source = replay.sources[at];
    let code: string | null = !source ? 'UNKNOWN_SOURCE_SESSION' : identityKeys.some(k => source[k as keyof Identity] !== rec[k as keyof Identity]) ? 'IDENTITY_CONFLICT' : rec.validation === 'invalid' ? 'INVALID_RECORD' : null;
    if (!code && source) {
      if (rec.receipt_timestamp.clock_domain !== source.receipt_clock_domain || (rec.source_timestamp && rec.source_timestamp.clock_domain !== source.source_clock_domain)) code = 'CLOCK_DOMAIN_MISMATCH';
      else if (nano(rec.receipt_timestamp) > nano(replay.evaluation_timestamp)) code = 'RECEIPT_AFTER_EVALUATION';
      else if ((last[at] && nano(rec.receipt_timestamp) < nano(last[at]!)) || (sourceTimes[at] && rec.source_timestamp && nano(rec.source_timestamp) < nano(sourceTimes[at]!))) code = 'TIMESTAMP_REGRESSION';
      else if (rec.value && rec.field === 'reception' && 'status' in rec.value && !['open', 'receiving', 'silent', 'closed', 'unknown'].includes(rec.value.status)) code = 'UNSUPPORTED_RECEPTION_DECLARATION';
      else if (rec.value && rec.field === 'altitude' && ('reference' in rec.value) && (rec.value.reference === 'unknown' || rec.value.reference_id === null)) code = 'ALTITUDE_REFERENCE_UNAVAILABLE';
      else if (rec.value && rec.field === 'battery' && ('percentage' in rec.value) && (rec.value.percentage < 0 || rec.value.percentage > 100)) code = 'VALUE_OUT_OF_RANGE';
      else if (rec.value && rec.field === 'ground_speed' && ('value' in rec.value) && rec.value.value < 0) code = 'VALUE_OUT_OF_RANGE';
    }
    if (code) {
      diagnostics.push({ record_index: index, record_id: rec.record_id, code, field: rec.field, source_id: rec.source_id, session_id: rec.session_id });
      if (source && code === 'UNSUPPORTED_RECEPTION_DECLARATION') unsupportedReception[at] = true;
      // Identity conflicts cannot poison a different configured vehicle.
      if (source && code !== 'IDENTITY_CONFLICT') errors[at]!.set(rec.field, [...new Set([...(errors[at]!.get(rec.field) ?? []), code])]);
      return;
    }
    if (rec.field === 'reception') unsupportedReception[at] = false;
    samples[at]!.set(rec.field, rec); last[at] = rec.receipt_timestamp; if (rec.source_timestamp) sourceTimes[at] = rec.source_timestamp; accepted++;
  });
  const vehicles: VehicleResult[] = replay.sources.map((source, at) => {
    const fields = Object.fromEntries(FIELD_NAMES.map(field => {
      const sample = samples[at]!.get(field), codes = errors[at]!.get(field) ?? [];
      const age = sample ? BigInt(replay.evaluation_timestamp.value) - BigInt(sample.receipt_timestamp.value) : null;
      const present = sample !== undefined && sample.value !== null;
      const result: FieldResult = { state: present ? age! > BigInt(replay.policy.fresh_for_ms[field]) ? 'stale' : 'available' : sample ? 'missing' : codes.length ? 'invalid' : 'missing', validation: sample ? 'valid' : codes.length ? 'invalid' : 'not_evaluated', value: sample?.value ?? null, age_ms: present ? age!.toString() : null, record_id: sample?.record_id ?? null, source_timestamp: sample?.source_timestamp ?? null, receipt_timestamp: sample?.receipt_timestamp ?? null, provenance: sample?.provenance ?? null, diagnostic_codes: [...new Set([...(sample?.diagnostic_codes ?? []), ...codes])] };
      return [field, result];
    })) as Record<FieldName, FieldResult>;
    const reception = fields.reception;
    const state = reception.value && 'status' in reception.value ? reception.value.status : null;
    // Only the reception declaration can establish reception status. Other
    // telemetry may update last_receipt_timestamp, never this field's freshness.
    const expired = reception.age_ms !== null && BigInt(reception.age_ms) > BigInt(replay.policy.reception_timeout_ms);
    const reception_state: VehicleResult['reception_state'] = unsupportedReception[at] ? 'unsupported'
      : state === null ? (reception.state === 'invalid' ? 'unknown' : 'missing')
      : reception.state === 'stale' || expired ? 'stale'
      : state === 'receiving' ? 'records_received' : state as VehicleResult['reception_state'];
    return { identity_key: `${sourceKey(source)}/${source.vehicle_id}`, source, reception_state, last_receipt_timestamp: last[at]!, fields };
  });
  const snapshot: TelemetrySnapshot = { schema_version: 1, normalization_policy_version: 1, document_type: 'sitl_snapshot', recorded_only: true, replay, vehicles, diagnostics, summary: { accepted_count: accepted, rejected_count: diagnostics.length, validation: diagnostics.length ? 'with_rejections' : 'valid' } };
  canonicalTelemetry(snapshot); return freeze(snapshot);
}
export function loadTelemetrySnapshot(textValue: string): TelemetrySnapshot {
  const row = object(parse(textValue), ['schema_version', 'normalization_policy_version', 'document_type', 'recorded_only', 'replay', 'vehicles', 'diagnostics', 'summary'], 'Snapshot');
  requireValue(row.schema_version === 1 && row.normalization_policy_version === 1 && row.document_type === 'sitl_snapshot' && row.recorded_only === true, 'Unsupported snapshot version or recorded-only boundary');
  const expected = replayTelemetry(validateReplay(row.replay));
  requireValue(canonicalTelemetry(row) === canonicalTelemetry(expected), 'Snapshot differs from reproducible replay; derived fields or diagnostics are invalid'); return expected;
}
