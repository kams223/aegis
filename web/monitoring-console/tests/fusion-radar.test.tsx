import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { RadarDisplay } from '../src/radar/RadarDisplay';
import { SensorFusionPanel, SensorDiagnostics } from '../src/fusion/SensorFusionPanel';
import { inspectSnapshot } from '../src/fusion/inspection';
import { loadSession, validateSession } from '../src/validate';
import fixtureText from '../src/data/session.json?raw';
import { readFileSync } from 'node:fs';

const fixture = () => loadSession(fixtureText);
const originalFullscreen = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  if (originalFullscreen) Object.defineProperty(document, 'fullscreenElement', originalFullscreen);
  else delete (document as unknown as Record<string, unknown>).fullscreenElement;
});

it('changes decorative ring density without adding spatial observation markers', () => {
  const { container } = render(<RadarDisplay />);
  expect(container.querySelectorAll('.radar-grid circle')).toHaveLength(4);
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '8' } });
  expect(container.querySelectorAll('.radar-grid circle')).toHaveLength(8);
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '3' } });
  expect(container.querySelectorAll('.radar-grid circle')).toHaveLength(3);
  expect(screen.getByText('No spatial observation positions are supplied.')).toBeVisible();
  expect(screen.getByText('No observation markers')).toBeVisible();
  expect(container.querySelector('[data-observation-position]')).toBeNull();
});

it('pauses the decorative sweep and toggles decorative history using keyboard controls', async () => {
  const user = userEvent.setup(); const { container } = render(<RadarDisplay />);
  screen.getByRole('button', { name: 'Pause decorative sweep' }).focus(); await user.keyboard('{Enter}');
  expect(container.querySelector('.radar-frame')).toHaveClass('scan-paused');
  await user.keyboard('{Enter}'); expect(container.querySelector('.radar-frame')).not.toHaveClass('scan-paused');
  expect(container.querySelector('.scan-history')).not.toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Decorative scan history' }));
  expect(container.querySelector('.scan-history')).toBeNull();
});

it('keeps reduced-motion sweep static, reports the preference, and cleans up listeners', () => {
  const remove = vi.fn(); let update: (() => void) | undefined;
  const query = { matches: true, addEventListener: vi.fn((_name, fn) => { update = fn; }), removeEventListener: remove };
  vi.stubGlobal('matchMedia', vi.fn(() => query));
  const { container, unmount } = render(<RadarDisplay />);
  expect(screen.getByRole('button', { name: 'Resume decorative sweep' })).toBeDisabled();
  expect(container.querySelector('.radar-frame')).toHaveClass('scan-paused');
  expect(screen.getByText('Reduced motion: radar sweep is static.')).toBeVisible();
  act(() => { query.matches = false; update?.(); });
  expect(screen.getByRole('button', { name: 'Pause decorative sweep' })).toBeEnabled();
  unmount(); expect(remove).toHaveBeenCalled();
});

it('requests radar fullscreen and handles native exit notifications', async () => {
  const { container } = render(<RadarDisplay />); const frame = container.querySelector('.radar-frame')!;
  let full: Element | null = null;
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => full });
  const request = vi.fn(async () => { full = frame; document.dispatchEvent(new Event('fullscreenchange')); });
  Object.defineProperty(frame, 'requestFullscreen', { value: request });
  const exit = vi.fn(async () => { full = null; document.dispatchEvent(new Event('fullscreenchange')); });
  Object.defineProperty(document, 'exitFullscreen', { value: exit, configurable: true });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Exit radar fullscreen' }));
  expect(request).toHaveBeenCalledOnce(); expect(exit).toHaveBeenCalledOnce();
  expect(await screen.findByRole('button', { name: 'Fullscreen radar' })).toBeVisible();
});

it('shows fullscreen unavailability and permission failures without touching fixture data', async () => {
  const { container } = render(<RadarDisplay />);
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' }));
  expect(await screen.findByText('Radar fullscreen unavailable in this browser.')).toBeVisible();
  Object.defineProperty(container.querySelector('.radar-frame'), 'requestFullscreen', { value: vi.fn().mockRejectedValue(new Error('denied')) });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' }));
  expect(await screen.findByText('Radar fullscreen unavailable or permission denied.')).toBeVisible();
});

it('projects exactly the supplied source inventory and preserves its ordering and caller input', () => {
  const snapshot = fixture().final_snapshot; const before = JSON.stringify(snapshot);
  const inspection = inspectSnapshot(snapshot);
  expect(inspection.sensors.map(r => r.source.source_id)).toEqual(['camera-a', 'metadata-g', 'display-r']);
  expect(inspection.sensors.map(r => r.availability)).toEqual(['unknown', 'unavailable', 'unknown']);
  expect(inspection.sensors.map(r => r.device.health.status)).toEqual(['degraded', 'unknown', 'unknown']);
  expect(inspection.sensors.map(r => r.evidence.length)).toEqual([2, 1, 1]);
  expect(inspection.sensors.map(r => r.observations.length)).toEqual([0, 1, 2]);
  expect(JSON.stringify(snapshot)).toBe(before);
});

it('does not infer sensor type from an identifier, device capability or camera evidence', () => {
  render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  const table = screen.getByRole('table'); const rows = within(table).getAllByRole('row').slice(1);
  rows.forEach(row => expect(within(row).getAllByRole('cell')[2]).toHaveTextContent('Not supplied'));
  expect(screen.getByText(/not separate physical sensor IDs/)).toBeVisible();
  expect(screen.getAllByText(/sensor health not supplied/, { selector: 'small' })).toHaveLength(3);
});

it('keeps device health timestamps and missing source timestamps distinct', () => {
  render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  const row = within(screen.getByRole('table')).getAllByRole('row')[1]!;
  const cells = within(row).getAllByRole('cell');
  expect(cells[4]).toHaveTextContent('degraded'); expect(cells[4]).toHaveTextContent('2 s'); expect(cells[4]).toHaveTextContent('demo:camera-a');
  expect(cells[5]).toHaveTextContent('Not supplied');
});

it('records only explicit graph relationships despite shared recording paths', () => {
  const snapshot = fixture().final_snapshot; const graph = inspectSnapshot(snapshot);
  expect(graph.nodes).toHaveLength(13); expect(graph.edges).toHaveLength(13);
  expect(graph.edges).toContainEqual({ from: 'device/native-aerial', to: 'source/camera-a', relation: 'declares source' });
  expect(graph.edges).toContainEqual({ from: 'source/camera-a', to: 'evidence/camera-a:recorded', relation: 'evidence source' });
  expect(graph.edges).toContainEqual({ from: 'evidence/display-r:evidence', to: 'observation/monitor-unusual', relation: 'observation evidence' });
  expect(graph.edges.some(e => e.from.startsWith('source/') && e.to.startsWith('source/'))).toBe(false);
  expect(snapshot.evidence.every(e => e.local_path === 'examples/recorded_datasets/placeholder.txt')).toBe(true);
  expect(graph.edges.some(e => e.from === 'evidence/camera-a:evidence' && e.to === 'evidence/metadata-g:evidence')).toBe(false);
});

it('keeps every reference node fully inside the diagram viewBox', () => {
  const { container } = render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  const svg = screen.getByRole('group', { name: 'Declared reference relationships' });
  const height = Number(svg.getAttribute('viewBox')!.split(' ')[3]);
  for (const node of container.querySelectorAll('.graph-node')) {
    const y = Number(node.getAttribute('transform')!.match(/translate\(\d+ (\d+)\)/)![1]);
    const bottom = y + Number(node.querySelector('rect')!.getAttribute('height'));
    expect(bottom).toBeLessThanOrEqual(height);
  }
});

it('rejects dangling and duplicate graph references instead of silently repairing them', () => {
  const bad = fixture().final_snapshot; bad.evidence.pop();
  // Remove primary evidence, which is still referenced by a source.
  bad.evidence.splice(0, 1); expect(() => inspectSnapshot(bad)).toThrow(/resolved/);
  const duplicate = fixture().final_snapshot; duplicate.registry.devices.push(duplicate.registry.devices[0]!);
  expect(() => inspectSnapshot(duplicate)).toThrow(/unique/);
});

it('selects source, observation and evidence records and keeps evidence paths as plain text', () => {
  const { container } = render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect source display-r' }));
  expect(screen.getByRole('heading', { name: 'source: display-r' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect observation monitor-unusual' }));
  expect(container.querySelector('.inspection-json')).toHaveTextContent('Illustrative missing context.');
  fireEvent.click(screen.getByRole('button', { name: 'Inspect evidence camera-a:recorded' }));
  expect(container.querySelector('.inspection-json')).toHaveTextContent('examples/recorded_datasets/placeholder.txt');
  expect(container.querySelector('a, video, audio, iframe')).toBeNull();
});

it('supports keyboard selection in the relationship diagram', async () => {
  const user = userEvent.setup(); render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  screen.getByRole('button', { name: 'Diagram: observation display-normal' }).focus(); await user.keyboard('{Enter}');
  expect(screen.getByRole('heading', { name: 'observation: display-normal' })).toBeVisible();
});

it('shows no fusion computation or fabricated confidence scores', () => {
  const { container } = render(<SensorFusionPanel snapshot={fixture().final_snapshot} />);
  expect(screen.getByText('NO VALIDATED FUSION OUTPUTS AVAILABLE')).toBeVisible();
  expect(screen.getByText(/cannot claim a fusion computation occurred/)).toBeVisible();
  expect(screen.getByText('Confidence percentages and sensor quality scores: Not supplied.')).toBeVisible();
  expect(container.textContent).not.toMatch(/\d+(?:\.\d+)?%/);
});

it('keeps supplied metadata failure and verified-byte status independent', () => {
  const snapshot = fixture().final_snapshot;
  snapshot.evidence.push({ schema_version: 1, evidence_id: 'test-report', source_id: 'display-r', kind: 'validation_result', local_path: 'test/report.json', dataset_id: 'test-dataset' });
  snapshot.validation_results.push({ schema_version: 1, evidence_id: 'test-report', dataset_id: 'test-dataset', metadata_status: 'failed', integrity_status: 'verified' });
  render(<SensorDiagnostics snapshot={snapshot} />);
  expect(screen.getByText(/test-report: metadata failed, integrity verified/)).toBeVisible();
});

it('shows unavailable inventory clearly for a valid empty fixture', () => {
  const session = fixture(); const s = session.final_snapshot;
  s.registry.devices = []; s.evidence = []; s.observations = []; s.sentinels = []; s.alerts = []; s.investigation_requests = []; s.investigation_results = []; s.review_history = []; s.audit_entries = []; s.validation_results = [];
  session.event_results = []; session.summary = { schema_version: 1, event_count: 0, applied_count: 0, rejected_count: 0, status: 'completed' };
  render(<App text={JSON.stringify(validateSession(session))} />); fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' }));
  expect(screen.getAllByText('No declared sensor inputs are supplied.')).toHaveLength(2);
  expect(screen.getByText('No metadata selected.')).toBeVisible();
});

it('rejects attempted new fusion fields and unsafe paths at the unchanged fixture boundary', () => {
  const session = JSON.parse(fixtureText); session.final_snapshot.fusion_outputs = [{ confidence: 99 }];
  expect(() => validateSession(session)).toThrow(/fields/);
  const unsafe = fixture(); unsafe.final_snapshot.evidence[0]!.local_path = 'https://example.com/video.mp4';
  expect(() => validateSession(unsafe)).toThrow(/unsafe/);
  render(<App text={JSON.stringify(session)} />); expect(screen.getByRole('alert')).toBeVisible(); expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
});

it('renders deterministic escaped inspection metadata with no external services', () => {
  const snapshot = fixture().final_snapshot; snapshot.observations[0]!.annotation = '<script>alert(1)</script>';
  const html = renderToStaticMarkup(<SensorFusionPanel snapshot={snapshot} />);
  expect(html).toBe(renderToStaticMarkup(<SensorFusionPanel snapshot={snapshot} />)); expect(html).not.toContain('<script>');
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const { container } = render(<SensorFusionPanel snapshot={snapshot} />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect observation display-normal' }));
  expect(container.querySelector('.inspection-json')).toHaveTextContent('<script>alert(1)</script>');
  expect(container.querySelector('script, iframe, video, form')).toBeNull(); expect(fetch).not.toHaveBeenCalled();
});

it('preserves demo playback when adjusting the dashboard radar and adds fusion navigation', () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '6' } });
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  expect(screen.getByRole('article', { name: 'Applied events' }).querySelector('strong')).toHaveTextContent('06');
  fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' }));
  expect(screen.getByRole('heading', { name: 'Sensor Fusion', level: 1 })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Sensor Fusion' })).toHaveAttribute('aria-current', 'page');
});

it('places essential demo playback controls before secondary view controls and bounds responsive structure', () => {
  const { container } = render(<App />);
  const play = screen.getByRole('button', { name: 'Play simulation' });
  const view = screen.getByRole('button', { name: 'Orbit left' });
  expect(play.compareDocumentPosition(view) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(container.querySelectorAll('.visual-grid > section')).toHaveLength(3);
  const css = readFileSync('src/styles.css', 'utf-8');
  expect(css).toContain('.radar-frame:fullscreen'); expect(css).toContain('.reference-diagram { overflow: auto');
  expect(css).toContain('.visual-grid, .fusion-inspection-grid { grid-template-columns: 1fr; }');
});

it('preserves readable complete device declarations in an accessible scrollable table', () => {
  render(<App />);
  const scroller = screen.getByLabelText('Compact device status table');
  expect(scroller).toHaveAttribute('tabindex', '0');
  const table = within(scroller).getByRole('table');
  expect(within(table).getAllByRole('columnheader')).toHaveLength(6);
  for (const device of fixture().final_snapshot.registry.devices) {
    expect(within(table).getByText(device.device_id)).toBeVisible();
    expect(within(table).getAllByText(device.health.status).length).toBeGreaterThan(0);
  }
  const css = readFileSync('src/styles.css', 'utf-8');
  expect(css).toContain('.device-status th, .device-status td { overflow-wrap: normal; word-break: normal; }');
  expect(css).toContain('.device-status td:first-child code, .device-status .compact-list li { white-space: nowrap; }');
  expect(css).toContain('.device-status table { min-width: 640px; table-layout: auto; }');
});

it('keeps fullscreen radar controls grouped and preserves inspection and sweep state on native exit', async () => {
  const { container } = render(<RadarDisplay><p>Observation inspection remains available</p></RadarDisplay>);
  const frame = container.querySelector('.radar-frame')!;
  let full: Element | null = null;
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => full });
  Object.defineProperty(frame, 'requestFullscreen', { value: vi.fn(async () => { full = frame; document.dispatchEvent(new Event('fullscreenchange')); }) });
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '6' } });
  fireEvent.click(screen.getByRole('button', { name: 'Pause decorative sweep' }));
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' }));
  await screen.findByRole('button', { name: 'Exit radar fullscreen' });
  expect(within(frame as HTMLElement).getByText('Observation inspection remains available')).toBeVisible();
  act(() => { full = null; document.dispatchEvent(new Event('fullscreenchange')); });
  expect(screen.getByRole('button', { name: 'Fullscreen radar' })).toBeVisible();
  expect(screen.getByLabelText('Decorative ring density')).toHaveValue('6');
  expect(frame).toHaveClass('scan-paused');
  const css = readFileSync('src/styles.css', 'utf-8');
  expect(css).toContain('.radar-frame:fullscreen .radar-controls { position: sticky; top: 0;');
  expect(css).toContain('grid-template-columns: minmax(180px, 240px) repeat(3, max-content)');
  expect(css).toContain('.radar-frame:fullscreen .radar-controls label { grid-column: 1 / -1; }');
});

const enableDemo = () => fireEvent.click(screen.getByRole('button', { name: 'SHOW SYNTHETIC DEMO MARKERS' }));
const marker = (number: number) => screen.getByRole('button', { name: new RegExp(`Inspect synthetic demo demo-marker-0${number}:`) });

it('keeps demo markers off by default and shows exactly four explicitly fictional markers on opt-in', () => {
  const { container } = render(<RadarDisplay />);
  expect(screen.getByRole('button', { name: 'SHOW SYNTHETIC DEMO MARKERS' })).toHaveAttribute('aria-pressed', 'false');
  expect(container.querySelectorAll('.demo-marker')).toHaveLength(0);
  enableDemo();
  expect(container.querySelectorAll('.demo-marker')).toHaveLength(4);
  expect(screen.getByText('SYNTHETIC DEMONSTRATION — MARKER POSITIONS ARE NOT SENSOR MEASUREMENTS')).toBeVisible();
  expect(screen.getByText('No spatial observation positions are supplied.')).toBeVisible();
  enableDemo(); expect(container.querySelectorAll('.demo-marker')).toHaveLength(0);
  expect(screen.getByText('No observation markers')).toBeVisible();
});

it('selects markers by pointer and keeps read-only details truthful with bounded previous and next navigation', () => {
  render(<RadarDisplay />); enableDemo(); fireEvent.click(marker(1));
  const details = screen.getByRole('region', { name: 'Synthetic demo observation details' });
  expect(within(details).getByRole('heading', { name: 'demo-marker-01' })).toHaveFocus();
  expect(details).toHaveTextContent('Illustrative observation Alpha'); expect(details).toHaveTextContent('SYNTHETIC DEMO');
  expect(details).toHaveTextContent('0 s · demo-only clock'); expect(details).toHaveTextContent('NOT AVAILABLE');
  expect(details).toHaveTextContent('NOT ESTABLISHED'); expect(details).toHaveTextContent('Not sensor measurements');
  expect(screen.getByRole('button', { name: 'Previous demo observation' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Next demo observation' }));
  expect(details).toHaveTextContent('demo-marker-02'); expect(details).toHaveTextContent('Not supplied');
  fireEvent.click(screen.getByRole('button', { name: 'Previous demo observation' }));
  expect(details).toHaveTextContent('demo-marker-01');
  fireEvent.click(marker(4)); expect(screen.getByRole('button', { name: 'Next demo observation' })).toBeDisabled();
  expect(marker(4)).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Close demo details' }));
  expect(screen.queryByRole('region', { name: 'Synthetic demo observation details' })).toBeNull();
  expect(marker(4)).toHaveFocus(); expect(marker(4)).toHaveAttribute('aria-pressed', 'false');
});

it('supports Enter and Space marker selection and clears selection when the layer is disabled', async () => {
  const user = userEvent.setup(); render(<RadarDisplay />); enableDemo();
  marker(2).focus(); await user.keyboard('{Enter}');
  expect(screen.getByRole('heading', { name: 'demo-marker-02' })).toHaveFocus();
  marker(3).focus(); await user.keyboard(' ');
  expect(screen.getByRole('heading', { name: 'demo-marker-03' })).toHaveFocus();
  enableDemo(); enableDemo();
  expect(screen.queryByRole('region', { name: 'Synthetic demo observation details' })).toBeNull();
});

it('retains marker selection through native fullscreen entry and exit', async () => {
  const { container } = render(<RadarDisplay />); enableDemo(); fireEvent.click(marker(2));
  const frame = container.querySelector('.radar-frame')!; let full: Element | null = null;
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => full });
  Object.defineProperty(frame, 'requestFullscreen', { value: vi.fn(async () => { full = frame; document.dispatchEvent(new Event('fullscreenchange')); }) });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen radar' }));
  await screen.findByRole('button', { name: 'Exit radar fullscreen' });
  expect(within(frame as HTMLElement).getByRole('heading', { name: 'demo-marker-02' })).toBeVisible();
  act(() => { full = null; document.dispatchEvent(new Event('fullscreenchange')); });
  expect(marker(2)).toHaveAttribute('aria-pressed', 'true');
});

it('keeps markers static and usable under reduced motion while preserving decorative controls', () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const { container } = render(<RadarDisplay />); enableDemo(); fireEvent.click(marker(1));
  expect(screen.getByRole('button', { name: 'Resume decorative sweep' })).toBeDisabled();
  expect(container.querySelector('.demo-marker')!.closest('.radar-sweep')).toBeNull();
  fireEvent.change(screen.getByLabelText('Decorative ring density'), { target: { value: '8' } });
  fireEvent.click(screen.getByRole('button', { name: 'Decorative scan history' }));
  expect(container.querySelectorAll('.radar-grid circle')).toHaveLength(8);
  expect(container.querySelector('.scan-history')).toBeNull();
  expect(screen.getByRole('heading', { name: 'demo-marker-01' })).toBeVisible();
});

it('keeps fictional selection separate from validated observation metadata and simulation state', () => {
  const before = JSON.stringify(fixture()); const { container } = render(<App />);
  enableDemo(); fireEvent.click(marker(1));
  const validated = fixture().final_snapshot.observations;
  for (const observation of validated) {
    fireEvent.click(screen.getByRole('button', { name: `${observation.observation_id}${observation.quality}` }));
    expect(screen.getByText(observation.annotation)).toBeVisible();
    expect(container.querySelector('.demo-observation-details')).not.toHaveTextContent(observation.observation_id);
  }
  expect(container.querySelectorAll('[data-demo-id]')).toHaveLength(4);
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  expect(JSON.stringify(fixture())).toBe(before);
});
