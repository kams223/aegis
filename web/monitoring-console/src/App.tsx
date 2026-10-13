import { useMemo, useState } from 'react';
import fixtureText from './data/session.json?raw';
import { loadSession } from './validate';
import { Overview, Devices, Observations, Evidence, Alerts, EventReplay, Reviews } from './panels';
import { CameraPanel, SimulationPanel } from './hud';
import { Badge } from './components';
import { SensorFusionPanel } from './fusion/SensorFusionPanel';

const panels = [
  ['Overview', 'Overview'], ['Devices', 'Devices'], ['Observations', 'Radar / Observations'],
  ['Sensor Fusion', 'SENSOR FUSION'], ['Evidence', 'Camera / Evidence'], ['Simulation', 'Simulation'], ['Alerts & Copilot', 'Alerts & Copilot'],
  ['Event replay', 'Event Replay'], ['Review & audit', 'Review & Audit'],
] as const;
type Panel = typeof panels[number][0];

export default function App({ text = fixtureText }: { text?: string }) {
  const [panel, setPanel] = useState<Panel>('Overview');
  const [replayIndex, setReplayIndex] = useState(0);
  const loaded = useMemo(() => {
    try { return { session: loadSession(text), error: null }; }
    catch (error) { return { session: null, error: error instanceof Error ? error.message : 'Invalid offline fixture' }; }
  }, [text]);
  if (!loaded.session) return <main className="fixture-error"><span className="eyebrow">AEGIS · OFFLINE CONSOLE</span><h1>Fixture unavailable</h1><div role="alert"><p>The offline fixture could not be validated. No monitoring data is shown.</p><code>{loaded.error}</code></div></main>;
  const session = loaded.session;
  const snapshot = session.final_snapshot;
  function openEvent(index: number) { setReplayIndex(index); setPanel('Event replay'); }
  const content = panel === 'Overview' ? <Overview session={session} onEventSelect={openEvent} />
    : panel === 'Devices' ? <Devices snapshot={snapshot} />
    : panel === 'Observations' ? <Observations snapshot={snapshot} />
    : panel === 'Sensor Fusion' ? <SensorFusionPanel snapshot={snapshot} />
    : panel === 'Evidence' ? <><CameraPanel snapshot={snapshot} /><Evidence snapshot={snapshot} /></>
    : panel === 'Simulation' ? <SimulationPanel />
    : panel === 'Alerts & Copilot' ? <Alerts snapshot={snapshot} />
    : panel === 'Event replay' ? <EventReplay key={`${session.initial_snapshot_id}:${replayIndex}`} session={session} initialIndex={replayIndex} />
    : <Reviews snapshot={snapshot} />;
  return <div className="console">
    <a className="skip-link" href="#main-content">Skip to monitoring content</a>
    <aside className="sidebar">
      <div className="brand"><svg width="34" height="38" aria-hidden="true" viewBox="0 0 32 36"><path d="M16 2 29 7v13L16 34 3 20V7Z" /><path d="m9 22 7-13 7 13M12 17h8" /></svg><div><strong>AEGIS</strong><small>MONITORING CONSOLE</small></div></div>
      <span className="nav-caption">OFFLINE WORKSPACE</span>
      <nav aria-label="Console navigation">{panels.map(([name, title], i) => <button key={name} aria-label={name} aria-current={panel === name ? 'page' : undefined} onClick={() => { if (name === 'Event replay') setReplayIndex(0); setPanel(name); }}><span className="nav-number" aria-hidden="true">{(i + 1).toString().padStart(2, '0')}</span>{title}</button>)}</nav>
      <div className="sidebar-footer"><span className="offline-dot" aria-hidden="true" /><strong>Offline workspace</strong><small>Read-only synthetic fixture<br />Platform schema v{snapshot.schema_version}</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><span className="simulation">SIMULATION</span><div className="system-telemetry"><span>SESSION REF <code>{session.initial_snapshot_id}</code></span><span>SNAPSHOT v{snapshot.schema_version}</span><span>DEVICES {snapshot.registry.devices.length}</span><span>MONITORING <Badge value={session.summary.status} /></span></div><span className="read-only">READ ONLY</span></header>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><span className="eyebrow">AEGIS / TACTICAL HUD / OFFLINE</span><h1>{panel === 'Overview' ? 'Monitoring overview' : panel}</h1><p>Inspect supplied software evidence and final simulation state.</p></div><div className="snapshot-label"><span>FINAL SNAPSHOT</span><code>{snapshot.snapshot_id}</code></div></div>
        {content}
        <footer className="workspace-footer">AEGIS · Local inspection only<span>Final snapshot v{snapshot.schema_version} · No live hardware integration</span></footer>
      </main>
    </div>
  </div>;
}
