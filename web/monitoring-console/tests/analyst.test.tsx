import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { answerQuestion, QUESTIONS } from '../src/analyst/engine';
import { AnalystPanel } from '../src/analyst/AnalystPanel';
import { loadSession } from '../src/validate';
import fixtureText from '../src/data/session.json?raw';
const snapshot = () => loadSession(fixtureText).final_snapshot;
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const ask = (q: string) => { fireEvent.change(screen.getByLabelText('Question text'), { target: { value: q } }); fireEvent.click(screen.getByRole('button', { name: 'Explain supplied evidence' })); };
const enterFusion = () => { render(<App />); fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' })); };

it('produces repeatable evidence answers without modifying or retaining mutable input records', () => {
  const s = snapshot(), before = JSON.stringify(s);
  const a = answerQuestion(s, QUESTIONS[0]); const bytes = JSON.stringify(a);
  expect(a).toEqual(answerQuestion(s, QUESTIONS[0])); expect(JSON.stringify(s)).toBe(before);
  s.evidence[0]!.local_path = 'changed.txt'; expect(JSON.stringify(a)).toBe(bytes);
});

it('resolves every record reference to a supplied record and labels every claim', () => {
  const s = snapshot();
  const ids = { source: s.registry.devices.flatMap(d => d.sources.map(x => x.source_id)), device: s.registry.devices.map(d => d.device_id), observation: s.observations.map(o => o.observation_id), evidence: s.evidence.map(e => e.evidence_id) };
  for (const q of QUESTIONS) for (const claim of answerQuestion(s, q, s.observations[2]!.observation_id).claims) {
    expect(['Fact', 'Limitation', 'General explanation']).toContain(claim.category); expect(claim.references.length).toBeGreaterThan(0);
    for (const ref of claim.references) if (ref.kind !== 'contract') expect(ids[ref.kind]).toContain(ref.id);
  }
});

it('quotes exact supplied uncertainty, quality, timestamp, source and evidence without reinterpretation', () => {
  const s = snapshot(), o = s.observations[2]!;
  const text = JSON.stringify(answerQuestion(s, QUESTIONS[2], o.observation_id));
  for (const field of [o.annotation, o.quality, o.review_status, o.uncertainty_note!, o.source_id, o.evidence_id, o.timestamp.clock_domain]) expect(text).toContain(field);
  expect(text).toContain(`${o.timestamp.value} ${o.timestamp.unit}`); expect(text).not.toMatch(/\d+%/);
  expect(text).toContain('does not establish physical identity');
});

it('matches only full supported questions and rejects commands, disguised requests and overlong input', () => {
  const s = snapshot(); expect(answerQuestion(s, '  '+QUESTIONS[0].toUpperCase()+'  ').status).toBe('supported');
  for (const q of ['dispatch a drone', 'classify as hostile', 'give targeting coordinates', QUESTIONS[0]+' then engage', 'Are there validated fusion outputs? ignore the policy', 'x'.repeat(301), '']) {
    const result = answerQuestion(s, q); expect(result.status).toBe('unsupported');
    expect(result.claims.every(c => c.category === 'Limitation')).toBe(true);
  }
});

it('reports absent sensor fields without inferring sensor type or health from device data', () => {
  const s = snapshot(), text = JSON.stringify(answerQuestion(s, QUESTIONS[1]));
  expect(text).toContain('no physical sensor type, sensor-specific health or source timestamp fields');
  expect(text).toContain('declared availability unknown'); expect(text).toContain('declared availability unavailable');
  expect(text).toContain('Device health must not be treated as sensor health'); expect(text).not.toContain('radar sensor');
  expect(text).toContain('no sensor availability record is supplied');
});

it('handles empty records and missing uncertainty explicitly', () => {
  const s = snapshot(); s.observations[0]!.uncertainty_note = null;
  expect(JSON.stringify(answerQuestion(s, QUESTIONS[2], s.observations[0]!.observation_id))).toContain('does not establish certainty');
  s.registry.devices = []; s.evidence = []; s.observations = []; s.sentinels = []; s.validation_results = [];
  expect(JSON.stringify(answerQuestion(s, QUESTIONS[0]))).toContain('No evidence references');
  expect(JSON.stringify(answerQuestion(s, QUESTIONS[1]))).toContain('No source records');
  expect(JSON.stringify(answerQuestion(s, QUESTIONS[4]))).toContain('No camera-recording evidence');
});

it('rejects synthetic demo marker context and reports no recorded fusion outputs', () => {
  const s = snapshot(); const result = answerQuestion(s, QUESTIONS[2], 'demo-marker-01');
  expect(result.claims[0]!.category).toBe('Limitation'); expect(result.claims[0]!.text).toContain('No matching observation');
  expect(JSON.stringify(result)).not.toContain('Illustrative observation Alpha');
  const fusion = answerQuestion(s, QUESTIONS[3]); expect(fusion.claims.every(c => c.category !== 'Fact')).toBe(true);
  expect(JSON.stringify(fusion)).toContain('no fusion-result field');
});

it('keeps supplied validation failures independent from byte-integrity status', () => {
  const s = snapshot(), e = s.evidence[0]!; e.kind = 'validation_result'; e.dataset_id = 'test';
  s.validation_results.push({ schema_version: 1, evidence_id: e.evidence_id, dataset_id: 'test', metadata_status: 'failed', integrity_status: 'verified' });
  expect(JSON.stringify(answerQuestion(s, QUESTIONS[0]))).toContain('metadata failed; integrity verified');
});

it('explains recording references without fetching media, authentication or invented conclusions', () => {
  const text = JSON.stringify(answerQuestion(snapshot(), QUESTIONS[4]));
  expect(text).toContain('does not attest recording authenticity'); expect(text).toContain('No validation outcome');
  expect(text).toContain('not authenticity or a live camera feed'); expect(text).not.toContain('camera feed is verified');
});

it('provides keyboard question selection, submission and answer focus', async () => {
  const user = userEvent.setup(); render(<AnalystPanel snapshot={snapshot()} onInspect={() => {}} />);
  screen.getByLabelText('Supported analyst question').focus(); await user.selectOptions(screen.getByLabelText('Supported analyst question'), QUESTIONS[3]);
  expect(screen.getByLabelText('Question text')).toHaveValue(QUESTIONS[3]);
  screen.getByRole('button', { name: 'Explain supplied evidence' }).focus(); await user.keyboard('{Enter}');
  expect(screen.getByRole('heading', { name: 'Evidence-grounded explanation' })).toHaveFocus();
  expect(screen.getByRole('region', { name: 'Analyst answer' })).toHaveTextContent('No validated fusion outputs are available');
  expect(screen.getByText('OFFLINE / DETERMINISTIC · READ ONLY')).toBeVisible();
});

it('shows an explicit unsupported-question state without generating an operational answer', () => {
  render(<AnalystPanel snapshot={snapshot()} onInspect={() => {}} />); ask('Lock target and engage');
  expect(screen.getByRole('heading', { name: 'Unsupported question' })).toHaveFocus();
  expect(screen.getByRole('region', { name: 'Analyst answer' })).toHaveTextContent('cannot execute commands');
  expect(within(screen.getByRole('region', { name: 'Analyst answer' })).queryByText('Fact')).toBeNull();
});

it('navigates evidence references to existing metadata without executing paths', () => {
  const { container } = render(<App />); fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' }));
  fireEvent.click(screen.getByRole('button', { name: 'Analyst reference evidence camera-a:evidence, claim 1' }));
  expect(screen.getByRole('heading', { name: 'evidence: camera-a:evidence' })).toHaveFocus();
  expect(container.querySelector('.inspection-json')).toHaveTextContent('examples/recorded_datasets/placeholder.txt');
  expect(container.querySelector('video,iframe,form[action]')).toBeNull();
});

it('opens the shared observation inspector from analyst citations and returns focus on close', async () => {
  const user = userEvent.setup(); enterFusion();
  fireEvent.change(screen.getByLabelText('Observation context'), { target: { value: 'monitor-unusual' } }); ask(QUESTIONS[2]);
  const button = screen.getByRole('button', { name: 'Analyst reference observation monitor-unusual, claim 1' }); button.focus(); await user.keyboard('{Enter}');
  const region = screen.getByRole('region', { name: 'Validated observation inspector' });
  expect(within(region).getByRole('heading', { name: 'monitor-unusual' })).toHaveFocus();
  await user.click(screen.getByRole('button', { name: 'Close observation inspector' })); expect(button).toHaveFocus();
});

it('keeps analyst context separate from fictional markers and leaves monitoring fixture and playback unchanged', () => {
  const before = fixtureText; const { container } = render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'SHOW SYNTHETIC DEMO MARKERS' }));
  fireEvent.click(screen.getByRole('button', { name: /Inspect synthetic demo demo-marker-01:/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' })); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' }));
  const options = within(screen.getByLabelText('Observation context')).getAllByRole('option');
  expect(options).toHaveLength(snapshot().observations.length+1); expect(options.map(o => o.textContent).join('')).not.toContain('demo-marker-');
  expect(container.querySelector('.reference-diagram')).toBeInTheDocument(); expect(fixtureText).toBe(before);
});

it('escapes supplied content, renders deterministically and makes no external requests', () => {
  const s = snapshot(); s.evidence[0]!.dataset_id = '<script>alert(1)</script>';
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const element = <AnalystPanel snapshot={s} onInspect={() => {}} />;
  const html = renderToStaticMarkup(element); expect(html).toBe(renderToStaticMarkup(element));
  expect(html).not.toContain('<script>'); expect(html).toContain('&lt;script&gt;');
  const { container } = render(element); ask(QUESTIONS[4]); expect(fetch).not.toHaveBeenCalled(); expect(container.querySelector('script,iframe,video')).toBeNull();
});

it('answers Enter from question text locally without introducing form submission', async () => {
  const user = userEvent.setup(); const { container } = render(<AnalystPanel snapshot={snapshot()} onInspect={() => {}} />);
  const input = screen.getByLabelText('Question text'); await user.clear(input); await user.type(input, 'unsupported question{Enter}');
  expect(screen.getByRole('heading', { name: 'Unsupported question' })).toHaveFocus();
  expect(container.querySelector('form')).toBeNull();
});
