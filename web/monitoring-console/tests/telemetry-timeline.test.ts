import { expect, it, vi } from 'vitest';
import { canonicalTelemetry, FIELD_NAMES, loadTelemetryReplay, replayTelemetry } from '../src/flight/telemetry';
import type { Replay, Stamp, TelemetrySnapshot } from '../src/flight/telemetry';
import { projectTelemetryTimeline as project } from '../src/flight/telemetryTimeline';
import px4 from '../examples/telemetry/px4.json?raw';
import conflict from '../examples/telemetry/conflict.json?raw';
import ardu from '../examples/telemetry/ardupilot.json?raw';

function replay(): Replay { return loadTelemetryReplay(px4); }
function snapshot(input = replay()): TelemetrySnapshot { return replayTelemetry(input); }
function at(value: string, clock_domain = 'replay:receipt'): Stamp { return { value, unit: 'ms', clock_domain }; }

it('represents zero frontier without accepted values or a selected record', () => {
  const s = snapshot(), result = project(s, 0, s.replay.evaluation_timestamp);
  expect(result.record_count).toBe(5); expect(result.frontier).toBe(0); expect(result.selected).toBeNull();
  expect(result.snapshot.summary).toEqual({ accepted_count: 0, rejected_count: 0, validation: 'valid' });
  for (const field of FIELD_NAMES) expect(result.snapshot.vehicles[0]!.fields[field].state).toBe('missing');
});

it('matches original snapshots at full frontier, including rejection diagnostics', () => {
  for (const text of [px4, ardu, conflict]) {
    const s = snapshot(loadTelemetryReplay(text));
    expect(canonicalTelemetry(project(s, s.replay.records.length, s.replay.evaluation_timestamp).snapshot)).toBe(canonicalTelemetry(s));
  }
});

it('matches direct replay at every prefix and multiple explicit evaluations', () => {
  const s = snapshot();
  for (const value of ['0', '899', '900', '1000', '1901']) for (let frontier = 0; frontier <= s.replay.records.length; frontier++) {
    const result = project(s, frontier, at(value));
    expect(result.snapshot).toEqual(replayTelemetry({ ...s.replay, records: s.replay.records.slice(0, frontier), evaluation_timestamp: at(value) }));
    expect(result.selected?.record_index ?? null).toBe(frontier ? frontier - 1 : null);
    expect(result.selected?.record.record_id ?? null).toBe(frontier ? s.replay.records[frontier - 1]!.record_id : null);
  }
});

it.each([-1, 6, 0.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER, '1', true, null, undefined])('rejects invalid frontier %s', frontier => {
  const s = snapshot(); expect(() => project(s, frontier as number, at('1000'))).toThrow(/frontier/);
});

it('supports empty records and empty source inventories while preserving the original clock', () => {
  const s = snapshot({ ...replay(), sources: [], records: [] });
  expect(project(s, 0, at('0')).selected).toBeNull();
  expect(() => project(s, 0, at('0', 'other'))).toThrow(/clock domain/);
});

it.each(['-1', '01', '1.5', '18446744073709551616', ''])('rejects invalid evaluation value %s', value => {
  expect(() => project(snapshot(), 0, at(value))).toThrow();
});

it('delegates evaluation shape and unit validation without aligning clocks', () => {
  const s = snapshot();
  for (const stamp of [{ ...at('1000'), unit: 'us' }, { ...at('1000'), value: 1000 }, { ...at('1000'), extra: 1 }, { value: '1000', clock_domain: 'replay:receipt' }, at('1000', 'other')]) {
    expect(() => project(s, 0, stamp as Stamp)).toThrow();
  }
});

it('preserves uint64 precision and exact freshness boundaries', () => {
  const base = replay(), max = '18446744073709551615';
  const s = snapshot({ ...base, evaluation_timestamp: at(max), records: base.records.map(r => ({ ...r, receipt_timestamp: at('18446744073709550615') })) });
  expect(project(s, 1, at(max)).snapshot.vehicles[0]!.fields.altitude.age_ms).toBe('1000');
  expect(project(s, 1, at(max)).snapshot.vehicles[0]!.fields.altitude.state).toBe('available');
  expect(project(snapshot(), 1, at('1901')).snapshot.vehicles[0]!.fields.altitude.state).toBe('stale');
  expect(project(snapshot(), 1, at('0')).selected?.diagnostic?.code).toBe('RECEIPT_AFTER_EVALUATION');
});

it('uses replay rejection diagnostics and retains original order and indices', () => {
  const base = replay(), bad = { ...base.records[0]!, record_id: 'bad', validation: 'invalid' as const, receipt_timestamp: at('950') };
  const regressed = { ...base.records[0]!, record_id: 'regressed', receipt_timestamp: at('899') };
  const s = snapshot({ ...base, records: [base.records[0]!, bad, regressed] });
  const rejected = project(s, 2, at('1000'));
  expect(rejected.selected).toMatchObject({ status: 'rejected', record_index: 1, record: bad, diagnostic: { record_index: 1, code: 'INVALID_RECORD' } });
  expect(rejected.snapshot.vehicles[0]!.fields.altitude.record_id).toBe(base.records[0]!.record_id);
  expect(project(s, 3, at('1000')).selected?.diagnostic?.code).toBe('TIMESTAMP_REGRESSION');
  expect(project(s, 1, at('1000')).selected).toMatchObject({ status: 'accepted', diagnostic: null });
});

it('distinguishes absent, supplied zero, and accepted explicit null clearing', () => {
  const base = replay(), clear = { ...base.records[0]!, record_id: 'clear', value: null, receipt_timestamp: at('950') };
  const s = snapshot({ ...base, records: [base.records[0]!, clear] });
  const first = project(s, 1, at('1000')).snapshot.vehicles[0]!;
  expect(first.fields.altitude.value).toHaveProperty('value', 0); expect(first.fields.battery.record_id).toBeNull();
  const result = project(s, 2, at('1000'));
  expect(result.selected?.status).toBe('accepted');
  expect(result.snapshot.vehicles[0]!.fields.altitude).toMatchObject({ state: 'missing', value: null, age_ms: null, record_id: 'clear', validation: 'valid' });
});

it('expires fields independently and never invents reception from other telemetry', () => {
  const base = replay();
  const s = snapshot({ ...base, records: [base.records[0]!, { ...base.records[1]!, receipt_timestamp: at('1900') }], evaluation_timestamp: at('2000') });
  const v = project(s, 2, at('2000')).snapshot.vehicles[0]!;
  expect(v.fields.altitude.state).toBe('stale'); expect(v.fields.ground_speed.state).toBe('available'); expect(v.reception_state).toBe('missing');
});

it('isolates source, session, system and component identities despite shared vehicle IDs', () => {
  const base = replay(), source = base.sources[0]!;
  const sources = [source, { ...source, source_id: 'other-source' }, { ...source, session_id: 'other-session' }, { ...source, system_id: 2 }, { ...source, component_id: 2 }];
  const records = sources.map((s, i) => ({ ...base.records[0]!, ...s, record_id: `identity-${i}`, value: { value: i, unit: 'm' as const, reference: 'home_relative' as const, reference_id: 'home' } }));
  // Source clock declarations belong to sources, not normalized records.
  const normalized = records.map(({ source_clock_domain: _sourceClock, receipt_clock_domain: _receiptClock, ...r }) => r);
  const s = snapshot({ ...base, sources, records: normalized });
  expect(project(s, 5, at('1000')).snapshot.vehicles.map(v => v.fields.altitude.value)).toEqual(records.map(r => r.value));
  expect(project(s, 1, at('1000')).snapshot.vehicles.slice(1).every(v => v.fields.altitude.state === 'missing')).toBe(true);
});

it('recomputes backward and repeated selections without clocks, randomness or network', () => {
  const s = snapshot(), first = project(s, 2, at('1000'));
  const spies = [vi.spyOn(Date, 'now'), vi.spyOn(Math, 'random'), vi.spyOn(globalThis, 'fetch')];
  try {
    for (const spy of spies) spy.mockImplementation(() => { throw new Error('forbidden'); });
    project(s, 5, at('2000')); project(s, 0, at('0'));
    expect(canonicalTelemetry(project(s, 2, at('1000')))).toBe(canonicalTelemetry(first));
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  } finally { for (const spy of spies) spy.mockRestore(); }
});

it('owns deeply frozen results without mutating or freezing caller inputs', () => {
  const input: TelemetrySnapshot = JSON.parse(canonicalTelemetry(snapshot())), stamp = { ...at('1000') };
  const before = canonicalTelemetry(input), result = project(input, 1, stamp);
  expect(canonicalTelemetry(input)).toBe(before); expect(Object.isFrozen(input)).toBe(false); expect(Object.isFrozen(stamp)).toBe(false);
  function frozen(value: unknown): void { if (value && typeof value === 'object') { expect(Object.isFrozen(value)).toBe(true); Object.values(value).forEach(frozen); } }
  frozen(result); expect(result.selected!.record).not.toBe(input.replay.records[0]);
  stamp.value = '2000'; expect(result.snapshot.replay.evaluation_timestamp.value).toBe('1000');
});

it('revalidates the entire original snapshot before projecting even zero records', () => {
  for (const mutate of [
    (s: TelemetrySnapshot) => ({ ...s, recorded_only: false }),
    (s: TelemetrySnapshot) => ({ ...s, summary: { ...s.summary, accepted_count: 99 } }),
    (s: TelemetrySnapshot) => ({ ...s, replay: { ...s.replay, records: [...s.replay.records, s.replay.records[0]] } }),
  ]) expect(() => project(mutate(snapshot()) as TelemetrySnapshot, 0, at('1000'))).toThrow();
});
