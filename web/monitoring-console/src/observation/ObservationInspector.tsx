import { useEffect, useRef } from 'react';
import type { Observation, Snapshot } from '../models';
import { Time } from '../components';

// Projection only: preserve supplied references; never join demo marker positions.
export function ObservationInspector({ observation, snapshot, onClose, focusRequest = 0 }: { observation: Observation; snapshot: Snapshot; onClose: () => void; focusRequest?: number }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (focusRequest > 0) heading.current?.focus(); }, [observation.observation_id, focusRequest]);
  const device = snapshot.registry.devices.find(d => d.sources.some(s => s.source_id === observation.source_id));
  const source = device?.sources.find(s => s.source_id === observation.source_id);
  const evidence = snapshot.evidence.find(e => e.evidence_id === observation.evidence_id);
  const outcome = snapshot.validation_results.find(v => v.evidence_id === observation.evidence_id);
  return <section className="observation-inspector" aria-label="Validated observation inspector">
    <div className="inspector-heading"><span className="eyebrow">VALIDATED SNAPSHOT RECORD · READ ONLY</span><button onClick={onClose}>Close observation inspector</button></div>
    <h3 ref={heading} tabIndex={-1}>{observation.observation_id}</h3>
    <p className="note">Validated refers to the software contract, not physical accuracy or authenticity. Separate from fictional demo markers.</p>
    <p>{observation.annotation || 'Not supplied'}</p>
    <dl><dt>Observation ID</dt><dd><code>{observation.observation_id}</code></dd><dt>Category</dt><dd>{observation.category}</dd><dt>Source</dt><dd><code>{observation.source_id}</code></dd><dt>Declared device</dt><dd>{device?.device_id ?? 'Not supplied'}</dd><dt>Source clock domain</dt><dd>{source ? `Declared source clock: ${source.clock_domain}` : 'Not supplied'}</dd><dt>Explicit timestamp</dt><dd><Time value={observation.timestamp} /></dd><dt>Quality</dt><dd>{observation.quality}</dd><dt>Uncertainty</dt><dd>{observation.uncertainty_note ?? 'Not supplied'}</dd><dt>Review status</dt><dd>{observation.review_status}</dd><dt>Evidence reference</dt><dd><code>{observation.evidence_id}</code></dd><dt>Evidence source</dt><dd>{evidence?.source_id ?? 'Not supplied'}</dd><dt>Evidence type</dt><dd>{evidence?.kind ?? 'Not supplied'}</dd><dt>Recording-reference metadata</dt><dd><code>{evidence?.local_path ?? 'Not supplied'}</code></dd><dt>Dataset reference</dt><dd>{evidence?.dataset_id ?? 'Not supplied'}</dd><dt>Metadata validation</dt><dd>{outcome?.metadata_status ?? 'Not supplied'}</dd><dt>File integrity</dt><dd>{outcome?.integrity_status ?? 'Not supplied'}</dd></dl>
    <p className="note">No spatial observation positions are supplied. References are plain text and files are not opened. Matching paths or times do not establish correlation.</p>
    <strong className="fusion-unavailable">NO VALIDATED FUSION OUTPUTS AVAILABLE</strong>
  </section>;
}
