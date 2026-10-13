import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DEMO_DURATION_MS, INITIAL_PLAYBACK, playbackReducer, scenarioAt } from '../src/simulation/scenario';
import { createSceneRenderer, INITIAL_VIEW, multiply, updateView, viewProjection } from '../src/simulation/renderer';
import { SimulationViewer } from '../src/simulation/SimulationViewer';
import App from '../src/App';
import fixtureText from '../src/data/session.json?raw';

let nextFrame = 0;
let frames: Map<number, FrameRequestCallback>;
beforeEach(() => {
  frames = new Map(); nextFrame = 0;
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => { frames.delete(id); }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function frame(now: number) { const callbacks = [...frames.values()]; frames.clear(); act(() => callbacks.forEach(fn => fn(now))); }
function fakeGL() {
  return {
    VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4, ARRAY_BUFFER: 5, STATIC_DRAW: 6, DEPTH_TEST: 7, COLOR_BUFFER_BIT: 8, DEPTH_BUFFER_BIT: 16, FLOAT: 17, LINES: 18, TRIANGLES: 19,
    createShader: vi.fn(() => ({})), shaderSource: vi.fn(), compileShader: vi.fn(), getShaderParameter: vi.fn(() => true), deleteShader: vi.fn(),
    createProgram: vi.fn(() => ({})), attachShader: vi.fn(), linkProgram: vi.fn(), getProgramParameter: vi.fn(() => true), deleteProgram: vi.fn(),
    getAttribLocation: vi.fn((_program: unknown, name: string) => name === 'a_position' ? 0 : 1), getUniformLocation: vi.fn((_program: unknown, name: string) => ({ name })), createBuffer: vi.fn(() => ({})), bindBuffer: vi.fn(), bufferData: vi.fn(), deleteBuffer: vi.fn(),
    isContextLost: vi.fn(() => false), viewport: vi.fn(), clearColor: vi.fn(), enable: vi.fn(), clear: vi.fn(), useProgram: vi.fn(), enableVertexAttribArray: vi.fn(), vertexAttribPointer: vi.fn(), uniformMatrix4fv: vi.fn(), uniform3fv: vi.fn(), drawArrays: vi.fn(),
  };
}
function mockCanvas(gl: ReturnType<typeof fakeGL>) {
  vi.stubGlobal('WebGLRenderingContext', function () {});
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => gl as unknown as WebGLRenderingContext);
}

it('starts paused with deterministic, frozen demo state and no caller mutation', () => {
  expect(INITIAL_PLAYBACK).toEqual({ timeMs: 0, playing: false, speed: 1 });
  expect(scenarioAt(0)).toEqual(scenarioAt(0));
  expect(Object.isFrozen(scenarioAt(0))).toBe(true); expect(Object.isFrozen(scenarioAt(0).aerial)).toBe(true);
  const before = { ...INITIAL_PLAYBACK }; playbackReducer(before, { type: 'step' }); expect(before).toEqual(INITIAL_PLAYBACK);
});

it.each([0, 250, 1000, 3000, 6000, 9000, 12000])('reproduces exactly the same scenario at %i ms', time => {
  expect(JSON.stringify(scenarioAt(time))).toBe(JSON.stringify(scenarioAt(time)));
  expect(scenarioAt(time).aerial.every(Number.isFinite)).toBe(true);
});

it('follows explicit harmless keyframes and clamps bounds without random motion', () => {
  expect(scenarioAt(0).aerial).toEqual([-3, 2, -2]); expect(scenarioAt(3000).aerial).toEqual([1, 2, -2]);
  expect(scenarioAt(12000).aerial).toEqual(scenarioAt(0).aerial);
  expect(scenarioAt(-1).timeMs).toBe(0); expect(scenarioAt(99999).timeMs).toBe(12000);
  expect(() => scenarioAt(Infinity)).toThrow(/finite/);
});

it('plays, pauses, resets, steps and stops exactly at the bounded end', () => {
  let state = playbackReducer(INITIAL_PLAYBACK, { type: 'play' });
  state = playbackReducer(state, { type: 'advance', elapsedMs: 1000 }); expect(state.timeMs).toBe(1000);
  state = playbackReducer(state, { type: 'pause' }); expect(playbackReducer(state, { type: 'advance', elapsedMs: 5000 })).toBe(state);
  state = playbackReducer(state, { type: 'step' }); expect(state.timeMs).toBe(1250); expect(state.playing).toBe(false);
  expect(playbackReducer(state, { type: 'reset' })).toEqual(INITIAL_PLAYBACK);
  state = playbackReducer({ ...state, playing: true }, { type: 'advance', elapsedMs: 20000 }); expect(state.timeMs).toBe(DEMO_DURATION_MS); expect(state.playing).toBe(false);
  expect(playbackReducer(state, { type: 'play' }).playing).toBe(false);
});

it.each([.5, 1, 2] as const)('advances reproducibly at speed %s', speed => {
  const state = playbackReducer({ ...INITIAL_PLAYBACK, playing: true }, { type: 'speed', speed });
  const run = () => [100, 200, 400].reduce((s, elapsedMs) => playbackReducer(s, { type: 'advance', elapsedMs }), state);
  expect(run().timeMs).toBe(700 * speed); expect(run()).toEqual(run());
});

it('rejects invalid elapsed and speed and pauses when seeking', () => {
  expect(() => playbackReducer(INITIAL_PLAYBACK, { type: 'advance', elapsedMs: NaN })).toThrow();
  expect(() => playbackReducer(INITIAL_PLAYBACK, { type: 'advance', elapsedMs: -1 })).toThrow();
  expect(() => playbackReducer(INITIAL_PLAYBACK, { type: 'speed', speed: 9 as 1 })).toThrow();
  expect(playbackReducer({ ...INITIAL_PLAYBACK, playing: true }, { type: 'seek', timeMs: 750 })).toEqual({ ...INITIAL_PLAYBACK, timeMs: 750 });
});

it('initializes real shader, mesh, grid and depth-test commands and releases resources once', () => {
  const gl = fakeGL(); mockCanvas(gl);
  const canvas = document.createElement('canvas'), scene = createSceneRenderer(canvas);
  expect(gl.createShader).toHaveBeenCalledTimes(2); expect(gl.createBuffer).toHaveBeenCalledTimes(2);
  scene.draw(scenarioAt(0), INITIAL_VIEW);
  expect(gl.enable).toHaveBeenCalledWith(gl.DEPTH_TEST);
  expect(gl.drawArrays.mock.calls.some(call => call[0] === gl.LINES)).toBe(true);
  expect(gl.drawArrays.mock.calls.filter(call => call[0] === gl.TRIANGLES).length).toBeGreaterThan(10);
  expect(gl.uniformMatrix4fv.mock.calls.every(call => [...call[2] as Float32Array].every(Number.isFinite))).toBe(true);
  scene.dispose(); scene.dispose(); expect(gl.deleteBuffer).toHaveBeenCalledTimes(2); expect(gl.deleteShader).toHaveBeenCalledTimes(2); expect(gl.deleteProgram).toHaveBeenCalledOnce();
  const count = gl.drawArrays.mock.calls.length; scene.draw(scenarioAt(100), INITIAL_VIEW); expect(gl.drawArrays).toHaveBeenCalledTimes(count);
});

it('cleans up partial shader/program initialization on failure', () => {
  const gl = fakeGL(); mockCanvas(gl); gl.getShaderParameter.mockReturnValue(false);
  expect(() => createSceneRenderer(document.createElement('canvas'))).toThrow(/compilation/);
  expect(gl.deleteShader).toHaveBeenCalledOnce(); expect(gl.createBuffer).not.toHaveBeenCalled();
});

it('caps drawing buffer size while preserving responsive aspect ratio', () => {
  const gl = fakeGL(); mockCanvas(gl); vi.stubGlobal('devicePixelRatio', 3);
  const canvas = document.createElement('canvas');
  Object.defineProperty(canvas, 'clientWidth', { value: 3000 }); Object.defineProperty(canvas, 'clientHeight', { value: 1500 });
  const scene = createSceneRenderer(canvas); scene.draw(scenarioAt(0), INITIAL_VIEW);
  expect(canvas.width).toBe(2048); expect(canvas.height).toBe(1024);
  expect(gl.viewport).toHaveBeenCalledWith(0, 0, 2048, 1024); scene.dispose();
});

it('reports missing WebGL instead of showing an invented rendered scene', () => {
  vi.stubGlobal('WebGLRenderingContext', undefined);
  render(<SimulationViewer />);
  expect(screen.getByText(/WebGL unavailable/)).toBeVisible();
  expect(screen.getByText(/DEMO SIMULATION STATE/)).toBeVisible();
  expect(screen.getByText(/VALIDATED MONITORING SNAPSHOT is independent/)).toBeVisible();
});

it('bounds orbit, zoom and pan and uses finite perspective/orthographic matrices', () => {
  const before = { ...INITIAL_VIEW };
  const view = updateView(before, { distance: 100, panX: 100, pitch: -1, yaw: 100 });
  expect(view.distance).toBe(28); expect(view.panX).toBe(5); expect(view.pitch).toBe(.15); expect(before).toEqual(INITIAL_VIEW);
  expect(() => updateView(before, { yaw: NaN })).toThrow();
  for (const mode of ['2D', '3D'] as const) expect([...viewProjection({ ...view, mode }, 1.5)].every(Number.isFinite)).toBe(true);
  expect(() => viewProjection(view, 0)).toThrow();
  const identity = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]); expect(multiply(identity, identity)).toEqual(identity);
});

it('handles view controls, wheel and keyboard without hardware commands', () => {
  const gl = fakeGL(); mockCanvas(gl); render(<SimulationViewer />);
  fireEvent.click(screen.getByRole('button', { name: 'left view' }));
  const canvas = screen.getByLabelText('Synthetic 3D demo environment, left view; illustrative models only');
  fireEvent.keyDown(canvas, { key: 'Home' });
  expect(screen.getByLabelText('View zoom')).toHaveValue('15');
  fireEvent.wheel(canvas, { deltaY: 10 }); expect(screen.getByLabelText('View zoom')).toHaveValue('16');
  fireEvent.keyDown(canvas, { key: '+' }); expect(screen.getByLabelText('View zoom')).toHaveValue('15');
  const draws = gl.drawArrays.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Pan left' })); expect(gl.drawArrays.mock.calls.length).toBeGreaterThan(draws);
  fireEvent.click(screen.getByRole('button', { name: '2D' })); expect(screen.getByRole('button', { name: '2D' })).toHaveAttribute('aria-pressed', 'true');
});

it('handles renderer resize, context loss/restoration and unmount cleanup', () => {
  const gl = fakeGL(); mockCanvas(gl);
  const disconnect = vi.fn(); let resize: ResizeObserverCallback | undefined;
  vi.stubGlobal('ResizeObserver', class { constructor(callback: ResizeObserverCallback) { resize = callback; } observe() {} disconnect() { disconnect(); } });
  const { unmount } = render(<SimulationViewer />);
  act(() => resize?.([], {} as ResizeObserver));
  const canvas = screen.getByLabelText(/Synthetic 3D demo environment/);
  fireEvent(canvas, new Event('webglcontextlost', { cancelable: true })); expect(screen.getByText(/WebGL context lost/)).toBeVisible();
  fireEvent(canvas, new Event('webglcontextrestored')); expect(screen.queryByText(/WebGL context lost/)).not.toBeInTheDocument();
  unmount(); expect(disconnect).toHaveBeenCalled(); expect(gl.deleteProgram).toHaveBeenCalledTimes(2);
});

it('supports play/pause/reset/step/speed/seek with a controllable local animation clock', () => {
  render(<SimulationViewer />);
  fireEvent.click(screen.getByRole('button', { name: 'Play simulation' })); frame(0); frame(100);
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.10 / 12.00 s');
  fireEvent.change(screen.getByLabelText('Simulation playback speed'), { target: { value: '2' } }); frame(200);
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.30 / 12.00 s');
  fireEvent.click(screen.getByRole('button', { name: 'Pause simulation' })); expect(frames.size).toBe(0);
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' })); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.55 / 12.00 s');
  fireEvent.change(screen.getByLabelText('Simulation timeline'), { target: { value: '3000' } }); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('3.00 / 12.00 s');
  fireEvent.click(screen.getByRole('button', { name: 'Reset simulation' })); expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.00 / 12.00 s');
});

it('cancels active animation frames when the viewer unmounts', () => {
  const { unmount } = render(<SimulationViewer />); fireEvent.click(screen.getByRole('button', { name: 'Play simulation' }));
  expect(frames.size).toBe(1); unmount(); expect(frames.size).toBe(0);
});

it('initializes and releases scene resources under React StrictMode', async () => {
  const { StrictMode } = await import('react');
  const gl = fakeGL(); mockCanvas(gl);
  const { unmount } = render(<StrictMode><SimulationViewer /></StrictMode>);
  expect(gl.createProgram).toHaveBeenCalledTimes(2);
  expect(gl.deleteProgram).toHaveBeenCalledOnce();
  unmount(); expect(gl.deleteProgram).toHaveBeenCalledTimes(2);
});

it('respects reduced motion by disabling continuous playback and keeping steps available', () => {
  const remove = vi.fn();
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: remove })));
  const { unmount } = render(<SimulationViewer />);
  expect(screen.getByRole('button', { name: 'Play simulation' })).toBeDisabled();
  expect(frames.size).toBe(0); fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s'); unmount(); expect(remove).toHaveBeenCalled();
});

it('keeps fixture metrics and radar unchanged when demonstration state advances', () => {
  const before = fixtureText; render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  expect(screen.getByRole('article', { name: 'Devices' }).querySelector('strong')).toHaveTextContent('03');
  expect(screen.getByRole('article', { name: 'Applied events' }).querySelector('strong')).toHaveTextContent('06');
  expect(screen.getByText('SYNTHETIC DISPLAY — NON-GEOGRAPHIC')).toBeVisible(); expect(fixtureText).toBe(before);
  expect(document.querySelector('video')).toBeNull();
});


function currentModelPositions(gl: ReturnType<typeof fakeGL>) {
  const transforms = gl.uniformMatrix4fv.mock.calls.filter(call => (call[0] as { name: string }).name === 'u_model').slice(-17);
  expect(transforms).toHaveLength(17);
  const position = (index: number) => Array.from(transforms[index]![2] as Float32Array).slice(12, 15);
  return { aerial: position(5), ground: position(12) };
}

it('connects playback, pause, reset, step and seek to changed WebGL model transforms', () => {
  const gl = fakeGL(); mockCanvas(gl); render(<SimulationViewer />);
  const initial = currentModelPositions(gl);
  expect(initial.aerial).toEqual([-3, 2, -2]);
  expect(initial.ground[0]).toBe(-2);
  fireEvent.click(screen.getByRole('button', { name: 'Play simulation' }));
  frame(0);
  for (let i = 1; i <= 12; i++) frame(i * 250);
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('3.00 / 12.00 s');
  expect(currentModelPositions(gl).aerial).toEqual([1, 2, -2]);
  expect(currentModelPositions(gl).ground[0]).toBe(0);
  fireEvent.click(screen.getByRole('button', { name: 'Pause simulation' }));
  const draws = gl.drawArrays.mock.calls.length;
  frame(4000); expect(gl.drawArrays).toHaveBeenCalledTimes(draws);
  fireEvent.click(screen.getByRole('button', { name: 'Reset simulation' }));
  expect(currentModelPositions(gl)).toEqual(initial);
  fireEvent.click(screen.getByRole('button', { name: 'Step simulation' }));
  expect(screen.getByLabelText('Simulation time')).toHaveTextContent('0.25 / 12.00 s');
  expect(currentModelPositions(gl).aerial).not.toEqual(initial.aerial);
  expect(currentModelPositions(gl).ground).not.toEqual(initial.ground);
  fireEvent.change(screen.getByLabelText('Simulation timeline'), { target: { value: '6000' } });
  expect(currentModelPositions(gl).aerial).toEqual([1, 2, 2]);
  expect(currentModelPositions(gl).ground[0]).toBe(2);
});

it('has exactly one playback animation loop under StrictMode and advances both models', async () => {
  const { StrictMode } = await import('react'); const gl = fakeGL(); mockCanvas(gl);
  const { unmount } = render(<StrictMode><SimulationViewer /></StrictMode>);
  fireEvent.click(screen.getByRole('button', { name: 'Play simulation' }));
  expect(frames.size).toBe(1); frame(0); frame(250);
  expect(frames.size).toBe(1); expect(currentModelPositions(gl).aerial).not.toEqual([-3, 2, -2]);
  unmount(); expect(frames.size).toBe(0);
});

it('makes demo time and endpoint behavior explicit without changing monitoring telemetry', () => {
  render(<SimulationViewer />);
  fireEvent.change(screen.getByLabelText('Simulation timeline'), { target: { value: '12000' } });
  expect(screen.getByLabelText('Demo playback state')).toHaveTextContent('Demo complete — Reset to replay');
  expect(screen.getByRole('button', { name: 'Play simulation' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Step simulation' })).toBeDisabled();
  const canvas = screen.getByLabelText(/Synthetic 3D demo environment/);
  expect(canvas).toHaveAttribute('data-demo-time-ms', '12000');
  expect(canvas).toHaveAttribute('data-demo-playing', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Reset simulation' }));
  expect(screen.getByLabelText('Demo playback state')).toHaveTextContent('Paused demo');
  expect(canvas).toHaveAttribute('data-demo-time-ms', '0');
});

it('does not conceal reduced-motion changes during active playback', () => {
  let listener: (() => void) | undefined;
  const query = { matches: false, addEventListener: vi.fn((_type: string, callback: () => void) => { listener = callback; }), removeEventListener: vi.fn() };
  vi.stubGlobal('matchMedia', vi.fn(() => query)); render(<SimulationViewer />);
  fireEvent.click(screen.getByRole('button', { name: 'Play simulation' })); frame(0); frame(250);
  expect(frames.size).toBe(1);
  act(() => { query.matches = true; listener?.(); });
  expect(frames.size).toBe(0); expect(screen.getByRole('button', { name: 'Play simulation' })).toBeDisabled();
  expect(screen.getByLabelText('Demo playback state')).toHaveTextContent('Paused demo');
  expect(screen.getByText(/Reduced motion: continuous demo playback disabled/)).toBeVisible();
});
