import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { WORKSPACES, workspaceForPage } from './workspaces';
import type { PageId } from './workspaces';

export function WorkspaceShell({ page, onNavigate, focusRequest, fixtureId, fixtureMetadata, children }: {
  page: PageId;
  onNavigate: (page: PageId) => void;
  focusRequest: number;
  fixtureId: string;
  fixtureMetadata: ReactNode;
  children: ReactNode;
}) {
  const workspace = workspaceForPage(page);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (focusRequest > 0) heading.current?.focus(); }, [focusRequest]);
  const pageLabel = workspace.pages.find(p => p.id === page)!.label;
  const fixtureContext = workspace.id === 'command' || workspace.id === 'sensors' || workspace.id === 'investigation';
  return <div className="console workspace-shell">
    <a className="skip-link" href="#main-content">Skip to monitoring content</a>
    <aside className="sidebar">
      <div className="brand"><svg width="34" height="38" aria-hidden="true" viewBox="0 0 32 36"><path d="M16 2 29 7v13L16 34 3 20V7Z" /><path d="m9 22 7-13 7 13M12 17h8" /></svg><div><strong>AEGIS</strong><small>MONITORING CONSOLE</small></div></div>
      <nav className="workspace-primary" aria-label="Workspaces">
        {WORKSPACES.map(w => <button key={w.id} type="button" aria-current={w.id === workspace.id ? 'page' : undefined} onClick={() => { if (w.id !== workspace.id) onNavigate(w.pages[0].id); }}>{w.label}</button>)}
      </nav>
      <div className="sidebar-footer">Local inspection only · No vehicle control link</div>
    </aside>
    <div className="workspace">
      <header className="topbar"><span className="simulation">OFFLINE</span><strong>{workspace.label}</strong>{fixtureContext && fixtureMetadata}<span className="read-only">READ ONLY</span></header>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><span className="eyebrow">{workspace.label}</span><h1 ref={heading} tabIndex={-1}>{page === 'Overview' ? 'Monitoring overview' : pageLabel}</h1><p>{workspace.context}</p></div>
          {fixtureContext && <div className="snapshot-label"><span>MONITORING FIXTURE · FINAL SNAPSHOT</span><code>{fixtureId}</code></div>}
        </div>
        <nav className="workspace-pages" aria-label="Workspace pages">
          {workspace.pages.map(p => <button key={p.id} type="button" aria-current={p.id === page ? 'page' : undefined} onClick={() => onNavigate(p.id)}>{p.label}</button>)}
        </nav>
        <div key={page} className="workspace-content">{children}</div>
        <footer className="workspace-footer">AEGIS · Local inspection only<span>No live hardware integration</span></footer>
      </main>
    </div>
  </div>;
}
