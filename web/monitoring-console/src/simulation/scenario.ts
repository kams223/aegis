// Abstract scene units only. These are not coordinates from a sensor or fixture.
export const DEMO_DURATION_MS = 12000;
export const DEMO_STEP_MS = 250;
export type Speed = 0.5 | 1 | 2;
export type Vec3 = readonly [number, number, number];
export interface DemoState { readonly timeMs: number; readonly aerial: Vec3; readonly ground: Vec3 }
export interface Playback { readonly timeMs: number; readonly playing: boolean; readonly speed: Speed }
export type PlaybackAction = { type: 'play' | 'pause' | 'reset' | 'step' } | { type: 'seek'; timeMs: number } | { type: 'speed'; speed: Speed } | { type: 'advance'; elapsedMs: number };
export const INITIAL_PLAYBACK: Playback = Object.freeze({ timeMs: 0, playing: false, speed: 1 });
function boundedTime(value: number) {
  if (!Number.isFinite(value)) throw new Error('Demo time must be finite');
  return Math.max(0, Math.min(DEMO_DURATION_MS, value));
}
const AERIAL_POINTS: readonly Vec3[] = Object.freeze([Object.freeze([-3, 2, -2] as const), Object.freeze([1, 2, -2] as const), Object.freeze([1, 2, 2] as const), Object.freeze([-3, 2, 2] as const), Object.freeze([-3, 2, -2] as const)]);
const GROUND_POINTS: readonly Vec3[] = Object.freeze([Object.freeze([-2, .4, 3] as const), Object.freeze([0, .4, 3] as const), Object.freeze([2, .4, 3] as const), Object.freeze([0, .4, 3] as const), Object.freeze([-2, .4, 3] as const)]);
function interpolate(points: readonly Vec3[], timeMs: number): Vec3 {
  const phase = timeMs / DEMO_DURATION_MS * (points.length - 1);
  const index = Math.min(Math.floor(phase), points.length - 2);
  const a = points[index]!, b = points[index + 1]!, t = phase - index;
  return Object.freeze([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
}
export function scenarioAt(time: number): DemoState {
  const timeMs = boundedTime(time);
  return Object.freeze({ timeMs, aerial: interpolate(AERIAL_POINTS, timeMs), ground: interpolate(GROUND_POINTS, timeMs) });
}
export function playbackReducer(state: Playback, action: PlaybackAction): Playback {
  switch (action.type) {
    case 'play': return { ...state, playing: state.timeMs < DEMO_DURATION_MS };
    case 'pause': return { ...state, playing: false };
    case 'reset': return INITIAL_PLAYBACK;
    case 'speed':
      if (![.5, 1, 2].includes(action.speed)) throw new Error('Unsupported demo playback speed');
      return { ...state, speed: action.speed };
    case 'seek': return { ...state, playing: false, timeMs: boundedTime(action.timeMs) };
    case 'step': return { ...state, playing: false, timeMs: boundedTime(state.timeMs + DEMO_STEP_MS) };
    case 'advance': {
      if (!Number.isFinite(action.elapsedMs) || action.elapsedMs < 0) throw new Error('Invalid demo elapsed interval');
      if (!state.playing) return state;
      const timeMs = boundedTime(state.timeMs + action.elapsedMs * state.speed);
      return { ...state, timeMs, playing: timeMs < DEMO_DURATION_MS };
    }
  }
}
