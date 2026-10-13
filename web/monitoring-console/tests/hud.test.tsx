import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { CameraPanel, SimulationPanel, RadarPanel } from '../src/hud';
import { loadSession } from '../src/validate';
import fixtureText from '../src/data/session.json?raw';
import { readFileSync } from 'node:fs';
const css = readFileSync('src/styles.css', 'utf-8');
import html from '../index.html?raw';
import main from '../src/main.tsx?raw';

afterEach(() => vi.restoreAllMocks());
const fixture = () => loadSession(fixtureText);

it('renders six grounded metrics and the three dashboard viewports', () => {
  render(<App />);
  const metrics = screen.getByLabelText('Session metrics');
  expect(within(metrics).getAllByRole('article')).toHaveLength(6);
  for (const [name, number] of [['Devices', '03'], ['Applied events', '06'], ['Rejected events', '01'], ['Observations', '03'], ['Alerts', '02'], ['Reviews', '02']] as const) {
    expect(within(metrics).getByRole('article', { name }).querySelector('strong')).toHaveTextContent(number!);
  }
  for (const name of ['Tactical radar', 'Drone camera', '3D simulation', 'Device status', 'Recent events', 'Alerts']) expect(screen.getByRole('heading', { name, level: 2 })).toBeVisible();
  expect(screen.getByText('SESSION REF')).toHaveTextContent('synthetic-platform-v1');
});

it('provides nine accessible navigation destinations with the expanded visible labels', () => {
  render(<App />);
  const nav = screen.getByRole('navigation');
  expect(within(nav).getAllByRole('button')).toHaveLength(9);
  expect(within(nav).getByText('Radar / Observations')).toBeVisible();
  expect(within(nav).getByText('Camera / Evidence')).toBeVisible();
  fireEvent.click(within(nav).getByRole('button', { name: 'Simulation' }));
  expect(screen.getByRole('heading', { name: 'Simulation', level: 1 })).toBeVisible();
  expect(within(nav).getByRole('button', { name: 'Simulation' })).toHaveAttribute('aria-current', 'page');
});

it('keeps the radar decorative and observations non-spatial', () => {
  const { container } = render(<RadarPanel snapshot={fixture().final_snapshot} />);
  expect(screen.getByText('SYNTHETIC DISPLAY — NON-GEOGRAPHIC')).toBeVisible();
  expect(screen.getByText('No observation markers')).toBeVisible();
  expect(container.querySelectorAll('.radar-grid circle')).toHaveLength(4);
  expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  expect(container.querySelectorAll('.radar-scope button')).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: /monitor-unusual/ }));
  expect(screen.getByText('Illustrative missing context.')).toBeVisible();
  expect(screen.getByText('demo:display-r')).toBeVisible();
});

it('uses a camera placeholder with supplied identifiers and explicit unknown availability', () => {
  const { container } = render(<CameraPanel snapshot={fixture().final_snapshot} />);
  expect(screen.getByText('NO VERIFIED CAMERA FEED')).toBeVisible();
  expect(screen.getByText('native-aerial')).toBeVisible();
  expect(screen.getByText('Unavailable — metadata only')).toBeVisible();
  expect(screen.getAllByText('Not supplied')).toHaveLength(1);
  expect(screen.getAllByText('unknown').length).toBeGreaterThan(0);
  expect(container.querySelector('video, audio, img, iframe, a')).toBeNull();
  fireEvent.change(screen.getByLabelText('Camera evidence'), { target: { value: 'camera-a:recorded' } });
  expect(screen.getByText('camera-a:recorded', { selector: 'code' })).toBeVisible();
});

it('reports missing camera metadata without fabrication', () => {
  const snapshot = fixture().final_snapshot;
  snapshot.evidence = [];
  render(<CameraPanel snapshot={snapshot} />);
  expect(screen.getByText('Camera identifier unavailable')).toBeVisible();
  expect(screen.getAllByText('Not supplied').length).toBeGreaterThan(1);
  expect(screen.queryByLabelText('Camera evidence')).not.toBeInTheDocument();
});

it('offers fullscreen for the placeholder only and exposes browser unavailability', async () => {
  const { container } = render(<CameraPanel snapshot={fixture().final_snapshot} />);
  const request = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(container.querySelector('.camera-viewport'), 'requestFullscreen', { value: request, configurable: true });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen placeholder' }));
  expect(request).toHaveBeenCalledOnce();
  await Promise.resolve();
});

it('handles fullscreen refusal without requesting media or changing dataset state', async () => {
  const snapshot = fixture().final_snapshot;
  const before = JSON.stringify(snapshot);
  render(<CameraPanel snapshot={snapshot} />);
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen placeholder' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Fullscreen unavailable');
  expect(JSON.stringify(snapshot)).toBe(before);
});

it('changes illustrative perspective and mode locally and resets them', () => {
  render(<SimulationPanel />);
  expect(screen.getByText('SIMULATION PREVIEW — ILLUSTRATIVE')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '2D' }));
  fireEvent.click(screen.getByRole('button', { name: 'left view' }));
  expect(screen.getByLabelText('Synthetic 2D demo environment, left view; illustrative models only')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
  expect(screen.getByLabelText('Synthetic 3D demo environment, right view; illustrative models only')).toBeVisible();
});

it('opens exactly the selected recent event in replay and preserves final-state boundaries', () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect event 7: conflict-1' }));
  expect(screen.getByRole('heading', { name: 'Event replay', level: 1 })).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Event 7 of 7');
  expect(screen.getByText('CONFLICTING_UPDATE')).toBeVisible();
  expect(screen.getByRole('button', { name: /Next event/ })).toBeDisabled();
  expect(screen.getByText(/The final snapshot stays fixed/)).toBeVisible();
});

it('preserves event timestamps and ordering rather than inventing wall-clock time', () => {
  render(<App />);
  const heading = screen.getByRole('heading', { name: 'Recent events' });
  const list = heading.closest('section')!;
  expect(within(list).getAllByRole('button')[0]).toHaveAccessibleName('Inspect event 1: connectivity-1');
  expect(within(list).getAllByRole('button')[6]).toHaveAccessibleName('Inspect event 7: conflict-1');
  expect(within(list).getByText('6 s')).toBeVisible();
  expect(within(list).getAllByText('demo:camera-a').length).toBeGreaterThan(0);
});

it('shows review status and descriptions without invented alert severity', () => {
  render(<App />);
  const section = screen.getByRole('heading', { name: 'Alerts', level: 2 }).closest('section')!;
  expect(within(section).getByText(/severity not supplied/)).toBeVisible();
  expect(within(section).getByText('Descriptive fixture annotation only.')).toBeVisible();
  expect(within(section).getByText('reviewed')).toBeVisible();
});

it('keeps unknown values explicit in the compact device table', () => {
  render(<App />);
  const section = screen.getByRole('heading', { name: 'Device status' }).closest('section')!;
  expect(within(section).getByText('Unknown — no monitor supplied')).toBeVisible();
  expect(within(section).getByText('camera-a: unknown')).toBeVisible();
  expect(within(section).getAllByText('unknown').length).toBeGreaterThan(0);
});

it('does not invent operational telemetry or expose command controls', () => {
  const { container } = render(<App />);
  expect(container.textContent).not.toMatch(/GPS|altitude|velocity|heading estimate|target lock|threat score|operational readiness/i);
  expect(screen.queryByRole('button', { name: /dispatch|engage|intercept|launch|submit|approve|lock target/i })).not.toBeInTheDocument();
  expect(container.querySelector('video, audio, iframe, form, textarea')).toBeNull();
});

it('supports keyboard navigation to all nine destinations', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.tab(); expect(screen.getByRole('link')).toHaveFocus();
  for (const name of ['Overview', 'Devices', 'Observations', 'Sensor Fusion', 'Evidence', 'Simulation', 'Alerts & Copilot', 'Event replay', 'Review & audit']) {
    await user.tab(); expect(screen.getByRole('button', { name })).toHaveFocus();
  }
  await user.keyboard('{Enter}');
  expect(screen.getByRole('heading', { name: 'Review & audit', level: 1 })).toBeVisible();
});

it('implements reduced-motion and bounded responsive decorative sizing in CSS', () => {
  expect(css).toContain('@media (prefers-reduced-motion: reduce) { .radar-sweep { animation: none; }');
  expect(css).toContain('@media (max-width: 1150px)');
  expect(css).toContain('@media (max-width: 760px)');
  expect(css).toContain('@media (max-width: 420px)');
  expect(css).toContain('max-width: 310px');
  expect(css).not.toContain('@import'); expect(css).not.toContain('url(');
});

it('preserves external CSS and the restrictive CSP', () => {
  expect(html.match(/rel="stylesheet"/g)).toHaveLength(1);
  expect(html).toContain('href="./src/styles.css"');
  expect(html).toContain("style-src 'self'"); expect(html).toContain("connect-src 'none'");
  expect(html).not.toMatch(/unsafe-inline|https?:/);
  expect(main).not.toContain('styles.css');
});

it('renders repeatably, escapes supplied text and does not mutate inputs', () => {
  const session = fixture(); session.final_snapshot.description = '<script>alert(1)</script>';
  const text = JSON.stringify(session);
  const a = renderToStaticMarkup(<App text={text} />);
  expect(a).toBe(renderToStaticMarkup(<App text={text} />));
  expect(a).not.toContain('<script>'); expect(a).toContain('&lt;script&gt;');
  expect(JSON.stringify(session)).toBe(text);
});

it('rejects invalid fixtures before showing any HUD panels', () => {
  render(<App text='{ "schema_version": 2 }' />);
  expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.queryByText('Tactical radar')).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
});

it('makes no external requests when navigating or using preview controls', () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const xhr = vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(() => { throw new Error('network forbidden'); });
  const socket = vi.spyOn(globalThis, 'WebSocket').mockImplementation(() => { throw new Error('network forbidden'); });
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: '2D' }));
  fireEvent.click(screen.getByRole('button', { name: 'right view' }));
  for (const name of ['Devices', 'Observations', 'Evidence', 'Simulation', 'Alerts & Copilot', 'Event replay', 'Review & audit']) fireEvent.click(screen.getByRole('button', { name }));
  expect(fetch).not.toHaveBeenCalled(); expect(xhr).not.toHaveBeenCalled(); expect(socket).not.toHaveBeenCalled();
});
