import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Card } from '../components';
import { TelemetryTimeline } from './TelemetryTimeline';
import { FIELD_NAMES, loadTelemetrySnapshot, MAX_TELEMETRY_BYTES } from './telemetry';
import type { FieldValue, TelemetrySnapshot, VehicleResult } from './telemetry';

export function OfflineTelemetry() {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | null>(null);
  const [selectedKey, setSelectedKey] = useState('');
  const [message, setMessage] = useState(''), [loading, setLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0], request = ++generation.current;
    setSnapshot(null); setSelectedKey(''); setMessage('');
    if (!file) { setLoading(false); return; }
    if (file.size > MAX_TELEMETRY_BYTES) { setMessage('Snapshot exceeds 1 MiB. No recorded data loaded.'); setLoading(false); return; }
    setLoading(true);
    try {
      const bytes = await file.arrayBuffer();
      if (bytes.byteLength > MAX_TELEMETRY_BYTES) throw new Error('Snapshot exceeds 1 MiB');
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      const result = loadTelemetrySnapshot(text);
      if (generation.current !== request) return;
      setSnapshot(result); setSelectedKey(result.vehicles[0]?.identity_key ?? '');
    } catch (error) { if (generation.current === request) setMessage(error instanceof Error ? error.message : 'Unable to load offline snapshot'); }
    finally { if (generation.current === request) setLoading(false); }
  }
  return <Card title="Recorded SITL snapshot inspection" className="offline-telemetry">
    <div className="telemetry-toolbar" aria-label="Recorded telemetry toolbar">
      <label>Import recorded SITL snapshot<input ref={fileInput} type="file" accept=".json,application/json" onChange={event => { void importFile(event); }} /></label>
      <button onClick={() => { generation.current++; if (fileInput.current) fileInput.current.value = ''; setSnapshot(null); setSelectedKey(''); setMessage(''); setLoading(false); }}>Clear recorded snapshot</button>
      {snapshot && <label>Recorded source/session<select value={selectedKey} onChange={event => setSelectedKey(event.target.value)} disabled={!snapshot.vehicles.length}>
        {!snapshot.vehicles.length && <option value="">No configured sources</option>}
        {snapshot.vehicles.map(v => <option key={v.identity_key} value={v.identity_key}>{v.source.vehicle_id} · {v.source.source_id}/{v.source.session_id} · {v.source.system_id}/{v.source.component_id}</option>)}
      </select></label>}
      {snapshot && <p className="import-summary">Imported snapshot validation: {snapshot.summary.validation} · Accepted {snapshot.summary.accepted_count} · Rejected {snapshot.summary.rejected_count}</p>}
    </div>
    <p className="boundary-label">RECORDED SNAPSHOT — NEVER LIVE · SEPARATE FROM DEMO FLEET</p>
    {loading && <p role="status">Validating offline snapshot…</p>}{message && <p role="alert">{message}</p>}
    {snapshot && <>
      <TelemetryTimeline snapshot={snapshot}>{projected => <ProjectedDetails snapshot={projected} selectedKey={selectedKey} />}</TelemetryTimeline>
      <details><summary>Snapshot context and inspection limits</summary><p>{snapshot.replay.description}</p><p>Read-only inspection of local UTF-8 JSON snapshots, at most 1 MiB. Software validation does not attest genuine simulator origin. No vehicle, simulator, camera or control link is opened.</p></details>
    </>}
  </Card>;
}

function ProjectedDetails({ snapshot, selectedKey }: { snapshot: TelemetrySnapshot; selectedKey: string }) {
  const selected = snapshot.vehicles.find(v => v.identity_key === selectedKey);
  return <>
      <p>Evaluation: {snapshot.replay.evaluation_timestamp.value} {snapshot.replay.evaluation_timestamp.unit} · {snapshot.replay.evaluation_timestamp.clock_domain}</p>
      {selected && <section aria-label="Recorded SITL vehicle details"><h3>{selected.source.vehicle_id} · {selected.source.autopilot_family} · SITL</h3><p>Recorded reception: {selected.reception_state === 'stale' ? 'STALE — LAST REPORTED DECLARATION' : selected.reception_state} (at evaluation only){selected.fields.reception.value && 'status' in selected.fields.reception.value ? ` · Last reported: ${selected.fields.reception.value.status}` : ''}</p><details><summary>Source identity and clocks</summary><dl><dt>Source/session</dt><dd>{selected.source.source_id}/{selected.source.session_id}</dd><dt>System/component</dt><dd>{selected.source.system_id}/{selected.source.component_id}</dd><dt>Source clock</dt><dd>{selected.source.source_clock_domain}</dd><dt>Receipt clock</dt><dd>{selected.source.receipt_clock_domain}</dd></dl></details>
        <div className="telemetry-fields">{FIELD_NAMES.map(name => { const f = selected.fields[name]; return <article key={name} data-freshness={name === 'reception' ? selected.reception_state : f.state}><h3>{name.replaceAll('_', ' ')}</h3><strong className="telemetry-value">{displayFieldValue(f.value)}</strong><span className="field-state">{name === 'reception' ? receptionLabel(selected.reception_state) : f.state === 'available' ? 'Fresh' : f.state === 'stale' ? 'Stale · Last reported' : f.state.toUpperCase()}</span>{f.age_ms !== null && <small>{f.age_ms} ms old at evaluation</small>}
          <details><summary>{name.replaceAll('_', ' ')} evidence details</summary><p>Field validation: {f.validation}</p><dl><FieldEvidence value={f.value} /><dt>Age at evaluation</dt><dd>{f.age_ms === null ? 'Not evaluated' : `${f.age_ms} ms`}</dd><dt>Record reference</dt><dd>{f.record_id ?? 'Not supplied'}</dd><dt>Source timestamp</dt><dd>{f.source_timestamp ? `${f.source_timestamp.value} ${f.source_timestamp.unit} · ${f.source_timestamp.clock_domain}` : 'Not supplied'}</dd><dt>Receipt timestamp</dt><dd>{f.receipt_timestamp ? `${f.receipt_timestamp.value} ms · ${f.receipt_timestamp.clock_domain}` : 'Not supplied'}</dd><dt>Provenance</dt><dd>{f.provenance ? `${f.provenance.kind} · ${f.provenance.record_reference} · ${f.provenance.note}` : 'Not supplied'}</dd><dt>Diagnostics</dt><dd>{f.diagnostic_codes.join(', ') || 'None supplied'}</dd></dl></details></article>; })}</div>
        <p className="note">NO VERIFIED CAMERA FEED</p>
      </section>}
      <details><summary>Replay rejection diagnostics</summary>{snapshot.diagnostics.length ? <ol>{snapshot.diagnostics.map(d => <li key={d.record_index}>Record {d.record_index}: {d.record_id} · {d.source_id}/{d.session_id} · {d.field} · {d.code}</li>)}</ol> : <p>No rejected records.</p>}</details>
  </>;
}

function displayFieldValue(value: FieldValue | null): string {
  if (value === null) return '—';
  if ('percentage' in value) return `${value.percentage} ${value.unit}`;
  if ('base_mode' in value) return `Base ${value.base_mode} / Custom ${value.custom_mode}`;
  if ('status' in value) return value.status;
  if ('reference' in value) return `${value.value} ${value.unit} · ${value.reference.replaceAll('_', ' ')}`;
  return `${value.value} ${value.unit}`;
}

// Reception has its own timeout; a recent field value is not proof that its
// declaration remains current. These labels never infer link health.
function receptionLabel(state: VehicleResult['reception_state']): string {
  switch (state) {
    case 'stale': return 'Stale — Last reported';
    case 'missing': return 'Missing';
    case 'unsupported': return 'Unsupported';
    case 'unknown': return 'Unknown';
    default: return 'Fresh';
  }
}

// Closed normalized payload variants, rendered as named fields rather than JSON.
// Null marks missing data; explicit zero and supplied strings are preserved.
function FieldEvidence({ value }: { value: FieldValue | null }) {
  if (value === null) return <><dt>Field payload</dt><dd>Not supplied</dd></>;
  if ('reference' in value) return <>
    <dt>Altitude value</dt><dd>{value.value}</dd><dt>Altitude unit</dt><dd>{value.unit}</dd>
    <dt>Altitude reference</dt><dd>{value.reference}</dd><dt>Altitude reference ID</dt><dd>{value.reference_id ?? 'Not supplied'}</dd>
  </>;
  if ('percentage' in value) return <>
    <dt>Battery ID</dt><dd>{value.battery_id}</dd><dt>Battery percentage</dt><dd>{value.percentage}</dd><dt>Battery unit</dt><dd>{value.unit}</dd>
  </>;
  if ('base_mode' in value) return <><dt>Base mode</dt><dd>{value.base_mode}</dd><dt>Custom mode</dt><dd>{value.custom_mode}</dd></>;
  if ('status' in value) return <><dt>Declared status</dt><dd>{value.status}</dd><dt>Status note</dt><dd>{value.note}</dd></>;
  return <><dt>Ground speed value</dt><dd>{value.value}</dd><dt>Ground speed unit</dt><dd>{value.unit}</dd></>;
}
