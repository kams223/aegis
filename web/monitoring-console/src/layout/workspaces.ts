export const WORKSPACES = [
  { id: 'command', label: 'Command Center', context: 'Synthetic monitoring fixture.', pages: [
    { id: 'Overview', label: 'Overview' }, { id: 'Devices', label: 'Devices' },
  ] },
  { id: 'sensors', label: 'Sensor Lab', context: 'Declared evidence references; clocks not aligned.', pages: [
    { id: 'Observations', label: 'Observations' }, { id: 'Sensor Telemetry', label: 'Sensor Telemetry' }, { id: 'Sensor Fusion', label: 'Sensor Fusion' }, { id: 'Evidence', label: 'Camera & Evidence' },
  ] },
  { id: 'training', label: 'Training Ground', context: 'Illustrative simulation; abstract scene units.', pages: [
    { id: 'Simulation', label: 'Simulation' },
  ] },
  { id: 'fleet', label: 'Fleet Operations', context: 'Fictional demo fleet or imported recorded snapshot. Separate sources; inspect the selected local data view.', pages: [
    { id: 'Flight Operations', label: 'Flight Operations' },
  ] },
  { id: 'investigation', label: 'Investigation', context: 'Synthetic monitoring fixture.', pages: [
    { id: 'Alerts & Copilot', label: 'Alerts & Copilot' }, { id: 'Event replay', label: 'Event Replay' }, { id: 'Review & audit', label: 'Review & Audit' },
  ] },
] as const;

export type Workspace = typeof WORKSPACES[number];
export type WorkspaceId = Workspace['id'];
export type PageId = Workspace['pages'][number]['id'];
export const INITIAL_PAGE: PageId = 'Overview';

export function workspaceForPage(page: PageId): Workspace {
  const workspace = WORKSPACES.find(w => w.pages.some(p => p.id === page));
  if (!workspace) throw new Error('Unknown workspace page');
  return workspace;
}
