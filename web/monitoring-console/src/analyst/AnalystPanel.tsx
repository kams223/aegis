import { useEffect, useMemo, useRef, useState } from 'react';
import type { Snapshot } from '../models';
import { Card } from '../components';
import { answerQuestion, QUESTIONS } from './engine';
import type { RecordReference } from './engine';

export function AnalystPanel({ snapshot, onInspect }: { snapshot: Snapshot; onInspect: (reference: RecordReference, trigger: HTMLButtonElement) => void }) {
  const [question, setQuestion] = useState<string>(QUESTIONS[0]);
  const [observationId, setObservationId] = useState(snapshot.observations[0]?.observation_id ?? '');
  const [request, setRequest] = useState({ question: QUESTIONS[0] as string, observationId, sequence: 0 });
  const answer = useMemo(() => answerQuestion(snapshot, request.question, request.observationId), [snapshot, request]);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (request.sequence > 0) heading.current?.focus(); }, [request]);
  const explain = () => setRequest(previous => ({ question, observationId, sequence: previous.sequence + 1 }));
  return <Card title="AEGIS AI Analyst" className="analyst-panel">
    <strong className="analyst-mode">OFFLINE / DETERMINISTIC · READ ONLY</strong>
    <p>V1 uses five fixed question intents and evidence templates. No LLM, model inference, chat service or investigation execution is connected. Synthetic radar markers are excluded.</p>
    <div role="group" aria-label="Analyst question controls">
      <div className="analyst-question-controls"><label>Supported analyst question<select value={QUESTIONS.includes(question as typeof QUESTIONS[number]) ? question : ''} onChange={event => setQuestion(event.target.value)}><option value="" disabled>Choose a supported question</option>{QUESTIONS.map(q => <option key={q}>{q}</option>)}</select></label>
      <label>Observation context<select value={observationId} onChange={event => setObservationId(event.target.value)}><option value="">No observation selected</option>{snapshot.observations.map(o => <option key={o.observation_id} value={o.observation_id}>{o.observation_id}</option>)}</select></label></div>
      <label>Question text<input type="text" maxLength={300} value={question} onChange={event => setQuestion(event.target.value)} aria-describedby="analyst-intent-help" onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); explain(); } }} /></label>
      <p id="analyst-intent-help" className="note">Only the five complete questions above are recognized, ignoring case and surrounding whitespace. Other wording is unsupported. No free-form answer generation occurs.</p>
      <button type="button" onClick={explain}>Explain supplied evidence</button>
    </div>
    <section className="analyst-answer" aria-label="Analyst answer"><h3 ref={heading} tabIndex={-1}>{answer.status === 'supported' ? 'Evidence-grounded explanation' : 'Unsupported question'}</h3>
      <p className="note">Answered question: {request.question || 'Not supplied'}</p>
      {answer.claims.map((claim, i) => <article key={i} className={`analyst-claim ${claim.category === 'Limitation' ? 'analyst-limitation' : ''}`}><strong>{claim.category}</strong><p>{claim.text}</p><ul className="analyst-references" aria-label="Supporting references">{claim.references.map((ref, j) => <li key={j}>{ref.kind === 'contract' ? <span>Contract: {ref.id} · existing frontend model</span> : <button type="button" aria-label={`Analyst reference ${ref.kind} ${ref.id}, claim ${i + 1}`} onClick={event => onInspect(ref, event.currentTarget)}>{ref.kind}: {ref.id}</button>}</li>)}</ul></article>)}
    </section>
  </Card>;
}
