import { navigateTo } from './navigation';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync, mkdtempSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import App from '../src/App';
import { FlightOperations } from '../src/flight/FlightOperations';
import { OfflineTelemetry } from '../src/flight/OfflineTelemetry';
import { canonicalTelemetry, FIELD_NAMES, loadTelemetryReplay, loadTelemetrySnapshot, MAX_TELEMETRY_BYTES, replayTelemetry } from '../src/flight/telemetry';
import px4Text from '../examples/telemetry/px4.json?raw';
import arduText from '../examples/telemetry/ardupilot.json?raw';
import missingText from '../examples/telemetry/missing.json?raw';
import staleText from '../examples/telemetry/stale.json?raw';
import conflictText from '../examples/telemetry/conflict.json?raw';
import unsupportedText from '../examples/telemetry/unsupported.json?raw';
const data = () => JSON.parse(px4Text);
const snapshotText = () => canonicalTelemetry(replayTelemetry(loadTelemetryReplay(px4Text)));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function file(text: string | Uint8Array, name = 'snapshot.json') {
  const bytes = new Uint8Array(typeof text === 'string' ? new TextEncoder().encode(text) : text);
  const f = new File([bytes], name, { type: 'application/json' });
  const read = vi.fn(async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  Object.defineProperty(f, 'arrayBuffer', { configurable: true, value: read }); return { f, read };
}
function upload(f: File) { fireEvent.change(screen.getByLabelText('Import recorded SITL snapshot'), { target: { files: [f] } }); }

it('replays PX4 and ArduPilot fictional normalized inputs under strict v1 contracts', () => {
  for (const [text, family] of [[px4Text, 'PX4'], [arduText, 'ArduPilot']]) {
    const result = replayTelemetry(loadTelemetryReplay(text!));
    expect(result.vehicles[0]!.source.autopilot_family).toBe(family);
    expect(result.recorded_only).toBe(true); expect(result.summary.accepted_count).toBe(5);
    expect(result.replay.description).toContain('NOT CAPTURED MAVLINK OR GENUINE SIMULATOR OUTPUT');
    expect(result.vehicles[0]!.fields.altitude.provenance!.kind).toBe('fictional_normalized');
  }
});

it('produces byte-identical replay and owns deeply immutable comparison inputs', () => {
  const d = data(), before = JSON.stringify(d), a = replayTelemetry(d);
  expect(canonicalTelemetry(a)).toBe(canonicalTelemetry(replayTelemetry(d))); expect(JSON.stringify(d)).toBe(before);
  expect(Object.isFrozen(d)).toBe(false); expect(Object.isFrozen(a)).toBe(true); expect(Object.isFrozen(a.replay.records[0]!.value)).toBe(true);
  d.records[0].value.value = 500; expect(a.vehicles[0]!.fields.altitude.value).toHaveProperty('value', 0);
});

it('preserves supplied zeros and differentiates absent telemetry', () => {
  const result = replayTelemetry(loadTelemetryReplay(px4Text)).vehicles[0]!;
  expect(result.fields.altitude.value).toHaveProperty('value', 0); expect(result.fields.ground_speed.value).toHaveProperty('value', 0);
  expect(result.fields.battery.value).toHaveProperty('percentage', 0); expect(result.fields.flight_mode.value).toHaveProperty('custom_mode', '0');
  const empty = replayTelemetry(loadTelemetryReplay(missingText)).vehicles[0]!;
  expect(empty.reception_state).toBe('missing');
  for (const f of FIELD_NAMES) { expect(empty.fields[f].state).toBe('missing'); expect(empty.fields[f].value).toBeNull(); expect(empty.fields[f].validation).toBe('not_evaluated'); }
});

it('evaluates the exact freshness boundary with explicit policy and evaluation time', () => {
  const d = data(); d.evaluation_timestamp.value = '1900';
  expect(replayTelemetry(d).vehicles[0]!.fields.altitude.state).toBe('available');
  d.evaluation_timestamp.value = '1901'; const f = replayTelemetry(d).vehicles[0]!.fields.altitude;
  expect(f.state).toBe('stale'); expect(f.age_ms).toBe('1001'); expect(f.receipt_timestamp!.value).toBe('900');
});

it('ages fields independently rather than refreshing all telemetry from a later record', () => {
  const d = data(); d.evaluation_timestamp.value = '2000';
  const update = structuredClone(d.records[1]); update.record_id = 'new-speed'; update.receipt_timestamp.value = '1900'; d.records.push(update);
  const vehicle = replayTelemetry(d).vehicles[0]!;
  expect(vehicle.fields.ground_speed.state).toBe('available'); expect(vehicle.fields.altitude.state).toBe('stale');
});

it('rejects invalid records atomically without refreshing fields or reception freshness', () => {
  const d = data(); d.evaluation_timestamp.value = '2000'; d.policy.reception_timeout_ms = 1000;
  const bad = structuredClone(d.records[0]); bad.record_id = 'invalid'; bad.receipt_timestamp.value = '1900'; bad.validation = 'invalid'; bad.value.value = 100;
  d.records.push(bad); const result = replayTelemetry(d), v = result.vehicles[0]!;
  expect(result.diagnostics[0]!.code).toBe('INVALID_RECORD'); expect(v.fields.altitude.value).toHaveProperty('value', 0);
  expect(v.fields.altitude.receipt_timestamp!.value).toBe('900'); expect(v.fields.altitude.state).toBe('stale'); expect(v.reception_state).toBe('missing');
});

it('clears a field only for an explicitly supplied valid missing record', () => {
  const d = data(); const missing = structuredClone(d.records[0]); missing.record_id = 'missing'; missing.receipt_timestamp.value = '1000'; missing.value = null;
  d.records.push(missing); const f = replayTelemetry(d).vehicles[0]!.fields.altitude;
  expect(f.state).toBe('missing'); expect(f.value).toBeNull(); expect(f.age_ms).toBeNull(); expect(f.record_id).toBe('missing');
});

it('rejects unknown altitude references and out-of-range normalized values', () => {
  const d = data(); d.records[0].value.reference = 'unknown'; d.records[2].value.percentage = -1;
  const s = replayTelemetry(d); expect(s.diagnostics.map(x => x.code)).toEqual(['ALTITUDE_REFERENCE_UNAVAILABLE', 'VALUE_OUT_OF_RANGE']);
  expect(s.vehicles[0]!.fields.altitude.value).toBeNull(); expect(s.vehicles[0]!.fields.altitude.state).toBe('invalid'); expect(s.vehicles[0]!.fields.battery.value).toBeNull();
  const noFrame = data(); noFrame.records[0].value.reference_id = null; expect(replayTelemetry(noFrame).diagnostics[0]!.code).toBe('ALTITUDE_REFERENCE_UNAVAILABLE');
});

it('preserves uint64 timestamps exactly and subtracts them losslessly', () => {
  const d = data(); d.evaluation_timestamp.value = '18446744073709551615';
  for (const rec of d.records) { rec.receipt_timestamp.value = '18446744073709551605'; rec.source_timestamp.value = '18446744073709551615'; rec.source_timestamp.unit = 'ns'; }
  const s = replayTelemetry(d); expect(s.vehicles[0]!.fields.altitude.age_ms).toBe('10');
  expect(s.vehicles[0]!.fields.altitude.source_timestamp!.value).toBe('18446744073709551615');
  expect(loadTelemetrySnapshot(canonicalTelemetry(s))).toEqual(s);
});

it('does not align different clock domains or invent source timestamps', () => {
  const d = data(); d.records[0].source_timestamp = null;
  expect(replayTelemetry(d).vehicles[0]!.fields.altitude.source_timestamp).toBeNull();
  d.records[1].source_timestamp.clock_domain = 'another-clock'; expect(replayTelemetry(d).diagnostics[0]!.code).toBe('CLOCK_DOMAIN_MISMATCH');
  d.evaluation_timestamp.clock_domain = 'wrong-evaluation'; expect(() => replayTelemetry(d)).toThrow(/clocks must match/);
});

it('rejects per-session timestamp regressions and future receipts with stable ordering', () => {
  const d = data(); d.records[1].receipt_timestamp.value = '899'; d.records[2].source_timestamp.value = '49'; d.records[3].receipt_timestamp.value = '1001';
  expect(replayTelemetry(d).diagnostics.map(x => [x.record_index, x.code])).toEqual([[1, 'TIMESTAMP_REGRESSION'], [2, 'TIMESTAMP_REGRESSION'], [3, 'RECEIPT_AFTER_EVALUATION']]);
});

it('rejects identity conflicts instead of merging or overwriting a configured vehicle', () => {
  const s = replayTelemetry(loadTelemetryReplay(conflictText));
  expect(s.summary.rejected_count).toBe(1); expect(s.diagnostics[0]!.code).toBe('IDENTITY_CONFLICT');
  expect(s.vehicles[0]!.fields.altitude.value).toHaveProperty('value', 0);
  const d = data(); d.records[0].session_id = 'undeclared-session'; expect(replayTelemetry(d).diagnostics[0]!.code).toBe('UNKNOWN_SOURCE_SESSION');
});

it('separates repeated vehicle IDs across declared sessions and source identities', () => {
  const d = data(), second = structuredClone(d.sources[0]); second.session_id = 'session-b'; second.source_clock_domain = 'boot:b'; d.sources.push(second);
  const rec = structuredClone(d.records[0]); rec.record_id = 'other-session'; rec.session_id = 'session-b'; rec.source_timestamp.clock_domain = 'boot:b'; rec.value.value = 7; d.records.push(rec);
  const s = replayTelemetry(d); expect(s.vehicles).toHaveLength(2); expect(s.vehicles[0]!.identity_key).not.toBe(s.vehicles[1]!.identity_key);
  expect(s.vehicles[0]!.fields.altitude.value).toHaveProperty('value', 0); expect(s.vehicles[1]!.fields.altitude.value).toHaveProperty('value', 7); expect(s.vehicles[1]!.fields.battery.state).toBe('missing');
});

it('rejects unsupported fields and versions, missing required fields, incorrect types and duplicate IDs', () => {
  expect(() => loadTelemetryReplay(unsupportedText)).toThrow(/unknown fields/);
  for (const modify of [(d: ReturnType<typeof data>) => { d.schema_version = 2; }, (d: ReturnType<typeof data>) => { d.normalization_policy_version = 2; }, (d: ReturnType<typeof data>) => { d.sources[0].environment = 'REAL'; }, (d: ReturnType<typeof data>) => { delete d.records[0].provenance; }, (d: ReturnType<typeof data>) => { d.sources[0].system_id = true; }, (d: ReturnType<typeof data>) => { d.records[0].receipt_timestamp.value = 900; }, (d: ReturnType<typeof data>) => { d.records[0].value.unit = 'feet'; }, (d: ReturnType<typeof data>) => { d.records.push(d.records[0]); }, (d: ReturnType<typeof data>) => { d.sources.push(d.sources[0]); }]) {
    const d = data(); modify(d); expect(() => loadTelemetryReplay(JSON.stringify(d))).toThrow();
  }
});

it('rejects duplicate JSON keys including escaped duplicates and non-finite input', () => {
  expect(() => loadTelemetryReplay(px4Text.replace('"schema_version": 1', '"schema_version": 1, "\\u0073chema_version": 1'))).toThrow(/Duplicate/);
  expect(() => loadTelemetryReplay(px4Text.replace('"value": 0', '"value": 1e309'))).toThrow(/finite/);
  const d = data(); d.records[0].value.value = NaN; expect(() => replayTelemetry(d)).toThrow(/finite/);
  expect(() => canonicalTelemetry({ value: Infinity })).toThrow(/finite/);
});

it('bounds JSON, source/record counts, identifiers, policy intervals, depth and timestamps', () => {
  expect(() => loadTelemetryReplay(' '.repeat(MAX_TELEMETRY_BYTES + 1))).toThrow(/1 MiB/);
  const d = data(); d.records = Array.from({ length: 257 }, (_, i) => ({ ...d.records[0], record_id: `record-${i}` })); expect(() => replayTelemetry(d)).toThrow(/256/);
  const s = data(); s.sources = Array(9).fill(s.sources[0]); expect(() => replayTelemetry(s)).toThrow(/eight/);
  const long = data(); long.sources[0].vehicle_id = 'x'.repeat(129); expect(() => replayTelemetry(long)).toThrow(/bounded/);
  const policy = data(); policy.policy.fresh_for_ms.altitude = 0; expect(() => replayTelemetry(policy)).toThrow(/integer/);
  const stamp = data(); stamp.evaluation_timestamp.value = '18446744073709551616'; expect(() => replayTelemetry(stamp)).toThrow(/lossless/);
  expect(() => loadTelemetryReplay('['.repeat(25) + '0' + ']'.repeat(25))).toThrow(/nesting/);
});

it('recomputes snapshots and rejects forged stale states, extra fields, versions and non-finite outputs', () => {
  expect(loadTelemetrySnapshot(snapshotText()).recorded_only).toBe(true);
  for (const change of [(s: ReturnType<typeof data>) => { s.vehicles[0].fields.altitude.state = 'stale'; }, (s: ReturnType<typeof data>) => { s.vehicles[0].extra = true; }, (s: ReturnType<typeof data>) => { s.schema_version = 2; }, (s: ReturnType<typeof data>) => { s.recorded_only = false; }]) {
    const s = JSON.parse(snapshotText()); change(s); expect(() => loadTelemetrySnapshot(JSON.stringify(s))).toThrow();
  }
  expect(() => loadTelemetrySnapshot(snapshotText().replace('"value":null', '"value":1e309'))).toThrow(/finite/);
});

it('keeps pure replay independent of wall clocks, randomness and network APIs', () => {
  const d = data(); const now = vi.spyOn(Date, 'now').mockImplementation(() => { throw new Error('clock forbidden'); });
  const random = vi.spyOn(Math, 'random').mockImplementation(() => { throw new Error('random forbidden'); });
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  expect(replayTelemetry(d).summary.accepted_count).toBe(5); expect(now).not.toHaveBeenCalled(); expect(random).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

it('imports only explicit snapshots, keeps demo the default and preserves demo selection', async () => {
  render(<FlightOperations />); expect(screen.getByLabelText('Flight data source')).toHaveValue('demo'); expect(screen.queryByLabelText('Import recorded SITL snapshot')).toBeNull();
  fireEvent.change(screen.getByLabelText('Selected flight vehicle'), { target: { value: 'demo-synthetic-slot' } });
  fireEvent.change(screen.getByLabelText('Flight data source'), { target: { value: 'recorded' } });
  expect(screen.queryByLabelText('Selected flight vehicle')).toBeNull(); expect(screen.queryByLabelText('Recorded source/session')).toBeNull();
  const input = file(snapshotText()); expect(input.read).not.toHaveBeenCalled(); upload(input.f);
  expect(await screen.findByLabelText('Recorded source/session')).toBeVisible(); expect(input.read).toHaveBeenCalledOnce();
  expect(screen.getByRole('region', { name: 'Recorded SITL vehicle details' })).toHaveTextContent('fictional-px4');
  fireEvent.change(screen.getByLabelText('Flight data source'), { target: { value: 'demo' } });
  expect(screen.getByLabelText('Selected flight vehicle')).toHaveValue('demo-synthetic-slot'); expect(screen.queryByLabelText('Recorded source/session')).toBeNull();
});

it('shows recorded evaluation, stale last-known data and no live indicators or camera media', async () => {
  const { container } = render(<OfflineTelemetry />); const s = replayTelemetry(loadTelemetryReplay(staleText)); upload(file(canonicalTelemetry(s)).f);
  expect(await screen.findByLabelText('Recorded source/session')).toBeVisible();
  expect(screen.getAllByText('Stale · Last reported')).toHaveLength(5);
  expect(screen.getByText('RECORDED SNAPSHOT — NEVER LIVE · SEPARATE FROM DEMO FLEET')).toBeVisible();
  expect(screen.getByText('NO VERIFIED CAMERA FEED')).toBeVisible(); expect(container.querySelector('video,audio,iframe,[src],form')).toBeNull();
});

it('does not read oversized imports and rejects malformed JSON, UTF-8, replay inputs and tampered snapshots', async () => {
  render(<OfflineTelemetry />); const large = file(' '.repeat(MAX_TELEMETRY_BYTES + 1)); upload(large.f);
  expect(await screen.findByRole('alert')).toHaveTextContent('1 MiB'); expect(large.read).not.toHaveBeenCalled();
  for (const text of ['{', new Uint8Array([255]), px4Text, snapshotText().replace('"recorded_only":true', '"recorded_only":false')]) {
    upload(file(text).f); expect(await screen.findByRole('alert')).toBeVisible(); expect(screen.queryByLabelText('Recorded source/session')).toBeNull();
  }
});

it('clears recorded data explicitly and escapes imported provenance text', async () => {
  const d = data(); d.records[0].provenance.note = '<script>alert(1)</script>';
  const { container } = render(<OfflineTelemetry />); upload(file(canonicalTelemetry(replayTelemetry(d))).f); await screen.findByLabelText('Recorded source/session');
  fireEvent.click(screen.getByText('altitude evidence details')); expect(screen.getByText(/fictional_normalized.*<script>/)).toBeVisible(); expect(container.querySelector('script')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Clear recorded snapshot' })); expect(screen.queryByLabelText('Recorded source/session')).toBeNull();
});

it('maintains monitoring metrics, analyst navigation and simulation playback after offline inspection', () => {
  render(<App />); navigateTo('Flight Operations');
  fireEvent.change(screen.getByLabelText('Flight data source'), { target: { value: 'recorded' } });
  navigateTo('Sensor Fusion'); expect(screen.getByRole('heading', { name: 'AEGIS AI Analyst' })).toBeVisible();
  navigateTo('Overview'); expect(screen.getByRole('article', { name: 'Devices' }).querySelector('strong')).toHaveTextContent('03');
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' })); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
});

it('offers keyboard-accessible explicit import and source/session selection', async () => {
  render(<OfflineTelemetry />); const input = screen.getByLabelText('Import recorded SITL snapshot'); input.focus(); expect(input).toHaveFocus();
  upload(file(snapshotText()).f); const select = await screen.findByLabelText('Recorded source/session'); select.focus(); expect(select).toHaveFocus();
  const details = screen.getByRole('region', { name: 'Recorded SITL vehicle details' }); expect(within(details).getByRole('heading', { name: 'fictional-px4 · PX4 · SITL' })).toBeVisible();
});

it('runs the bounded offline CLI reproducibly with empty stdout for invalid input', () => {
  const run = (name: string) => spawnSync(process.execPath, ['scripts/replay_telemetry.mjs', `examples/telemetry/${name}.json`], { encoding: 'utf-8', timeout: 20000 });
  const a = run('px4'), b = run('px4'); expect(a.status).toBe(0); expect(a.stderr).toBe(''); expect(a.stdout).toBe(b.stdout); expect(a.stdout).toBe(snapshotText() + '\n');
  expect(run('ardupilot').status).toBe(0); const conflict = run('conflict'); expect(conflict.status).toBe(0); expect(loadTelemetrySnapshot(conflict.stdout).summary.rejected_count).toBe(1);
  const invalid = run('unsupported'); expect(invalid.status).toBe(2); expect(invalid.stdout).toBe(''); expect(invalid.stderr).toContain('Invalid offline telemetry replay');
});

it('keeps CSP and fixture-generation boundaries intact and adds no network or command APIs', () => {
  expect(readFileSync('index.html', 'utf8')).toContain("connect-src 'none'");
  for (const p of ['src/flight/telemetry.ts', 'src/flight/OfflineTelemetry.tsx', 'scripts/replay_telemetry.mjs']) {
    const text = readFileSync(p, 'utf8'); expect(text).not.toMatch(/fetch\(|WebSocket|XMLHttpRequest|dgram|createServer|mavsdk|pymavlink|child_process/);
  }
});

it('cancels pending import results when cleared without resurrecting recorded data', async () => {
  let resolve!: (value: ArrayBuffer) => void;
  const bytes = new TextEncoder().encode(snapshotText()); const f = file(snapshotText()).f;
  Object.defineProperty(f, 'arrayBuffer', { configurable: true, value: () => new Promise<ArrayBuffer>(done => { resolve = done; }) });
  render(<OfflineTelemetry />); upload(f); expect(screen.getByRole('status')).toHaveTextContent('Validating');
  fireEvent.click(screen.getByRole('button', { name: 'Clear recorded snapshot' }));
  await act(async () => { resolve(bytes.buffer); });
  expect(screen.queryByLabelText('Recorded source/session')).toBeNull(); expect(screen.queryByRole('status')).toBeNull();
});

it('preserves component isolation within the same source and session', () => {
  const d = data(), second = structuredClone(d.sources[0]); second.component_id = 2; d.sources.push(second);
  const rec = structuredClone(d.records[0]); rec.record_id = 'component-2'; rec.component_id = 2; rec.value.value = 3; d.records.push(rec);
  const s = replayTelemetry(d); expect(s.vehicles).toHaveLength(2);
  expect(s.vehicles[0]!.fields.altitude.value).toHaveProperty('value', 0); expect(s.vehicles[1]!.fields.altitude.value).toHaveProperty('value', 3);
});

it('retains declared reception and raw mode values without claiming a decoded mode or healthy link', () => {
  const d = data(), rec = structuredClone(d.records[4]); rec.record_id = 'closed'; rec.field = 'reception'; rec.value = { status: 'closed', note: 'Explicit fictional declaration' }; d.records.push(rec);
  const s = replayTelemetry(d); expect(s.vehicles[0]!.reception_state).toBe('closed');
  expect(s.vehicles[0]!.fields.flight_mode.value).toEqual({ base_mode: 0, custom_mode: '0' });
  expect(s.vehicles[0]!.fields.link_status.value).toHaveProperty('status', 'unknown');
});

it('marks a clock-invalid initial field as invalid rather than current or measured', () => {
  const d = data(); d.records[0].receipt_timestamp.clock_domain = 'wrong-clock';
  const s = replayTelemetry(d), f = s.vehicles[0]!.fields.altitude;
  expect(s.diagnostics[0]!.code).toBe('CLOCK_DOMAIN_MISMATCH'); expect(f.state).toBe('invalid'); expect(f.validation).toBe('invalid');
  expect(f.value).toBeNull(); expect(f.receipt_timestamp).toBeNull(); expect(f.age_ms).toBeNull();
});

it('distinguishes component identities in recorded selector labels and inspection', async () => {
  const d = data(), second = structuredClone(d.sources[0]); second.component_id = 2; d.sources.push(second);
  const rec = structuredClone(d.records[0]); rec.record_id = 'second-component'; rec.component_id = 2; d.records.push(rec);
  const snapshot = replayTelemetry(d); render(<OfflineTelemetry />); upload(file(canonicalTelemetry(snapshot)).f);
  const select = await screen.findByLabelText('Recorded source/session'); const options = within(select).getAllByRole('option');
  expect(options[0]).toHaveTextContent('1/1'); expect(options[1]).toHaveTextContent('1/2'); expect(options[0]!.textContent).not.toBe(options[1]!.textContent);
  fireEvent.change(select, { target: { value: snapshot.vehicles[1]!.identity_key } });
  expect(screen.getByRole('region', { name: 'Recorded SITL vehicle details' })).toHaveTextContent('1/2');
});


it.each(['closed', 'open', 'receiving'])('uses only fresh %s reception declarations and retains stale history', status => {
  const d = data(), rec = structuredClone(d.records[4]);
  rec.record_id = 'reception-declaration'; rec.field = 'reception'; rec.value = { status, note: 'Explicit fictional declaration' }; d.records.push(rec);
  expect(replayTelemetry(d).vehicles[0]!.reception_state).toBe(status === 'receiving' ? 'records_received' : status);
  d.evaluation_timestamp.value = '5000';
  const later = structuredClone(d.records[1]); later.record_id = 'later-speed'; later.receipt_timestamp.value = '4900'; d.records.push(later);
  const v = replayTelemetry(d).vehicles[0]!;
  expect(v.reception_state).toBe('stale'); expect(v.fields.reception.state).toBe('stale');
  expect(v.fields.reception.value).toHaveProperty('status', status);
  expect(v.fields.reception.receipt_timestamp!.value).toBe('900');
  expect(v.fields.ground_speed.state).toBe('available'); expect(v.last_receipt_timestamp!.value).toBe('4900');
});

it('distinguishes missing and unsupported reception without inferring from unrelated telemetry', () => {
  const d = data(); expect(replayTelemetry(d).vehicles[0]!.reception_state).toBe('missing');
  const rec = structuredClone(d.records[4]); rec.record_id = 'unsupported-reception'; rec.field = 'reception'; rec.value = { status: 'unrecognized', note: 'Unsupported declaration' }; d.records.push(rec);
  const s = replayTelemetry(d); expect(s.vehicles[0]!.reception_state).toBe('unsupported');
  expect(s.diagnostics[0]!.code).toBe('UNSUPPORTED_RECEPTION_DECLARATION');
  expect(s.vehicles[0]!.fields.reception.value).toBeNull(); expect(s.summary.rejected_count).toBe(1);
  rec.record_id = 'recovered-reception'; rec.value.status = 'open'; d.records.push(structuredClone(rec)); d.records[d.records.length - 2].record_id = 'unsupported-original'; d.records[d.records.length - 2].value.status = 'unrecognized';
  expect(replayTelemetry(d).vehicles[0]!.reception_state).toBe('open');
});

it('labels expired reception explicitly in the inspector with its last reported value', async () => {
  const d = data(), rec = structuredClone(d.records[4]); rec.record_id = 'old-closed'; rec.field = 'reception'; rec.value = { status: 'closed', note: 'Historical declaration' }; d.records.push(rec); d.evaluation_timestamp.value = '5000';
  render(<OfflineTelemetry />); upload(file(canonicalTelemetry(replayTelemetry(d))).f);
  expect(await screen.findByText(/Recorded reception: STALE — LAST REPORTED DECLARATION.*Last reported: closed/)).toBeVisible();
});


it.each(['missing', 'oversized', 'invalid-utf8', 'malformed-json'])('rejects %s CLI input without partial stdout', kind => {
  const dir = mkdtempSync(join(tmpdir(), 'aegis-telemetry-safety-'));
  try {
    const path = join(dir, 'input.json');
    if (kind !== 'missing') writeFileSync(path, kind === 'oversized' ? ' '.repeat(MAX_TELEMETRY_BYTES + 1) : kind === 'invalid-utf8' ? new Uint8Array([0xff, 0xfe]) : '{');
    const result = spawnSync(process.execPath, ['scripts/replay_telemetry.mjs', path], { encoding: 'utf-8', timeout: 20000 });
    expect(result.error).toBeUndefined(); expect(result.status).toBe(2); expect(result.stdout).toBe('');
    expect(result.stderr).toBe('Invalid offline telemetry replay or local input.\n');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

it('rejects symlink CLI input where symlink creation is supported', context => {
  const dir = mkdtempSync(join(tmpdir(), 'aegis-telemetry-symlink-'));
  try {
    const target = join(dir, 'target.json'), link = join(dir, 'link.json'); writeFileSync(target, px4Text);
    try { symlinkSync(target, link); } catch (error) {
      if (['EPERM', 'EACCES', 'ENOSYS', 'ENOTSUP'].includes((error as NodeJS.ErrnoException).code ?? '')) { context.skip(); return; }
      throw error;
    }
    const result = spawnSync(process.execPath, ['scripts/replay_telemetry.mjs', link], { encoding: 'utf-8', timeout: 20000 });
    expect(result.error).toBeUndefined(); expect(result.status).toBe(2); expect(result.stdout).toBe('');
    expect(result.stderr).toBe('Invalid offline telemetry replay or local input.\n'); expect(readFileSync(target, 'utf8')).toBe(px4Text);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

it('handles an injected open permission denial independent of OS permissions and user identity', () => {
  const script = `import fs from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
fs.open = async () => { throw Object.assign(new Error('Injected permission denial'), { code: 'EACCES' }); };
syncBuiltinESMExports();
process.argv = [process.execPath, 'scripts/replay_telemetry.mjs', ${JSON.stringify(resolve('examples/telemetry/px4.json'))}];
await import(${JSON.stringify(pathToFileURL(resolve('scripts/replay_telemetry.mjs')).href)});`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf-8', timeout: 20000 });
  expect(result.error).toBeUndefined(); expect(result.status).toBe(2); expect(result.stdout).toBe('');
  expect(result.stderr).toBe('Invalid offline telemetry replay or local input.\n');
});
