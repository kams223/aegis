import { useMemo, useRef, useState } from 'react';
import example from '../../../../examples/sensor_telemetry_example.json?raw';
import { chartData, filterRecords, freshness, loadInspection, matchOriginal, MAX_BYTES, SENSORS, sha256, uint64 } from './model';
import type { Inspection, RecordRow, Sensor, Timestamp } from './model';

type Loaded = {doc: Inspection; name: string; digest: string};
const printable = (v: unknown) => JSON.stringify(v, null, 2);
function History({ rows, field, unit }: {rows: RecordRow[]; field: string; unit: string}) {
  const points = chartData(rows, field), values = points.flatMap(p => p.value === null ? [] : [p.value]);
  if (!values.length) return <article><h4>{field} · {unit}</h4><p>No available readings.</p></article>;
  const min = Math.min(...values), max = Math.max(...values), first = BigInt(points[0]!.time), span = BigInt(points.at(-1)!.time) - first;
  const xy = (p: typeof points[number]) => `${30 + (span ? Number(BigInt(p.time) - first) / Number(span) : 0.5) * 440},${120 - ((p.value! - min) / (max - min || 1)) * 90}`;
  const segments: string[][] = [[]];
  for (const p of points) { if (p.value === null) segments.push([]); else segments.at(-1)!.push(xy(p)); }
  return <article className="sensor-chart"><h4>{field} · {unit}</h4><svg viewBox="0 0 500 160" role="img" aria-label={`${field} history, acquisition ns; ${rows.length} records, ${rows.filter(r => r.values === null).length} missing`}>
    <path d="M30 20V130H480" className="chart-axis" />
    {segments.map((s, i) => <g key={i}><polyline points={s.join(' ')} />{s.map((p, j) => <circle key={j} cx={p.split(',')[0]} cy={p.split(',')[1]} r="2" />)}</g>)}
    <text x="32" y="15">{min} … {max} {unit}</text><text x="30" y="150">{points[0]!.time}</text><text x="475" y="150" textAnchor="end">{points.at(-1)!.time} ns</text>
  </svg><small>Acquisition time · at most 256 points · gaps retained</small></article>;
}
function Reading({record}: {record: RecordRow | null}) {
  if (!record) return <p>Unavailable: no matching observation.</p>;
  return <><p>{record.origin} · {record.values === null ? 'MISSING / dropout — no measurement' : 'recorded measurement'}</p><p>Acquired {record.acquisition.value_ns} ns · delivered {record.delivery?.value_ns ?? 'unknown'} ns · {record.acquisition.domain}</p>
    {record.values && <dl>{record.values.map(f => <div key={f.name}><dt>{f.name}</dt><dd>{f.value} {f.unit}</dd></div>)}</dl>}
    <details><summary>Source and transformation provenance</summary><pre>{printable({source: record.source, source_sha256: record.source_sha256, frame: record.frame, simulation: record.simulation, config_sha256: record.config_sha256, seed_identifier: record.seed_identifier, config_json: record.config_json})}</pre><p>Configuration retained verbatim. Phase 75D does not export per-row transformation descriptions.</p></details></>;
}
export function SensorDashboard() {
  const [loaded, setLoaded] = useState<Loaded | null>(null), [comparison, setComparison] = useState<Loaded | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [sensor, setSensor] = useState<Sensor | 'all'>('all'), [index, setIndex] = useState(0);
  const [evaluation, setEvaluation] = useState('0'), [domain, setDomain] = useState('sim'), [threshold, setThreshold] = useState('100000000');
  const request = useRef(0);
  async function load(text: string, name: string, secondary = false) {
    const token = ++request.current; setBusy(true); setError('');
    try {
      const doc = await loadInspection(text), digest = await sha256(text);
      if (token !== request.current) return;
      const item = {doc, name, digest};
      if (secondary) setComparison(item);
      else { setLoaded(item); setComparison(null); setIndex(0); setSensor('all'); setEvaluation(doc.evaluation.value_ns); setDomain(doc.evaluation.domain); setThreshold(doc.stale_after_ns); }
    } catch (e) { if (token === request.current) { setError(`File rejected: ${e instanceof Error ? e.message : 'Malformed JSON'}`); if (secondary) setComparison(null); else { setLoaded(null); setComparison(null); } } }
    finally { if (token === request.current) setBusy(false); }
  }
  async function file(file: File | undefined, secondary: boolean) {
    if (!file) return;
    if (file.size > MAX_BYTES) { request.current++; setBusy(false); setError('File rejected: exceeds 8 MiB'); if (secondary) setComparison(null); else {setLoaded(null); setComparison(null);} return; }
    const token = ++request.current; setBusy(true); setError('');
    try {
      const bytes = await file.arrayBuffer();
      const text = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);
      if (token === request.current) await load(text, file.name, secondary);
    } catch { if (token === request.current) {
      setBusy(false); setError('File rejected: could not read strict UTF-8 JSON');
      if (secondary) setComparison(null); else {setLoaded(null); setComparison(null);}
    } }
  }
  const rows = useMemo(() => loaded ? filterRecords(loaded.doc, sensor) : [], [loaded, sensor]);
  const selected = rows[Math.min(index, Math.max(0, rows.length - 1))] ?? null;
  let clockError = '';
  const clock: Timestamp = {schema_version: 1, unit: 'ns', domain, value_ns: evaluation};
  try { uint64(evaluation); uint64(threshold); if (loaded && loaded.doc.evaluation.domain !== domain) throw new Error('CLOCK_DOMAIN: selected evaluation domain differs; no clock synchronization'); }
  catch(e) {clockError = e instanceof Error ? e.message : 'Invalid evaluation';}
  const states = !clockError ? rows.map(r => freshness(r, clock, threshold)) : [];
  const originals = useMemo(() => comparison ? filterRecords(comparison.doc, 'all') : [], [comparison]);
  const match = selected ? matchOriginal(selected, [...rows, ...originals]) : null;
  const impaired = selected?.origin === 'impaired' ? selected : selected ? [...rows, ...originals].find(r => r.origin === 'impaired' && matchOriginal(r, [selected])) ?? null : null;
  const range = (delivery: boolean) => {
    const ts = rows.flatMap(r => delivery ? r.delivery ? [BigInt(r.delivery.value_ns)] : [] : [BigInt(r.acquisition.value_ns)]).sort((a,b) => a < b ? -1 : a > b ? 1 : 0);
    return ts.length ? `${ts[0]} … ${ts.at(-1)} ns` : 'Unavailable';
  };
  return <section className="sensor-dashboard" aria-label="Offline sensor telemetry dashboard">
    <p>Recorded simulation inspection · local files only · no geographic accuracy attestation.</p>
    <div className="sensor-controls"><label>Load Phase 75D inspection JSON<input type="file" accept=".json,application/json" disabled={busy} onChange={e => {void file(e.target.files?.[0], false); e.target.value = '';}} /></label>
      <button type="button" disabled={busy} onClick={() => void load(example, 'sensor_telemetry_example.json')}>Load synthetic example</button>
      <label>Comparison inspection JSON<input type="file" accept=".json,application/json" disabled={busy || !loaded} onChange={e => {void file(e.target.files?.[0], true); e.target.value = '';}} /></label></div>
    {busy && <p role="status">Validating local file…</p>}{error && <p role="alert">{error}</p>}
    {!loaded ? <p>Select a bounded Phase 75D inspection output (8 MiB, 1024 records maximum) or explicitly load the synthetic example.</p> : <>
      <section aria-label="Dataset overview"><h2>Overview</h2><p><strong>{loaded.name}</strong> · {loaded.doc.example_kind === 'synthetic_fixture' ? 'SYNTHETIC EXAMPLE — no evidence' : 'Recorded simulation output — provenance supplied by file'}</p>
        {loaded.doc.evidence_attestation && <p>{loaded.doc.evidence_attestation}</p>}
        <dl><div><dt>Dataset SHA-256 (selected bytes)</dt><dd>{loaded.digest}</dd></div><div><dt>Input artifact SHA-256</dt><dd>{loaded.doc.input_sha256 ?? 'Not supplied (example)'}</dd></div>
          <div><dt>Simulation source / sessions</dt><dd>{[...new Set(rows.map(r => r.source.session_id))].join(', ') || 'No observations'}</dd></div>
          <div><dt>Sensor count / observation count</dt><dd>{new Set(rows.map(r => r.observation_type)).size} / {rows.length}</dd></div>
          <div><dt>Valid / rejected / missing / stale</dt><dd>{rows.length} / {loaded.doc.rejected.filter(r => sensor === 'all' || r.sensor === sensor).length} / {rows.filter(r => r.values === null).length} / {clockError ? 'unknown' : states.filter(s => s === 'stale').length}</dd></div>
          <div><dt>Acquisition range</dt><dd>{range(false)}</dd></div><div><dt>Delivery range</dt><dd>{range(true)} · unknown for {rows.filter(r => !r.delivery).length} records</dd></div>
          <div><dt>Clock domains</dt><dd>{loaded.doc.evaluation.domain} · simulation nanoseconds; no host-clock mapping</dd></div></dl>
        <details><summary>Dataset provenance</summary><pre>{printable([...new Set(rows.map(r => printable({source: r.source, source_sha256: r.source_sha256, config_sha256: r.config_sha256})))].map(s => JSON.parse(s)))}</pre></details>
      </section>
      <section aria-label="Replay timeline"><h2>Replay timeline</h2><div className="sensor-controls">
        <label>Sensor filter<select value={sensor} onChange={e => {setSensor(e.target.value as Sensor | 'all'); setIndex(0);}}><option value="all">All sensors</option>{SENSORS.map(s => <option key={s}>{s}</option>)}</select></label>
        <label>Evaluation time (ns)<input value={evaluation} onChange={e => setEvaluation(e.target.value)} inputMode="numeric" /></label>
        <label>Evaluation clock domain<input value={domain} onChange={e => setDomain(e.target.value)} /></label>
        <label>Stale after (ns)<input value={threshold} onChange={e => setThreshold(e.target.value)} inputMode="numeric" /></label></div>
        <p>Age = evaluation − acquisition. Threshold equality is fresh. Future and pending deliveries are labeled separately. All history remains visible.</p>
        {clockError && <p role="alert">{clockError}</p>}
        <label>Observation scrubber<input type="range" min="0" max={Math.max(0, rows.length - 1)} value={Math.min(index, Math.max(0, rows.length - 1))} disabled={!rows.length} onChange={e => setIndex(Number(e.target.value))} /></label>
        {selected ? <><p>Observation {Math.min(index, rows.length - 1) + 1} / {rows.length} · {selected.observation_type} · <strong>{clockError ? 'freshness unavailable' : freshness(selected, clock, threshold).toUpperCase()}</strong></p>
          <button type="button" onClick={() => setEvaluation(selected.acquisition.value_ns)}>Evaluate at selected acquisition</button><Reading record={selected} /></> : <p>No observations for this sensor. Missing stream; expected sample rate unknown.</p>}
      </section>
      {SENSORS.filter(s => sensor === 'all' || s === sensor).map(s => { const history = rows.filter(r => r.observation_type === s && r.source.session_id === selected?.source.session_id && r.source_sha256 === selected?.source_sha256 && (r.origin === 'raw' || r.config_sha256 === selected?.config_sha256)); const fields = new Map(history.flatMap(r => r.values ?? []).map(f => [f.name, f.unit])); return <section key={s} aria-label={`${s} history`}><h2>{s === 'imu' ? 'IMU' : s === 'gnss' ? 'GNSS' : 'Barometer'}</h2>
        <p>{s === 'imu' ? 'Body FLU sensor frame. Acceleration is specific force; orientation is quaternion xyzw relative to initial world alignment.' : s === 'gnss' ? 'WGS84 degrees; altitude relative to configured spherical origin. Simulated reference only; geographic elevation accuracy is not established.' : 'Scalar pressure at sensor origin. Derived altitude shown only when supplied; atmosphere/reference assumptions are not exported by Phase 75D and are not inferred.'}</p>
        <p>Charts use the selected observation’s session, recording digest and impairment configuration.</p><p>Frame: {[...new Set(history.map(r => r.frame))].join(', ') || 'unavailable'} · Missing observations: {history.filter(r => r.values === null).length}</p>
        {history.length ? <div className="sensor-chart-grid">{[...fields].flatMap(([field, unit]) => (['raw', 'impaired'] as const).map(origin => {const series = history.filter(r => r.origin === origin); return series.length ? <div key={`${field}/${origin}`}><p>{origin}</p><History rows={series} field={field} unit={unit} /></div> : null;}))}</div> : <p>Missing stream; no measurements.</p>}
      </section>; })}
      <section aria-label="Data quality"><h2>Data quality</h2><p>Dropouts: {rows.filter(r => r.values === null).length}. Source STALE labels describe recorded latency; selected-time freshness is calculated separately. Missing expected samples cannot be inferred without a rate contract.</p>
        <h3>Rejected records and reasons</h3>{loaded.doc.rejected.length ? <ul>{loaded.doc.rejected.map((r,i) => <li key={i}>Input index {r.index} · {r.sensor ?? 'unknown sensor'} · {r.diagnostic.code} · {r.diagnostic.path}: {r.diagnostic.explanation}</li>)}</ul> : <p>No rejected records.</p>}
        <h3>Ordering anomalies</h3><pre>{printable(loaded.doc.anomalies)}</pre><h3>Source diagnostics</h3><pre>{printable(loaded.doc.source_diagnostics ?? [])}</pre>
      </section>
      <section aria-label="Original versus impaired comparison"><h2>Original versus impaired</h2><p>{comparison ? `Comparison dataset: ${comparison.name} · SHA-256 ${comparison.digest}` : 'Load a second Phase 75D inspection to compare recordings.'}</p><p>Exact source identity, recording digest, acquisition timestamp and clock must match. Missing values remain unavailable.</p><div className="sensor-comparison"><article><h3>Original</h3><Reading record={selected?.origin === 'raw' ? selected : match} /></article><article><h3>Impaired</h3><Reading record={impaired} /></article></div></section>
    </>}
  </section>;
}
