import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import App from '../src/App';
import { navigateTo } from './navigation';
import { inspectSnapshot } from '../src/fusion/inspection';
import { loadSession } from '../src/validate';
import fixtureText from '../src/data/session.json?raw';

const shellCSS = readFileSync('src/layout/workspace-shell.css', 'utf8');

it('keeps narrow navigation in one scrollable row with five content-sized buttons', () => {
  // jsdom does not evaluate viewport media queries: apply the actual narrow rules explicitly.
  const narrow = shellCSS.split('@media (max-width: 760px) {')[1]!.split('@media (max-width: 420px)')[0]!.trim().slice(0, -1);
  const style = document.createElement('style'); style.textContent = shellCSS + narrow;
  document.head.append(style);
  try {
    render(<App />);
    const nav = screen.getByRole('navigation', { name: 'Workspaces' });
    expect(nav).toHaveAccessibleDescription(/Scroll horizontally or Tab/);
    expect(getComputedStyle(nav).flexDirection).toBe('row');
    expect(getComputedStyle(nav).flexWrap).toBe('nowrap');
    expect(getComputedStyle(nav).overflowX).toBe('auto');
    for (const button of within(nav).getAllByRole('button')) {
      expect(getComputedStyle(button).flexShrink).toBe('0');
      expect(getComputedStyle(button).width).toBe('auto');
    }
    expect(within(nav).getAllByRole('button')).toHaveLength(5);
    expect(within(nav).getByRole('button', { name: 'Command Center' })).toHaveAttribute('aria-current', 'page');
  } finally { style.remove(); }
});

it('allows keyboard traversal and activation of all workspaces without a trap', async () => {
  render(<App />); const user = userEvent.setup();
  await user.tab(); expect(screen.getByRole('link', { name: 'Skip to monitoring content' })).toHaveFocus();
  const nav = screen.getByRole('navigation', { name: 'Workspaces' });
  for (const button of within(nav).getAllByRole('button')) {
    await user.tab(); expect(button).toHaveFocus(); await user.keyboard('{Enter}');
    expect(button).toHaveAttribute('aria-current', 'page');
  }
  await user.tab();
  expect(within(screen.getByRole('navigation', { name: 'Workspace pages' })).getByRole('button', { name: 'Alerts & Copilot' })).toHaveFocus();
});

it('allows header metadata to shrink and wrap while keeping source indicators', () => {
  expect(shellCSS).toContain('.workspace-shell .topbar > *, .workspace-shell .system-telemetry > span { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }');
  expect(shellCSS).toContain('.workspace-shell .system-telemetry { flex: 1 1 20rem; max-width: 100%; }');
  render(<App />);
  expect(screen.getByText('OFFLINE')).toBeVisible(); expect(screen.getByText('READ ONLY')).toBeVisible();
  expect(screen.getByLabelText('Monitoring fixture summary')).toBeVisible();
});

it('labels evidence scrolling and supports bounded arrows without intercepting node keys', async () => {
  render(<App />); navigateTo('Sensor Fusion'); const user = userEvent.setup();
  const diagram = screen.getByRole('region', { name: 'Scrollable reference diagram' });
  expect(diagram).toHaveAccessibleDescription(/Left\/Right arrow keys.*Complete reference relationships/);
  Object.defineProperties(diagram, { scrollWidth: { value: 1000 }, clientWidth: { value: 400 } });
  diagram.focus(); await user.keyboard('{ArrowRight}'); expect(diagram.scrollLeft).toBe(160);
  await user.keyboard('{ArrowLeft}{ArrowLeft}'); expect(diagram.scrollLeft).toBe(0);
  diagram.scrollLeft = 590; await user.keyboard('{ArrowRight}'); expect(diagram.scrollLeft).toBe(600);
  const node = within(diagram).getAllByRole('button')[0]!;
  fireEvent.keyDown(node, { key: 'ArrowLeft' }); expect(diagram.scrollLeft).toBe(600);
  diagram.focus(); await user.tab(); expect(node).toHaveFocus();
  await user.keyboard('{Enter}'); expect(diagram).not.toHaveFocus();
});

it('retains every declared relationship in the expandable text alternative', async () => {
  render(<App />); navigateTo('Sensor Fusion'); const user = userEvent.setup();
  const summary = screen.getByText('Complete reference relationships');
  const details = summary.closest('details')!;
  expect(details).not.toHaveAttribute('open'); await user.click(summary);
  expect(details).toHaveAttribute('open');
  const edges = inspectSnapshot(loadSession(fixtureText).final_snapshot).edges;
  const items = within(details).getAllByRole('listitem');
  expect(items).toHaveLength(edges.length);
  edges.forEach((edge, i) => expect(items[i]).toHaveTextContent(`${edge.from} → ${edge.to}: ${edge.relation}`));
  await user.click(summary); expect(details).not.toHaveAttribute('open');
});
