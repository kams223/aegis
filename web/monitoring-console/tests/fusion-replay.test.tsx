import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { FusionReplay } from '../src/fusion/FusionReplay';
import { loadSession } from '../src/validate';
import sessionText from '../src/data/session.json?raw';
import replayText from '../src/data/fusion-replay.json?raw';
const session = () => loadSession(sessionText);
const selected = () => within(screen.getByRole('region', { name: 'Selected fusion event' }));
function scrub(frontier: number) { fireEvent.change(screen.getByRole('slider', { name: 'Fusion event frontier' }), { target: { value: String(frontier) } }); }

it('starts at the full recorded frontier, distinguishes rejection and keeps final views accessible', () => {
  render(<FusionReplay session={session()} />);
  expect(screen.getByRole('slider')).toHaveValue('7');
  expect(selected().getByText('CONFLICTING_UPDATE')).toBeVisible();
  expect(selected().getByText(/Rejected — state unchanged/)).toBeVisible();
  expect(screen.getByText('OFFLINE · SYNTHETIC · READ ONLY')).toBeVisible();
  expect(document.querySelectorAll('[data-event-active]')).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('Sensor Fusion state view'), { target: { value: 'final' } });
  expect(screen.queryByRole('slider')).toBeNull(); expect(screen.getByText('Final validated snapshot source inventory')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Sensor Fusion state view'), { target: { value: 'replay' } });
  expect(screen.getByRole('slider')).toHaveValue('7');
});
it('synchronizes scrubber, exact selector, backward/forward and reset, including zero', () => {
  render(<FusionReplay session={session()} />);
  expect(screen.getByRole('button', { name: 'Next fusion event' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Previous fusion event' }));
  expect(screen.getByLabelText('Exact fusion frontier')).toHaveValue('6');
  expect(selected().getByText(/review-1/)).toBeVisible();
  fireEvent.change(screen.getByLabelText('Exact fusion frontier'), { target: { value: '4' } });
  expect(screen.getByRole('slider')).toHaveValue('4');
  fireEvent.click(screen.getByRole('button', { name: 'Next fusion event' }));
  expect(screen.getByRole('slider')).toHaveValue('5');
  fireEvent.click(screen.getByRole('button', { name: 'Reset fusion replay' }));
  expect(screen.getByRole('slider')).toHaveValue('0'); expect(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', 'Before first event');
  expect(screen.getByRole('button', { name: 'Previous fusion event' })).toBeDisabled();
  expect(selected().getByText(/No selected record/)).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Diagram: observation monitor-unusual' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Diagram: evidence camera-a:recorded' })).toBeNull();
});
it('shows only actual source activity and preserves unavailable and missing states', () => {
  render(<FusionReplay session={session()} />); scrub(1);
  expect(screen.getByRole('button', { name: 'Diagram: source camera-a' })).not.toHaveAttribute('data-event-active');
  expect(selected().getByText('Not supplied — device-level event')).toBeVisible();
  scrub(3);
  expect(screen.getByRole('button', { name: 'Diagram: source metadata-g' })).toHaveAttribute('data-event-active', 'true');
  expect(screen.getByRole('button', { name: 'Diagram: source camera-a' })).not.toHaveAttribute('data-event-active');
  const inventory = screen.getByRole('table', { name: /source inventory/ });
  const sourceRow = within(inventory).getByRole('button', { name: 'Inspect source metadata-g' }).closest('tr')!;
  expect(within(sourceRow).getByText('unavailable')).toBeVisible();
  expect(selected().getByText(/demo:metadata-g · clocks not aligned/)).toBeVisible();
});
it('preserves selected timestamps, provenance, uncertainty and graph evidence inspection', async () => {
  render(<FusionReplay session={session()} />); const user = userEvent.setup(); scrub(4);
  await user.click(selected().getByText('Event evidence and provenance'));
  expect(selected().getByText('examples/recorded_datasets/placeholder.txt')).toBeVisible();
  expect(selected().getByText('Not supplied')).toBeVisible();
  scrub(5); await user.click(selected().getByText('Event evidence and provenance'));
  expect(selected().getByText('Illustrative missing context.')).toBeVisible();
  expect(selected().getByText('display-r:evidence')).toBeVisible();
  expect(selected().getAllByText('demo:display-r').length).toBeGreaterThan(0);
  await user.click(screen.getByRole('button', { name: 'Diagram: observation monitor-unusual' }));
  expect(screen.getByRole('heading', { name: 'monitor-unusual' })).toHaveFocus();
  scrub(0); expect(screen.queryByRole('heading', { name: 'monitor-unusual' })).toBeNull();
});
it('keeps controls keyboard reachable and retains focus while stepping', async () => {
  render(<FusionReplay session={session()} />); const user = userEvent.setup();
  const previous = screen.getByRole('button', { name: 'Previous fusion event' });
  previous.focus(); await user.keyboard('{Enter}'); expect(previous).toHaveFocus();
  expect(screen.getByRole('slider')).toHaveValue('6');
  await user.tab(); expect(screen.getByRole('button', { name: 'Next fusion event' })).toHaveFocus();
  await user.keyboard(' '); expect(screen.getByRole('slider')).toHaveValue('7');
  expect(screen.getByRole('slider')).toHaveAttribute('min', '0'); expect(screen.getByRole('slider')).toHaveAttribute('max', '7');
});
it('fails closed for unavailable replay, retaining only the supplied validated final state', () => {
  render(<FusionReplay session={session()} text="{}" />);
  expect(screen.getByRole('alert')).toHaveTextContent('Replay unavailable');
  expect(screen.queryByRole('slider')).toBeNull(); expect(screen.getByText('Final validated snapshot source inventory')).toBeVisible();
});
it('clears old selection on a replacement session and rejects mismatched provenance', () => {
  const { rerender } = render(<FusionReplay session={session()} />); scrub(0);
  const replacement = session(); replacement.initial_snapshot_id = 'different-fixture';
  rerender(<FusionReplay session={replacement} />);
  expect(screen.queryByRole('slider')).toBeNull(); expect(screen.queryByRole('region', { name: 'Selected fusion event' })).toBeNull();
  rerender(<FusionReplay session={session()} />); expect(screen.getByRole('slider')).toHaveValue('7');
});
it('uses finite selection feedback with reduced-motion override and no automatic stream', () => {
  const css = readFileSync('src/styles.css', 'utf8');
  expect(css).toContain('.fusion-event-inspector { animation: fusion-event-selection 180ms ease-out; }');
  expect(css).toContain('@media (prefers-reduced-motion: reduce) { .fusion-event-inspector { animation: none; } }');
  const interval = vi.spyOn(globalThis, 'setInterval');
  try { render(<FusionReplay session={session()} text={replayText} />); scrub(4); expect(interval).not.toHaveBeenCalled(); }
  finally { interval.mockRestore(); }
});

it('shows supplied review and audit provenance in event details', async () => {
  render(<FusionReplay session={session()} />); scrub(6); const user = userEvent.setup();
  await user.click(selected().getByText('Event evidence and provenance'));
  expect(selected().getAllByText('synthetic-operator')).toHaveLength(2);
  expect(selected().getByText('unreviewed → reviewed')).toBeVisible();
  expect(selected().getByText('monitor-review-audit')).toBeVisible();
});
it('keeps an empty replay at zero with no activity and no possible step', () => {
  const empty = JSON.parse(replayText).prefixes[0];
  render(<FusionReplay session={empty} text={JSON.stringify({ schema_version: 1, prefixes: [empty] })} />);
  expect(screen.getByRole('slider')).toHaveValue('0');
  expect(screen.getByRole('button', { name: 'Previous fusion event' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Next fusion event' })).toBeDisabled();
  expect(document.querySelectorAll('[data-event-active]')).toHaveLength(0);
});
it('labels unresolved rejected references as unavailable and attributes no activity', () => {
  const doc = JSON.parse(replayText), last = doc.prefixes.at(-1), event = last.event_results.at(-1);
  event.device_id = 'unknown-device'; event.source_id = 'unknown-source';
  Object.assign(event.diagnostics[0], { device_id: event.device_id, source_id: event.source_id, code: 'UNKNOWN_DEVICE', explanation: 'Event device is not present in the supplied registry.' });
  render(<FusionReplay session={last} text={JSON.stringify(doc)} />);
  expect(selected().getByText('unknown-device — unavailable in this state')).toBeVisible();
  expect(selected().getByText('unknown-source — unavailable in this state')).toBeVisible();
  expect(selected().getByText('UNKNOWN_DEVICE')).toBeVisible();
  expect(document.querySelectorAll('[data-event-active]')).toHaveLength(0);
});
