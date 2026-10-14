import { useRef, useState } from 'react';
import { ObservationInspector } from './observation/ObservationInspector';
import { RadarDisplay } from './radar/RadarDisplay';
export { RadarDisplay as RadarGraphic } from './radar/RadarDisplay';
import { RecordedPlayer } from './camera/RecordedPlayer';
import { APPROVED_RECORDINGS } from './camera/catalog';
export { SimulationViewer as SimulationPanel } from './simulation/SimulationViewer';
import type { Session, Snapshot } from './models';
import { Badge, Card, Empty, Time, label } from './components';

export function RadarPanel({ snapshot }: { snapshot: Snapshot }) {
  const [selectedId, setSelectedId] = useState(snapshot.observations[0]?.observation_id ?? '');
  const selected = snapshot.observations.find(o => o.observation_id === selectedId);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  return <Card title="Tactical radar" className="visual-panel"><RadarDisplay>
    <div className="radar-inspection-layout"><div><h3>Non-spatial observations · {snapshot.observations.length}</h3>
    {snapshot.observations.length ? <ul className="hud-observations">{snapshot.observations.map(o => <li key={o.observation_id}><button ref={element => { if (element && selectedId === o.observation_id) trigger.current = element; }} aria-pressed={selectedId === o.observation_id} onClick={event => { trigger.current = event.currentTarget; setFocusRequest(n => n + 1); setSelectedId(o.observation_id); }}><code>{o.observation_id}</code><Badge value={o.quality} /></button></li>)}</ul> : <Empty>No observations are supplied.</Empty>}
    </div>{selected ? <ObservationInspector observation={selected} snapshot={snapshot} focusRequest={focusRequest} onClose={() => { setSelectedId(''); trigger.current?.focus(); }} /> : <Empty>Select an observation to inspect its supplied metadata.</Empty>}</div>
    <details><summary>Supplied sensor availability</summary>{snapshot.sentinels.length ? snapshot.sentinels.map(s => <ul key={s.device_id} className="compact-list">{s.sensors.map(sensor => <li key={sensor.source_id}>{sensor.source_id}: {sensor.status}</li>)}</ul>) : <p>Unknown — no Sentinel monitors supplied.</p>}</details>
  </RadarDisplay></Card>;
}

export function CameraPanel({ snapshot }: { snapshot: Snapshot }) {
  const cameras = snapshot.evidence.filter(e => e.kind === 'camera_recording');
  const [cameraId, setCameraId] = useState(cameras[0]?.evidence_id ?? '');
  const [recordingId, setRecordingId] = useState<string | null>(null);
  const evidence = cameras.find(e => e.evidence_id === cameraId);
  const device = snapshot.registry.devices.find(d => d.sources.some(s => s.source_id === evidence?.source_id));
  const monitor = snapshot.sentinels.find(s => s.device_id === device?.device_id);
  const availability = monitor?.sensors.find(s => s.source_id === evidence?.source_id)?.status ?? 'unknown';
  return <Card title="Drone camera" className="visual-panel"><p className="boundary-label">RECORDED REFERENCE · METADATA ONLY</p>
    {cameras.length > 1 && <label>Camera evidence<select value={cameraId} onChange={e => setCameraId(e.target.value)}>{cameras.map(e => <option key={e.evidence_id} value={e.evidence_id}>{e.evidence_id}</option>)}</select></label>}
    {!evidence && <p>Camera identifier unavailable</p>}
    {APPROVED_RECORDINGS.length > 0 && <label>Approved demo recording<select value={recordingId ?? ''} onChange={e => setRecordingId(e.target.value || null)}><option value="">No recording selected</option>{APPROVED_RECORDINGS.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label>}
    <RecordedPlayer recordingId={recordingId} />
    {APPROVED_RECORDINGS.length > 0 && <p className="note">Bundled demonstration playback is separate from evidence metadata and does not verify referenced recordings.</p>}
    <Badge value={availability} />
    <dl><dt>Camera identifier</dt><dd>{evidence?.source_id ?? 'Not supplied'}</dd><dt>Device</dt><dd>{device?.device_id ?? 'Not supplied'}</dd><dt>Camera availability</dt><dd>{availability}</dd><dt>Playback status</dt><dd>Unavailable — metadata only</dd><dt>Recording timestamp</dt><dd>Not supplied</dd><dt>Evidence reference</dt><dd><code>{evidence?.evidence_id ?? 'Not supplied'}</code></dd><dt>Local reference metadata</dt><dd><code>{evidence?.local_path ?? 'Not supplied'}</code></dd></dl>
    <p className="note">Reference existence or checksum does not establish a verified camera feed. Evidence paths are never fetched. Only explicitly approved bundled media can be played.</p>
  </Card>;
}

export function DeviceStatus({ snapshot }: { snapshot: Snapshot }) {
  return <Card title="Device status" className="device-status">{snapshot.registry.devices.length ? <div className="table-scroll" tabIndex={0} aria-label="Compact device status table"><table><caption>Final snapshot declarations</caption><thead><tr>{['Device', 'Category', 'Connection', 'Health', 'Sensor availability', 'Details'].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{snapshot.registry.devices.map(d => { const s = snapshot.sentinels.find(m => m.device_id === d.device_id); return <tr key={d.device_id}><td><code>{d.device_id}</code><small>{d.device_type}</small></td><td>{label(d.category)}</td><td><Badge value={d.connection_status} /></td><td><Badge value={d.health.status} /></td><td>{s ? <ul className="compact-list">{s.sensors.map(a => <li key={a.source_id}>{a.source_id}: {a.status}</li>)}</ul> : 'Unknown — no monitor supplied'}</td><td><details><summary>Inspect</summary><p>{d.health.note}</p><Time value={d.health.timestamp} /><small>{d.adapter.adapter_id} · v{d.adapter.version}</small>{s && <small>{s.sentinel_category} Sentinel · Battery {s.battery_percent === null ? 'unknown' : `${s.battery_percent}%`} · Maintenance {s.maintenance_status}</small>}</details></td></tr>; })}</tbody></table></div> : <Empty>No devices are supplied.</Empty>}</Card>;
}

export function RecentEvents({ session, onSelect }: { session: Session; onSelect: (index: number) => void }) {
  return <Card title="Recent events"><p className="note">Supplied order · event results, not intermediate snapshots</p>{session.event_results.length ? <ol className="event-timeline">{session.event_results.map(e => <li key={e.event_index}><button aria-label={`Inspect event ${e.event_index + 1}: ${e.event_id}`} onClick={() => onSelect(e.event_index)}><span className="event-sequence">{(e.event_index + 1).toString().padStart(2, '0')}</span><span><strong>{e.event_id}</strong><small>{label(e.event_type)} · {e.source_id ?? e.device_id}</small><Time value={e.timestamp} /></span><Badge value={e.status} /></button></li>)}</ol> : <Empty>No event results are supplied.</Empty>}</Card>;
}

export function AlertSummary({ snapshot }: { snapshot: Snapshot }) {
  return <Card title="Alerts"><p className="note">Descriptive metadata · severity not supplied</p>{snapshot.alerts.length ? snapshot.alerts.map(a => <article className="record" key={a.alert_id}><Badge value={a.status} /><h3>{a.alert_id}</h3><p>{a.explanation.explanation}</p><small>Observation: {a.observation_id}</small><small>Evidence: {a.explanation.evidence_ids.join(', ')}</small></article>) : <Empty>No alerts are supplied.</Empty>}</Card>;
}
