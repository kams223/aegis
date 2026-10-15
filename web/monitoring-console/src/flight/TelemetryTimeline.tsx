import { useId, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Stamp, TelemetrySnapshot } from './telemetry';
import { projectTelemetryTimeline } from './telemetryTimeline';

export function TelemetryTimeline({ snapshot, children }: {
  snapshot: TelemetrySnapshot;
  children: (projected: TelemetrySnapshot) => ReactNode;
}) {
  const [frontier, setFrontier] = useState(snapshot.replay.records.length);
  const [evaluation, setEvaluation] = useState(snapshot.replay.evaluation_timestamp.value);
  const id = useId();
  const result = useMemo(() => {
    try {
      if (!/^(0|[1-9][0-9]{0,19})$/.test(evaluation) || BigInt(evaluation) > 18446744073709551615n) {
        throw new Error('Evaluation timestamp must be an unsigned decimal integer from 0 through 18446744073709551615, without leading zeros.');
      }
      return { projection: projectTelemetryTimeline(snapshot, frontier, { ...snapshot.replay.evaluation_timestamp, value: evaluation }), error: null };
    } catch (error) { return { projection: null, error: error instanceof Error ? error.message : 'Unable to project telemetry' }; }
  }, [snapshot, frontier, evaluation]);
  const count = snapshot.replay.records.length, selected = result.projection?.selected;
  return <section className="telemetry-timeline" aria-label="Offline telemetry timeline">
    <h3>Offline telemetry timeline</h3>

    <div className="timeline-controls">
      <label className="frontier-scrubber">Record frontier, not time<input type="range" min="0" max={count} step="1" value={frontier} disabled={count === 0} aria-valuetext={frontier === 0 ? `Before first record, 0 of ${count}` : `Record ${frontier} of ${count}`} onChange={event => setFrontier(Number(event.target.value))} /></label>
      <label>Record frontier<select value={frontier} onChange={event => setFrontier(Number(event.target.value))}>
        {Array.from({ length: count + 1 }, (_, index) => <option key={index} value={index}>{index === 0 ? '0 — Before first record' : `${index} — ${snapshot.replay.records[index - 1]!.record_id}`}</option>)}
      </select></label>
      <button disabled={frontier === 0} onClick={() => setFrontier(value => value - 1)}>Previous record</button>
      <button disabled={frontier === count} onClick={() => setFrontier(value => value + 1)}>Next record</button>
    </div>
    <p role="status">Record {frontier} of {count}{frontier === 0 ? ' — Before first record; no record selected.' : ''}</p>
    <div className="timeline-evaluation"><label htmlFor={`${id}-evaluation`}>Evaluation timestamp (ms)</label>
    <input id={`${id}-evaluation`} type="text" inputMode="numeric" value={evaluation} aria-invalid={result.error !== null} aria-describedby={`${id}-clock${result.error ? ` ${id}-error` : ''}`} onChange={event => setEvaluation(event.target.value)} />
    <p id={`${id}-clock`}>Receipt clock: {snapshot.replay.evaluation_timestamp.clock_domain}. Lossless unsigned decimal milliseconds.</p></div>
    {result.error && <p id={`${id}-error`} role="alert">{result.error} No projected telemetry shown.</p>}
    {result.projection && <>
      {selected && <section aria-label="Selected timeline record" className="timeline-record">
        <h4>Selected record: {selected.record.record_id}</h4>
        <p><strong>{selected.status.toUpperCase()}</strong> at this frontier and evaluation timestamp.{selected.status === 'rejected' ? ' This rejected record did not update telemetry values or refresh their timestamps.' : ''}</p>
        {selected.diagnostic && <p className="rejection-explanation"><code>{selected.diagnostic.code}</code> · {rejectionExplanation(selected.diagnostic.code)}</p>}
        <details><summary>Inspect selected record</summary><dl><dt>Original record index (zero-based)</dt><dd>{selected.record_index}</dd>
          <dt>Vehicle / autopilot / environment</dt><dd>{selected.record.vehicle_id} / {selected.record.autopilot_family} / {selected.record.environment}</dd>
          <dt>Source/session</dt><dd>{selected.record.source_id}/{selected.record.session_id}</dd>
          <dt>System/component</dt><dd>{selected.record.system_id}/{selected.record.component_id}</dd>
          <dt>Record type</dt><dd>{selected.record.field}</dd>
          <dt>Applicable replay diagnostic</dt><dd>{selected.diagnostic?.code ?? 'None — accepted'}</dd>
          <dt>Supplied diagnostic codes</dt><dd>{selected.record.diagnostic_codes.join(', ') || 'None supplied'}</dd>
          <dt>Provenance kind</dt><dd>{selected.record.provenance.kind}</dd>
          <dt>Provenance reference</dt><dd>{selected.record.provenance.record_reference}</dd>
          <dt>Provenance note</dt><dd>{selected.record.provenance.note}</dd>
          <dt>Source timestamp</dt><dd>{formatStamp(selected.record.source_timestamp)}</dd>
          <dt>Receipt timestamp</dt><dd>{formatStamp(selected.record.receipt_timestamp)}</dd>
        </dl></details>
      </section>}
      <h3>Projected telemetry state</h3>
      <p>Prefix validation: {result.projection.snapshot.summary.validation} · Accepted {result.projection.snapshot.summary.accepted_count} · Rejected {result.projection.snapshot.summary.rejected_count}</p>

      {children(result.projection.snapshot)}
    </>}
  </section>;
}

function formatStamp(stamp: Stamp | null): string { return stamp ? `${stamp.value} ${stamp.unit} · ${stamp.clock_domain}` : 'Not supplied'; }

function rejectionExplanation(code: string): string {
  const explanations: Record<string, string> = {
    UNKNOWN_SOURCE_SESSION: 'Source/session/system/component is not configured.',
    IDENTITY_CONFLICT: 'Record identity differs from the configured source identity.',
    INVALID_RECORD: 'The supplied record is marked invalid.',
    CLOCK_DOMAIN_MISMATCH: 'A supplied timestamp uses a different clock domain from its configured source.',
    RECEIPT_AFTER_EVALUATION: 'Receipt timestamp is later than the selected evaluation timestamp.',
    TIMESTAMP_REGRESSION: 'Receipt or source time precedes a previously accepted timestamp for this identity.',
    UNSUPPORTED_RECEPTION_DECLARATION: 'Reception declaration is unsupported; this can mark reception unsupported while retaining earlier accepted values.',
    ALTITUDE_REFERENCE_UNAVAILABLE: 'Altitude reference is unknown or its reference identifier is missing.',
    VALUE_OUT_OF_RANGE: 'Battery percentage is outside 0–100 or ground speed is negative.',
  };
  return explanations[code] ?? 'Replay rejected this record; inspect its supplied diagnostic and evidence.';
}
