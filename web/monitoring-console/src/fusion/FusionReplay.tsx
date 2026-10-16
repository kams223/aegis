import { useMemo, useState } from 'react';
import type { Session } from '../models';
import { Badge, Card, Time, label } from '../components';
import replayText from '../data/fusion-replay.json?raw';
import { SensorFusionPanel } from './SensorFusionPanel';
import { loadMonitoringReplay, projectMonitoringReplay } from './replay';

export function FusionReplay({ session, text = replayText }: { session: Session; text?: string }) {
  const loaded = useMemo(() => {
    try { return { replay: loadMonitoringReplay(text, session), error: null }; }
    catch (error) { return { replay: null, error: error instanceof Error ? error.message : 'Replay unavailable' }; }
  }, [text, session]);
  return <FusionReplayView session={session} loaded={loaded} />;
}

function FusionReplayView({ session, loaded }: { session: Session; loaded: { replay: ReturnType<typeof loadMonitoringReplay> | null; error: string | null } }) {
  const [selection, setSelection] = useState({ replay: loaded.replay, frontier: session.event_results.length, mode: 'replay' });
  // Never project an old frontier into a replacement fixture, even before effects run.
  const current = selection.replay === loaded.replay ? selection : { replay: loaded.replay, frontier: session.event_results.length, mode: 'replay' };
  const { frontier, mode } = current;
  function setFrontier(value: number | ((old: number) => number)) { setSelection({ ...current, frontier: typeof value === 'function' ? value(frontier) : value }); }
  function setMode(value: string) { setSelection({ ...current, mode: value }); }
  const projection = useMemo(() => loaded.replay ? projectMonitoringReplay(loaded.replay, frontier) : null, [loaded.replay, frontier]);
  const event = projection?.event;
  const showingReplay = mode === 'replay' && projection !== null;
  return <>
    <Card title="Offline monitoring replay">
      <div className="fusion-replay-toolbar"><strong>OFFLINE · SYNTHETIC · READ ONLY</strong><label>Sensor Fusion state view<select value={mode} onChange={e => setMode(e.target.value)}><option value="replay">Recorded prefix state</option><option value="final">Original final snapshot</option></select></label></div>
      <p className="note">Recorded outputs of the existing monitoring reducer. Event order is supplied order, not synchronized time. Manual stepping only; highlights show selected-record references, not live sensor detections or fused tracks.</p>
      {loaded.error && <p role="alert">Replay unavailable: {loaded.error}. Only the original validated final snapshot is shown.</p>}
      {showingReplay && projection && <>
        <div className="fusion-replay-toolbar">
          <button type="button" disabled={frontier === 0} onClick={() => setFrontier(n => n - 1)}>Previous fusion event</button>
          <button type="button" disabled={frontier === session.event_results.length} onClick={() => setFrontier(n => n + 1)}>Next fusion event</button>
          <button type="button" onClick={() => setFrontier(0)}>Reset fusion replay</button>
          <label>Exact fusion frontier<select value={frontier} onChange={e => setFrontier(Number(e.target.value))}><option value={0}>Before first event</option>{session.event_results.map((item, index) => <option key={index} value={index + 1}>{index + 1}. {item.event_id} — {item.status}</option>)}</select></label>
        </div>
        <label className="fusion-replay-scrubber">Event frontier — supplied record order<input type="range" aria-label="Fusion event frontier" min={0} max={session.event_results.length} step={1} value={frontier} aria-valuetext={frontier === 0 ? 'Before first event' : `Event ${frontier} of ${session.event_results.length}`} onChange={e => setFrontier(Number(e.target.value))} /></label>
        <p role="status">{frontier === 0 ? 'Before first event — initial validated state' : `Event ${frontier} of ${session.event_results.length}`} · {projection.summary.applied_count} accepted · {projection.summary.rejected_count} rejected</p>
        <section key={frontier} className="fusion-event-inspector" aria-label="Selected fusion event">
          {event ? <><h3>{event.event_id} · <Badge value={event.status} /></h3><dl><dt>Original index</dt><dd>{event.event_index}</dd><dt>Record type</dt><dd>{label(event.event_type)}</dd><dt>Device reference</dt><dd>{event.device_id}{!projection.device && ' — unavailable in this state'}</dd><dt>Source reference</dt><dd>{event.source_id ?? 'Not supplied — device-level event'}{event.source_id && !projection.source && ' — unavailable in this state'}</dd><dt>Original timestamp</dt><dd><Time value={event.timestamp} /></dd><dt>Source clock</dt><dd>{projection.source?.clock_domain ?? 'No resolved source clock supplied'} · clocks not aligned</dd></dl>
            {event.status === 'rejected' ? <div className="diagnostic"><strong>Rejected — state unchanged; no source activity attributed</strong>{event.diagnostics.map((d, i) => <p key={i}><code>{d.code}</code>: {d.explanation} · {d.severity} · original index {d.event_index}</p>)}</div> : <p>Accepted record. {projection.source ? `Explicit source reference: ${projection.source.source_id}.` : 'Device-level record; no individual source activity inferred.'}</p>}
            <details><summary>Event evidence and provenance</summary><p>Only new or changed records in this accepted prefix are listed here; the graph retains all declared references.</p>
              <h4>Evidence added by this record</h4>{projection.evidence.length ? projection.evidence.map(e => <dl key={e.evidence_id}><dt>Evidence</dt><dd>{e.evidence_id}</dd><dt>Source</dt><dd>{e.source_id}</dd><dt>Kind</dt><dd>{e.kind}</dd><dt>Local path (not opened)</dt><dd>{e.local_path}</dd><dt>Dataset</dt><dd>{e.dataset_id ?? 'Not supplied'}</dd></dl>) : <p>No evidence addition supplied.</p>}
              <h4>Observations added or changed</h4>{projection.observations.length ? projection.observations.map(o => <dl key={o.observation_id}><dt>Observation</dt><dd>{o.observation_id}</dd><dt>Source</dt><dd>{o.source_id}</dd><dt>Evidence reference</dt><dd>{o.evidence_id}</dd><dt>Timestamp</dt><dd><Time value={o.timestamp} /></dd><dt>Quality</dt><dd>{o.quality}</dd><dt>Uncertainty</dt><dd>{o.uncertainty_note ?? 'Not supplied'}</dd><dt>Annotation</dt><dd>{o.annotation}</dd><dt>Review status</dt><dd>{o.review_status}</dd></dl>) : <p>No observation addition or change supplied.</p>}
              <h4>Review decisions</h4>{projection.reviews.length ? projection.reviews.map(r => <dl key={r.decision_id}><dt>Decision</dt><dd>{r.decision_id}</dd><dt>Subject</dt><dd>{r.subject_kind}: {r.subject_id}</dd><dt>Reviewer</dt><dd>{r.reviewer_id}</dd><dt>Transition</dt><dd>{r.previous_status} → {r.new_status}</dd><dt>Timestamp</dt><dd><Time value={r.timestamp} /></dd><dt>Note</dt><dd>{r.note}</dd></dl>) : <p>No review decision supplied.</p>}
              <h4>Audit entries</h4>{projection.audits.length ? projection.audits.map(a => <dl key={a.audit_id}><dt>Audit</dt><dd>{a.audit_id}</dd><dt>Actor</dt><dd>{a.actor_id}</dd><dt>Event</dt><dd>{a.event}</dd><dt>Reference</dt><dd>{a.reference_id}</dd><dt>Timestamp</dt><dd><Time value={a.timestamp} /></dd><dt>Note</dt><dd>{a.note}</dd></dl>) : <p>No audit entry supplied.</p>}
            </details></> : <p>No selected record. Initial snapshot declarations remain visible; no event activity is highlighted.</p>}
        </section>
      </>}
    </Card>
    <SensorFusionPanel snapshot={showingReplay ? projection.snapshot : session.final_snapshot} stateLabel={showingReplay ? `Validated prefix state · ${frontier} supplied events` : 'Final validated snapshot'} activity={showingReplay ? projection.activity : []} />
  </>;
}
