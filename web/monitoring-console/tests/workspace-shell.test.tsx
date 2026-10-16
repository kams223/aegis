import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import App from '../src/App';
import { navigateTo } from './navigation';
import { canonicalTelemetry, loadTelemetryReplay, replayTelemetry } from '../src/flight/telemetry';
import px4 from '../examples/telemetry/px4.json?raw';
const css = readFileSync('src/layout/workspace-shell.css', 'utf8');

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const primary = () => within(screen.getByRole('navigation', { name: 'Workspaces' }));
const secondary = () => within(screen.getByRole('navigation', { name: 'Workspace pages' }));
function recorded() { navigateTo('Flight Operations'); fireEvent.change(screen.getByLabelText('Flight data source'), { target: { value: 'recorded' } }); }
function upload(read?: () => Promise<ArrayBuffer>) {
  const bytes = new TextEncoder().encode(canonicalTelemetry(replayTelemetry(loadTelemetryReplay(px4))));
  const file = new File([bytes], 'snapshot.json');
  Object.defineProperty(file, 'arrayBuffer', { value: read ?? (async () => bytes.buffer) });
  fireEvent.change(screen.getByLabelText('Import recorded SITL snapshot'), { target: { files: [file] } });
  return bytes.buffer;
}

it('starts with exactly five primary workspaces and only Command Center pages', () => {
  render(<App />);
  expect(primary().getAllByRole('button').map(b => b.textContent)).toEqual(['Command Center', 'Sensor Lab', 'Training Ground', 'Fleet Operations', 'Investigation']);
  expect(secondary().getAllByRole('button').map(b => b.textContent)).toEqual(['Overview', 'Devices']);
  expect(primary().getByRole('button', { name: 'Command Center' })).toHaveAttribute('aria-current', 'page');
  expect(secondary().getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Monitoring overview');
  expect(screen.getByText('OFFLINE')).toBeVisible(); expect(screen.getByText('READ ONLY')).toBeVisible();
});

it.each([
  ['Overview', 'Monitoring overview', 'Session metrics'],
  ['Devices', 'Devices', 'Device registry'],
  ['Observations', 'Observations', 'Synthetic observation display'],
  ['Sensor Fusion', 'Sensor Fusion', 'AEGIS AI Analyst'],
  ['Evidence', 'Camera & Evidence', 'Evidence reference inventory'],
  ['Simulation', 'Simulation', '3D simulation'],
  ['Flight Operations', 'Flight Operations', 'Vehicle overview'],
  ['Alerts & Copilot', 'Alerts & Copilot', 'Descriptive alerts'],
  ['Event replay', 'Event Replay', 'Ordered event replay'],
  ['Review & audit', 'Review & Audit', 'Human interpretation review'],
] as const)('reaches existing %s page with its feature content', (page, title, feature) => {
  render(<App />); navigateTo(page);
  expect(screen.getByRole('heading', { level: 1, name: title })).toBeVisible();
  if (page === 'Overview') expect(screen.getByLabelText(feature)).toBeVisible();
  else expect(screen.getByRole('heading', { name: feature })).toBeVisible();
  expect(secondary().getAllByRole('button').filter(b => b.getAttribute('aria-current') === 'page')).toHaveLength(1);
  expect(document.querySelectorAll('.workspace-content')).toHaveLength(1);
});

it('opens each workspace default and preserves the active page and filter state on reselection', () => {
  render(<App />);
  for (const [workspace, page] of [['Sensor Lab', 'Observations'], ['Training Ground', 'Simulation'], ['Fleet Operations', 'Flight Operations'], ['Investigation', 'Alerts & Copilot'], ['Command Center', 'Overview']] as const) {
    fireEvent.click(primary().getByRole('button', { name: workspace })); expect(secondary().getByRole('button', { name: page })).toHaveAttribute('aria-current', 'page');
  }
  navigateTo('Devices'); fireEvent.change(screen.getByLabelText('Device category'), { target: { value: 'third_party' } });
  fireEvent.click(primary().getByRole('button', { name: 'Command Center' }));
  expect(secondary().getByRole('button', { name: 'Devices' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByLabelText('Device category')).toHaveValue('third_party');
  fireEvent.click(primary().getByRole('button', { name: 'Sensor Lab' }));
  expect(secondary().getAllByRole('button').map(b => b.textContent)).toEqual(['Observations', 'Sensor Fusion', 'Camera & Evidence']);
  expect(secondary().queryByRole('button', { name: 'Devices' })).toBeNull();
});

it('opens recent events at the requested occurrence, focuses the destination, and resets direct replay navigation', async () => {
  render(<App />); const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Inspect event 7: conflict-1' }));
  expect(primary().getByRole('button', { name: 'Investigation' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('heading', { level: 1, name: 'Event Replay' })).toHaveFocus();
  expect(screen.getByRole('status')).toHaveTextContent('Event 7 of 7');
  await user.click(secondary().getByRole('button', { name: 'Event Replay' }));
  expect(screen.getByRole('status')).toHaveTextContent('Event 1 of 7');
  fireEvent.click(screen.getByRole('button', { name: /Next event/ }));
  expect(screen.getByRole('status')).toHaveTextContent('Event 2 of 7');
  await user.click(primary().getByRole('button', { name: 'Investigation' }));
  expect(screen.getByRole('status')).toHaveTextContent('Event 2 of 7');
  await user.click(secondary().getByRole('button', { name: 'Event Replay' }));
  expect(screen.getByRole('status')).toHaveTextContent('Event 1 of 7');
});

it('keeps navigation native, keyboard reachable, and the URL unchanged', async () => {
  const url = location.href; render(<App />); const user = userEvent.setup();
  await user.tab(); expect(screen.getByRole('link', { name: 'Skip to monitoring content' })).toHaveFocus();
  expect(screen.getByRole('link')).toHaveAttribute('href', '#main-content'); expect(screen.getByRole('main')).toHaveAttribute('tabindex', '-1');
  await user.tab(); expect(primary().getByRole('button', { name: 'Command Center' })).toHaveFocus();
  await user.tab(); await user.keyboard(' ');
  expect(primary().getByRole('button', { name: 'Sensor Lab' })).toHaveFocus();
  expect(secondary().getByRole('button', { name: 'Observations' })).toHaveAttribute('aria-current', 'page');
  expect(location.href).toBe(url); expect(screen.queryByRole('tablist')).toBeNull();
});

it('keeps source context separate from the monitoring fixture identifier', () => {
  render(<App />);
  expect(screen.getByText('Synthetic monitoring fixture.')).toBeVisible();
  navigateTo('Sensor Fusion'); expect(screen.getByText('Declared evidence references; clocks not aligned.')).toBeVisible();
  navigateTo('Simulation'); expect(screen.getByText('Illustrative simulation; abstract scene units.')).toBeVisible();
  expect(screen.queryByText('MONITORING FIXTURE · FINAL SNAPSHOT')).toBeNull();
  navigateTo('Flight Operations'); expect(screen.getByText(/Fictional demo fleet or imported recorded snapshot/)).toBeVisible();
  expect(screen.queryByText('MONITORING FIXTURE · FINAL SNAPSHOT')).toBeNull();
  navigateTo('Review & audit'); expect(screen.getByText('Synthetic monitoring fixture.')).toBeVisible();
});

it('unmounts imported telemetry and restores default demo state on return', async () => {
  render(<App />); recorded(); upload(); await screen.findByLabelText('Record frontier');
  fireEvent.change(screen.getByRole('slider'), { target: { value: '0' } });
  fireEvent.click(primary().getByRole('button', { name: 'Fleet Operations' }));
  expect(screen.getByLabelText('Record frontier')).toHaveValue('0');
  navigateTo('Devices'); expect(screen.queryByLabelText('Record frontier')).toBeNull();
  navigateTo('Flight Operations'); expect(screen.getByLabelText('Flight data source')).toHaveValue('demo');
  fireEvent.change(screen.getByLabelText('Flight data source'), { target: { value: 'recorded' } });
  expect(screen.queryByLabelText('Record frontier')).toBeNull();
});

it('ignores a pending import after cross-workspace navigation', async () => {
  render(<App />); recorded(); let resolve!: (bytes: ArrayBuffer) => void;
  const bytes = upload(() => new Promise(done => { resolve = done; }));
  navigateTo('Observations'); await act(async () => resolve(bytes));
  recorded(); expect(screen.queryByLabelText('Record frontier')).toBeNull(); expect(screen.queryByText('Validating offline snapshot…')).toBeNull();
});

it('cancels simulation playback on leaving and mounts only the new page', () => {
  const cancel = vi.fn(); vi.stubGlobal('requestAnimationFrame', vi.fn(() => 72)); vi.stubGlobal('cancelAnimationFrame', cancel);
  render(<App />); navigateTo('Simulation'); fireEvent.click(screen.getByRole('button', { name: 'Play simulation' }));
  expect(document.querySelectorAll('canvas')).toHaveLength(1);
  navigateTo('Devices'); expect(cancel).toHaveBeenCalledWith(72); expect(document.querySelector('canvas')).toBeNull();
  navigateTo('Simulation'); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.00 / 12.00 s');
  expect(screen.getByRole('button', { name: 'Pause simulation' })).toBeDisabled();
});

it('fails closed for invalid fixtures without navigation or partial pages', () => {
  render(<App text="{" />); expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.queryByRole('navigation')).toBeNull(); expect(screen.queryByLabelText('Session metrics')).toBeNull();
});

it('scopes responsive styles and focus rules without adding animations', () => {
  expect(css).toContain('@media (max-width: 760px)'); expect(css).toContain('@media (max-width: 420px)');
  expect(css).toContain('.workspace-shell .workspace-pages'); expect(css).toContain('flex-wrap: wrap');
  expect(css).toContain('min-width: 0'); expect(css).toContain(':focus-visible'); expect(css).not.toMatch(/animation:|height:\s*100vh/);
});


it('loads the shell as a linked stylesheet under the unchanged restrictive CSP', () => {
  const html = readFileSync('index.html', 'utf8');
  const doc = new DOMParser().parseFromString(html, 'text/html');
  expect(doc.querySelectorAll('link[rel="stylesheet"][href="./src/layout/workspace-shell.css"]')).toHaveLength(1);
  expect(doc.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toContain("style-src 'self';");
  expect(html).not.toContain("'unsafe-inline'");
  expect(readFileSync('src/layout/WorkspaceShell.tsx', 'utf8')).not.toMatch(/import\s+['"]\.\/workspace-shell\.css['"]/);
});

it('keeps secondary navigation horizontal and content-sized with compact, wrapping buttons', () => {
  const style = document.createElement('style');
  style.textContent = readFileSync('src/styles.css', 'utf8') + '\n' + css;
  document.head.append(style);
  try {
    render(<App />); navigateTo('Sensor Fusion');
    const nav = screen.getByRole('navigation', { name: 'Workspace pages' });
    const computed = getComputedStyle(nav);
    expect(computed.display).toBe('flex'); expect(computed.flexDirection).toBe('row'); expect(computed.flexWrap).toBe('wrap');
    expect(within(nav).getAllByRole('button').map(b => b.textContent)).toEqual(['Observations', 'Sensor Fusion', 'Camera & Evidence']);
    for (const button of within(nav).getAllByRole('button')) {
      const rules = getComputedStyle(button);
      expect(rules.width).toBe('auto'); expect(rules.flexGrow).toBe('0'); expect(rules.minHeight).toBe('36px');
      expect(rules.paddingTop).toBe('6px'); expect(rules.maxWidth).toBe('100%'); expect(rules.overflowWrap).toBe('anywhere');
      expect(button).toBeVisible();
    }
    expect(secondary().getByRole('button', { name: 'Sensor Fusion' })).toHaveAttribute('aria-current', 'page');
    expect(primary().getAllByRole('button')).toHaveLength(5);
    expect(getComputedStyle(screen.getByRole('navigation', { name: 'Workspaces' })).flexDirection).toBe('column');
  } finally { style.remove(); }
});
