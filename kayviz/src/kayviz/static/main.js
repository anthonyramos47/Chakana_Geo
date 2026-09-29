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
import { LabelRenderer }  from './LabelRenderer.js';
import { startScreenshotBridge } from './screenshot.js';

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
// comes back blank on most browsers.
const renderer  = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
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

window.__lights = { ambient, keyLight, fillLight };   // consumed by app_loader.js

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

// ── Render loop ───────────────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
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
