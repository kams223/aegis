import type { Session, Snapshot } from '../models';
import { loadSession } from '../validate';

export interface MonitoringReplay { readonly prefixes: readonly Session[] }

// Structural equality does not depend on JSON member ordering; never order event arrays.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(',')}}`;
  return JSON.stringify(value) ?? 'null';
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

// This selects recorded outputs of the existing Python reducer. It does not
// reconstruct state from result metadata or implement another monitoring reducer.
export function loadMonitoringReplay(text: string, session: Session): MonitoringReplay {
  if (new TextEncoder().encode(text).length > 16 * 1024 * 1024) throw new Error('Monitoring replay exceeds 16 MiB');
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid monitoring replay');
  const doc = value as Record<string, unknown>;
  if (Object.keys(doc).length !== 2 || doc.schema_version !== 1 || !Array.isArray(doc.prefixes) || doc.prefixes.length !== session.event_results.length + 1 || doc.prefixes.length > 257) throw new Error('Invalid monitoring replay prefixes');
  const prefixes = doc.prefixes.map(frame => loadSession(JSON.stringify(frame)));
  prefixes.forEach((prefix, frontier) => {
    if (prefix.initial_snapshot_id !== session.initial_snapshot_id || prefix.final_snapshot.snapshot_id !== session.initial_snapshot_id || canonical(prefix.event_results) !== canonical(session.event_results.slice(0, frontier))) throw new Error('Monitoring replay order or identity differs');
    if (frontier && prefix.event_results.at(-1)?.status === 'rejected' && canonical(prefix.final_snapshot) !== canonical(prefixes[frontier - 1]!.final_snapshot)) throw new Error('Rejected event changed recorded state');
  });
  if (canonical(prefixes.at(-1)) !== canonical(session)) throw new Error('Monitoring replay does not match the supplied final session');
  return freeze({ prefixes });
}

export function projectMonitoringReplay(replay: MonitoringReplay, frontier: number) {
  if (!Number.isInteger(frontier) || frontier < 0 || frontier >= replay.prefixes.length) throw new RangeError('Invalid monitoring event frontier');
  const prefix = replay.prefixes[frontier]!;
  const snapshot = prefix.final_snapshot;
  const event = prefix.event_results.at(-1) ?? null;
  const previous: Snapshot = replay.prefixes[Math.max(0, frontier - 1)]!.final_snapshot;
  const device = event ? snapshot.registry.devices.find(d => d.device_id === event.device_id) ?? null : null;
  const source = event?.source_id ? device?.sources.find(s => s.source_id === event.source_id) ?? null : null;
  const applied = event?.status === 'applied';
  const evidence = applied ? snapshot.evidence.filter(e => !previous.evidence.some(old => old.evidence_id === e.evidence_id)) : [];
  const observations = applied ? snapshot.observations.filter(o => { const old = previous.observations.find(item => item.observation_id === o.observation_id); return !old || canonical(old) !== canonical(o); }) : [];
  const reviews = applied ? snapshot.review_history.filter(r => !previous.review_history.some(old => old.decision_id === r.decision_id)) : [];
  const audits = applied ? snapshot.audit_entries.filter(a => !previous.audit_entries.some(old => old.audit_id === a.audit_id)) : [];
  const activity = applied ? [ ...(device ? [`device/${device.device_id}`] : []), ...(source ? [`source/${source.source_id}`] : []), ...evidence.map(e => `evidence/${e.evidence_id}`), ...observations.map(o => `observation/${o.observation_id}`) ] : [];
  return freeze({ frontier, snapshot, event, device, source, evidence, observations, reviews, audits, activity, summary: prefix.summary });
}
