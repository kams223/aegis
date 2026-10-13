import { useRef, useState } from 'react';
import type { Session, Snapshot } from './models';
import { Badge, Card, Empty, Time, label } from './components';

export function RadarGraphic() {
  return <div className="radar-scope"><svg width="320" height="320" viewBox="0 0 320 320" aria-hidden="true">
    <g className="radar-grid">{[40, 80, 120, 144].map(r => <circle key={r} cx="160" cy="160" r={r} />)}
      <path d="M16 160h288M160 16v288M58 58l204 204M58 262 262 58" />
      {Array.from({ length: 36 }, (_, i) => <path key={i} transform={`rotate(${i * 10} 160 160)`} d={i % 3 === 0 ? 'M160 9v10' : 'M160 9v5'} />)}
    </g><g className="radar-sweep"><path d="M160 160V20A140 140 0 0 1 281 90Z" /><path className="sweep-edge" d="M160 160V20" /></g>
    <path className="radar-crosshair" d="M151 160h18M160 151v18" />
    <g className="radar-labels"><text x="160" y="35">000°</text><text x="280" y="155">090°</text><text x="160" y="293">180°</text><text x="40" y="155">270°</text></g>
  </svg><span className="scope-caption">DECORATIVE SCAN · NO POSITION DATA</span></div>;
}

export function RadarPanel({ snapshot }: { snapshot: Snapshot }) {
  const [selectedId, setSelectedId] = useState(snapshot.observations[0]?.observation_id ?? '');
  const selected = snapshot.observations.find(o => o.observation_id === selectedId);
  return <Card title="Tactical radar" className="visual-panel"><p className="boundary-label">SYNTHETIC DISPLAY — NON-GEOGRAPHIC</p><RadarGraphic />
    <div className="scope-legend"><span>Rings / azimuth: decorative</span><span>No observation markers</span></div>
    <h3>Non-spatial observations · {snapshot.observations.length}</h3>
    {snapshot.observations.length ? <ul className="hud-observations">{snapshot.observations.map(o => <li key={o.observation_id}><button aria-pressed={selectedId === o.observation_id} onClick={() => setSelectedId(o.observation_id)}><code>{o.observation_id}</code><Badge value={o.quality} /></button></li>)}</ul> : <Empty>No observations are supplied.</Empty>}
    {selected && <details key={selected.observation_id} open><summary>Selected observation metadata</summary><p>{selected.annotation}</p><dl><dt>Source</dt><dd>{selected.source_id}</dd><dt>Time</dt><dd><Time value={selected.timestamp} /></dd><dt>Uncertainty</dt><dd>{selected.uncertainty_note ?? 'No uncertainty note supplied'}</dd><dt>Review</dt><dd>{selected.review_status}</dd><dt>Evidence</dt><dd><code>{selected.evidence_id}</code></dd></dl></details>}
    <details><summary>Supplied sensor availability</summary>{snapshot.sentinels.length ? snapshot.sentinels.map(s => <ul key={s.device_id} className="compact-list">{s.sensors.map(sensor => <li key={sensor.source_id}>{sensor.source_id}: {sensor.status}</li>)}</ul>) : <p>Unknown — no Sentinel monitors supplied.</p>}</details>
  </Card>;
}

export function CameraPanel({ snapshot }: { snapshot: Snapshot }) {
  const cameras = snapshot.evidence.filter(e => e.kind === 'camera_recording');
  const [cameraId, setCameraId] = useState(cameras[0]?.evidence_id ?? '');
  const [fullscreenError, setFullscreenError] = useState('');
  const viewport = useRef<HTMLDivElement>(null);
  const evidence = cameras.find(e => e.evidence_id === cameraId);
  const device = snapshot.registry.devices.find(d => d.sources.some(s => s.source_id === evidence?.source_id));
  const monitor = snapshot.sentinels.find(s => s.device_id === device?.device_id);
  const availability = monitor?.sensors.find(s => s.source_id === evidence?.source_id)?.status ?? 'unknown';
  async function fullscreen() {
    try {
      if (!viewport.current?.requestFullscreen) { setFullscreenError('Fullscreen unavailable in this browser.'); return; }
      await viewport.current.requestFullscreen(); setFullscreenError('');
    } catch { setFullscreenError('Fullscreen unavailable or permission denied.'); }
  }
  return <Card title="Drone camera" className="visual-panel"><p className="boundary-label">RECORDED REFERENCE · METADATA ONLY</p>
    {cameras.length > 1 && <label>Camera evidence<select value={cameraId} onChange={e => setCameraId(e.target.value)}>{cameras.map(e => <option key={e.evidence_id} value={e.evidence_id}>{e.evidence_id}</option>)}</select></label>}
    <div ref={viewport} className="camera-viewport"><div className="camera-overlay"><span>{evidence?.source_id ?? 'Camera identifier unavailable'}</span><span>PLACEHOLDER</span></div><div className="camera-empty"><svg width="48" height="36" viewBox="0 0 48 36" aria-hidden="true"><path d="M3 7h28v22H3Z M31 14l13-7v22l-13-7 M8 32 39 2" /></svg><strong>NO VERIFIED CAMERA FEED</strong><small>No playable recording supplied</small></div><span className="viewport-caption">NO MEDIA LOADED · NO LIVE ACQUISITION</span></div>
    <div className="viewport-toolbar"><Badge value={availability} /><button onClick={() => { void fullscreen(); }}>Fullscreen placeholder</button></div>
    {fullscreenError && <p role="status">{fullscreenError}</p>}
    <dl><dt>Camera identifier</dt><dd>{evidence?.source_id ?? 'Not supplied'}</dd><dt>Device</dt><dd>{device?.device_id ?? 'Not supplied'}</dd><dt>Camera availability</dt><dd>{availability}</dd><dt>Playback status</dt><dd>Unavailable — metadata only</dd><dt>Recording timestamp</dt><dd>Not supplied</dd><dt>Evidence reference</dt><dd><code>{evidence?.evidence_id ?? 'Not supplied'}</code></dd><dt>Local reference metadata</dt><dd><code>{evidence?.local_path ?? 'Not supplied'}</code></dd></dl>
    <p className="note">Reference existence or checksum does not establish a verified camera feed. Files are never fetched.</p>
  </Card>;
}

export function SimulationPanel() {
  const [mode, setMode] = useState<'2D' | '3D'>('3D');
  const [view, setView] = useState<'front' | 'left' | 'right'>('front');
  return <Card title="3D simulation" className="visual-panel"><p className="boundary-label">SIMULATION PREVIEW — ILLUSTRATIVE</p>
    <div className={`simulation-viewport mode-${mode.toLowerCase()} view-${view}`} role="img" aria-label={`Abstract ${mode} environment, ${view} view; no device positions`}><div className="abstract-ridge ridge-back" /><div className="abstract-ridge" /><div className="perspective-grid" /><span className="viewport-caption">ABSTRACT ENVIRONMENT · NO WORLD STATE</span></div>
    <div className="viewport-toolbar" role="group" aria-label="Illustrative visual mode">{(['2D', '3D'] as const).map(m => <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>{m}</button>)}<button onClick={() => { setMode('3D'); setView('front'); }}>Reset view</button></div>
    <div className="viewport-toolbar" role="group" aria-label="Illustrative camera orientation">{(['left', 'front', 'right'] as const).map(v => <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>{label(v)} view</button>)}</div>
    <h3>Device-category legend</h3><ul className="category-legend"><li>◇ AEGIS native</li><li>□ Simulated</li><li>△ Third party</li></ul>
    <p className="note">Legend only; no devices are placed in this scene. View controls change decorative perspective, not a physical camera. No coordinates, trajectories, ranges or physics are supplied.</p>
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
