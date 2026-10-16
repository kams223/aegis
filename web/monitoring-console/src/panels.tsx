import { useRef, useState } from 'react';
import type { Session, Snapshot } from './models';
import { Badge, Card, Empty, Metric, MetricGroup, Time, label } from './components';
import { ObservationInspector } from './observation/ObservationInspector';
import { SensorDiagnostics } from './fusion/SensorFusionPanel';
import { RadarGraphic, RadarPanel, CameraPanel, SimulationPanel, DeviceStatus, RecentEvents, AlertSummary } from './hud';

export function Overview({ session, onEventSelect }: { session: Session; onEventSelect: (index: number) => void }) {
  const snapshot = session.final_snapshot;
  return <section className="command-dashboard" aria-label="Command Center dashboard">
    <MetricGroup>
      <Metric title="Devices" value={snapshot.registry.devices.length} detail="Declared registry entries" />
      <Metric title="Applied events" value={session.summary.applied_count} detail="Accepted software updates" />
      <Metric title="Rejected events" value={session.summary.rejected_count} detail="Explicit validation diagnostics" tone="warning" />
      <Metric title="Observations" value={snapshot.observations.length} detail="Synthetic display metadata" />
      <Metric title="Alerts" value={snapshot.alerts.length} detail="Descriptive observations" />
      <Metric title="Reviews" value={snapshot.review_history.length} detail="Existing human decisions" />
    </MetricGroup>
    <div className="session-strip"><span>{session.summary.event_count} supplied events processed in their declared order.</span><span>Intermediate snapshots are not supplied. All device and observation panels show the final state.</span></div>
    <div className="dashboard-bottom"><DeviceStatus snapshot={snapshot} /><RecentEvents session={session} onSelect={onEventSelect} /><AlertSummary snapshot={snapshot} /></div>
    <div className="visual-grid"><RadarPanel snapshot={snapshot} /><CameraPanel snapshot={snapshot} /><SimulationPanel /></div>
    <SensorDiagnostics snapshot={snapshot} />
    <p className="note data-boundary">{snapshot.description}</p>
  </section>;
}

export function Devices({ snapshot }: { snapshot: Snapshot }) {
  const [category, setCategory] = useState('all'); const [connection, setConnection] = useState('all');
  const devices = snapshot.registry.devices.filter(d => (category === 'all' || d.category === category) && (connection === 'all' || d.connection_status === connection));
  return <Card title="Device registry">
    <div className="filters"><label>Device category<select value={category} onChange={e => setCategory(e.target.value)}><option value="all">All categories</option><option value="aegis_native">AEGIS native</option><option value="simulated">Simulated</option><option value="third_party">Third party</option></select></label><label>Connection state<select value={connection} onChange={e => setConnection(e.target.value)}><option value="all">All states</option><option value="offline">Offline</option><option value="recorded">Recorded</option><option value="unknown">Unknown</option></select></label></div>
    {devices.length ? <div className="table-scroll" tabIndex={0} aria-label="Device registry table"><table><caption>Final snapshot device declarations</caption><thead><tr><th scope="col">Device</th><th scope="col">Adapter</th><th scope="col">Connection</th><th scope="col">Health</th><th scope="col">Sentinel / sensors</th></tr></thead><tbody>{devices.map(device => {
      const sentinel = snapshot.sentinels.find(s => s.device_id === device.device_id);
      return <tr key={device.device_id}><td><strong>{device.device_id}</strong><small>{label(device.category)} · {device.device_type}</small></td><td><code>{device.adapter.adapter_id}</code><small>Version {device.adapter.version}</small></td><td><Badge value={device.connection_status} /></td><td><Badge value={device.health.status} /><small>{device.health.note}</small><Time value={device.health.timestamp} /></td><td>{sentinel ? <><strong>{sentinel.sentinel_category} Sentinel</strong><small>Battery: {sentinel.battery_percent === null ? 'Unknown' : `${sentinel.battery_percent}%`} · Maintenance: {sentinel.maintenance_status}</small><ul className="compact-list">{sentinel.sensors.map(s => <li key={s.source_id}><code>{s.source_id}</code>: {s.status}</li>)}</ul></> : <span>Unknown sensor availability — no Sentinel monitor supplied</span>}<details><summary>Declared capabilities</summary><ul className="compact-list">{device.capabilities.map(c => <li key={c.name}>{label(c.name)}: {c.support}</li>)}</ul></details></td></tr>;
    })}</tbody></table></div> : <Empty>No devices match these filters.</Empty>}
  </Card>;
}

export function Observations({ snapshot }: { snapshot: Snapshot }) {
  const [selectedId, setSelectedId] = useState(snapshot.observations[0]?.observation_id ?? '');
  const trigger = useRef<HTMLButtonElement | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const selected = snapshot.observations.find(o => o.observation_id === selectedId);
  return <Card title="Synthetic observation display" className="observation-display"><RadarGraphic>
    <p className="note">Non-geographic list. Validated observations have no plotted positions; optional fictional markers are separate.</p>
    <div className="radar-inspection-layout"><div>{snapshot.observations.length ? <ul className="observation-list">{snapshot.observations.map(o => <li key={o.observation_id}><button ref={element => { if (element && selectedId === o.observation_id) trigger.current = element; }} aria-pressed={o.observation_id === selectedId} onClick={event => { trigger.current = event.currentTarget; setFocusRequest(n => n + 1); setSelectedId(o.observation_id); }}><div><strong>{o.observation_id}</strong><small>{o.source_id} · {o.category}</small></div><Badge value={o.quality} /></button></li>)}</ul> : <Empty>No observations are supplied.</Empty>}</div>
    {selected ? <ObservationInspector observation={selected} snapshot={snapshot} focusRequest={focusRequest} onClose={() => { setSelectedId(''); trigger.current?.focus(); }} /> : <Empty>Select an observation to inspect its supplied metadata.</Empty>}</div>
  </RadarGraphic></Card>;
}

export function Evidence({ snapshot }: { snapshot: Snapshot }) {
  return <Card title="Evidence reference inventory"><p className="note">Metadata only. Recording paths are plain text; this console does not retrieve or decode files.</p>
    {snapshot.evidence.length ? <div className="table-scroll" tabIndex={0} aria-label="Evidence metadata table"><table><caption>Declared local evidence references</caption><thead><tr><th scope="col">Evidence</th><th scope="col">Source / type</th><th scope="col">Local reference metadata</th><th scope="col">Related observations</th><th scope="col">Supplied validation</th></tr></thead><tbody>{snapshot.evidence.map(e => { const outcome = snapshot.validation_results.find(v => v.evidence_id === e.evidence_id); return <tr key={e.evidence_id}><td><code>{e.evidence_id}</code></td><td>{e.source_id}<small>{label(e.kind)}</small></td><td><code>{e.local_path}</code><small>Dataset: {e.dataset_id ?? 'Not supplied'}</small></td><td>{snapshot.observations.filter(o => o.evidence_id === e.evidence_id).map(o => o.observation_id).join(', ') || 'None supplied'}</td><td>{outcome ? <>Metadata: <Badge value={outcome.metadata_status} /><small>Integrity: {outcome.integrity_status}</small></> : 'Not supplied — media unverified by this console'}</td></tr>; })}</tbody></table></div> : <Empty>No evidence references are supplied.</Empty>}
  </Card>;
}

export function Alerts({ snapshot }: { snapshot: Snapshot }) {
  return <div className="overview-grid"><Card title="Descriptive alerts">{snapshot.alerts.length ? snapshot.alerts.map(a => <article className="record" key={a.alert_id}><Badge value={a.status} /><h3>{a.alert_id}</h3><p>{a.explanation.explanation}</p><small>Observation: {a.observation_id} · Code: {a.explanation.code}</small><p><code>{a.explanation.evidence_ids.join(', ')}</code></p></article>) : <Empty>No alerts are supplied.</Empty>}</Card><Card title="Copilot · read-only investigation history"><p className="note">Existing deterministic results only. Investigation execution and chat are unavailable.</p>{snapshot.investigation_requests.length ? snapshot.investigation_requests.map(request => { const result = snapshot.investigation_results.find(r => r.request_id === request.request_id); return <article className="record" key={request.request_id}><Badge value={result?.status ?? 'not_evaluated'} /><h3>{request.request_id}</h3><small>{label(request.action)} · Alert: {request.alert_id}</small><p>References: <code>{request.reference_ids.join(', ')}</code></p><p>{result?.summary ?? 'No investigation result supplied'}</p><small>Evidence: {result?.evidence_ids.join(', ') || 'Not supplied'}</small></article>; }) : <Empty>No investigation requests are supplied.</Empty>}</Card></div>;
}

export function EventReplay({ session, initialIndex = 0 }: { session: Session; initialIndex?: number }) {
  const [index, setIndex] = useState(Math.max(0, Math.min(initialIndex, session.event_results.length - 1))); const events = session.event_results; const event = events[index];
  return <Card title="Ordered event replay"><p className="note">Navigate supplied event results locally. The final snapshot stays fixed; intermediate states are not provided.</p>
    {event ? <><div className="replay-controls"><button disabled={index === 0} onClick={() => setIndex(i => Math.max(0, i - 1))}>← Previous event</button><label>Jump to event<select value={index} onChange={e => setIndex(Number(e.target.value))}>{events.map((e, i) => <option key={i} value={i}>{i + 1}. {e.event_id} ({e.status})</option>)}</select></label><button disabled={index === events.length - 1} onClick={() => setIndex(i => Math.min(events.length - 1, i + 1))}>Next event →</button></div><div className="replay-position" role="status">Event {index + 1} of {events.length} · <strong>{event.event_id}</strong></div><Badge value={event.status} /><dl><dt>Event type</dt><dd>{label(event.event_type)}</dd><dt>Device</dt><dd><code>{event.device_id}</code></dd><dt>Source</dt><dd>{event.source_id ?? 'Device-level event; no source reference'}</dd><dt>Explicit timestamp</dt><dd><Time value={event.timestamp} /></dd><dt>Stable event index</dt><dd>{event.event_index}</dd></dl><h3>Rejection diagnostics</h3>{event.diagnostics.length ? event.diagnostics.map(d => <article className="diagnostic" key={d.code}><strong>{d.code}</strong><p>{d.explanation}</p><small>Severity: {d.severity} · Event index: {d.event_index}</small></article>) : <p>No rejection diagnostics supplied.</p>}</> : <Empty>No event results are supplied.</Empty>}
  </Card>;
}

export function Reviews({ snapshot }: { snapshot: Snapshot }) {
  return <div className="overview-grid"><Card title="Human interpretation review"><p className="note">Existing decisions only. Human review concerns interpretation of observations and provides no engagement authorization.</p>{snapshot.review_history.length ? snapshot.review_history.map(r => <article className="record" key={r.decision_id}><h3>{r.decision_id}</h3><p><Badge value={r.previous_status} /> → <Badge value={r.new_status} /></p><dl><dt>Subject</dt><dd>{r.subject_kind}: <code>{r.subject_id}</code></dd><dt>Reviewer</dt><dd>{r.reviewer_id}</dd><dt>Declared time</dt><dd><Time value={r.timestamp} /></dd></dl><p>{r.note}</p></article>) : <Empty>No review decisions are supplied.</Empty>}</Card><Card title="Audit records">{snapshot.audit_entries.length ? snapshot.audit_entries.map(a => <article className="record" key={a.audit_id}><span className="eyebrow">{label(a.event)}</span><h3>{a.audit_id}</h3><p>{a.note}</p><small>Actor: {a.actor_id} · Reference: {a.reference_id}</small><Time value={a.timestamp} /></article>) : <Empty>No audit records are supplied.</Empty>}</Card></div>;
}
