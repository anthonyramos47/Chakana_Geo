/**
 * main.js — Three.js renderer, scene, camera, and render loop.
 *
 * Sets up the WebGL context and exposes window.__scene and window.__lights
 * for app_loader.js to attach geometry and panels.
 *
 * Replaces:
 *   ps.init()             → renderer + camera + controls setup below
 *   ps.set_bounding_box() → camera.position + controls.target
 *   ps.show()             → animate() render loop below
 */

import * as THREE from 'three';
import { OrbitControls }  from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { LabelRenderer }  from './LabelRenderer.js';
import { startScreenshotBridge } from './screenshot.js';
import { Studio }         from './lib/Studio.js';

// Catch unhandled JS errors and show them in the status bar
window.addEventListener('error', e => {
  const el = document.getElementById('status');
  if (el) { el.textContent = `JS Error: ${e.message} (${e.filename}:${e.lineno})`; el.className = 'error'; }
  console.error(e);
});
window.addEventListener('unhandledrejection', e => {
  const el = document.getElementById('status');
  if (el) { el.textContent = `Promise error: ${e.reason}`; el.className = 'error'; }
  console.error(e);
});

// ── Renderer ──────────────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
// preserveDrawingBuffer keeps the colour buffer readable after render(), which
// is what canvas.toDataURL() needs for ws.screenshot(); without it the capture
// comes back blank on most browsers.  alpha lets a capture use a transparent
// background (screenshot background="transparent"); the viewer itself still
// shows scene.background.
const renderer  = new THREE.WebGLRenderer({ antialias: true, alpha: true,
                                            preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.outputColorSpace       = THREE.SRGBColorSpace;
renderer.toneMapping            = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure    = 1.0;
container.appendChild(renderer.domElement);

// ── Scene ─────────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a1a);
window.__scene = scene;   // consumed by app_loader.js

const grid = new THREE.GridHelper(4, 20, 0x333333, 0x333333);
scene.add(grid);

// ── Camera ────────────────────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(
  45,
  window.innerWidth / window.innerHeight,
  0.001,
  100,
);
camera.position.set(0, 1.5, 4);

// ── Orbit controls ────────────────────────────────────────────────────────────
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 0, 0);
controls.update();

// ── Lighting ──────────────────────────────────────────────────────────────────
const ambient   = new THREE.AmbientLight(0xffffff, 0.5);
const keyLight  = new THREE.DirectionalLight(0xffffff, 1.2);   // bumped for ACES curve
const fillLight = new THREE.DirectionalLight(0xffffff, 0.5);   // bumped for ACES curve
keyLight.position.set(4, 8, 6);
fillLight.position.set(-4, 2, -4);
scene.add(ambient, keyLight, fillLight);

// Environment map (procedural room, no texture download): only MeshStandard/MeshPhysical
// materials use it, so the 'physical' shader gets reflections the others don't have.
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.6;
pmrem.dispose();

window.__lights = { ambient, keyLight, fillLight, scene };   // consumed by app_loader.js

// Studio render mode (AO, soft floor shadow, softbox environment); see lib/Studio.js.
const studio = new Studio(renderer, scene, camera, { keyLight, ambient, grid });
window.__studio = studio;
window.__lights.studio = studio;
// One frame of the current mode; also used by the screenshot bridge.
window.__renderFrame = () => studio.enabled ? studio.render() : renderer.render(scene, camera);

// Exposed for the screenshot bridge (frontend/screenshot.js).
window.__renderer = renderer;
window.__camera   = camera;
window.__controls = controls;
window.__grid     = grid;

// ── Label renderer (2D canvas overlay for index labels) ───────────────────────
const labelRenderer = new LabelRenderer();
window.__labelRenderer = labelRenderer;

// ── Axis gizmo (Blender-style 2D canvas overlay, bottom-left) ────────────────
const _gizmo = (() => {
  const SIZE = 120;   // logical px
  const dpr  = window.devicePixelRatio || 1;
  const canvas = document.createElement('canvas');
  canvas.width  = SIZE * dpr;
  canvas.height = SIZE * dpr;
  Object.assign(canvas.style, {
    position:      'fixed',
    bottom:        '8px',
    left:          '288px',   // just right of the scene panel (280px wide)
    width:         SIZE + 'px',
    height:        SIZE + 'px',
    pointerEvents: 'none',
    zIndex:        '1001',
  });
  document.body.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const AXES = [
    { dir: new THREE.Vector3(1, 0, 0), color: '#e05555', neg: '#7a2222', label: 'X' },
    { dir: new THREE.Vector3(0, 1, 0), color: '#5aad5a', neg: '#2a5a2a', label: 'Y' },
    { dir: new THREE.Vector3(0, 0, 1), color: '#5588e0', neg: '#22337a', label: 'Z' },
  ];

  // Reusable quaternion-based projection (no THREE.Camera needed)
  function project(vec3, quat) {
    // Rotate the world-space axis by the camera quaternion inverse → view space tip
    const v = vec3.clone().applyQuaternion(quat.clone().invert());
    return { x: v.x, y: v.y, z: v.z };
  }

  function draw(camQuat) {
    const S   = SIZE;
    const cx  = S / 2;
    const cy  = S / 2;
    const ARM = S * 0.36;   // arm length in px
    const R   = S * 0.11;   // sphere radius

    ctx.clearRect(0, 0, S, S);

    // Project all 6 tips (±X, ±Y, ±Z) and sort back-to-front by z
    const tips = [];
    for (const ax of AXES) {
      for (const sign of [-1, 1]) {
        const v = project(ax.dir.clone().multiplyScalar(sign), camQuat);
        tips.push({
          x:     cx + v.x * ARM,
          y:     cy - v.y * ARM,   // flip Y (canvas y grows downward)
          z:     v.z,
          color: sign > 0 ? ax.color : ax.neg,
          label: sign > 0 ? ax.label : null,
          r:     sign > 0 ? R : R * 0.65,
        });
      }
    }
    tips.sort((a, b) => a.z - b.z);   // paint farthest first

    // Draw stems first (behind spheres)
    for (const ax of AXES) {
      const pos = project(ax.dir.clone(), camQuat);
      const px = cx + pos.x * ARM;
      const py = cy - pos.y * ARM;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(px, py);
      ctx.strokeStyle = ax.color;
      ctx.lineWidth   = 2.5;
      ctx.stroke();
    }

    // Draw spheres + labels back-to-front
    for (const t of tips) {
      ctx.beginPath();
      ctx.arc(t.x, t.y, t.r, 0, Math.PI * 2);
      ctx.fillStyle = t.color;
      ctx.fill();

      if (t.label) {
        ctx.fillStyle   = '#ffffff';
        ctx.font        = `bold ${Math.round(t.r * 1.1)}px sans-serif`;
        ctx.textAlign   = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(t.label, t.x, t.y + 0.5);
      }
    }
  }

  return { draw };
})();

// ── Background toggle (sun/moon button, right of the gizmo) ──────────────────
// Switches the scene between dark and light background; remembered across reloads.
const _BG_THEMES = {
  dark:  { bg: 0x1a1a1a, grid: 0x333333, icon: '☀️', title: 'Light background' },
  light: { bg: 0xffffff, grid: 0xcccccc, icon: '🌙', title: 'Dark background'  },
};
const _bgButton = document.createElement('button');
Object.assign(_bgButton.style, {
  position:     'fixed',
  bottom:       '12px',
  left:         '416px',   // just right of the gizmo (288 + 120 + 8)
  width:        '32px',
  height:       '32px',
  fontSize:     '18px',
  lineHeight:   '1',
  padding:      '0',
  cursor:       'pointer',
  background:   '#2a2a2a',
  border:       '1px solid #444',
  borderRadius: '50%',
  zIndex:       '1001',
});
const _bgColor = new THREE.Color(0x1a1a1a);
function setBackgroundTheme(name) {
  const t = _BG_THEMES[name] ?? _BG_THEMES.dark;
  _bgColor.setHex(t.bg);
  if (studio.enabled) studio.applyTheme(name);
  else { studio.theme = name; scene.background = _bgColor; }
  document.body.style.background = '#' + t.bg.toString(16).padStart(6, '0');
  // GridHelper bakes its colour into vertex colours, so rewrite the attribute.
  const gc = new THREE.Color(t.grid), ca = grid.geometry.attributes.color;
  for (let i = 0; i < ca.count; i++) ca.setXYZ(i, gc.r, gc.g, gc.b);
  ca.needsUpdate = true;
  _bgButton.textContent = t.icon;
  _bgButton.title       = t.title;
  _bgButton.dataset.theme = name;
  try { localStorage.setItem('kayviz.background', name); } catch (_) {}
}
_bgButton.addEventListener('click', () =>
  setBackgroundTheme(_bgButton.dataset.theme === 'dark' ? 'light' : 'dark'));
document.body.appendChild(_bgButton);
let _savedBg = null;
try { _savedBg = localStorage.getItem('kayviz.background'); } catch (_) {}
setBackgroundTheme(_savedBg === 'light' ? 'light' : 'dark');
window.__setBackgroundTheme = setBackgroundTheme;

// ── Studio toggle (next to the background button) ───────────────────────────
const _studioButton = _bgButton.cloneNode();
_studioButton.style.left = '456px';
_studioButton.textContent = '\uD83D\uDCA1';
function setStudio(on) {
  studio.setEnabled(on);
  if (!on) scene.background = _bgColor;
  _studioButton.title = on ? 'Studio render: on (AO + soft shadows)' : 'Studio render: off';
  _studioButton.style.background = on ? '#6a5a20' : '#2a2a2a';
  try { localStorage.setItem('kayviz.studio', on ? '1' : '0'); } catch (_) {}
}
_studioButton.addEventListener('click', () => setStudio(!studio.enabled));
document.body.appendChild(_studioButton);
let _savedStudio = null;
try { _savedStudio = localStorage.getItem('kayviz.studio'); } catch (_) {}
setStudio(_savedStudio === '1');
window.__setStudio = setStudio;

// ── Save picture (camera button) ────────────────────────────────────────────
// Renders one frame at `scale` × the screen resolution and downloads it as PNG.
// background 'viewer' keeps what is on screen; 'transparent' drops the backdrop
// and the grid (the studio floor shadow stays, half-transparent).
// The picture is capped at SAVE_MAX_PIXELS: GPU memory grows with the pixel count
// (studio ≈ 200 bytes/pixel: 16.7 Mpx measured +3.3 GB), and on Apple silicon it is
// system RAM; an uncapped 4× studio save (~66 Mpx) froze a 16 GB Mac.
const SAVE_MAX_PIXELS = 12e6;   // ≈ 4600 × 2600
function savePicture({ background = 'viewer', scale = 2 } = {}) {
  const pr = renderer.getPixelRatio(), size = renderer.getSize(new THREE.Vector2());
  const maxSide = renderer.capabilities.maxTextureSize;
  const s = Math.min(scale, maxSide / (Math.max(size.x, size.y) * pr),
                     Math.sqrt(SAVE_MAX_PIXELS / (size.x * size.y)) / pr);
  const oldBg = scene.background, oldGrid = grid.visible;
  const oldClear = renderer.getClearColor(new THREE.Color()), oldAlpha = renderer.getClearAlpha();
  renderer.setPixelRatio(pr * s);
  if (background === 'transparent') {
    scene.background = null;
    renderer.setClearColor(0x000000, 0);
    grid.visible = false;
  }
  try {
    window.__renderFrame();
    // toBlob snapshots the canvas now; the restore below does not affect it
    renderer.domElement.toBlob((blob) => {
      const a = document.createElement('a');
      const app = new URLSearchParams(location.search).get('app') ?? 'kayviz';
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      a.href = URL.createObjectURL(blob);
      a.download = `${app}_${stamp}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }, 'image/png');
  } finally {
    scene.background = oldBg;
    grid.visible = oldGrid;
    renderer.setClearColor(oldClear, oldAlpha);
    renderer.setPixelRatio(pr);
  }
}
window.__savePicture = savePicture;

const _saveButton = _bgButton.cloneNode();
_saveButton.style.left = '496px';
_saveButton.textContent = '📷';
_saveButton.title = 'Save picture';
const _saveMenu = document.createElement('div');
Object.assign(_saveMenu.style, {
  position: 'fixed', bottom: '52px', left: '496px', display: 'none', zIndex: '1002',
  background: '#2a2a2a', border: '1px solid #444', borderRadius: '6px', padding: '8px',
  font: '12px sans-serif', color: '#ddd', flexDirection: 'column', gap: '6px',
});
const _saveScale = document.createElement('select');
for (const k of [1, 2]) _saveScale.add(new Option(`${k}× resolution`, k, k === 2, k === 2));
_saveMenu.appendChild(_saveScale);
for (const [bg, label] of [['viewer', 'Current background'], ['transparent', 'Empty background']]) {
  const b = document.createElement('button');
  b.textContent = label;
  Object.assign(b.style, { cursor: 'pointer', background: '#3a3a3a', color: '#eee',
                           border: '1px solid #555', borderRadius: '4px', padding: '4px 8px' });
  b.addEventListener('click', () => {
    _saveMenu.style.display = 'none';
    savePicture({ background: bg, scale: Number(_saveScale.value) });
  });
  _saveMenu.appendChild(b);
}
_saveButton.addEventListener('click', () => {
  _saveMenu.style.display = _saveMenu.style.display === 'none' ? 'flex' : 'none';
});
document.body.append(_saveButton, _saveMenu);

// ── Render loop ───────────────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  window.__renderFrame();
  _gizmo.draw(camera.quaternion);
  if (window.__viewer) labelRenderer.render(window.__viewer, camera);
}
animate();

// ── Click-to-inspect ──────────────────────────────────────────────────────────

// Floating debug panel
const _inspectPanel = (() => {
  const el = document.createElement('div');
  Object.assign(el.style, {
    position:    'fixed',
    bottom:      '20px',
    right:       '20px',
    background:  '#1f1f1f',
    color:       '#eee',
    fontFamily:  'monospace',
    fontSize:    '12px',
    padding:     '10px 14px',
    border:      '1px solid #444',
    borderRadius:'6px',
    zIndex:      '2000',
    maxWidth:    '320px',
    display:     'none',
    pointerEvents: 'none',
    lineHeight:  '1.7',
  });
  document.body.appendChild(el);
  return el;
})();

function _escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

const _raycaster = new THREE.Raycaster();
_raycaster.params.Line.threshold = 0.02;

let _mouseDownX = 0, _mouseDownY = 0;
renderer.domElement.addEventListener('mousedown', e => {
  _mouseDownX = e.clientX; _mouseDownY = e.clientY;
});

renderer.domElement.addEventListener('click', e => {
  // Skip if mouse moved more than 4px (drag, not click)
  if (Math.hypot(e.clientX - _mouseDownX, e.clientY - _mouseDownY) > 4) return;

  const viewer = window.__viewer;
  if (!viewer) return;

  const pointer = new THREE.Vector2(
    (e.clientX / window.innerWidth)  *  2 - 1,
    (e.clientY / window.innerHeight) * -2 + 1,
  );
  _raycaster.setFromCamera(pointer, camera);

  // Collect surface_mesh and curve_network meshes
  const candidates = [];
  for (const [, entry] of viewer.objects) {
    if (entry.type === 'surface_mesh' || entry.type === 'curve_network') {
      if (entry.mesh && entry.visible) candidates.push(entry.mesh);
    }
  }

  const hits = _raycaster.intersectObjects(candidates, false);
  if (!hits.length) { _inspectPanel.style.display = 'none'; return; }

  const hit   = hits[0];
  const entry = [...viewer.objects.values()].find(e => e.mesh === hit.object);
  if (!entry) return;

  const objName = hit.object.name;
  const pt      = hit.point;
  const ptStr   = `(${pt.x.toFixed(4)}, ${pt.y.toFixed(4)}, ${pt.z.toFixed(4)})`;

  let html = `<b>${_escHtml(objName)}</b><br>`;

  if (entry.type === 'surface_mesh') {
    const fi  = hit.faceIndex;   // triangle index
    // Map triangle → polygon using trisPerFace
    let polyIdx = fi;
    const tpf = entry.opts.trisPerFace;
    if (tpf) {
      let cum = 0;
      for (let p = 0; p < tpf.length; p++) {
        cum += tpf[p];
        if (fi < cum) { polyIdx = p; break; }
      }
    }
    // Vertex indices from index buffer
    const geo = entry.mesh.geometry;
    let v0, v1, v2;
    if (geo.index) {
      v0 = geo.index.getX(fi*3);
      v1 = geo.index.getX(fi*3 + 1);
      v2 = geo.index.getX(fi*3 + 2);
    } else {
      v0 = fi*3; v1 = fi*3+1; v2 = fi*3+2;
    }
    html += `type:     surface_mesh<br>`;
    html += `triangle: ${fi}<br>`;
    html += tpf ? `polygon:  ${polyIdx}<br>` : '';
    html += `vertices: [${v0}, ${v1}, ${v2}]<br>`;
    html += `hit:      ${ptStr}`;
  } else {
    // curve_network
    html += `type: curve_network<br>`;
    if (entry.radius > 0) {
      html += `edge: — (tube mesh, no edge ID)<br>`;
    } else {
      const edgeIdx = Math.floor(hit.index / 2);
      const v0 = entry.opts.edges[edgeIdx*2];
      const v1 = entry.opts.edges[edgeIdx*2 + 1];
      html += `edge:      ${edgeIdx}<br>`;
      html += `endpoints: [${v0}, ${v1}]<br>`;
    }
    html += `hit: ${ptStr}`;
  }

  _inspectPanel.innerHTML = html;
  _inspectPanel.style.display = 'block';
});

// ── Window resize ─────────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelRenderer.resize(window.innerWidth, window.innerHeight);
});

// ── Screenshot bridge ─────────────────────────────────────────────────────────
// Polls the server for capture requests issued by ws.screenshot* from Python.
startScreenshotBridge(THREE);
