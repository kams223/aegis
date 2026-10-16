import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import App from '../src/App';
import { Badge, Card, Metric, MetricGroup } from '../src/components';
import { navigateTo } from './navigation';
import fixture from '../src/data/session.json?raw';
import { loadSession } from '../src/validate';

const css = readFileSync('src/styles.css', 'utf8');
afterEach(() => vi.restoreAllMocks());

it.each([
  ['available', 'good'], ['rejected', 'warning'], ['mismatch', 'critical'],
  ['unknown', 'neutral'], ['offline', 'neutral'], ['not_evaluated', 'neutral'],
])('keeps the declared %s status visible with a reusable %s indicator', (value, tone) => {
  const { container } = render(<Badge value={value} />);
  const badge = screen.getByText(value.replaceAll('_', ' '));
  expect(badge).toHaveAttribute('data-tone', tone); expect(badge).toHaveClass('badge', tone);
  expect(badge.querySelector('.status-dot')).toHaveAttribute('aria-hidden', 'true');
  expect(container.querySelector('[role=status],[aria-live]')).toBeNull();
});

it('preserves semantic card headings, zero metrics and honest metric descriptions', () => {
  render(<Card title="Fixture counters"><MetricGroup><Metric title="Rejected events" value={0} detail="Explicit validation diagnostics" tone="warning" /><Metric title="Devices" value={2} detail="Declared registry entries" /></MetricGroup></Card>);
  expect(screen.getByRole('heading', { level: 2, name: 'Fixture counters' })).toBeVisible();
  const rejected = screen.getByRole('article', { name: 'Rejected events' });
  expect(rejected).toHaveAttribute('data-tone', 'warning'); expect(within(rejected).getByText('00')).toBeVisible();
  expect(within(rejected).getByText('Explicit validation diagnostics')).toBeVisible();
  expect(screen.getByRole('article', { name: 'Devices' })).toHaveAttribute('data-tone', 'neutral');
});

it('puts supplied monitoring records before visual previews without losing tools or counts', () => {
  const before = fixture, session = loadSession(fixture);
  const { container } = render(<App />);
  const dashboard = screen.getByRole('region', { name: 'Command Center dashboard' });
  expect(within(dashboard).getAllByRole('article', { name: 'Devices' })).toHaveLength(1);
  expect(screen.getByRole('article', { name: 'Devices' }).querySelector('strong')).toHaveTextContent(String(session.final_snapshot.registry.devices.length).padStart(2, '0'));
  const records = dashboard.querySelector('.dashboard-bottom')!, previews = dashboard.querySelector('.visual-grid')!;
  expect(records.compareDocumentPosition(previews) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(previews.querySelectorAll(':scope > section')).toHaveLength(3);
  for (const name of ['Tactical radar', 'Drone camera', '3D simulation', 'Device status', 'Recent events', 'Alerts', 'Sensor diagnostics']) expect(within(dashboard).getByRole('heading', { name, level: 2 })).toBeVisible();
  expect(container.querySelectorAll('canvas')).toHaveLength(1); expect(fixture).toBe(before);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect event 7: conflict-1' }));
  expect(screen.getByRole('status')).toHaveTextContent('Event 7 of 7');
  expect(screen.getByRole('heading', { level: 1, name: 'Event Replay' })).toHaveFocus();
});

it('retains five-workspace navigation, keyboard focus and truthful source boundaries', () => {
  render(<App />);
  expect(within(screen.getByRole('navigation', { name: 'Workspaces' })).getAllByRole('button')).toHaveLength(5);
  navigateTo('Flight Operations'); expect(screen.getByText(/Fictional demo fleet or imported recorded snapshot/)).toBeVisible();
  expect(screen.queryByText('MONITORING FIXTURE · FINAL SNAPSHOT')).toBeNull();
  navigateTo('Simulation'); expect(screen.getByText('Illustrative simulation; abstract scene units.')).toBeVisible();
  const next = within(screen.getByRole('navigation', { name: 'Workspaces' })).getByRole('button', { name: 'Sensor Lab' }); next.focus(); expect(next).toHaveFocus();
});

function color(token: string): string {
  const value = css.match(new RegExp(`--${token}:\\s*(#[0-9A-Fa-f]{6})`))?.[1];
  if (!value) throw new Error(`Missing literal color token: ${token}`);
  return value;
}
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map(i => { const x = parseInt(hex.slice(i, i + 2), 16) / 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; });
  return .2126 * r! + .7152 * g! + .0722 * b!;
}
function contrast(a: string, b: string) { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }

it('gives foundation text and status colors adequate contrast against their surfaces', () => {
  for (const surface of ['background', 'sidebar', 'panel', 'elevated', 'surface-hover', 'surface-selected']) {
    for (const foreground of ['text', 'muted']) expect(contrast(color(foreground), color(surface)), `${foreground} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    expect(contrast(color('cyan'), color(surface)), `focus on ${surface}`).toBeGreaterThanOrEqual(3);
  }
  for (const [foreground, background] of [['green', 'status-good-bg'], ['amber', 'status-warning-bg'], ['red', 'status-critical-bg']]) expect(contrast(color(foreground!), color(background!))).toBeGreaterThanOrEqual(4.5);
});

it('keeps transitions restrained and disabled for reduced motion without clipping responsive content', () => {
  expect(css).toContain('--motion-fast: 120ms');
  expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*button \{ transition: none; \}/);
  expect(css).toContain('.command-dashboard .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }');
  expect(css).toContain('.command-dashboard { display: grid;');
  expect(css).toContain('min-width: 0'); expect(css).toContain(':focus-visible');
  expect(css).not.toMatch(/@import|url\(/);
});

it('adds no network, clocks or random activity through the visual foundation', () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw new Error('network forbidden'); });
  const random = vi.spyOn(Math, 'random');
  render(<App />); navigateTo('Devices'); navigateTo('Sensor Fusion');
  expect(fetch).not.toHaveBeenCalled(); expect(random).not.toHaveBeenCalled();
  expect(document.querySelector('video,audio,iframe')).toBeNull();
});
