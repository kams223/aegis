import { useState } from 'react';
import { Card } from '../components';
import { RecordedPlayer } from '../camera/RecordedPlayer';
import { DEMO_VEHICLES } from './demo';
import type { Availability, VehiclePresentation } from './models';

export function displayValue(value: Availability<string | number>, unit = ''): string {
  return value.state === 'supplied' ? `${value.value}${unit ? ` ${unit}` : ''}` : `Unavailable — ${value.reason}`;
}
const connectionLabel = (vehicle: VehiclePresentation) => vehicle.connection === 'offline_demo' ? 'OFFLINE DEMO · NO VEHICLE LINK' : vehicle.connection === 'not_connected' ? 'NOT CONNECTED' : 'UNKNOWN · CONNECTION NOT ESTABLISHED';

export function FlightOperations() {
  const [selectedId, setSelectedId] = useState(DEMO_VEHICLES[0]!.vehicleId);
  const selected = DEMO_VEHICLES.find(v => v.vehicleId === selectedId)!;
  const telemetry = selected.telemetry;
  return <div className="flight-workspace">
    <div className="inspection-banner"><strong>SYNTHETIC DEMONSTRATION RECORDS · READ ONLY</strong><p>All entries are fictional interface slots, including those labeled REAL or SITL. No real vehicle or simulator is connected. These records are separate from the validated monitoring snapshot and do not change its metrics or observations.</p></div>
    <Card title="Vehicle overview"><label className="flight-selection">Selected flight vehicle<select value={selectedId} onChange={event => { if (DEMO_VEHICLES.some(v => v.vehicleId === event.target.value)) setSelectedId(event.target.value); }}>{DEMO_VEHICLES.map(v => <option key={v.vehicleId} value={v.vehicleId}>{v.vehicleId} · {v.platform} · {v.environment} · DEMO SLOT</option>)}</select></label>
      <section className="flight-selected" aria-label="Selected vehicle details" aria-live="polite"><h3>{selected.label}</h3><span className="flight-environment" data-environment={selected.environment}>{selected.environment} · DEMO SLOT</span>
      <dl><dt>Vehicle identifier</dt><dd><code>{selected.vehicleId}</code></dd><dt>Platform label</dt><dd>{selected.platform}</dd><dt>Environment category</dt><dd>{selected.environment}</dd><dt>Connection</dt><dd>{connectionLabel(selected)}</dd><dt>Last update</dt><dd>{displayValue(selected.lastUpdate)}</dd><dt>Source provenance</dt><dd>SYNTHETIC DEMO · {selected.provenance.reference}</dd></dl><p className="note">{selected.provenance.note}</p></section>
    </Card>
    <div className="flight-main-grid"><Card title="Vehicle camera" className="flight-camera"><p className="boundary-label">PLACEHOLDER · NO LIVE FEED</p><dl><dt>Selected vehicle</dt><dd><code>{selected.vehicleId}</code></dd><dt>Camera identifier</dt><dd>{selected.camera.cameraId ?? 'Not supplied'}</dd><dt>Feed availability</dt><dd>{selected.camera.availability}</dd></dl>
      <RecordedPlayer key={selected.vehicleId} recordingId={null} /><p className="note">{selected.camera.note} Vehicle labels and camera metadata never resolve to media URLs. Only the existing approved bundled-media catalog can supply playback.</p>
    </Card><Card title="Flight telemetry"><p className="boundary-label">DEMO SLOT · NO MEASUREMENTS SUPPLIED</p><p className="note">Missing values are not zero readings. No physical position, readiness or health is inferred.</p><dl className="flight-telemetry" aria-label="Selected vehicle telemetry"><dt>Altitude</dt><dd>{displayValue(telemetry.altitude, telemetry.altitudeUnit)}</dd><dt>Ground speed</dt><dd>{displayValue(telemetry.groundSpeed, telemetry.groundSpeedUnit)}</dd><dt>Battery</dt><dd>{displayValue(telemetry.battery, telemetry.batteryUnit)}</dd><dt>Flight mode</dt><dd>{displayValue(telemetry.flightMode)}</dd><dt>Link health</dt><dd>{displayValue(telemetry.linkHealth)}</dd></dl></Card></div>
    <Card title="Fleet overview"><p className="note">Independent fictional records. Selecting a card changes inspection only; no fleet commands or coordination occur.</p><div className="flight-fleet" aria-label="Demonstration vehicle fleet">{DEMO_VEHICLES.map(v => <article key={v.vehicleId}><span className="flight-environment" data-environment={v.environment}>{v.environment} · DEMO SLOT</span><h3>{v.vehicleId}</h3><p>{v.platform} · {connectionLabel(v)}</p><small>{displayValue(v.lastUpdate)}</small><small>Camera: {v.camera.cameraId ?? 'Not supplied'} · {v.camera.availability}</small><button aria-pressed={selectedId === v.vehicleId} aria-label={`Inspect flight vehicle ${v.vehicleId}`} onClick={() => setSelectedId(v.vehicleId)}>Inspect vehicle</button></article>)}</div></Card>
    <Card title="Operator safety"><strong className="analyst-mode">READ ONLY · NO ACTIVE CONTROL LINK · NO COMMAND CAPABILITY</strong><p>Vehicle and camera selection are local inspection actions. No autopilot transport, vehicle connection, flight commands, mission upload, joystick control or fleet control is implemented.</p><p className="note">Future integrations would require explicit operator permissions and safety interlocks. No such integration is active in this phase.</p></Card>
  </div>;
}
