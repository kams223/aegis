import type { Snapshot } from '../models';
import type { NodeKind } from '../fusion/inspection';

export const QUESTIONS = Object.freeze([
  'What evidence is available?',
  'What is missing from the sensor records?',
  'What can be concluded about this observation?',
  'Are there validated fusion outputs?',
  'Why is an evidence reference not proof of a verified camera recording?',
] as const);
export type RecordReference = Readonly<{ kind: NodeKind; id: string }>;
export type Support = RecordReference | Readonly<{ kind: 'contract'; id: 'Snapshot v1' | 'Observation v1' | 'Evidence reference v1' }>;
export interface Claim { readonly category: 'Fact' | 'Limitation' | 'General explanation'; readonly text: string; readonly references: readonly Support[] }
export interface AnalystAnswer { readonly status: 'supported' | 'unsupported'; readonly claims: readonly Claim[] }
const contract = (id: 'Snapshot v1' | 'Observation v1' | 'Evidence reference v1'): Support => ({ kind: 'contract', id });
const reference = (kind: NodeKind, id: string): RecordReference => ({ kind, id });

// Accept an already validated snapshot. No inference, mutation, I/O or runtime
// clocks. Exact whole-question matching prevents substring-based intent drift.
export function answerQuestion(snapshot: Snapshot, question: string, observationId?: string): AnalystAnswer {
  const index = typeof question === 'string' && question.length <= 300 ? QUESTIONS.findIndex(q => q.toLowerCase() === question.trim().toLowerCase()) : -1;
  const claims: Claim[] = [];
  const add = (category: Claim['category'], text: string, references: readonly Support[]) => claims.push({ category, text, references });
  const schema = [contract('Snapshot v1')];
  if (index < 0) return { status: 'unsupported', claims: [{ category: 'Limitation', text: 'Unsupported question. V1 answers only the five listed questions. It uses fixed templates, not an LLM, and cannot execute commands, classify threats or recommend actions.', references: schema }] };
  if (index === 0) {
    if (!snapshot.evidence.length) add('Limitation', 'No evidence references are supplied in this snapshot.', schema);
    for (const e of snapshot.evidence) {
      const refs = [reference('evidence', e.evidence_id), reference('source', e.source_id)];
      add('Fact', `Evidence ${e.evidence_id}: declared kind ${e.kind}; source ${e.source_id}; local reference metadata ${e.local_path}; dataset ${e.dataset_id ?? 'Not supplied'}.`, refs);
      const outcome = snapshot.validation_results.find(v => v.evidence_id === e.evidence_id);
      if (outcome) add('Fact', `Supplied validation for ${e.evidence_id}: metadata ${outcome.metadata_status}; integrity ${outcome.integrity_status}; dataset ${outcome.dataset_id}.`, refs);
      else add('Limitation', `No validation outcome is supplied for ${e.evidence_id}.`, refs);
    }
    add('General explanation', 'A declaration is evidence metadata, not proof that media was opened or verified by this console. Shared paths do not establish cross-source association.', [contract('Evidence reference v1')]);
  } else if (index === 1) {
    add('Limitation', 'The closed source contract has no physical sensor type, sensor-specific health or source timestamp fields. Device health must not be treated as sensor health.', schema);
    let count = 0;
    for (const d of snapshot.registry.devices) for (const source of d.sources) {
      count++;
      const refs = [reference('source', source.source_id), reference('device', d.device_id)];
      const availability = snapshot.sentinels.find(s => s.device_id === d.device_id)?.sensors.find(s => s.source_id === source.source_id);
      if (availability) add('Fact', `Source ${source.source_id}: declared availability ${availability.status}; device ${d.device_id}.`, refs);
      else add('Limitation', `Source ${source.source_id}: no sensor availability record is supplied. Availability is not established.`, refs);
      if (!snapshot.observations.some(o => o.source_id === source.source_id)) add('Limitation', `Source ${source.source_id}: no observation records are supplied.`, refs);
      const evidence = snapshot.evidence.filter(e => e.source_id === source.source_id);
      if (!evidence.some(e => snapshot.validation_results.some(v => v.evidence_id === e.evidence_id))) add('Limitation', `Source ${source.source_id}: no evidence validation outcomes are supplied.`, refs);
    }
    if (!count) add('Limitation', 'No source records are supplied.', schema);
    for (const o of snapshot.observations) if (o.uncertainty_note === null) add('Limitation', `Observation ${o.observation_id}: uncertainty note Not supplied. Absence does not establish certainty.`, [reference('observation', o.observation_id)]);
  } else if (index === 2) {
    const o = snapshot.observations.find(o => o.observation_id === observationId);
    if (!o) add('Limitation', 'Select an existing validated-snapshot observation. No matching observation is selected; synthetic demo markers are not analyst inputs.', [contract('Observation v1')]);
    else {
      const refs = [reference('observation', o.observation_id), reference('source', o.source_id), reference('evidence', o.evidence_id)];
      add('Fact', `Observation ${o.observation_id}: category ${o.category}; source ${o.source_id}; evidence ${o.evidence_id}.`, refs);
      add('Fact', `Supplied annotation: ${o.annotation}`, refs);
      add('Fact', `Supplied quality: ${o.quality}; review status: ${o.review_status}.`, refs);
      add('Fact', `Supplied timestamp: ${o.timestamp.value} ${o.timestamp.unit}; clock domain ${o.timestamp.clock_domain}.`, refs);
      if (o.uncertainty_note !== null) add('Fact', `Supplied uncertainty note: ${o.uncertainty_note}`, refs);
      else add('Limitation', 'Uncertainty note: Not supplied. This does not establish certainty.', refs);
      add('Limitation', 'This record does not establish physical identity, spatial location, a threat classification or cross-sensor association. Review status concerns interpretation only.', [contract('Observation v1'), ...refs]);
    }
  } else if (index === 3) {
    add('Limitation', 'No validated fusion outputs are available. Snapshot v1 has no fusion-result field. Declared reference relationships are not fusion computations.', schema);
    add('General explanation', 'A recorded fusion output would require an approved contract and explicit input/output provenance. No fusion calculation is executed by this analyst.', schema);
  } else {
    add('General explanation', 'An evidence reference declares an identifier, source, kind and local path. It does not attest recording authenticity, content or physical accuracy. This console does not open or decode the referenced file.', [contract('Evidence reference v1')]);
    const cameras = snapshot.evidence.filter(e => e.kind === 'camera_recording');
    if (!cameras.length) add('Limitation', 'No camera-recording evidence references are supplied.', schema);
    for (const e of cameras) {
      const refs = [reference('evidence', e.evidence_id), reference('source', e.source_id)];
      add('Fact', `Reference ${e.evidence_id} declares kind camera_recording and source ${e.source_id}. This is a declaration only.`, refs);
      const outcome = snapshot.validation_results.find(v => v.evidence_id === e.evidence_id);
      if (outcome) add('Fact', `Supplied metadata status ${outcome.metadata_status}; integrity status ${outcome.integrity_status} for ${e.evidence_id}.`, refs);
      else add('Limitation', `No validation outcome is supplied for ${e.evidence_id}.`, refs);
    }
    add('General explanation', 'Matching a checksum verifies agreement with declared bytes, not authenticity or a live camera feed. Playback uses only the separate approved bundled-media catalog.', [contract('Evidence reference v1')]);
  }
  add('Limitation', 'No numerical confidence, physical measurements or spatial observation positions are supplied by this monitoring contract. Equal timestamps in separate clock domains are not synchronization.', [contract('Observation v1')]);
  return { status: 'supported', claims };
}
