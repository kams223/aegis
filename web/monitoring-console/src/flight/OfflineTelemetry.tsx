import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Card } from '../components';
import { RecordedPlayer } from '../camera/RecordedPlayer';
import { FIELD_NAMES, loadTelemetrySnapshot, MAX_TELEMETRY_BYTES } from './telemetry';
import type { TelemetrySnapshot } from './telemetry';

export function OfflineTelemetry() {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | null>(null), [selectedKey, setSelectedKey] = useState('');
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
  const selected = snapshot?.vehicles.find(v => v.identity_key === selectedKey);
  return <Card title="Recorded SITL snapshot inspection" className="offline-telemetry">
    <p className="boundary-label">RECORDED SNAPSHOT — NEVER LIVE · SEPARATE FROM DEMO FLEET</p>
    <p className="note">Read-only inspection. No vehicle, simulator, camera or control link is opened.</p>
    <p>Explicitly select a local UTF-8 JSON snapshot, at most 1 MiB. Values and freshness are replayed at the supplied evaluation time; they do not describe current vehicle state. No file is opened automatically.</p>
    <label>Import recorded SITL snapshot<input ref={fileInput} type="file" accept=".json,application/json" onChange={event => { void importFile(event); }} /></label>
    <button onClick={() => { generation.current++; if (fileInput.current) fileInput.current.value = ''; setSnapshot(null); setSelectedKey(''); setMessage(''); setLoading(false); }}>Clear recorded snapshot</button>
    {loading && <p role="status">Validating offline snapshot…</p>}{message && <p role="alert">{message}</p>}
    {snapshot && <><p>{snapshot.replay.description}</p><p className="note">Validation: {snapshot.summary.validation} · Accepted {snapshot.summary.accepted_count} · Rejected {snapshot.summary.rejected_count}. Software validation does not attest genuine simulator origin.</p>
      <p>Evaluation: {snapshot.replay.evaluation_timestamp.value} {snapshot.replay.evaluation_timestamp.unit} · {snapshot.replay.evaluation_timestamp.clock_domain}</p>
      {snapshot.vehicles.length ? <label>Recorded source/session<select value={selectedKey} onChange={event => setSelectedKey(event.target.value)}>{snapshot.vehicles.map(v => <option key={v.identity_key} value={v.identity_key}>{v.source.vehicle_id} · {v.source.autopilot_family} · SITL · {v.source.source_id}/{v.source.session_id} · {v.source.system_id}/{v.source.component_id}</option>)}</select></label> : <p>No configured source/session records.</p>}
      {selected && <section aria-label="Recorded SITL vehicle details"><h3>{selected.source.vehicle_id} · {selected.source.autopilot_family} · SITL</h3><p>Recorded reception: {selected.reception_state === 'stale' ? 'STALE — LAST REPORTED DECLARATION' : selected.reception_state} (at evaluation only){selected.fields.reception.value && 'status' in selected.fields.reception.value ? ` · Last reported: ${selected.fields.reception.value.status}` : ''}</p><dl><dt>Source/session</dt><dd>{selected.source.source_id}/{selected.source.session_id}</dd><dt>System/component</dt><dd>{selected.source.system_id}/{selected.source.component_id}</dd><dt>Source clock</dt><dd>{selected.source.source_clock_domain}</dd><dt>Receipt clock</dt><dd>{selected.source.receipt_clock_domain}</dd></dl>
        <div className="telemetry-fields">{FIELD_NAMES.map(name => { const f = selected.fields[name]; return <article key={name} data-freshness={f.state}><h3>{name.replaceAll('_', ' ')}</h3><strong>{f.state === 'stale' ? 'STALE — LAST KNOWN AT EVALUATION' : f.state === 'available' ? 'AVAILABLE AT RECORDED EVALUATION ONLY' : f.state.toUpperCase()}</strong><p>Field validation: {f.validation}</p>{f.value !== null ? <pre>{JSON.stringify(f.value, null, 2)}</pre> : <p>No value supplied or accepted.</p>}<dl><dt>Age at evaluation</dt><dd>{f.age_ms === null ? 'Not evaluated' : `${f.age_ms} ms`}</dd><dt>Record reference</dt><dd>{f.record_id ?? 'Not supplied'}</dd><dt>Source timestamp</dt><dd>{f.source_timestamp ? `${f.source_timestamp.value} ${f.source_timestamp.unit} · ${f.source_timestamp.clock_domain}` : 'Not supplied'}</dd><dt>Receipt timestamp</dt><dd>{f.receipt_timestamp ? `${f.receipt_timestamp.value} ms · ${f.receipt_timestamp.clock_domain}` : 'Not supplied'}</dd><dt>Provenance</dt><dd>{f.provenance ? `${f.provenance.kind} · ${f.provenance.record_reference} · ${f.provenance.note}` : 'Not supplied'}</dd><dt>Diagnostics</dt><dd>{f.diagnostic_codes.join(', ') || 'None supplied'}</dd></dl></article>; })}</div>
        <h3>Recorded camera unavailable</h3><RecordedPlayer recordingId={null} />
      </section>}
      <details><summary>Replay rejection diagnostics</summary>{snapshot.diagnostics.length ? <ol>{snapshot.diagnostics.map(d => <li key={d.record_index}>Record {d.record_index}: {d.record_id} · {d.source_id}/{d.session_id} · {d.field} · {d.code}</li>)}</ol> : <p>No rejected records.</p>}</details>
    </>}
  </Card>;
}
