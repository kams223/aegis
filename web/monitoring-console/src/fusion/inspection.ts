import type { Device, Evidence, Observation, Outcome, Snapshot, Source } from '../models';

export interface SensorRow {
  readonly source: Source;
  readonly device: Device;
  readonly availability: 'available' | 'unavailable' | 'unknown';
  readonly evidence: readonly Evidence[];
  readonly observations: readonly Observation[];
  readonly validation: readonly Outcome[];
}
export type NodeKind = 'device' | 'source' | 'evidence' | 'observation';
export interface ReferenceNode { readonly key: string; readonly kind: NodeKind; readonly id: string; readonly column: number; readonly row: number }
export interface ReferenceEdge { readonly from: string; readonly to: string; readonly relation: 'declares source' | 'primary evidence reference' | 'evidence source' | 'observation source' | 'observation evidence' }

// This is a read-only projection of an already validated snapshot, not a fusion
// computation. IDs are references; a shared pathname is never an association.
export function inspectSnapshot(snapshot: Snapshot) {
  const sensors: SensorRow[] = [];
  const nodes: ReferenceNode[] = [];
  const edges: ReferenceEdge[] = [];
  const key = (kind: NodeKind, id: string) => `${kind}/${id}`;
  snapshot.registry.devices.forEach((device, row) => {
    nodes.push({ key: key('device', device.device_id), kind: 'device', id: device.device_id, column: 0, row });
    for (const source of device.sources) {
      const monitor = snapshot.sentinels.find(s => s.device_id === device.device_id);
      const evidence = snapshot.evidence.filter(e => e.source_id === source.source_id);
      const observations = snapshot.observations.filter(o => o.source_id === source.source_id);
      sensors.push({ source, device, availability: monitor?.sensors.find(s => s.source_id === source.source_id)?.status ?? 'unknown', evidence, observations, validation: snapshot.validation_results.filter(v => evidence.some(e => e.evidence_id === v.evidence_id)) });
      nodes.push({ key: key('source', source.source_id), kind: 'source', id: source.source_id, column: 1, row: sensors.length - 1 });
      edges.push({ from: key('device', device.device_id), to: key('source', source.source_id), relation: 'declares source' });
      edges.push({ from: key('source', source.source_id), to: key('evidence', source.evidence_id), relation: 'primary evidence reference' });
    }
  });
  snapshot.evidence.forEach((e, row) => {
    nodes.push({ key: key('evidence', e.evidence_id), kind: 'evidence', id: e.evidence_id, column: 2, row });
    // Primary references are already recorded above; retain the stronger explicit
    // relationship without duplicating the same line for the same declaration.
    if (!edges.some(edge => edge.from === key('source', e.source_id) && edge.to === key('evidence', e.evidence_id))) edges.push({ from: key('source', e.source_id), to: key('evidence', e.evidence_id), relation: 'evidence source' });
  });
  snapshot.observations.forEach((o, row) => {
    nodes.push({ key: key('observation', o.observation_id), kind: 'observation', id: o.observation_id, column: 3, row });
    edges.push({ from: key('source', o.source_id), to: key('observation', o.observation_id), relation: 'observation source' });
    edges.push({ from: key('evidence', o.evidence_id), to: key('observation', o.observation_id), relation: 'observation evidence' });
  });
  const keys = new Set(nodes.map(node => node.key));
  if (keys.size !== nodes.length || edges.some(edge => !keys.has(edge.from) || !keys.has(edge.to))) throw new Error('Inspection requires unique, resolved snapshot references');
  return { sensors, nodes, edges };
}
