import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { validate } from '../src/sensor/schema';
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import example from '../../../examples/sensor_telemetry_example.json?raw';
import { freshness, loadInspection, sha256, SENSORS } from '../src/sensor/model';
import type { Inspection, RecordRow, Sensor, Timestamp } from '../src/sensor/model';
import { buildReplay, encodeReplay, inspectReplay, replayInspections, MAX_REPLAY_DIAGNOSTICS } from '../src/sensor/replay';
import { SensorDashboard } from '../src/sensor/SensorDashboard';
Object.defineProperty(globalThis, 'crypto', {value: webcrypto, configurable: true});
const clock = (n = '100', domain = 'sim'): Timestamp => ({schema_version: 1, value_ns: n, domain, unit: 'ns'});
function row(sensor: Sensor, acquisition: number, delivery: number | null = acquisition): RecordRow {
  const r = (JSON.parse(example) as Inspection).observations[0]!.record;
  const fields = sensor === 'imu' ? ['acceleration.x', 'acceleration.y', 'acceleration.z'] : sensor === 'gnss' ? ['latitude', 'longitude', 'altitude'] : ['pressure'];
  return {...r, observation_type: sensor, source: {...r.source, component_id: sensor, source_id: `passive_aircraft::body::${sensor}`},
    frame: `passive_aircraft::body::${sensor}`, acquisition: clock(String(acquisition)), simulation: clock(String(acquisition)), delivery: delivery === null ? null : clock(String(delivery)),
    values: fields.map(name => ({schema_version: 1, name, value: sensor === 'barometer' ? 101325 : 0, unit: sensor === 'imu' ? 'm/s^2' : name === 'altitude' ? 'm' : sensor === 'gnss' ? 'deg' : 'Pa'}))};
}
function fixture(rows: RecordRow[]): Inspection {
  const d = JSON.parse(example) as Inspection;
  d.evaluation = clock(); d.stale_after_ns = '20';
  d.observations = rows.map(record => ({record, freshness: freshness(record, d.evaluation, d.stale_after_ns)}));
  for (const sensor of SENSORS) {
    const entries = d.observations.filter(o => o.record.observation_type === sensor);
    const latest = entries.filter(o => ['fresh', 'stale'].includes(o.freshness)).sort((a, b) => Number(BigInt(a.record.acquisition.value_ns) - BigInt(b.record.acquisition.value_ns))).at(-1);
    d.summary[sensor] = {count: entries.length, rejected: 0, missing: entries.filter(o => o.record.values === null).length,
      latest_acquisition_ns: latest?.record.acquisition.value_ns ?? null, freshness: latest?.freshness ?? 'missing',
      origins: {raw: entries.filter(o => o.record.origin === 'raw').length, impaired: entries.filter(o => o.record.origin === 'impaired').length},
      units: Object.fromEntries(entries.flatMap(o => o.record.values ?? []).map(f => [f.name, f.unit])), frames: [...new Set(entries.map(o => o.record.frame))].sort()};
  }
  return d;
}
const load = (rows: RecordRow[]) => loadInspection(JSON.stringify(fixture(rows)));
const state = (h: ReturnType<typeof buildReplay>, n: string, sensor: Sensor = 'imu') => inspectReplay(h, clock(n), '20').sensors.find(s => s.sensor === sensor)!;
it('aligns mixed rates without interpolation with stable sensor ordering at equal times', async () => {
  const doc = await load([row('barometer', 0), row('gnss', 0), row('imu', 0), row('imu', 10), row('barometer', 20), row('imu', 20)]);
  const before = JSON.stringify(doc), h = buildReplay([doc]);
  expect(h.timeline.map(e => [e.record.acquisition.value_ns, e.record.observation_type])).toEqual([['0','imu'],['0','gnss'],['0','barometer'],['10','imu'],['20','imu'],['20','barometer']]);
  const result = inspectReplay(h, clock('15'), '20');
  expect(result.sensors.map(s => s.channels[0]!.age_ns)).toEqual(['5','15','15']);
  expect(result.sensors.map(s => h.timeline[s.channels[0]!.timeline_index!]!.record.acquisition.value_ns)).toEqual(['10','0','0']);
  expect(JSON.stringify(doc)).toBe(before); expect(Object.isFrozen(h.timeline[0]!.record)).toBe(true);
});
it('keeps duplicates across inspections, breaking equal-time ties by input file and index', async () => {
  const doc = await load([row('imu', 10)]), h = buildReplay([doc, doc]);
  expect(h.timeline).toHaveLength(2); expect(h.timeline.map(e => e.dataset)).toEqual([0,1]);
  expect(h.diagnostics.some(d => d.code === 'DUPLICATE')).toBe(true);
  expect(state(h, '10').channels[0]!.timeline_index).toBe(0);
  const repeated = fixture([row('imu', 10), row('imu', 10)]);
  await expect(loadInspection(JSON.stringify(repeated))).rejects.toThrow('DUPLICATE');
});
it('never exposes pending measurements and older delayed arrivals do not supersede newer acquisition', async () => {
  const h = buildReplay([await load([row('imu', 10, 50), row('imu', 20, 25), row('imu', 30, 90)])]);
  expect(state(h, '24').channels[0]!.timeline_index).toBeNull();
  const at25 = state(h, '25').channels[0]!;
  expect(h.timeline[at25.timeline_index!]!.record.acquisition.value_ns).toBe('20');
  expect(state(h, '50').channels[0]!.timeline_index).toBe(at25.timeline_index);
  expect(state(h, '89').channels[0]!.timeline_index).toBe(at25.timeline_index);
  expect(h.timeline[state(h, '90').channels[0]!.timeline_index!]!.record.acquisition.value_ns).toBe('30');
  expect(h.diagnostics.some(d => d.code === 'DELIVERY_REGRESSION')).toBe(true);
});
it('dropout replaces earlier measurement only when delivered; unknown delivery remains unknown', async () => {
  const dropped = {...row('imu', 20, 40), values: null};
  const h = buildReplay([await load([row('imu', 0), dropped, row('imu', 30, null)])]);
  expect(state(h, '39').status).toBe('stale');
  expect(state(h, '40').status).toBe('missing');
  expect(h.timeline[state(h, '40').channels[0]!.timeline_index!]!.record.values).toBeNull();
  expect(state(h, '100').status).toBe('missing');
  expect(h.diagnostics.map(d => d.code)).toEqual(expect.arrayContaining(['DROPOUT','AVAILABILITY_UNKNOWN','MISSING_HISTORY']));
});
it('uses exact selected-time freshness and no wall clock; distinguishes missing histories', async () => {
  const h = buildReplay([await load([row('imu', 10)])]);
  const now = vi.spyOn(Date, 'now').mockImplementation(() => {throw Error('No wall clock');});
  try {
    expect(state(h, '30').status).toBe('fresh'); expect(state(h, '31').status).toBe('stale');
    expect(state(h, '0').status).toBe('missing'); expect(state(h, '31', 'gnss').channels).toEqual([]);
    expect(inspectReplay(h, clock('31'), '20').diagnostics.some(d => d.code === 'STALE')).toBe(true);
    expect(now).not.toHaveBeenCalled();
  } finally {now.mockRestore();}
});
it('rejects invalid timestamps and domains without guessing conversions', async () => {
  const h = buildReplay([await load([row('imu', 0)])]);
  const extended = {...clock(), extra: true};
  expect(inspectReplay(h, extended, '20').sensors.every(s => s.status === 'invalid')).toBe(true);
  await expect(replayInspections([JSON.stringify(fixture([row('imu',0)]))], extended, '20')).rejects.toThrow('TIMESTAMP');
  for (const stamp of ['-1','1.5','18446744073709551616','abc']) {
    expect(inspectReplay(h, clock(stamp), '20').sensors.every(s => s.status === 'invalid')).toBe(true);
    await expect(replayInspections([JSON.stringify(fixture([row('imu',0)]))], clock(stamp), '20')).rejects.toThrow();
  }
  expect(inspectReplay(h, clock('10','unknown'), '20').diagnostics.at(-1)!.code).toBe('CLOCK_DOMAIN');
  await expect(replayInspections([JSON.stringify(fixture([row('imu',0)]))], clock('10','other'), '20')).rejects.toThrow('CLOCK_DOMAIN');
  const other = fixture([row('imu',0)]); other.evaluation.domain='other'; other.observations[0]!.record.source.clock_domain='other';
  for (const t of [other.observations[0]!.record.acquisition, other.observations[0]!.record.simulation, other.observations[0]!.record.delivery]) if(t)t.domain='other';
  expect(() => buildReplay([fixture([row('imu',0)]),other])).toThrow('CLOCK_DOMAIN');
  const bad = fixture([row('imu',0)]); bad.observations[0]!.record.delivery!.domain='other';
  await expect(replayInspections([JSON.stringify(bad)],clock(),'20')).rejects.toThrow();
});
it('retains lossless uint64 time precision', async () => {
  const r = row('imu',0); r.acquisition.value_ns=r.simulation.value_ns=r.delivery!.value_ns='18446744073709551610';
  const d = fixture([r]); d.evaluation=clock('18446744073709551615'); d.observations[0]!.freshness='fresh';d.summary.imu.freshness='fresh';d.summary.imu.latest_acquisition_ns=r.acquisition.value_ns;
  const h=buildReplay([await loadInspection(JSON.stringify(d))]);
  expect(state(h,'18446744073709551615').channels[0]!.age_ns).toBe('5');
});
it('bounds rows and diagnostics while preserving producer rejection indices and source labels', async () => {
  const d=fixture([row('imu',0)]);
  d.rejected=[{index:3,sensor:'imu',diagnostic:{code:'TIMESTAMP',path:'acquisition',explanation:'Invalid timestamp'}}];d.summary.imu.rejected=1;
  d.anomalies=Array.from({length:2048},()=>({index:3,code:'OUT_OF_ORDER'}));
  d.source_diagnostics=[{index:3,sensor:'imu',acquisition_ns:'0',reasons:['STALE','OUT_OF_ORDER']}];
  const loaded=await loadInspection(JSON.stringify(d));const h=buildReplay([loaded,loaded]);
  expect(h.diagnostics).toHaveLength(MAX_REPLAY_DIAGNOSTICS);expect(h.diagnostics_dropped).toBeGreaterThan(0);
  expect(h.diagnostics.find(d=>d.code==='TIMESTAMP')!.index).toBeNull();
  expect(h.diagnostics.find(d=>d.code==='TIMESTAMP')!.detail).toContain('original input index 3');
  expect(h.diagnostics.some(d=>d.code==='SOURCE_STALE')).toBe(true);
  expect(() => buildReplay([])).toThrow('BOUND');
  expect(() => buildReplay([loaded,loaded,loaded])).toThrow('BOUND');
  const big=fixture(Array.from({length:513},(_,i)=>row('imu',i)));const b=await loadInspection(JSON.stringify(big));
  expect(()=>buildReplay([b,b])).toThrow('BOUND');
});
it('keeps raw/impaired provenance and conflicting recording digests as distinct channels', async () => {
  const raw=row('imu',10), impaired={...row('imu',10),origin:'impaired' as const,config_json:'{"policies":[],"reference_ns":0,"rules":[],"schema_version":1,"seed":0,"stale_after_ns":100000000}',seed_identifier:'0'};
  impaired.config_sha256=await sha256(impaired.config_json+'\n');
  const h=buildReplay([await load([raw]),await load([impaired])]);
  const s=state(h,'10');expect(s.status).toBe('invalid');expect(s.channels.map(c=>h.timeline[c.history_index]!.record.origin)).toEqual(['raw','impaired']);
  const conflict={...row('imu',10),source_sha256:'b'.repeat(64)};
  const anomalous=buildReplay([await load([raw]),await load([conflict])]);
  expect(anomalous.diagnostics.some(d=>d.code==='SOURCE_PROVENANCE')).toBe(true);
});
it('replays identically three times and never mutates input text', async () => {
  const text=JSON.stringify(fixture([row('imu',0),row('gnss',10),row('barometer',20)]));
  const results=[];for(let i=0;i<3;i++)results.push(encodeReplay(await replayInspections([text],clock('30'),'20')));
  expect(JSON.parse(results[0]!).inputs[0].inspection_sha256).toBe(await sha256(text));
  expect(JSON.parse(results[0]!).inputs[0].example_kind).toBe('synthetic_fixture');
  expect(new Set(results).size).toBe(1);expect(JSON.parse(results[0]!).timeline).toHaveLength(3);
});
it('integrates shared timeline and selected-time availability with existing dashboard controls', async () => {
  render(<SensorDashboard />);
  const text=JSON.stringify(fixture([row('imu',10,30),row('gnss',0,0)]));
  const file=new File([text],'replay.json');Object.defineProperty(file,'arrayBuffer',{value:async()=>new TextEncoder().encode(text).buffer});
  fireEvent.change(screen.getByLabelText('Load Phase 75D inspection JSON'),{target:{files:[file]}});
  const region=await screen.findByRole('region',{name:'Shared multi-sensor replay'});
  expect(within(region).getByText(/Known delivery must be at or before evaluation/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Evaluation time (ns)'),{target:{value:'20'}});
  expect(within(region).getByRole('article',{name:'imu selected-time inspection'})).toHaveTextContent('Selected-time status: missing');
  expect(within(region).getByRole('article',{name:'gnss selected-time inspection'})).toHaveTextContent('Selected-time status: fresh');
  fireEvent.change(screen.getByLabelText('Shared replay timeline'),{target:{value:'1'}});
  expect(within(region).getByText(/Timeline entry 2/)).toHaveTextContent('imu');
  fireEvent.change(screen.getByLabelText('Evaluation time (ns)'),{target:{value:'30'}});
  expect(within(region).getByRole('article',{name:'imu selected-time inspection'})).toHaveTextContent('Selected-time status: fresh');
  fireEvent.change(screen.getByLabelText('Evaluation clock domain'),{target:{value:'unknown'}});
  expect(within(region).getByRole('article',{name:'imu selected-time inspection'})).toHaveTextContent('Selected-time status: invalid');
});

it('exports the closed output schema and a bounded read-only CLI with repeatable hashes', async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'aegis76a-test-'));
  const run = (args: string[]) => spawnSync(process.execPath, args, {encoding:'utf8', timeout:30000, maxBuffer:9*1024*1024});
  try {
    const build = run(['scripts/build_sensor_replay.mjs', temporary]);
    expect(build.error).toBeUndefined(); expect(build.status, build.stderr).toBe(0);
    const file = join(temporary, 'input.json'), text = JSON.stringify(fixture([row('imu',0),row('gnss',10),row('barometer',20)]));
    writeFileSync(file,text);
    const args = [join(temporary,'sensor-replay.mjs'),'--domain','sim','--evaluation-ns','30','--stale-after-ns','20',file];
    const outputs = Array.from({length:3},()=>run(args));
    for(const out of outputs) {expect(out.status,out.stderr).toBe(0);expect(out.error).toBeUndefined();}
    expect(new Set(outputs.map(o=>o.stdout)).size).toBe(1);expect(readFileSync(file,'utf8')).toBe(text);
    const schema=JSON.parse(readFileSync(resolve('../../configs/simulation/multisensor-replay-v1.schema.json'),'utf8'));
    const wire=JSON.parse(readFileSync(resolve('../../configs/simulation/sensor-telemetry-v1.schema.json'),'utf8'));
    schema.properties.timeline.items.properties.record=wire.properties.observations.items;
    const output=JSON.parse(outputs[0]!.stdout);expect(()=>validate(output,schema)).not.toThrow();
    expect(()=>validate({...output,extra:true},schema)).toThrow('unknown field');
    const bad=run(args.map(a=>a==='sim'?'unknown':a));expect(bad.status).toBe(2);expect(bad.stdout).toBe('');
    writeFileSync(file,'{');const malformed=run(args);expect(malformed.status).toBe(2);expect(malformed.stdout).toBe('');
    writeFileSync(file,' '.repeat(8*1024*1024+1));const large=run(args);expect(large.status).toBe(2);expect(large.stdout).toBe('');
  } finally {rmSync(temporary,{recursive:true,force:true});}
},30000);
