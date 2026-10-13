import type { DemoState, Vec3 } from './scenario';

export interface View { readonly yaw: number; readonly pitch: number; readonly distance: number; readonly panX: number; readonly panZ: number; readonly mode: '2D' | '3D' }
export const INITIAL_VIEW: View = Object.freeze({ yaw: .65, pitch: .65, distance: 15, panX: 0, panZ: 0, mode: '3D' });
export function updateView(view: View, patch: Partial<View>): View {
  const v = { ...view, ...patch };
  if (![v.yaw, v.pitch, v.distance, v.panX, v.panZ].every(Number.isFinite) || !['2D', '3D'].includes(v.mode)) throw new Error('Invalid demo view');
  return { ...v, yaw: v.yaw % (Math.PI * 2), pitch: Math.max(.15, Math.min(1.4, v.pitch)), distance: Math.max(5, Math.min(28, v.distance)), panX: Math.max(-5, Math.min(5, v.panX)), panZ: Math.max(-5, Math.min(5, v.panZ)) };
}

type Matrix = Float32Array;
export function multiply(a: Matrix, b: Matrix): Matrix {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r]! += a[k * 4 + r]! * b[c * 4 + k]!;
  return out;
}
function normalize(v: Vec3): Vec3 { const n = Math.hypot(...v); return [v[0] / n, v[1] / n, v[2] / n]; }
function cross(a: Vec3, b: Vec3): Vec3 { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function dot(a: Vec3, b: Vec3) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function lookAt(eye: Vec3, center: Vec3, up: Vec3): Matrix {
  const z = normalize([eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]]), x = normalize(cross(up, z)), y = cross(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
}
export function viewProjection(view: View, aspect: number): Matrix {
  if (!Number.isFinite(aspect) || aspect <= 0) throw new Error('Invalid viewport aspect');
  const center: Vec3 = [view.panX, .5, view.panZ];
  const eye: Vec3 = view.mode === '2D' ? [center[0], 20, center[2]] : [center[0] + view.distance * Math.cos(view.pitch) * Math.sin(view.yaw), center[1] + view.distance * Math.sin(view.pitch), center[2] + view.distance * Math.cos(view.pitch) * Math.cos(view.yaw)];
  const f = 1 / Math.tan(Math.PI / 8), near = .1, far = 100, size = view.distance / 2;
  const projection = view.mode === '2D' ? new Float32Array([1 / (size * aspect), 0, 0, 0, 0, 1 / size, 0, 0, 0, 0, -2 / (far - near), 0, 0, 0, -(far + near) / (far - near), 1]) : new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0]);
  return multiply(projection, lookAt(eye, center, view.mode === '2D' ? [0, 0, -1] : [0, 1, 0]));
}
function model(position: Vec3, scale: Vec3): Matrix { return new Float32Array([scale[0], 0, 0, 0, 0, scale[1], 0, 0, 0, 0, scale[2], 0, position[0], position[1], position[2], 1]); }
function cube(): Float32Array {
  const vertices: number[] = [];
  const faces: readonly [Vec3, readonly Vec3[]][] = [
    [[0, 1, 0], [[-.5, .5, -.5], [-.5, .5, .5], [.5, .5, .5], [.5, .5, -.5]]],
    [[0, -1, 0], [[-.5, -.5, .5], [-.5, -.5, -.5], [.5, -.5, -.5], [.5, -.5, .5]]],
    [[0, 0, 1], [[-.5, -.5, .5], [.5, -.5, .5], [.5, .5, .5], [-.5, .5, .5]]],
    [[0, 0, -1], [[.5, -.5, -.5], [-.5, -.5, -.5], [-.5, .5, -.5], [.5, .5, -.5]]],
    [[1, 0, 0], [[.5, -.5, .5], [.5, -.5, -.5], [.5, .5, -.5], [.5, .5, .5]]],
    [[-1, 0, 0], [[-.5, -.5, -.5], [-.5, -.5, .5], [-.5, .5, .5], [-.5, .5, -.5]]],
  ];
  for (const [normal, corners] of faces) for (const i of [0, 1, 2, 0, 2, 3]) vertices.push(...corners[i]!, ...normal);
  return new Float32Array(vertices);
}
function grid(): Float32Array {
  const v: number[] = [];
  for (let i = -6; i <= 6; i++) for (const p of [[i, .01, -6], [i, .01, 6], [-6, .01, i], [6, .01, i]]) v.push(...p, 0, 1, 0);
  return new Float32Array(v);
}
const VERTEX = `attribute vec3 a_position; attribute vec3 a_normal;
uniform mat4 u_mvp; uniform mat4 u_model; varying float v_light;
void main() { gl_Position = u_mvp * vec4(a_position, 1.0);
vec3 n = normalize(mat3(u_model) * a_normal); v_light = 0.3 + 0.7 * max(dot(n, normalize(vec3(0.4, 0.8, 0.5))), 0.0); }`;
const FRAGMENT = `precision mediump float; uniform vec3 u_color; varying float v_light;
void main() { gl_FragColor = vec4(u_color * v_light, 1.0); }`;

export interface SceneRenderer { draw: (state: DemoState, view: View) => void; dispose: () => void }
export function createSceneRenderer(canvas: HTMLCanvasElement): SceneRenderer {
  const gl = canvas.getContext('webgl', { alpha: false, antialias: true });
  if (!gl) throw new Error('WebGL unavailable');
  const shaders: WebGLShader[] = [], buffers: WebGLBuffer[] = [];
  let program: WebGLProgram | null = null, disposed = false;
  function dispose() {
    if (disposed) return;
    disposed = true;
    buffers.forEach(b => gl!.deleteBuffer(b)); shaders.forEach(s => gl!.deleteShader(s));
    if (program) gl!.deleteProgram(program);
  }
  try {
    for (const [type, source] of [[gl.VERTEX_SHADER, VERTEX], [gl.FRAGMENT_SHADER, FRAGMENT]] as const) {
      const shader = gl.createShader(type); if (!shader) throw new Error('WebGL shader unavailable'); shaders.push(shader);
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('WebGL shader compilation failed');
    }
    program = gl.createProgram(); if (!program) throw new Error('WebGL program unavailable');
    shaders.forEach(s => gl.attachShader(program!, s)); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('WebGL program linking failed');
    const position = gl.getAttribLocation(program, 'a_position'), normal = gl.getAttribLocation(program, 'a_normal');
    const mvp = gl.getUniformLocation(program, 'u_mvp'), transform = gl.getUniformLocation(program, 'u_model'), color = gl.getUniformLocation(program, 'u_color');
    if (position < 0 || normal < 0 || !mvp || !transform || !color) throw new Error('WebGL bindings unavailable');
    function upload(data: Float32Array) {
      const buffer = gl!.createBuffer(); if (!buffer) throw new Error('WebGL buffer unavailable'); buffers.push(buffer);
      gl!.bindBuffer(gl!.ARRAY_BUFFER, buffer); gl!.bufferData(gl!.ARRAY_BUFFER, data, gl!.STATIC_DRAW);
      return { buffer, count: data.length / 6 };
    }
    const solid = upload(cube()), lines = upload(grid());
    function draw(state: DemoState, view: View) {
      if (disposed || gl!.isContextLost()) return;
      const ratio = Math.min(2, Math.max(1, globalThis.devicePixelRatio || 1));
      const width = canvas.clientWidth || 480, height = canvas.clientHeight || 320;
      const scale = Math.min(ratio, 2048 / width, 2048 / height);
      const w = Math.max(1, Math.round(width * scale)), h = Math.max(1, Math.round(height * scale));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl!.viewport(0, 0, w, h); gl!.clearColor(.02, .045, .035, 1); gl!.enable(gl!.DEPTH_TEST); gl!.clear(gl!.COLOR_BUFFER_BIT | gl!.DEPTH_BUFFER_BIT); gl!.useProgram(program);
      const vp = viewProjection(view, w / h);
      function mesh(positionValue: Vec3, scale: Vec3, colorValue: Vec3, wire = false) {
        const data = wire ? lines : solid, matrix = model(positionValue, scale);
        gl!.bindBuffer(gl!.ARRAY_BUFFER, data.buffer); gl!.enableVertexAttribArray(position); gl!.enableVertexAttribArray(normal);
        gl!.vertexAttribPointer(position, 3, gl!.FLOAT, false, 24, 0); gl!.vertexAttribPointer(normal, 3, gl!.FLOAT, false, 24, 12);
        gl!.uniformMatrix4fv(mvp, false, multiply(vp, matrix)); gl!.uniformMatrix4fv(transform, false, matrix); gl!.uniform3fv(color, new Float32Array(colorValue));
        gl!.drawArrays(wire ? gl!.LINES : gl!.TRIANGLES, 0, data.count);
      }
      mesh([0, -.06, 0], [12, .1, 12], [.06, .14, .1]); mesh([0, 0, 0], [1, 1, 1], [.12, .4, .25], true);
      for (const p of [[-4, .5, -4], [4, .8, -4], [4, .4, 1]] as const) mesh(p, [.7, p[1] * 2, .7], [.18, .27, .22]);
      const a = state.aerial, g = state.ground;
      mesh(a, [.65, .25, .65], [.12, .75, .42]); mesh(a, [1.7, .08, .15], [.14, .35, .25]); mesh(a, [.15, .08, 1.7], [.14, .35, .25]);
      for (const [x, z] of [[-.7, -.7], [-.7, .7], [.7, -.7], [.7, .7]]) mesh([a[0] + x!, a[1] + .1, a[2] + z!], [.55, .05, .15], [.35, .7, .5]);
      mesh(g, [.9, .45, 1.2], [.55, .38, .12]);
      for (const [x, z] of [[-.5, -.4], [-.5, .4], [.5, -.4], [.5, .4]]) mesh([g[0] + x!, .18, g[2] + z!], [.2, .3, .3], [.1, .15, .12]);
    }
    return { draw, dispose };
  } catch (error) { dispose(); throw error; }
}
