import { expect, it } from 'vitest';
import { loadMonitoringReplay, projectMonitoringReplay } from '../src/fusion/replay';
import { loadSession } from '../src/validate';
import sessionText from '../src/data/session.json?raw';
import replayText from '../src/data/fusion-replay.json?raw';
const session = () => loadSession(sessionText);
const replay = () => loadMonitoringReplay(replayText, session());

it('selects every original ordered prefix with exact timestamps, counts and final equivalence', () => {
  const r = replay(), original = session();
  for (let frontier = 0; frontier <= original.event_results.length; frontier++) {
    const p = projectMonitoringReplay(r, frontier);
    expect(r.prefixes[frontier]!.event_results).toEqual(original.event_results.slice(0, frontier));
    expect(p.event).toEqual(original.event_results[frontier - 1] ?? null);
    expect(p.summary.event_count).toBe(frontier);
  }
  expect(projectMonitoringReplay(r, 0).event).toBeNull();
  expect(projectMonitoringReplay(r, 7).snapshot).toEqual(original.final_snapshot);
  expect(new Set(original.event_results.map(e => e.timestamp.clock_domain)).size).toBeGreaterThan(1);
});
it.each([-1, 8, 1.5, NaN, Infinity])('rejects invalid frontier %s', frontier => {
  expect(() => projectMonitoringReplay(replay(), frontier)).toThrow(RangeError);
});
it('does not attribute rejected state updates or activity', () => {
  const r = replay(), rejected = projectMonitoringReplay(r, 7);
  expect(rejected.event?.diagnostics[0]?.code).toBe('CONFLICTING_UPDATE');
  expect(rejected.snapshot).toEqual(projectMonitoringReplay(r, 6).snapshot);
  expect(rejected.activity).toEqual([]); expect(rejected.evidence).toEqual([]); expect(rejected.observations).toEqual([]);
});
it('highlights only explicit accepted sources and exact added or changed references', () => {
  const r = replay();
  expect(projectMonitoringReplay(r, 1).source).toBeNull();
  expect(projectMonitoringReplay(r, 1).activity).toEqual(['device/native-aerial']);
  const evidence = projectMonitoringReplay(r, 4);
  expect(evidence.source?.source_id).toBe('camera-a');
  expect(evidence.evidence.map(e => e.evidence_id)).toEqual(['camera-a:recorded']);
  expect(evidence.evidence[0]?.dataset_id).toBeNull();
  const observation = projectMonitoringReplay(r, 5);
  expect(observation.observations[0]?.observation_id).toBe('monitor-unusual');
  expect(observation.observations[0]?.uncertainty_note).toBe('Illustrative missing context.');
  expect(observation.observations[0]?.evidence_id).toBe('display-r:evidence');
  expect(projectMonitoringReplay(r, 6).observations[0]?.review_status).toBe('reviewed');
});
it('supports repeated and backward selection without mutating or exposing mutable inputs', () => {
  const input = session(), before = JSON.stringify(input), r = loadMonitoringReplay(replayText, input), bytes = JSON.stringify(r);
  const expected = projectMonitoringReplay(r, 3);
  for (const frontier of [7, 1, 0, 3, 3, 5, 2]) projectMonitoringReplay(r, frontier);
  expect(projectMonitoringReplay(r, 3)).toEqual(expected); expect(JSON.stringify(r)).toBe(bytes); expect(JSON.stringify(input)).toBe(before);
  expect(Object.isFrozen(expected.snapshot.registry.devices[0])).toBe(true);
  expect(() => { expected.snapshot.registry.devices.pop(); }).toThrow();
});
it.each(['order', 'timestamp', 'missing', 'version', 'rejected state', 'final state'])('fails closed for %s corruption', change => {
  const doc = JSON.parse(replayText);
  if (change === 'order') doc.prefixes[2].event_results.reverse();
  if (change === 'timestamp') doc.prefixes[1].event_results[0].timestamp.value = 99;
  if (change === 'missing') doc.prefixes.pop();
  if (change === 'version') doc.schema_version = 2;
  if (change === 'rejected state') doc.prefixes[7].final_snapshot.description = 'Changed rejected state';
  if (change === 'final state') doc.prefixes[7].summary.applied_count = 0;
  expect(() => loadMonitoringReplay(JSON.stringify(doc), session())).toThrow();
});
it('refuses unrelated sessions instead of borrowing their history', () => {
  const other = session(); other.initial_snapshot_id = 'another-fixture';
  expect(() => loadMonitoringReplay(replayText, other)).toThrow();
});

it('supports an empty session without manufacturing an event or activity', () => {
  const empty = JSON.parse(replayText).prefixes[0];
  const r = loadMonitoringReplay(JSON.stringify({ schema_version: 1, prefixes: [empty] }), empty);
  const p = projectMonitoringReplay(r, 0);
  expect(p.event).toBeNull(); expect(p.activity).toEqual([]); expect(p.summary.event_count).toBe(0);
});
it('retains the exact supplied review actor, transition, timestamp and audit provenance', () => {
  const p = projectMonitoringReplay(replay(), 6);
  expect(p.reviews[0]?.reviewer_id).toBe('synthetic-operator');
  expect(p.reviews[0]?.previous_status).toBe('unreviewed'); expect(p.reviews[0]?.new_status).toBe('reviewed');
  expect(p.reviews[0]?.timestamp).toEqual(p.event?.timestamp);
  expect(p.audits[0]?.reference_id).toBe(p.reviews[0]?.decision_id);
});
it('preserves unresolved rejected references without fabricating source or device objects', () => {
  const doc = JSON.parse(replayText);
  const last = doc.prefixes.at(-1);
  const event = last.event_results.at(-1);
  event.device_id = 'unknown-device'; event.source_id = 'unknown-source';
  Object.assign(event.diagnostics[0], { device_id: event.device_id, source_id: event.source_id, code: 'UNKNOWN_DEVICE', explanation: 'Event device is not present in the supplied registry.' });
  const p = projectMonitoringReplay(loadMonitoringReplay(JSON.stringify(doc), last), 7);
  expect(p.event?.device_id).toBe('unknown-device'); expect(p.device).toBeNull(); expect(p.source).toBeNull(); expect(p.activity).toEqual([]);
});
