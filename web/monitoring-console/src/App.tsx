import { useMemo, useState } from 'react';
import fixtureText from './data/session.json?raw';
import { loadSession } from './validate';
import { Overview, Devices, Observations, Evidence, Alerts, EventReplay, Reviews } from './panels';
import { CameraPanel, SimulationPanel } from './hud';
import { Badge } from './components';
import { WorkspaceShell } from './layout/WorkspaceShell';
import { INITIAL_PAGE } from './layout/workspaces';
import type { PageId } from './layout/workspaces';
import { FlightOperations } from './flight/FlightOperations';
import { SensorFusionPanel } from './fusion/SensorFusionPanel';

export default function App({ text = fixtureText }: { text?: string }) {
  const [panel, setPanel] = useState<PageId>(INITIAL_PAGE);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayVisit, setReplayVisit] = useState(0);
  const [focusRequest, setFocusRequest] = useState(0);
  const loaded = useMemo(() => {
    try { return { session: loadSession(text), error: null }; }
    catch (error) { return { session: null, error: error instanceof Error ? error.message : 'Invalid offline fixture' }; }
  }, [text]);
  if (!loaded.session) return <main className="fixture-error"><span className="eyebrow">AEGIS · OFFLINE CONSOLE</span><h1>Fixture unavailable</h1><div role="alert"><p>The offline fixture could not be validated. No monitoring data is shown.</p><code>{loaded.error}</code></div></main>;
  const session = loaded.session;
  const snapshot = session.final_snapshot;
  function navigate(page: PageId) {
    if (page === 'Event replay') { setReplayIndex(0); setReplayVisit(n => n + 1); }
    setPanel(page);
  }
  function openEvent(index: number) {
    setReplayIndex(index); setReplayVisit(n => n + 1); setPanel('Event replay'); setFocusRequest(n => n + 1);
  }
  const content = panel === 'Overview' ? <Overview session={session} onEventSelect={openEvent} />
    : panel === 'Devices' ? <Devices snapshot={snapshot} />
    : panel === 'Observations' ? <Observations snapshot={snapshot} />
    : panel === 'Sensor Fusion' ? <SensorFusionPanel snapshot={snapshot} />
    : panel === 'Evidence' ? <><CameraPanel snapshot={snapshot} /><Evidence snapshot={snapshot} /></>
    : panel === 'Simulation' ? <SimulationPanel />
    : panel === 'Flight Operations' ? <FlightOperations />
    : panel === 'Alerts & Copilot' ? <Alerts snapshot={snapshot} />
    : panel === 'Event replay' ? <EventReplay key={`${session.initial_snapshot_id}:${replayVisit}`} session={session} initialIndex={replayIndex} />
    : <Reviews snapshot={snapshot} />;
  return <WorkspaceShell page={panel} onNavigate={navigate} focusRequest={focusRequest} fixtureId={snapshot.snapshot_id}
    fixtureMetadata={<div className="system-telemetry" aria-label="Monitoring fixture summary"><span>SESSION REF <code>{session.initial_snapshot_id}</code></span><span>SNAPSHOT v{snapshot.schema_version}</span><span>DEVICES {snapshot.registry.devices.length}</span><span>MONITORING <Badge value={session.summary.status} /></span></div>}>
    {content}
  </WorkspaceShell>;
}
