import { it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import example from '../../../examples/sensor_telemetry_example.json?raw';
import { SensorDashboard } from '../src/sensor/SensorDashboard';
import { chartData, filterRecords, freshness, loadInspection, matchOriginal, MAX_BYTES, sha256 } from '../src/sensor/model';
import type { Inspection, RecordRow } from '../src/sensor/model';
import { parseJson } from '../src/sensor/schema';
Object.defineProperty(globalThis, 'crypto', {value: webcrypto, configurable: true});
const fixture = (): Inspection => JSON.parse(example) as Inspection;
async function impaired(missing = false) {
  const d = fixture(), r = d.observations[0]!.record;
  r.origin = 'impaired'; r.config_json = '{"policies":[],"reference_ns":0,"rules":[],"schema_version":1,"seed":0,"stale_after_ns":100000000}';
  r.config_sha256 = await sha256(r.config_json + '\n'); r.seed_identifier = '0';
  d.summary.barometer.origins = {raw: 0, impaired: 1};
  if (missing) {r.values = null; d.observations[0]!.freshness = 'missing'; Object.assign(d.summary.barometer, {missing: 1, latest_acquisition_ns: null, freshness: 'missing', units: {}});}
  return d;
}
function upload(d: unknown, label = 'Load Phase 75D inspection JSON') {
  const f = new File([JSON.stringify(d)], 'local.json'); Object.defineProperty(f, 'arrayBuffer', {value: async () => new TextEncoder().encode(JSON.stringify(d)).buffer});
  fireEvent.change(screen.getByLabelText(label), {target: {files: [f]}});
}
it('accepts raw and impaired; freezes source; matches provenance', async () => {
  const raw = await loadInspection(example), before = JSON.stringify(raw), imp = await loadInspection(JSON.stringify(await impaired()));
  expect(imp.observations[0]!.record.origin).toBe('impaired');
  expect(Object.isFrozen(raw.observations[0]!.record.values)).toBe(true);
  expect(() => {raw.observations[0]!.record.frame = 'changed';}).toThrow(); expect(JSON.stringify(raw)).toBe(before);
  expect(matchOriginal(imp.observations[0]!.record, filterRecords(raw, 'all'))).toEqual(raw.observations[0]!.record);
  expect(matchOriginal(imp.observations[0]!.record, [{...raw.observations[0]!.record, source_sha256: 'b'.repeat(64)}])).toBeNull();
});
it('uses selected time and exact threshold; distinguishes future, pending, missing and domain mismatch', async () => {
  const r = (await loadInspection(example)).observations[0]!.record, t = {...r.acquisition, value_ns: '100000000'};
  expect(freshness(r, t, '100000000')).toBe('fresh'); expect(freshness(r, {...t, value_ns: '100000001'}, '100000000')).toBe('stale');
  expect(freshness({...r, acquisition: {...t, value_ns: '200000000'}}, t, '0')).toBe('future');
  expect(freshness({...r, delivery: {...t, value_ns: '200000000'}}, t, '0')).toBe('pending');
  expect(freshness({...r, values: null}, t, '0')).toBe('missing');
  expect(() => freshness(r, {...t, domain: 'other'}, '0')).toThrow('CLOCK_DOMAIN');
});
it('rejects malformed, duplicate-key, nonfinite, deep, oversized and unknown-version input', async () => {
  for (const s of ['{', '{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"x":1e999}', '['.repeat(34) + '0' + ']'.repeat(34)]) expect(() => parseJson(s)).toThrow();
  await expect(loadInspection(' '.repeat(MAX_BYTES + 1))).rejects.toThrow('8 MiB');
  await expect(loadInspection('{"schema_version":2}')).rejects.toThrow();
  const d = fixture(); d.observations = Array(1025).fill(d.observations[0]); await expect(loadInspection(JSON.stringify(d))).rejects.toThrow();
});
it('rejects invalid units/frames, timestamp ordering, clocks, uint64 overflow, duplicate observations and summary lies', async () => {
  const mutations = [
    (d: Inspection) => {d.observations[0]!.record.values![0]!.unit = 'psi';},
    (d: Inspection) => {d.observations[0]!.record.frame = 'world';},
    (d: Inspection) => {d.observations[0]!.record.acquisition.value_ns = '10';},
    (d: Inspection) => {d.observations[0]!.record.acquisition.domain = 'other';},
    (d: Inspection) => {d.observations[0]!.record.acquisition.value_ns = '18446744073709551616';},
    (d: Inspection) => {d.summary.barometer.count = 9;},
    (d: Inspection) => {d.observations.push(d.observations[0]!);},
  ];
  for (const mutate of mutations) {const d = fixture(); mutate(d); await expect(loadInspection(JSON.stringify(d))).rejects.toThrow();}
  const d = await impaired(); d.observations[0]!.record.config_sha256 = 'b'.repeat(64); await expect(loadInspection(JSON.stringify(d))).rejects.toThrow('PROVENANCE');
  const unsupported = await impaired();
  const cfg = JSON.parse(unsupported.observations[0]!.record.config_json!);
  cfg.rules = [{schema_version: 1, sensor: 'barometer', field: 'derived_altitude', unit: 'm', noise_std: 0, bias: 0, drift_per_second: 0}];
  unsupported.observations[0]!.record.config_json = JSON.stringify(cfg);
  unsupported.observations[0]!.record.config_sha256 = await sha256(JSON.stringify(cfg) + '\n');
  await expect(loadInspection(JSON.stringify(unsupported))).rejects.toThrow('UNITS');
});
it('filters sensors, sorts uint64 times and deterministically downsamples with gaps', () => {
  const d = fixture(), r = d.observations[0]!.record;
  expect(filterRecords(d, 'gnss')).toEqual([]);
  const rows: RecordRow[] = Array.from({length: 1024}, (_,i) => ({...r, acquisition: {...r.acquisition, value_ns: String(18446744073709550000n + BigInt(i))}, values: i === 1 ? null : r.values}));
  const p = chartData(rows, 'pressure'); expect(p.length).toBe(256); expect(p[0]!.value).toBe(r.values![0]!.value); expect(p).toEqual(chartData(rows, 'pressure')); expect(p.at(-1)!.time).toBe(rows.at(-1)!.acquisition.value_ns);
  d.observations = rows.slice(0,2).reverse().map(record => ({record, freshness: 'future'})); expect(filterRecords(d, 'all')[0]!.acquisition.value_ns).toBe(rows[0]!.acquisition.value_ns);
});
it('requires explicit loading, then supports evaluation controls and sensor filtering', async () => {
  render(<SensorDashboard />); expect(screen.queryByText('Dataset provenance')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Load synthetic example')); await screen.findByText(/SYNTHETIC EXAMPLE — no evidence/); expect(screen.getByText('STALE')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Evaluation time (ns)'), {target: {value: '0'}}); expect(screen.getByText('FRESH')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Evaluation clock domain'), {target: {value: 'other'}}); expect(screen.getByRole('alert')).toHaveTextContent('CLOCK_DOMAIN');
  fireEvent.change(screen.getByLabelText('Sensor filter'), {target: {value: 'gnss'}}); expect(screen.getByText(/No observations for this sensor/)).toBeInTheDocument();
});
it('renders dropouts, rejected diagnostics, ordering and untrusted metadata safely', async () => {
  const d = await impaired(true); d.rejected = [{index: 1, sensor: 'barometer', diagnostic: {code: 'UNITS', path: 'values', explanation: '<img src=x onerror=alert(1)>'}}]; d.summary.barometer.rejected = 1;
  d.anomalies = [{index: 2, code: 'DELIVERY_REGRESSION'}]; d.source_diagnostics = [{index: 0, sensor: 'barometer', acquisition_ns: '0', reasons: ['MISSING_OBSERVATION', 'STALE']}];
  const {container} = render(<SensorDashboard />); upload(d); await screen.findByText('MISSING');
  expect(screen.getAllByText(/MISSING \/ dropout/).length).toBeGreaterThan(0); expect(within(screen.getByRole('region', {name: 'Data quality'})).getByText(/<img src=x/)).toBeInTheDocument(); expect(container.querySelector('img')).toBeNull(); expect(within(screen.getByRole('region', {name: 'Data quality'})).getByText(/DELIVERY_REGRESSION/)).toBeInTheDocument(); expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
it('compares original with missing impaired without zero fill', async () => {
  render(<SensorDashboard />); upload(fixture()); await screen.findByText('STALE'); upload(await impaired(true), 'Comparison inspection JSON');
  const region = screen.getByRole('region', {name: 'Original versus impaired comparison'});
  await waitFor(() => expect(within(region).getByText(/MISSING \/ dropout/)).toBeInTheDocument()); expect(within(region).getByText('101325 Pa')).toBeInTheDocument();
});
it('reports invalid/oversized picker files and clears previous dataset', async () => {
  render(<SensorDashboard />); upload(fixture()); await screen.findByText('STALE'); upload({schema_version: 2}); await screen.findByRole('alert'); expect(screen.queryByText('Dataset provenance')).not.toBeInTheDocument();
  const f = new File(['x'], 'big.json'); Object.defineProperty(f, 'size', {value: MAX_BYTES + 1}); fireEvent.change(screen.getByLabelText('Load Phase 75D inspection JSON'), {target: {files: [f]}}); expect(screen.getByRole('alert')).toHaveTextContent('8 MiB');
});
function allSensors() {
  const d = fixture(), base = d.observations[0]!.record;
  for (const sensor of ['imu', 'gnss'] as const) {
    const values = sensor === 'gnss' ? [['latitude', 10, 'deg'], ['longitude', 20, 'deg'], ['altitude', 3, 'm']] : [
      ...['x','y','z'].map(a => [`acceleration.${a}`, 0, 'm/s^2']),
      ...['x','y','z'].map(a => [`angular_velocity.${a}`, 0, 'rad/s']),
      ...['x','y','z','w'].map(a => [`orientation.${a}`, a === 'w' ? 1 : 0, '1']),
    ];
    const r: RecordRow = {...base, observation_type: sensor, source: {...base.source, component_id: sensor, source_id: `passive_aircraft::body::${sensor}`}, frame: `passive_aircraft::body::${sensor}`, values: values.map(([name,value,unit]) => ({schema_version: 1, name: String(name), value: Number(value), unit: String(unit)}))};
    d.observations.push({record: r, freshness: 'stale'});
    d.summary[sensor] = {...d.summary.barometer, frames: [r.frame], units: Object.fromEntries(r.values!.map(f => [f.name, f.unit])), origins: {raw: 1, impaired: 0}};
  }
  return d;
}
it('renders all sensor components and allows observation scrubbing', async () => {
  const d = allSensors(); await expect(loadInspection(JSON.stringify(d))).resolves.toBeDefined();
  render(<SensorDashboard />); upload(d); await screen.findByRole('img', {name: /latitude history/});
  expect(screen.getByRole('img', {name: /orientation.w history/})).toBeInTheDocument();
  expect(screen.getByRole('img', {name: /angular_velocity.x history/})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Observation scrubber'), {target: {value: '2'}});
  expect(screen.getByText(/Observation 3 \/ 3/)).toHaveTextContent('gnss');
});
it('rejects incomplete vectors, unknown nested fields and false saved freshness', async () => {
  const d = allSensors(); d.observations[1]!.record.values!.pop(); await expect(loadInspection(JSON.stringify(d))).rejects.toThrow('incomplete vector');
  const bad = JSON.parse(example); bad.observations[0].record.source.extra = 'x'; await expect(loadInspection(JSON.stringify(bad))).rejects.toThrow();
  const stale = fixture(); stale.observations[0]!.freshness = 'fresh'; await expect(loadInspection(JSON.stringify(stale))).rejects.toThrow('Freshness');
});
it('rejects invalid UTF-8 before accepting metadata', async () => {
  render(<SensorDashboard />); const f = new File(['x'], 'invalid.json'); Object.defineProperty(f, 'arrayBuffer', {value: async () => new Uint8Array([0xff]).buffer});
  fireEvent.change(screen.getByLabelText('Load Phase 75D inspection JSON'), {target: {files: [f]}});
  expect(await screen.findByRole('alert')).toHaveTextContent('UTF-8');
});

it('validates without network or implicit wall clock and preserves unknown rejected sensor labels', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {throw new Error('Network forbidden');});
  const now = vi.spyOn(Date, 'now').mockImplementation(() => {throw new Error('Wall clock forbidden');});
  try {
    const d = fixture();
    d.rejected = [{index: 1, sensor: 'unrecognized_sensor', diagnostic: {code: 'SCHEMA', path: 'observation_type', explanation: 'Unknown sensor'}}];
    const loaded = await loadInspection(JSON.stringify(d));
    expect(loaded.rejected[0]!.sensor).toBe('unrecognized_sensor');
    expect(fetch).not.toHaveBeenCalled(); expect(now).not.toHaveBeenCalled();
  } finally {fetch.mockRestore(); now.mockRestore();}
});

it('preserves narrow extrema, stable duplicates, endpoints and budgets without mutation', () => {
  const r = fixture().observations[0]!.record;
  const rows = Array.from({length: 1000}, (_, i) => ({...r, acquisition: {...r.acquisition, value_ns: String(i)}, values: [{...r.values![0]!, value: i === 321 ? 900 : i === 654 ? -800 : 1}]}));
  const before = JSON.stringify(rows);
  expect(chartData(rows, 'pressure', 32).map(p => p.value)).toEqual(expect.arrayContaining([900, -800]));
  for (const budget of [2, 3, 4, 17, 32, 256]) {
    const p = chartData(rows, 'pressure', budget);
    expect(p.length).toBeLessThanOrEqual(budget); expect(p[0]!.time).toBe('0'); expect(p.at(-1)!.time).toBe('999');
    expect(p).toEqual(chartData(rows, 'pressure', budget));
  }
  expect(JSON.stringify(rows)).toBe(before);
  expect(chartData([rows[2]!, {...rows[1]!, values: [{...r.values![0]!, value: 7}]}, rows[1]!], 'pressure').map(p => [p.time, p.value])).toEqual([['1', 7], ['1', 1], ['2', 1]]);
  expect(() => chartData([{...r, acquisition: {...r.acquisition, value_ns: 'bad'}}], 'pressure')).toThrow();
});
it('retains omitted dropout boundaries, unavailable values and channel separation', () => {
  const r = fixture().observations[0]!.record;
  const rows = Array.from({length: 100}, (_, i) => ({...r, acquisition: {...r.acquisition, value_ns: String(i)}, values: i === 50 ? null : r.values}));
  const p = chartData(rows, 'pressure', 2);
  expect(p).toHaveLength(2); expect(p[0]!.segment).not.toBe(p[1]!.segment);
  for (const value of [NaN, Infinity, 'bad']) {
    expect(chartData([{...r, values: [{...r.values![0]!, value}]} as RecordRow], 'pressure')[0]!.value).toBeNull();
  }
  expect(chartData([r], 'absent')[0]!.value).toBeNull();
  const channels = chartData([r, {...r, origin: 'impaired'}], 'pressure');
  expect(channels[0]!.segment).not.toBe(channels[1]!.segment);
});
it('announces loaded data and selected observation with accessible controls', async () => {
  render(<SensorDashboard />);
  expect(screen.getByLabelText('Load Phase 75D inspection JSON')).toHaveAttribute('type', 'file');
  expect(screen.getByLabelText('Comparison inspection JSON')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', {name: 'Load synthetic example'}));
  await screen.findByText(/Local dataset loaded:/);
  expect(screen.getByRole('slider', {name: 'Observation scrubber'})).toHaveAttribute('aria-valuetext', expect.stringContaining('acquisition 0 ns'));
  expect(screen.getByRole('img', {name: /pressure history/})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Evaluation time (ns)'), {target: {value: '0'}});
  expect(screen.getByText('FRESH')).toBeInTheDocument();
});
it('never invents an original for impaired-only data', async () => {
  render(<SensorDashboard />); upload(await impaired()); await screen.findByText('STALE');
  expect(within(screen.getByRole('region', {name: 'Original versus impaired comparison'})).getByText('Unavailable: no matching observation.')).toBeInTheDocument();
});

it('preserves first and last valid observations beside unavailable boundaries', () => {
  const r = fixture().observations[0]!.record;
  const rows = Array.from({length: 100}, (_, i) => ({...r, acquisition: {...r.acquisition, value_ns: String(i)}, values: i === 0 || i === 99 ? null : r.values}));
  const p = chartData(rows, 'pressure', 2);
  expect(p.map(p => p.time)).toEqual(['1', '98']);
  const empty = chartData(rows.map(r => ({...r, values: null})), 'pressure', 4);
  expect(empty).toHaveLength(4); expect(empty.every(p => p.value === null)).toBe(true);
  for (const budget of [0, 1, 2.5, NaN]) expect(() => chartData(rows, 'pressure', budget)).toThrow('chart limit');
});
