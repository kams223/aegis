import type { Session, Snapshot } from './models';

type Shape = Record<string, string>;
const review = '=unreviewed|under_review|reviewed|dismissed';
const connection = '=offline|recorded|unknown';
const shapes: Record<string, Shape> = {
  Timestamp: { value: 'number', unit: '=s|ms|us|ns', clock_domain: 'string' },
  Adapter: { adapter_id: 'id', version: 'string' },
  Capability: { name: '=recorded_metadata|recorded_integrity|health_snapshot|observation_display|camera_evidence', support: '=supported|unsupported|unknown' },
  Health: { status: '=healthy|degraded|unavailable|unknown', timestamp: '@Timestamp', note: 'text' },
  Source: { source_id: 'id', device_id: 'id', clock_domain: 'string', evidence_id: 'id' },
  Device: { device_id: 'id', category: '=aegis_native|third_party|simulated', device_type: '=aerial|ground|other', adapter: '@Adapter', capabilities: '[]@Capability', connection_status: connection, health: '@Health', sources: '[]@Source' },
  Registry: { devices: '[]@Device' },
  Evidence: { evidence_id: 'id', source_id: 'id', kind: '=camera_recording|dataset_report|validation_result|observation_note|health_snapshot', local_path: 'path', dataset_id: '?id' },
  Observation: { observation_id: 'id', source_id: 'id', timestamp: '@Timestamp', category: '=synthetic|recorded_metadata', quality: '=declared|uncertain|missing', uncertainty_note: '?string', annotation: 'text', review_status: review, evidence_id: 'id' },
  Availability: { source_id: 'id', status: '=available|unavailable|unknown' },
  Sentinel: { device_id: 'id', sentinel_category: '=aerial|ground', connectivity: connection, sensors: '[]@Availability', battery_percent: '?battery', maintenance_status: '=nominal|due|unknown', camera_evidence_id: '?id', review_status: review },
  Explanation: { code: '=unusual_metadata|quality_warning|review_requested', explanation: 'text', evidence_ids: '[]id' },
  Alert: { alert_id: 'id', observation_id: 'id', status: review, explanation: '@Explanation' },
  Request: { request_id: 'id', alert_id: 'id', action: '=inspect_dataset_report|retrieve_evidence|summarize_device_health|explain_observation|compare_validation_results', reference_ids: '[]id' },
  Result: { result_id: 'id', request_id: 'id', status: '=completed|not_evaluated', summary: 'text', evidence_ids: '[]id' },
  Review: { decision_id: 'id', subject_kind: '=observation|sentinel|alert', subject_id: 'id', reviewer_id: 'id', previous_status: review, new_status: review, timestamp: '@Timestamp', note: 'text' },
  Audit: { audit_id: 'id', actor_id: 'id', event: '=investigation_completed|investigation_not_evaluated|human_review', reference_id: 'id', timestamp: '@Timestamp', note: 'text' },
  Outcome: { evidence_id: 'id', dataset_id: 'id', metadata_status: '=passed|failed|not_evaluated', integrity_status: '=verified|mismatch|not_evaluated' },
  Snapshot: { snapshot_id: 'id', description: 'text', registry: '@Registry', evidence: '[]@Evidence', observations: '[]@Observation', sentinels: '[]@Sentinel', alerts: '[]@Alert', investigation_requests: '[]@Request', investigation_results: '[]@Result', review_history: '[]@Review', audit_entries: '[]@Audit', validation_results: '[]@Outcome' },
  Diagnostic: { event_id: 'id', event_index: 'index', device_id: 'id', source_id: '?id', code: '=DUPLICATE_EVENT_ID|UNKNOWN_DEVICE|SOURCE_ASSOCIATION|CLOCK_DOMAIN_MISMATCH|TIMESTAMP_REGRESSION|CONFLICTING_UPDATE|MONITOR_UNAVAILABLE|DUPLICATE_EVIDENCE_ID|DUPLICATE_OBSERVATION_ID|REVIEW_ASSOCIATION|UNAVAILABLE_MEASUREMENT|SNAPSHOT_REJECTED', severity: '=Rejected', explanation: 'text' },
  Event: { event_id: 'id', event_index: 'index', event_type: '=device_connectivity|device_health|sensor_availability|evidence_announcement|observation_announcement|human_review', device_id: 'id', source_id: '?id', timestamp: '@Timestamp', status: '=applied|rejected', diagnostics: '[]@Diagnostic' },
  Summary: { event_count: 'count', applied_count: 'count', rejected_count: 'count', status: '=completed|completed_with_rejections' },
  Session: { initial_snapshot_id: 'id', event_results: '[]@Event', final_snapshot: '@Snapshot', summary: '@Summary' },
};

export class FixtureError extends Error { constructor(message: string) { super(message); this.name = 'FixtureError'; } }
function requireValue(condition: unknown, message: string): asserts condition { if (!condition) throw new FixtureError(message); }

function check(spec: string, value: unknown, path: string): void {
  if (spec.startsWith('?')) { if (value !== null) check(spec.slice(1), value, path); return; }
  if (spec.startsWith('[]')) {
    requireValue(Array.isArray(value) && value.length <= 256, `${path}: expected array of at most 256 entries`);
    value.forEach((item: unknown, i: number) => check(spec.slice(2), item, `${path}[${i}]`)); return;
  }
  if (spec.startsWith('@')) {
    const fields = shapes[spec.slice(1)]; requireValue(fields, 'Unsupported validator schema');
    requireValue(typeof value === 'object' && value !== null && !Array.isArray(value), `${path}: required object`);
    const row = value as Record<string, unknown>;
    const keys = ['schema_version', ...Object.keys(fields)];
    requireValue(Object.keys(row).length === keys.length && keys.every(key => Object.hasOwn(row, key)), `${path}: missing or unexpected fields`);
    requireValue(row.schema_version === 1, `${path}: unsupported schema version`);
    Object.entries(fields).forEach(([key, child]) => check(child, row[key], `${path}.${key}`)); return;
  }
  if (spec.startsWith('=')) { requireValue(typeof value === 'string' && spec.slice(1).split('|').includes(value), `${path}: unsupported value`); return; }
  if (['number', 'count', 'index', 'battery'].includes(spec)) {
    requireValue(typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1e18, `${path}: finite bounded number required`);
    if (spec === 'count' || spec === 'index') requireValue(Number.isInteger(value) && value >= 0 && value <= (spec === 'index' ? 255 : 256), `${path}: invalid count or index`);
    if (spec === 'battery') requireValue(value >= 0 && value <= 100, `${path}: invalid battery percentage`); return;
  }
  const limit = spec === 'text' ? 1024 : spec === 'path' ? 256 : 128;
  requireValue(typeof value === 'string' && value.trim().length > 0 && Array.from(value).length <= limit, `${path}: bounded nonempty string required`);
  requireValue(!Array.from(value).some(char => { const n = char.codePointAt(0)!; return n < 32 || n === 127 || (n >= 0xd800 && n <= 0xdfff); }), `${path}: invalid text encoding`);
  if (spec === 'id') requireValue(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(value), `${path}: malformed identifier`);
  if (spec === 'path') requireValue(!/[\\:%?#]/.test(value) && value.split('/').every(part => part !== '' && part !== '.' && part !== '..'), `${path}: unsafe evidence path`);
}

function keyed<T>(rows: T[], key: (row: T) => string, label: string): Map<string, T> {
  const result = new Map<string, T>();
  rows.forEach(row => { const id = key(row); requireValue(!result.has(id), `${label}: duplicate identifier`); result.set(id, row); }); return result;
}
function uniqueStrings(values: string[], label: string): void { requireValue(new Set(values).size === values.length, `${label}: duplicate reference`); }
function sameTime(a: { value: number; unit: string; clock_domain: string }, b: typeof a): boolean { return a.value === b.value && a.unit === b.unit && a.clock_domain === b.clock_domain; }

function relationships(snapshot: Snapshot): void {
  const devices = keyed(snapshot.registry.devices, d => d.device_id, 'Devices');
  const allSources = snapshot.registry.devices.flatMap(d => d.sources);
  requireValue(allSources.length <= 256, 'Source inventory exceeds 256 entries');
  const sources = keyed(allSources, s => s.source_id, 'Sources');
  const evidence = keyed(snapshot.evidence, e => e.evidence_id, 'Evidence');
  const observations = keyed(snapshot.observations, o => o.observation_id, 'Observations');
  const sentinels = keyed(snapshot.sentinels, s => s.device_id, 'Sentinels');
  const alerts = keyed(snapshot.alerts, a => a.alert_id, 'Alerts');
  const requests = keyed(snapshot.investigation_requests, r => r.request_id, 'Requests');
  const results = keyed(snapshot.investigation_results, r => r.result_id, 'Results');
  const decisions = keyed(snapshot.review_history, r => r.decision_id, 'Reviews');
  keyed(snapshot.audit_entries, a => a.audit_id, 'Audits');
  keyed(snapshot.validation_results, o => o.evidence_id, 'Validation outcomes');
  snapshot.registry.devices.forEach(device => {
    uniqueStrings(device.capabilities.map(c => c.name), 'Capabilities');
    device.sources.forEach(source => requireValue(source.device_id === device.device_id && evidence.get(source.evidence_id)?.source_id === source.source_id, 'Dangling or inconsistent source reference'));
  });
  snapshot.evidence.forEach(e => {
    requireValue(sources.has(e.source_id), 'Dangling evidence source');
    if (['dataset_report', 'validation_result'].includes(e.kind)) requireValue(e.dataset_id !== null, 'Report evidence requires dataset identity');
  });
  snapshot.observations.forEach(o => {
    const source = sources.get(o.source_id);
    requireValue(source && evidence.get(o.evidence_id)?.source_id === o.source_id, 'Dangling observation evidence or source');
    requireValue(source.clock_domain === o.timestamp.clock_domain, 'Observation clock domain mismatch');
    requireValue(devices.get(source.device_id)?.capabilities.some(c => c.name === 'observation_display' && c.support === 'supported'), 'Unsupported display capability');
    if (o.quality !== 'declared') requireValue(o.uncertainty_note !== null, 'Missing uncertainty explanation');
  });
  snapshot.sentinels.forEach(s => {
    const device = devices.get(s.device_id); requireValue(device, 'Dangling Sentinel device');
    requireValue(device.device_type === s.sentinel_category && device.connection_status === s.connectivity, 'Inconsistent Sentinel device state');
    uniqueStrings(s.sensors.map(sensor => sensor.source_id), 'Sensor availability');
    requireValue(s.sensors.length === device.sources.length && s.sensors.every(sensor => device.sources.some(source => source.source_id === sensor.source_id)), 'Inconsistent Sentinel sensor inventory');
    if (s.camera_evidence_id !== null) {
      const ref = evidence.get(s.camera_evidence_id);
      requireValue(ref?.kind === 'camera_recording' && device.sources.some(source => source.source_id === ref.source_id), 'Dangling camera reference');
      requireValue(device.capabilities.some(c => c.name === 'camera_evidence' && c.support === 'supported'), 'Unsupported camera capability');
    }
  });
  snapshot.alerts.forEach(a => {
    const observation = observations.get(a.observation_id); requireValue(observation, 'Dangling alert observation');
    uniqueStrings(a.explanation.evidence_ids, 'Alert evidence');
    requireValue(a.explanation.evidence_ids.includes(observation.evidence_id) && a.explanation.evidence_ids.every(id => evidence.has(id)), 'Dangling alert evidence');
  });
  snapshot.investigation_requests.forEach(r => {
    const alert = alerts.get(r.alert_id); requireValue(alert, 'Dangling investigation alert');
    uniqueStrings(r.reference_ids, 'Investigation references');
    requireValue(r.reference_ids.length === (r.action === 'compare_validation_results' ? 2 : 1), 'Invalid investigation reference count');
    r.reference_ids.forEach(id => {
      if (r.action === 'summarize_device_health') requireValue(devices.has(id), 'Dangling investigation device');
      else if (r.action === 'explain_observation') requireValue(id === alert.observation_id && observations.has(id), 'Inconsistent investigation observation');
      else {
        const ref = evidence.get(id); requireValue(ref, 'Dangling investigation evidence');
        if (r.action !== 'retrieve_evidence') requireValue(['dataset_report', 'validation_result'].includes(ref.kind), 'Wrong report evidence kind');
      }
    });
  });
  uniqueStrings(snapshot.investigation_results.map(r => r.request_id), 'Result requests');
  snapshot.investigation_results.forEach(r => {
    const request = requests.get(r.request_id); requireValue(request, 'Dangling investigation result');
    uniqueStrings(r.evidence_ids, 'Result evidence'); requireValue(r.evidence_ids.every(id => evidence.has(id)), 'Dangling result evidence');
    const expected = request.action === 'summarize_device_health' ? devices.get(request.reference_ids[0]!)!.sources.map(source => source.evidence_id) : request.action === 'explain_observation' ? [observations.get(request.reference_ids[0]!)!.evidence_id] : request.reference_ids;
    requireValue(r.result_id === `${request.request_id}:result` && JSON.stringify(r.evidence_ids) === JSON.stringify(expected), 'Inconsistent investigation result references');
  });
  snapshot.validation_results.forEach(o => { const ref = evidence.get(o.evidence_id); requireValue(ref && ['dataset_report', 'validation_result'].includes(ref.kind) && ref.dataset_id === o.dataset_id, 'Dangling validation outcome'); });
  const states = new Map<string, string>();
  const subjects = { observation: observations, sentinel: sentinels, alert: alerts };
  snapshot.review_history.forEach(r => {
    requireValue(subjects[r.subject_kind].has(r.subject_id), 'Dangling review subject');
    const key = `${r.subject_kind}/${r.subject_id}`;
    requireValue((states.get(key) ?? 'unreviewed') === r.previous_status, 'Contradictory review history');
    const permitted: Record<string, string[]> = { unreviewed: ['under_review', 'reviewed', 'dismissed'], under_review: ['reviewed', 'dismissed'], reviewed: [], dismissed: [] };
    requireValue(permitted[r.previous_status]?.includes(r.new_status), 'Invalid review transition'); states.set(key, r.new_status);
  });
  snapshot.observations.forEach(o => requireValue(o.review_status === (states.get(`observation/${o.observation_id}`) ?? 'unreviewed'), 'Observation review state differs'));
  snapshot.sentinels.forEach(s => requireValue(s.review_status === (states.get(`sentinel/${s.device_id}`) ?? 'unreviewed'), 'Sentinel review state differs'));
  snapshot.alerts.forEach(a => requireValue(a.status === (states.get(`alert/${a.alert_id}`) ?? 'unreviewed'), 'Alert review state differs'));
  snapshot.audit_entries.forEach(a => {
    if (a.event === 'human_review') { const r = decisions.get(a.reference_id); requireValue(r && r.reviewer_id === a.actor_id && sameTime(r.timestamp, a.timestamp), 'Inconsistent review audit'); }
    else { const r = results.get(a.reference_id); requireValue(r && a.event === (r.status === 'completed' ? 'investigation_completed' : 'investigation_not_evaluated'), 'Inconsistent investigation audit'); }
  });
}

export function validateSession(value: unknown): Session {
  check('@Session', value, 'session');
  // The schema walk above establishes the complete closed TypeScript shape.
  const session = value as Session;
  relationships(session.final_snapshot);
  const sum = session.summary;
  requireValue(sum.event_count === session.event_results.length && sum.applied_count === session.event_results.filter(r => r.status === 'applied').length && sum.rejected_count === sum.event_count - sum.applied_count, 'Invalid event counts');
  requireValue(sum.status === (sum.rejected_count ? 'completed_with_rejections' : 'completed'), 'Session status disagrees with counts');
  const deviceIds = new Set(session.final_snapshot.registry.devices.map(d => d.device_id));
  const sources = new Map(session.final_snapshot.registry.devices.flatMap(d => d.sources).map(s => [s.source_id, s]));
  const seen = new Set<string>();
  session.event_results.forEach((r, index) => {
    requireValue(r.event_index === index, 'Event ordering is invalid');
    requireValue(r.status === 'applied' ? r.diagnostics.length === 0 : r.diagnostics.length === 1, 'Invalid rejection diagnostics');
    r.diagnostics.forEach(d => requireValue(d.event_id === r.event_id && d.event_index === index && d.device_id === r.device_id && d.source_id === r.source_id, 'Dangling event diagnostic'));
    if (seen.has(r.event_id)) requireValue(r.status === 'rejected' && r.diagnostics[0]?.code === 'DUPLICATE_EVENT_ID', 'Duplicate event ID without rejection');
    else requireValue(!r.diagnostics.some(d => d.code === 'DUPLICATE_EVENT_ID'), 'Duplicate rejection without prior event');
    seen.add(r.event_id);
    if (r.status === 'applied') {
      requireValue(deviceIds.has(r.device_id), 'Dangling applied event device');
      if (['device_connectivity', 'device_health'].includes(r.event_type)) requireValue(r.source_id === null, 'Device update has unexpected source reference');
      if (['sensor_availability', 'evidence_announcement', 'observation_announcement'].includes(r.event_type)) requireValue(r.source_id !== null, 'Source event lacks a source reference');
      if (r.source_id !== null) { const source = sources.get(r.source_id); requireValue(source?.device_id === r.device_id && source.clock_domain === r.timestamp.clock_domain, 'Dangling applied event source or clock'); }
      else requireValue(session.final_snapshot.registry.devices.find(d => d.device_id === r.device_id)?.health.timestamp.clock_domain === r.timestamp.clock_domain, 'Applied device event clock mismatch');
    }
  });
  // Own the validated value; callers and React never share a mutable input tree.
  return JSON.parse(JSON.stringify(session)) as Session;
}

export function loadSession(text: string): Session {
  requireValue(new TextEncoder().encode(text).length <= 4 * 1024 * 1024, 'Fixture exceeds 4 MiB');
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new FixtureError('Fixture contains malformed JSON'); }
  // JSON.parse alone discards duplicate members. Inspect lexical tokens after
  // grammar parsing so ambiguous versions/fields cannot be silently overwritten.
  const stack: ({ keys: Set<string>; keyExpected: boolean } | null)[] = [];
  for (const match of text.matchAll(/"(?:[^"\\]|\\.)*"|[{}\[\],:]/g)) {
    const token = match[0]; const top = stack.at(-1);
    if (token === '{') stack.push({ keys: new Set(), keyExpected: true });
    else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop();
    else if (token === ',' && top) top.keyExpected = true;
    else if (token === ':' && top) top.keyExpected = false;
    else if (token.startsWith('"') && top?.keyExpected) {
      const key = JSON.parse(token) as string;
      requireValue(!top.keys.has(key), 'Fixture contains duplicate JSON keys'); top.keys.add(key); top.keyExpected = false;
    }
    requireValue(stack.length <= 32, 'Fixture nesting exceeds safe schema bounds');
  }
  return validateSession(value);
}
