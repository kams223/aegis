import { navigateTo } from './navigation';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { ObservationInspector } from '../src/observation/ObservationInspector';
import { loadSession } from '../src/validate';
import fixtureText from '../src/data/session.json?raw';
const snapshot = () => loadSession(fixtureText).final_snapshot;
const inspector = () => screen.getByRole('region', { name: 'Validated observation inspector' });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('shows only supplied observation, source, evidence and quality fields', () => {
  const s = snapshot(), o = s.observations[2]!;
  render(<ObservationInspector observation={o} snapshot={s} onClose={() => {}} />);
  const panel = inspector();
  for (const value of [o.annotation, o.source_id, o.evidence_id, o.quality, o.review_status, o.uncertainty_note!, o.timestamp.clock_domain]) expect(panel).toHaveTextContent(value);
  expect(panel).toHaveTextContent(`${o.timestamp.value} ${o.timestamp.unit}`);
  expect(panel).toHaveTextContent('third-party'); expect(panel).toHaveTextContent('examples/recorded_datasets/placeholder.txt');
  expect(panel).toHaveTextContent('NO VALIDATED FUSION OUTPUTS AVAILABLE');
  expect(panel.querySelector('a,video,iframe')).toBeNull();
});

it('makes absent optional metadata explicit without claiming validation or integrity success', () => {
  const s = snapshot(), o = s.observations[0]!; o.uncertainty_note = null;
  render(<ObservationInspector observation={o} snapshot={s} onClose={() => {}} />);
  const panel = inspector(); expect(within(panel).getAllByText('Not supplied').length).toBeGreaterThanOrEqual(4);
  expect(panel).not.toHaveTextContent('healthy'); expect(panel).not.toHaveTextContent('verified');
});

it('preserves supplied independent validation failure and integrity success', () => {
  const s = snapshot(), o = s.observations[0]!;
  const reference = s.evidence.find(e => e.evidence_id === o.evidence_id)!; reference.kind = 'validation_result'; reference.dataset_id = 'test-report';
  s.validation_results.push({ schema_version: 1, evidence_id: o.evidence_id, dataset_id: 'test-report', metadata_status: 'failed', integrity_status: 'verified' });
  render(<ObservationInspector observation={o} snapshot={s} onClose={() => {}} />);
  expect(within(inspector()).getByText('failed')).toBeVisible(); expect(within(inspector()).getByText('verified')).toBeVisible();
});

it('opens from a radar observation, focuses the inspector and returns focus on close', async () => {
  const user = userEvent.setup(); render(<App />);
  const button = screen.getByRole('button', { name: 'monitor-unusualuncertain' }); button.focus(); await user.keyboard('{Enter}');
  expect(within(inspector()).getByRole('heading', { name: 'monitor-unusual' })).toHaveFocus();
  await user.click(screen.getByRole('button', { name: 'Close observation inspector' }));
  expect(screen.queryByRole('region', { name: 'Validated observation inspector' })).toBeNull(); expect(button).toHaveFocus();
  await user.keyboard('{Enter}'); expect(inspector()).toBeVisible();
});

it('preserves fullscreen observation inspection and native exit', async () => {
  const original = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
  try {
    const { container } = render(<App />); const frame = container.querySelector('.radar-frame')!;
    let full: Element | null = null;
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => full });
    Object.defineProperty(frame, 'requestFullscreen', { value: vi.fn(async () => { full = frame; document.dispatchEvent(new Event('fullscreenchange')); }) });
    fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' })); await screen.findByRole('button', { name: 'Exit radar fullscreen' });
    fireEvent.click(screen.getByRole('button', { name: 'monitor-unusualuncertain' }));
    expect(frame.contains(inspector())).toBe(true);
    act(() => { full = null; document.dispatchEvent(new Event('fullscreenchange')); });
    expect(within(inspector()).getByRole('heading', { name: 'monitor-unusual' })).toBeVisible();
  } finally {
    if (original) Object.defineProperty(document, 'fullscreenElement', original);
    else delete (document as unknown as Record<string, unknown>).fullscreenElement;
  }
});

it('keeps the observations-page inspector inside the fullscreen radar boundary', () => {
  const { container } = render(<App />); navigateTo('Observations');
  fireEvent.click(screen.getByRole('button', { name: /monitor-unusual/ }));
  expect(container.querySelector('.radar-frame')!.contains(inspector())).toBe(true);
  expect(inspector()).toHaveTextContent('Illustrative missing context.');
  expect(inspector()).not.toHaveTextContent('demo-marker-');
});

it('keeps fictional marker details and validated inspector structurally separate', () => {
  const { container } = render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'SHOW SYNTHETIC DEMO MARKERS' }));
  fireEvent.click(screen.getByRole('button', { name: /Inspect synthetic demo demo-marker-01:/ }));
  const demo = screen.getByRole('region', { name: 'Synthetic demo observation details' });
  expect(demo).toHaveTextContent('SYNTHETIC DEMO'); expect(demo).toHaveTextContent('NOT ESTABLISHED');
  expect(inspector()).not.toHaveTextContent('demo-marker-01'); expect(inspector().querySelector('[data-demo-id]')).toBeNull();
  expect(demo.contains(inspector())).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Close observation inspector' })); expect(demo).toBeVisible();
  expect(container.querySelectorAll('[data-demo-id]')).toHaveLength(4);
});

it('integrates graph observation selection with the same supplied provenance inspector', async () => {
  const user = userEvent.setup(); render(<App />); navigateTo('Sensor Fusion');
  const node = screen.getByRole('button', { name: 'Diagram: observation monitor-unusual' }); node.focus(); await user.keyboard(' ');
  expect(within(inspector()).getByRole('heading', { name: 'monitor-unusual' })).toHaveFocus();
  expect(inspector()).toHaveTextContent('display-r:evidence'); expect(inspector()).toHaveTextContent('third-party');
  fireEvent.click(screen.getByRole('button', { name: 'Close observation inspector' })); expect(node).toHaveFocus();
  expect(screen.queryByRole('region', { name: 'Validated observation inspector' })).toBeNull();
});

it('renders deterministically without mutating supplied observations or interpreting paths', () => {
  const s = snapshot(), o = s.observations[0]!; o.annotation = '<script>alert(1)</script>';
  const before = JSON.stringify(s);
  const html = renderToStaticMarkup(<ObservationInspector observation={o} snapshot={s} onClose={() => {}} />);
  expect(html).toBe(renderToStaticMarkup(<ObservationInspector observation={o} snapshot={s} onClose={() => {}} />));
  expect(html).not.toContain('<script>'); expect(html).toContain('&lt;script&gt;'); expect(JSON.stringify(s)).toBe(before);
});

it('makes no network requests while inspecting and preserves demo playback and ring controls', () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const before = fixtureText; render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'monitor-unusualuncertain' }));
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '8' } });
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s'); expect(fetch).not.toHaveBeenCalled(); expect(fixtureText).toBe(before);
});

it('focuses an already selected observation on every explicit inspection request', async () => {
  const user = userEvent.setup(); render(<App />);
  const button = screen.getByRole('button', { name: 'display-normaldeclared' });
  for (let i = 0; i < 2; i++) {
    button.focus(); await user.keyboard('{Enter}');
    expect(within(inspector()).getByRole('heading', { name: 'display-normal' })).toHaveFocus();
  }
  await user.click(screen.getByRole('button', { name: 'Close observation inspector' })); expect(button).toHaveFocus();
});
