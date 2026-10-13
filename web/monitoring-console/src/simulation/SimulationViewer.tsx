import { useEffect, useReducer, useRef, useState } from 'react';
import { Card } from '../components';
import { DEMO_DURATION_MS, INITIAL_PLAYBACK, playbackReducer, scenarioAt } from './scenario';
import type { Speed } from './scenario';
import { createSceneRenderer, INITIAL_VIEW, updateView } from './renderer';
import type { SceneRenderer, View } from './renderer';

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  useEffect(() => {
    const query = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!query) return;
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update); update();
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

export function SimulationViewer() {
  const [playback, dispatch] = useReducer(playbackReducer, INITIAL_PLAYBACK);
  const [view, setView] = useState<View>(INITIAL_VIEW);
  const [unavailable, setUnavailable] = useState('');
  const canvas = useRef<HTMLCanvasElement>(null), scene = useRef<SceneRenderer | null>(null);
  const frameState = useRef({ timeMs: playback.timeMs, view });
  const drag = useRef<{ x: number; y: number; pan: boolean; pointer: number } | null>(null);
  const reduced = useReducedMotion();
  frameState.current = { timeMs: playback.timeMs, view };
  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    let disposed = false;
    function draw() { if (!disposed) scene.current?.draw(scenarioAt(frameState.current.timeMs), frameState.current.view); }
    function initialize() {
      scene.current?.dispose(); scene.current = null;
      try {
        if (typeof WebGLRenderingContext === 'undefined') throw new Error('WebGL unavailable');
        scene.current = createSceneRenderer(node!); setUnavailable(''); draw();
      } catch { setUnavailable('WebGL unavailable — scene could not be rendered. Demo controls remain separate from monitoring data.'); }
    }
    function lost(event: Event) { event.preventDefault(); scene.current?.dispose(); scene.current = null; setUnavailable('WebGL context lost — rendering paused.'); dispatch({ type: 'pause' }); }
    function wheel(event: WheelEvent) { event.preventDefault(); setView(v => updateView(v, { distance: v.distance + Math.sign(event.deltaY) })); }
    node.addEventListener('webglcontextlost', lost); node.addEventListener('webglcontextrestored', initialize);
    node.addEventListener('wheel', wheel, { passive: false });
    initialize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(draw);
    observer?.observe(node); globalThis.addEventListener('resize', draw);
    return () => {
      disposed = true; observer?.disconnect(); globalThis.removeEventListener('resize', draw);
      node.removeEventListener('wheel', wheel); node.removeEventListener('webglcontextlost', lost); node.removeEventListener('webglcontextrestored', initialize);
      scene.current?.dispose(); scene.current = null;
    };
  }, []);
  useEffect(() => { scene.current?.draw(scenarioAt(playback.timeMs), view); }, [playback.timeMs, view]);
  useEffect(() => {
    if (reduced) dispatch({ type: 'pause' });
    if (!playback.playing || reduced) return;
    let handle = 0, previous: number | null = null, active = true;
    function advance(now: number) {
      if (!active) return;
      if (previous !== null) dispatch({ type: 'advance', elapsedMs: Math.max(0, Math.min(250, Math.round(now - previous))) });
      previous = now; handle = requestAnimationFrame(advance);
    }
    handle = requestAnimationFrame(advance);
    return () => { active = false; cancelAnimationFrame(handle); };
  }, [playback.playing, reduced]);
  function patch(values: Partial<View>) { setView(v => updateView(v, values)); }
  function orbit(amount: number) { setView(v => updateView(v, { yaw: v.yaw + amount })); }
  function pan(x: number, z: number) { setView(v => updateView(v, { panX: v.panX + x, panZ: v.panZ + z })); }
  const playbackState = playback.timeMs === DEMO_DURATION_MS ? 'Demo complete — Reset to replay' : playback.playing ? 'Playing demo' : 'Paused demo';
  const orientation = Math.abs(view.yaw) < .01 ? 'front' : view.yaw < 0 ? 'left' : 'right';
  return <Card title="3D simulation" className="visual-panel"><p className="boundary-label">SIMULATION PREVIEW — ILLUSTRATIVE</p><p className="demo-state-label">DEMO SIMULATION STATE · SYNTHETIC / NON-GEOGRAPHIC</p>
    <div className="simulation-viewport webgl-viewport"><canvas ref={canvas} width="480" height="320" tabIndex={0} data-demo-time-ms={playback.timeMs} data-demo-playing={playback.playing} aria-label={`Synthetic ${view.mode} demo environment, ${orientation} view; illustrative models only`}
      onPointerDown={e => { drag.current = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2, pointer: e.pointerId }; e.currentTarget.setPointerCapture?.(e.pointerId); e.currentTarget.focus(); }}
      onPointerMove={e => { const start = drag.current; if (!start || start.pointer !== e.pointerId) return; const dx = e.clientX - start.x, dy = e.clientY - start.y; drag.current = { ...start, x: e.clientX, y: e.clientY }; setView(v => updateView(v, start.pan ? { panX: v.panX - dx * .015, panZ: v.panZ + dy * .015 } : { yaw: v.yaw - dx * .01, pitch: v.pitch + dy * .01 })); }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }} onContextMenu={e => e.preventDefault()}
      onKeyDown={e => { const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-', 'Home']; if (!keys.includes(e.key)) return; e.preventDefault(); if (e.key === 'Home') setView(INITIAL_VIEW); else if (e.key === '+' || e.key === '=' || e.key === '-') setView(v => updateView(v, { distance: v.distance + (e.key === '-' ? 1 : -1) })); else if (e.shiftKey) pan(e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0, e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : 0); else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') orbit(e.key === 'ArrowLeft' ? -.15 : .15); else setView(v => updateView(v, { pitch: v.pitch + (e.key === 'ArrowUp' ? .1 : -.1) })); }} />
      {unavailable && <p className="webgl-error" role="status">{unavailable}</p>}
      <span className="viewport-caption">DEMO {(playback.timeMs / 1000).toFixed(2)} s · {playbackState}<br />ABSTRACT SCENE UNITS · NO SENSOR POSITIONS</span>
    </div>
    <div className="demo-playback"><div className="viewport-toolbar"><button disabled={reduced || playback.timeMs === DEMO_DURATION_MS} onClick={() => dispatch({ type: 'play' })}>Play simulation</button><button disabled={!playback.playing} onClick={() => dispatch({ type: 'pause' })}>Pause simulation</button><button onClick={() => dispatch({ type: 'reset' })}>Reset simulation</button><button disabled={playback.timeMs === DEMO_DURATION_MS} onClick={() => dispatch({ type: 'step' })}>Step simulation</button></div>
      <label>Simulation timeline<input type="range" min="0" max={DEMO_DURATION_MS} step="250" value={playback.timeMs} onChange={e => dispatch({ type: 'seek', timeMs: Number(e.target.value) })} /></label>
      <div className="player-settings"><label>Simulation playback speed<select value={playback.speed} onChange={e => dispatch({ type: 'speed', speed: Number(e.target.value) as Speed })}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option></select></label><output aria-label="Simulation time">{(playback.timeMs / 1000).toFixed(2)} / 12.00 s</output><span aria-label="Demo playback state">{playbackState}</span></div>
    </div>{reduced && <p className="note">Reduced motion: continuous demo playback disabled. Use single steps or seeking.</p>}
    <p className="note">Drag to orbit; Shift-drag to pan; scroll to zoom. Keyboard arrows orbit, Shift-arrows pan, +/− zoom, Home resets.</p>
    <div className="viewport-toolbar" role="group" aria-label="Illustrative visual mode">{(['2D', '3D'] as const).map(mode => <button key={mode} aria-pressed={view.mode === mode} onClick={() => patch({ mode })}>{mode}</button>)}<button onClick={() => setView(INITIAL_VIEW)}>Reset view</button></div>
    <div className="viewport-toolbar" role="group" aria-label="Illustrative camera orientation">{(['left', 'front', 'right'] as const).map(direction => <button key={direction} aria-pressed={orientation === direction} onClick={() => patch({ yaw: direction === 'left' ? -.65 : direction === 'right' ? .65 : 0 })}>{direction} view</button>)}<button onClick={() => orbit(-.15)}>Orbit left</button><button onClick={() => orbit(.15)}>Orbit right</button></div>
    <label>View zoom<input type="range" min="5" max="28" step="0.5" value={view.distance} onChange={e => patch({ distance: Number(e.target.value) })} /></label>
    <div className="viewport-toolbar" role="group" aria-label="Pan demo view"><button onClick={() => pan(-1, 0)}>Pan left</button><button onClick={() => pan(1, 0)}>Pan right</button><button onClick={() => pan(0, -1)}>Pan forward</button><button onClick={() => pan(0, 1)}>Pan back</button></div>
    <ul className="category-legend"><li>Green: illustrative aerial model</li><li>Amber: illustrative ground model</li><li>Gray: fixed reference objects</li></ul>
    <p className="note">VALIDATED MONITORING SNAPSHOT is independent. Demo models do not represent measured device locations or reproduce real equipment. No physics accuracy, sensor ranges or real-world motion is claimed.</p>
  </Card>;
}
