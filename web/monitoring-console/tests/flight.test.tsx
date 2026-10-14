import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { FlightOperations, displayValue } from '../src/flight/FlightOperations';
import { DEMO_VEHICLES } from '../src/flight/demo';
import fixtureText from '../src/data/session.json?raw';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const selected = () => screen.getByRole('region', { name: 'Selected vehicle details' });
const open = () => { render(<App />); fireEvent.click(screen.getByRole('button', { name: 'Flight Operations' })); };

it('adds accessible Flight Operations navigation and its read-only sections', () => {
  open(); expect(screen.getByRole('heading', { name: 'Flight Operations', level: 1 })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Flight Operations' })).toHaveAttribute('aria-current', 'page');
  for (const name of ['Vehicle overview', 'Vehicle camera', 'Flight telemetry', 'Fleet overview', 'Operator safety']) expect(screen.getByRole('heading', { name, level: 2 })).toBeVisible();
});

it('declares exactly five unique fictional platform/environment slots with no connected source', () => {
  expect(DEMO_VEHICLES).toHaveLength(5); expect(new Set(DEMO_VEHICLES.map(v => v.vehicleId)).size).toBe(5);
  expect(DEMO_VEHICLES.map(v => `${v.platform}/${v.environment}`)).toEqual(['PX4/REAL', 'ArduPilot/REAL', 'PX4/SITL', 'ArduPilot/SITL', 'Simulation/SYNTHETIC']);
  for (const v of DEMO_VEHICLES) { expect(v.provenance.kind).toBe('synthetic_demo'); expect(v.connection).not.toBe('connected'); expect(v.lastUpdate.state).toBe('unavailable'); }
});

it('updates only local selection from the vehicle selector and preserves full identifiers', () => {
  render(<FlightOperations />);
  for (const v of DEMO_VEHICLES) {
    fireEvent.change(screen.getByLabelText('Selected flight vehicle'), { target: { value: v.vehicleId } });
    expect(selected()).toHaveTextContent(v.vehicleId); expect(selected()).toHaveTextContent(v.platform); expect(selected()).toHaveTextContent(v.environment);
    expect(selected()).toHaveTextContent(v.provenance.reference);
  }
});

it('keeps fleet cards independent and synchronized with inspection selection', () => {
  render(<FlightOperations />); const fleet = screen.getByLabelText('Demonstration vehicle fleet');
  expect(within(fleet).getAllByRole('article')).toHaveLength(5);
  for (const v of DEMO_VEHICLES) {
    const b = screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }); fireEvent.click(b);
    expect(screen.getByLabelText('Selected flight vehicle')).toHaveValue(v.vehicleId); expect(b).toHaveAttribute('aria-pressed', 'true');
    expect(within(fleet).getAllByRole('button').filter(button => button.getAttribute('aria-pressed') === 'true')).toHaveLength(1);
  }
});

it('never mistakes REAL or SITL integration labels for real connectivity', () => {
  render(<FlightOperations />);
  expect(screen.getByText(/All entries are fictional interface slots/)).toHaveTextContent('No real vehicle or simulator is connected');
  for (const v of DEMO_VEHICLES.filter(v => v.environment !== 'SYNTHETIC')) {
    fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }));
    expect(selected()).toHaveTextContent('NOT CONNECTED'); expect(selected()).toHaveTextContent('DEMO SLOT');
    expect(selected()).toHaveTextContent('future integration categories only');
  }
});

it('keeps synthetic records explicitly separate from future real/SITL categories', () => {
  render(<FlightOperations />); const v = DEMO_VEHICLES[4]!;
  fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }));
  expect(selected()).toHaveTextContent('SYNTHETIC'); expect(selected()).toHaveTextContent('OFFLINE DEMO · NO VEHICLE LINK');
  expect(selected()).not.toHaveTextContent('SITL'); expect(selected()).not.toHaveTextContent('REAL');
});

it('renders unavailable telemetry for every slot without invented measurements or zero defaults', () => {
  render(<FlightOperations />);
  for (const v of DEMO_VEHICLES) {
    fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }));
    const telemetry = screen.getByLabelText('Selected vehicle telemetry');
    for (const name of ['Altitude', 'Ground speed', 'Battery', 'Flight mode', 'Link health']) expect(within(telemetry).getByText(name)).toBeVisible();
    expect(telemetry.querySelectorAll('dd')).toHaveLength(5);
    telemetry.querySelectorAll('dd').forEach(value => { expect(value).toHaveTextContent(/^Unavailable — /); expect(value.textContent).not.toMatch(/\d/); });
  }
});

it('formats only explicitly supplied presentation values and keeps missing units from looking measured', () => {
  expect(displayValue({ state: 'supplied', value: 12 }, 'm')).toBe('12 m');
  expect(displayValue({ state: 'supplied', value: 'Example mode' })).toBe('Example mode');
  expect(displayValue({ state: 'unavailable', reason: 'Not supplied' }, 'm/s')).toBe('Unavailable — Not supplied');
});

it('uses camera placeholders with no media URLs and switches only supplied camera identity', () => {
  const { container } = render(<FlightOperations />);
  expect(screen.getByText('NO VERIFIED CAMERA FEED')).toBeVisible();
  expect(container.querySelector('video,audio,iframe,img')).toBeNull();
  const v = DEMO_VEHICLES[4]!; fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }));
  expect(screen.getAllByText(v.camera.cameraId!).length).toBeGreaterThan(0);
  expect(screen.getByText('NO VERIFIED CAMERA FEED')).toBeVisible(); expect(container.querySelector('[src]')).toBeNull();
});

it('exposes no command-capable or misleading disabled flight controls', () => {
  const { container } = render(<FlightOperations />);
  expect(screen.getByText('READ ONLY · NO ACTIVE CONTROL LINK · NO COMMAND CAPABILITY')).toBeVisible();
  expect(screen.queryByRole('button', { name: /arm|takeoff|land|mission|joystick|connect|dispatch|engage|intercept|swarm/i })).toBeNull();
  expect(container.querySelector('form,input,button:disabled')).toBeNull();
  for (const button of screen.getAllByRole('button')) expect(button.textContent).toMatch(/Inspect vehicle|Fullscreen placeholder/);
});

it('supports keyboard fleet selection and the vehicle selector', async () => {
  const user = userEvent.setup(); render(<FlightOperations />);
  const v = DEMO_VEHICLES[3]!; await user.selectOptions(screen.getByLabelText('Selected flight vehicle'), v.vehicleId); expect(selected()).toHaveTextContent(v.vehicleId);
  const other = DEMO_VEHICLES[4]!; screen.getByRole('button', { name: `Inspect flight vehicle ${other.vehicleId}` }).focus(); await user.keyboard('{Enter}');
  expect(screen.getByLabelText('Selected flight vehicle')).toHaveValue(other.vehicleId);
});

it('keeps deeply frozen demo records and monitoring data unchanged through selection', () => {
  const before = JSON.stringify(DEMO_VEHICLES); const fixture = fixtureText;
  for (const v of DEMO_VEHICLES) {
    expect(Object.isFrozen(v)).toBe(true); expect(Object.isFrozen(v.telemetry)).toBe(true); expect(Object.isFrozen(v.camera)).toBe(true); expect(Object.isFrozen(v.provenance)).toBe(true);
    expect(Object.isFrozen(v.telemetry.altitude)).toBe(true);
  }
  open(); fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${DEMO_VEHICLES[4]!.vehicleId}` }));
  expect(JSON.stringify(DEMO_VEHICLES)).toBe(before); expect(fixtureText).toBe(fixture);
  fireEvent.click(screen.getByRole('button', { name: 'Overview' })); expect(screen.getByRole('article', { name: 'Devices' }).querySelector('strong')).toHaveTextContent('03');
});

it('preserves observation, radar, analyst, graph and simulation behavior after workspace navigation', () => {
  open(); fireEvent.click(screen.getByRole('button', { name: 'Observations' }));
  expect(screen.getByText('No observation markers')).toBeVisible(); fireEvent.click(screen.getByRole('button', { name: /monitor-unusual/ }));
  expect(screen.getByRole('region', { name: 'Validated observation inspector' })).toHaveTextContent('Illustrative missing context.');
  fireEvent.click(screen.getByRole('button', { name: 'Sensor Fusion' })); expect(screen.getByRole('heading', { name: 'AEGIS AI Analyst' })).toBeVisible();
  expect(screen.getByRole('group', { name: 'Declared reference relationships' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Simulation' })); fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
});

it('makes no network or hardware camera requests and installs no command path', () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const xhr = vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(() => { throw new Error('network forbidden'); });
  const socket = vi.spyOn(globalThis, 'WebSocket').mockImplementation(() => { throw new Error('network forbidden'); });
  const media = vi.fn().mockRejectedValue(new Error('camera forbidden'));
  const prior = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: media } });
  try { render(<FlightOperations />); for (const v of DEMO_VEHICLES) fireEvent.click(screen.getByRole('button', { name: `Inspect flight vehicle ${v.vehicleId}` }));
    expect(fetch).not.toHaveBeenCalled(); expect(xhr).not.toHaveBeenCalled(); expect(socket).not.toHaveBeenCalled(); expect(media).not.toHaveBeenCalled();
  } finally { if (prior) Object.defineProperty(navigator, 'mediaDevices', prior); else delete (navigator as unknown as Record<string, unknown>).mediaDevices; }
});

it('renders the offline workspace deterministically with no implicit assets or scripts', () => {
  const first = renderToStaticMarkup(<FlightOperations />); expect(first).toBe(renderToStaticMarkup(<FlightOperations />));
  expect(first).not.toMatch(/<script|<iframe|<video|<form/); expect(first).toContain('NO VERIFIED CAMERA FEED');
});
