/**
 * benchmark.js — measure what drawing the current scene costs.
 *
 * Renders the scene `frames` times in each mode (plain, studio) and times every
 * frame until the GPU has finished it (a 1-pixel read-back waits for the GPU, so the
 * time is the real frame cost, not just the time to queue commands). Reports frame
 * times, triangles, draw calls, and the memory held: geometry buffers exactly (their
 * sizes are known), screen / studio / shadow buffers as estimates from their
 * formats, and the JavaScript heap (Chrome only).
 *
 * Used by the 📊 button (main.js) and by kv.benchmark() in Python.
 */

import * as THREE from 'three';
import { api } from './urls.js';

const MB = 1024 * 1024;

function stats(times) {
  const t = [...times].sort((a, b) => a - b);
  const q = p => t[Math.min(t.length - 1, Math.floor(p * t.length))];
  return { median_ms: q(0.5), p95_ms: q(0.95), fps: 1000 / q(0.5) };
}

/** Bytes of the GPU buffers of the scene's geometry (each buffer counted once). */
function geometryBytes(scene) {
  const seen = new Set();
  let bytes = 0, vertices = 0, objects = 0;
  const add = a => { if (a?.array && !seen.has(a.array)) { seen.add(a.array); bytes += a.array.byteLength; } };
  scene.traverse(o => {
    if (!o.geometry || o.userData.studioHelper) return;
    objects++;
    for (const a of Object.values(o.geometry.attributes)) add(a);
    add(o.geometry.index);
    if (o.isInstancedMesh) { add(o.instanceMatrix); add(o.instanceColor); }
    vertices += o.geometry.attributes.position?.count ?? 0;
  });
  return { bytes, vertices, objects };
}

/** Estimated bytes of the render buffers, from their pixel formats. */
export function bufferBytes(renderer, studio) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const px = size.x * size.y;
  // canvas: 4x MSAA colour + depth, plus the resolved colour
  const screen = px * (4 * 4 + 4 * 4 + 4);
  let composer = 0, shadow = 0;
  if (studio?.enabled) {
    const pr = renderer.getPixelRatio?.() ?? window.devicePixelRatio ?? 1;
    const s = Math.min(pr, studio.studioPixelRatio ?? studio.pixelRatioCap ?? 1) / pr;
    const spx = Math.round(size.x * s) * Math.round(size.y * s);
    // one 4x MSAA half-float target (render pass) + one non-MSAA target (post passes)
    composer = spx * ((8 * 4 + 8 + 4 * 4) + 8);
    // GTAO: normals + depth, AO and denoise targets (half float)
    composer += spx * (4 + 4 + 8 + 8);
    const m = studio.keyLight.shadow.mapSize;
    shadow = m.x * m.y * (8 + 8 + 4);              // VSM map, blur pass, depth
  }
  return { screen, composer, shadow, width: size.x, height: size.y };
}

function frameTimes(renderer, frames) {
  const gl = renderer.getContext(), pixel = new Uint8Array(4), times = [];
  for (let i = 0; i < frames + 5; i++) {         // 5 warm-up frames (shader compiles)
    const t0 = performance.now();
    window.__renderFrame();
    renderer.setRenderTarget(null);
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);   // waits for the GPU
    if (i >= 5) times.push(performance.now() - t0);
  }
  return times;
}

export function benchmark({ frames = 60 } = {}) {
  const renderer = window.__renderer, scene = window.__scene, studio = window.__studio;
  const wasStudio = studio.enabled;
  const geo = geometryBytes(scene);
  const out = { frames, modes: {}, scene: {}, memory_mb: {} };

  for (const mode of ['plain', 'studio']) {
    window.__setStudio(mode === 'studio');
    const times = frameTimes(renderer, frames);
    // Count over a whole frame: three.js resets the counters on every render call,
    // so with the studio's passes only its last (one full-screen triangle) remained.
    renderer.info.autoReset = false;
    renderer.info.reset();
    window.__renderFrame();
    const info = { ...renderer.info.render };
    renderer.info.autoReset = true;
    const buf = bufferBytes(renderer, studio);
    out.modes[mode] = {
      ...stats(times),
      triangles: info.triangles, draw_calls: info.calls,
      gpu_mb: (geo.bytes + buf.screen + buf.composer + buf.shadow) / MB,
      buffers_mb: { screen: buf.screen / MB, studio: buf.composer / MB, shadow: buf.shadow / MB },
    };
    out.scene.canvas = `${buf.width}x${buf.height}`;
  }
  window.__setStudio(wasStudio);

  out.scene.objects = geo.objects;
  out.scene.vertices = geo.vertices;
  out.memory_mb.geometry = geo.bytes / MB;
  out.memory_mb.js_heap = performance.memory ? performance.memory.usedJSHeapSize / MB : null;
  out.memory_mb.textures = renderer.info.memory.textures;   // a count
  out.pixel_ratio = renderer.getPixelRatio();
  window.__invalidate?.(2);
  return out;
}

/** A job from Python (kv.benchmark): run it and post the result back. */
export async function runBenchmarkJob(job) {
  let result = null, error = null;
  try { result = benchmark({ frames: job.frames ?? 60 }); }
  catch (e) { error = String(e?.message ?? e); }
  try {
    await fetch(api('script/screenshot/result'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: job.id, images: [], error, result }),
    });
  } catch (_) { /* Python times out */ }
}

const f = (x, d = 1) => (x == null ? '—' : Number(x).toFixed(d));

/** The result as an HTML table (the 📊 panel). */
export function benchmarkTable(r) {
  const p = r.modes.plain, s = r.modes.studio;
  const row = (label, a, b) => `<tr><td>${label}</td><td>${a}</td><td>${b}</td></tr>`;
  return `<table>
    <tr><th></th><th>plain</th><th>studio</th></tr>
    ${row('frame, median', `${f(p.median_ms)} ms`, `${f(s.median_ms)} ms`)}
    ${row('frame, 95%', `${f(p.p95_ms)} ms`, `${f(s.p95_ms)} ms`)}
    ${row('frames / s', f(p.fps, 0), f(s.fps, 0))}
    ${row('triangles', p.triangles.toLocaleString(), s.triangles.toLocaleString())}
    ${row('draw calls', p.draw_calls, s.draw_calls)}
    ${row('GPU memory', `${f(p.gpu_mb)} MB`, `${f(s.gpu_mb)} MB`)}
    ${row('&nbsp; geometry', `${f(r.memory_mb.geometry)} MB`, `${f(r.memory_mb.geometry)} MB`)}
    ${row('&nbsp; screen buffers', `${f(p.buffers_mb.screen)} MB`, `${f(s.buffers_mb.screen)} MB`)}
    ${row('&nbsp; studio buffers', '—', `${f(s.buffers_mb.studio)} MB`)}
    ${row('&nbsp; shadow maps', '—', `${f(s.buffers_mb.shadow)} MB`)}
    ${row('JS heap', `${f(r.memory_mb.js_heap)} MB`, '')}
  </table>
  <div class="kv-bench-note">${r.scene.objects} objects, ${r.scene.vertices.toLocaleString()} vertices,
  canvas ${r.scene.canvas} (pixel ratio ${r.pixel_ratio}), ${r.frames} frames per mode.
  Buffer sizes are estimates from their formats; geometry is exact.</div>`;
}
