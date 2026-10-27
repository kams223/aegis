import { useMemo, useState } from 'react';
import { buildReplay, inspectReplay } from './replay';
import type { Inspection, Timestamp } from './model';

export function SharedReplay({doc, evaluation, threshold}: {doc: Inspection; evaluation: Timestamp; threshold: string}) {
  const history = useMemo(() => buildReplay([doc]), [doc]);
  const result = useMemo(() => inspectReplay(history, evaluation, threshold), [history, evaluation.value_ns, evaluation.domain, threshold]);
  const [cursor, setCursor] = useState(0);
  const entry = history.timeline[Math.min(cursor, history.timeline.length - 1)];
  return <section aria-label="Shared multi-sensor replay"><h2>Shared multi-sensor replay</h2>
    <p>Acquisition-ordered inspection, not simultaneous samples or sensor fusion. Evaluation uses the controls above. Known delivery must be at or before evaluation; unknown delivery remains unavailable.</p>
    <label>Shared replay timeline<input type="range" min="0" max={Math.max(0, history.timeline.length - 1)} value={Math.min(cursor, Math.max(0, history.timeline.length - 1))} disabled={!entry} onChange={e => setCursor(Number(e.target.value))}
      aria-valuetext={entry ? `${entry.record.observation_type}, ${entry.record.origin}, acquisition ${entry.record.acquisition.value_ns} ns, delivery ${entry.available_ns ?? 'unknown'}` : 'No observations'} /></label>
    {entry && <p>Timeline entry {Math.min(cursor, history.timeline.length - 1) + 1} / {history.timeline.length}: {entry.record.observation_type} · {entry.record.origin} · acquired {entry.record.acquisition.value_ns} ns · delivery {entry.available_ns ?? 'unknown'} · {history.domain}. History cursor does not change evaluation or establish availability.</p>}
    <div className="sensor-chart-grid">{result.sensors.map(s => <article key={s.sensor} aria-label={`${s.sensor} selected-time inspection`}><h3>{s.sensor}</h3>
      <p role="status">Selected-time status: {s.status}</p>
      {!s.channels.length && <p>No accepted history.</p>}
      {s.channels.map(c => {const provenance = history.timeline[c.history_index]!.record; const latest = c.timeline_index === null ? null : history.timeline[c.timeline_index]!.record;
        return <div key={c.history_index}><p>{provenance.origin} · {provenance.source.session_id} · {provenance.source.source_id}</p>
          <p>{c.status} · age {c.age_ns ?? 'unavailable'} ns · acquired {latest?.acquisition.value_ns ?? 'unavailable'} · delivered {latest?.delivery?.value_ns ?? 'unavailable'} · {history.domain}</p>
          {latest?.values ? <dl>{latest.values.map(f => <div key={f.name}><dt>{f.name}</dt><dd>{f.value} {f.unit}</dd></div>)}</dl> : <p>No eligible measurement. Missing values are not zero.</p>}
          <details><summary>Replay channel provenance</summary><pre>{JSON.stringify({source: provenance.source, source_sha256: provenance.source_sha256, origin: provenance.origin, config_sha256: provenance.config_sha256, seed_identifier: provenance.seed_identifier}, null, 2)}</pre></details>
        </div>;})}</article>)}</div>
    <details><summary>Replay diagnostics ({result.diagnostics.length}; omitted {result.diagnostics_dropped})</summary><ul>{result.diagnostics.map((d, i) => <li key={i}>{d.code} · {d.evidence} · {d.sensor ?? 'dataset'} · {d.detail}</li>)}</ul></details>
  </section>;
}
