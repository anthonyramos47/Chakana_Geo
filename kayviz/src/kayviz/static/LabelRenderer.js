/**
 * LabelRenderer.js — 2D canvas overlay for index labels.
 *
 * Renders vertex / face / edge index labels as screen-space text on a
 * full-window canvas overlay, drawn each frame from the main render loop.
 *
 * Usage (main.js):
 *   import { LabelRenderer } from './LabelRenderer.js';
 *   const labelRenderer = new LabelRenderer();
 *   // in animate():
 *   if (window.__viewer) labelRenderer.render(window.__viewer, camera);
 *   // in resize handler:
 *   labelRenderer.resize(window.innerWidth, window.innerHeight);
 */

import * as THREE from 'three';

const MAX_VERTEX_LABELS = 5000;
const MAX_FACE_LABELS   = 3000;
const MAX_EDGE_LABELS   = 3000;

export class LabelRenderer {
  constructor() {
    const dpr = window.devicePixelRatio || 1;
    this._dpr = dpr;

    this._canvas = document.createElement('canvas');
    this._canvas.width  = window.innerWidth  * dpr;
    this._canvas.height = window.innerHeight * dpr;
    Object.assign(this._canvas.style, {
      position:      'fixed',
      top:           '0',
      left:          '0',
      width:         window.innerWidth  + 'px',
      height:        window.innerHeight + 'px',
      pointerEvents: 'none',
      zIndex:        '999',
    });
    document.body.appendChild(this._canvas);

    this._ctx = this._canvas.getContext('2d');
    this._ctx.scale(dpr, dpr);
  }

  resize(w, h) {
    const dpr = this._dpr;
    this._canvas.width  = w * dpr;
    this._canvas.height = h * dpr;
    this._canvas.style.width  = w + 'px';
    this._canvas.style.height = h + 'px';
    this._ctx = this._canvas.getContext('2d');
    this._ctx.scale(dpr, dpr);
  }

  render(viewer, camera) {
    const ctx = this._ctx;
    const W   = this._canvas.width  / this._dpr;
    const H   = this._canvas.height / this._dpr;
    ctx.clearRect(0, 0, W, H);

    for (const [, entry] of viewer.objects) {
      if (!entry.visible) continue;

      if (entry.type === 'surface_mesh') {
        if (entry.opts.showVertexIndices) this._drawVertexLabels(entry, camera, W, H);
        if (entry.opts.showFaceIndices)   this._drawFaceLabels(entry, camera, W, H);
      }

      if (entry.type === 'curve_network') {
        if (entry.opts.showVertexIndices) this._drawCurveVertexLabels(entry, camera, W, H);
        if (entry.opts.showEdgeIndices)   this._drawEdgeLabels(entry, camera, W, H);
      }
    }
  }

  // ── Surface mesh — vertex labels ─────────────────────────────────────────

  _drawVertexLabels(entry, camera, W, H) {
    const verts = entry.opts.vertices;
    const n     = verts.length / 3;
    if (n > MAX_VERTEX_LABELS) {
      this._drawWarning(`vertex labels: too many (${n}), max ${MAX_VERTEX_LABELS}`, W, H);
      return;
    }
    for (let i = 0; i < n; i++) {
      const pt = this._project(verts[i*3], verts[i*3+1], verts[i*3+2], camera, W, H);
      if (pt) this._drawLabel(String(i), pt.px, pt.py);
    }
  }

  // ── Surface mesh — face labels ────────────────────────────────────────────

  _drawFaceLabels(entry, camera, W, H) {
    const verts      = entry.opts.vertices;
    const geo        = entry.mesh.geometry;
    const trisPerFace = entry.opts.trisPerFace;

    if (trisPerFace) {
      // Polygon mesh — compute polygon centroids
      const nFaces = trisPerFace.length;
      if (nFaces > MAX_FACE_LABELS) {
        this._drawWarning(`face labels: too many (${nFaces}), max ${MAX_FACE_LABELS}`, W, H);
        return;
      }
      const idx = geo.index;
      let triOffset = 0;
      for (let fi = 0; fi < nFaces; fi++) {
        const nTris = trisPerFace[fi];
        // Collect unique vertex indices for this polygon
        const seen = new Set();
        for (let t = 0; t < nTris; t++) {
          const base = (triOffset + t) * 3;
          seen.add(idx.getX(base));
          seen.add(idx.getX(base + 1));
          seen.add(idx.getX(base + 2));
        }
        // Average positions
        let cx = 0, cy = 0, cz = 0;
        for (const vi of seen) {
          cx += verts[vi*3]; cy += verts[vi*3+1]; cz += verts[vi*3+2];
        }
        const s = seen.size;
        const pt = this._project(cx/s, cy/s, cz/s, camera, W, H);
        if (pt) this._drawLabel(String(fi), pt.px, pt.py);
        triOffset += nTris;
      }
    } else if (entry.opts.faceSize > 3) {
      // Uniform n-gon mesh (e.g. quads) sent untriangulated — the client
      // fan-triangulated it into (faceSize - 2) triangles per face, but no
      // trisPerFace map was sent. Group triangles back into original faces.
      const idx      = geo.index;
      const trisPerN = entry.opts.faceSize - 2;
      const nFaces   = idx.count / 3 / trisPerN;
      if (nFaces > MAX_FACE_LABELS) {
        this._drawWarning(`face labels: too many (${nFaces}), max ${MAX_FACE_LABELS}`, W, H);
        return;
      }
      let triOffset = 0;
      for (let fi = 0; fi < nFaces; fi++) {
        const seen = new Set();
        for (let t = 0; t < trisPerN; t++) {
          const base = (triOffset + t) * 3;
          seen.add(idx.getX(base));
          seen.add(idx.getX(base + 1));
          seen.add(idx.getX(base + 2));
        }
        let cx = 0, cy = 0, cz = 0;
        for (const vi of seen) {
          cx += verts[vi*3]; cy += verts[vi*3+1]; cz += verts[vi*3+2];
        }
        const s = seen.size;
        const pt = this._project(cx/s, cy/s, cz/s, camera, W, H);
        if (pt) this._drawLabel(String(fi), pt.px, pt.py);
        triOffset += trisPerN;
      }
    } else {
      // All-triangle mesh
      const idx    = geo.index;
      const nFaces = idx ? idx.count / 3 : geo.attributes.position.count / 3;
      if (nFaces > MAX_FACE_LABELS) {
        this._drawWarning(`face labels: too many (${nFaces}), max ${MAX_FACE_LABELS}`, W, H);
        return;
      }
      for (let fi = 0; fi < nFaces; fi++) {
        let i0, i1, i2;
        if (idx) {
          i0 = idx.getX(fi*3); i1 = idx.getX(fi*3+1); i2 = idx.getX(fi*3+2);
        } else {
          i0 = fi*3; i1 = fi*3+1; i2 = fi*3+2;
        }
        const cx = (verts[i0*3] + verts[i1*3] + verts[i2*3]) / 3;
        const cy = (verts[i0*3+1] + verts[i1*3+1] + verts[i2*3+1]) / 3;
        const cz = (verts[i0*3+2] + verts[i1*3+2] + verts[i2*3+2]) / 3;
        const pt = this._project(cx, cy, cz, camera, W, H);
        if (pt) this._drawLabel(String(fi), pt.px, pt.py);
      }
    }
  }

  // ── Curve network — vertex labels ─────────────────────────────────────────

  _drawCurveVertexLabels(entry, camera, W, H) {
    const verts = entry.opts.verts;
    const n     = verts.length / 3;
    if (n > MAX_VERTEX_LABELS) {
      this._drawWarning(`vertex labels: too many (${n}), max ${MAX_VERTEX_LABELS}`, W, H);
      return;
    }
    for (let i = 0; i < n; i++) {
      const pt = this._project(verts[i*3], verts[i*3+1], verts[i*3+2], camera, W, H);
      if (pt) this._drawLabel(String(i), pt.px, pt.py);
    }
  }

  // ── Curve network — edge labels ───────────────────────────────────────────

  _drawEdgeLabels(entry, camera, W, H) {
    const verts = entry.opts.verts;
    const edges = entry.opts.edges;
    const n     = edges.length / 2;
    if (n > MAX_EDGE_LABELS) {
      this._drawWarning(`edge labels: too many (${n}), max ${MAX_EDGE_LABELS}`, W, H);
      return;
    }
    for (let k = 0; k < n; k++) {
      const a = edges[k*2], b = edges[k*2+1];
      const mx = (verts[a*3]   + verts[b*3])   / 2;
      const my = (verts[a*3+1] + verts[b*3+1]) / 2;
      const mz = (verts[a*3+2] + verts[b*3+2]) / 2;
      const pt = this._project(mx, my, mz, camera, W, H);
      if (pt) this._drawLabel(String(k), pt.px, pt.py);
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _project(x, y, z, camera, W, H) {
    const v = new THREE.Vector3(x, y, z).project(camera);
    if (v.z >= 1) return null;   // behind camera
    return {
      px: (v.x + 1) / 2 * W,
      py: (-v.y + 1) / 2 * H,
    };
  }

  _drawLabel(text, px, py) {
    const ctx = this._ctx;
    ctx.font = '10px monospace';
    const tw = ctx.measureText(text).width;
    const pad = 2;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(px - pad, py - 10 - pad, tw + pad*2, 12 + pad*2);
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.fillText(text, px, py - 1);
  }

  _drawWarning(msg, W, H) {
    const ctx = this._ctx;
    ctx.font      = '11px monospace';
    ctx.fillStyle = 'rgba(255,180,0,0.9)';
    ctx.fillText(msg, W / 2 - ctx.measureText(msg).width / 2, H / 2);
  }
}
