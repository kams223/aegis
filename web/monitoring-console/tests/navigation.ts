import { fireEvent, screen, within } from '@testing-library/react';
import { workspaceForPage } from '../src/layout/workspaces';
import type { PageId } from '../src/layout/workspaces';

/** Exercise the visible two-level navigation; never query hidden controls. */
export function navigateTo(page: PageId) {
  const workspace = workspaceForPage(page);
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspaces' })).getByRole('button', { name: workspace.label }));
  const label = workspace.pages.find(p => p.id === page)!.label;
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Workspace pages' })).getByRole('button', { name: label }));
}
