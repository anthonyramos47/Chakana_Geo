/**
 * SceneEntry — owns one registered scene object and all its children.
 *
 * Universal fields (all types):
 *   type, mesh, visible, color, opacity, radius, children, activeScalar
 *
 * Type-specific state lives in opts:
 *   surface_mesh  — opts.vertices, opts.faces, opts.faceSize, opts.material, opts.trisPerFace,
 *                   opts.nonIndexed, opts.edgeVerts, opts.edgeIdx
 *   curve_network — opts.verts, opts.edges
 *   vector_field  — opts.origins, opts.vectors, opts.length
 *   point_cloud   — (no extra opts beyond universal fields)
 *
 * Children are polymorphic instances of Child subclasses stored in
 *   children: Map<string, EdgeChild | ScalarChild | VectorChild>
 * and are fully owned — dispose() removes them all.
 */

import * as THREE from 'three';
import { lut, sample, finiteRange, NAN_COLOR } from './lib/colormap.js';

// ── Base child class ──────────────────────────────────────────────────────────

export class Child {
  constructor(key, type) {
    this.key     = key;
    this.type    = type;
    this.visible = true;
    this.mesh    = null;   // null for ScalarChild
  }

  /** Remove mesh from scene and dispose GPU resources. Override in subclasses. */
  dispose(scene, parentMesh, parentEntry) {}

  /** Toggle visibility of this child's mesh (if any). */
  setVisible(visible) {
    this.visible = visible;
    if (this.mesh) this.mesh.visible = visible;
  }
}

// ── EdgeChild ─────────────────────────────────────────────────────────────────

export class EdgeChild extends Child {
  constructor({ mesh, color = [0.1, 0.1, 0.1], radius = 0 }) {
    super('edges', 'edges');
    this.mesh   = mesh;
    this.color  = [...color];
    this.radius = radius;
  }

  setColor(rgb) {
    this.color = [...rgb];
    if (this.mesh?.material) {
      this.mesh.material.color?.setRGB(rgb[0], rgb[1], rgb[2]);
    }
  }

  dispose(scene) {
    if (!this.mesh) return;
    scene.remove(this.mesh);
    this.mesh.geometry?.dispose();
    const mats = Array.isArray(this.mesh.material)
      ? this.mesh.material : [this.mesh.material];
    mats.forEach(m => m?.dispose());
    this.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.mesh = null;
  }
}

// ── VectorChild ───────────────────────────────────────────────────────────────

export class VectorChild extends Child {
  constructor({ key, mesh, origins, vectors, definedOn = 'vertices',
                color = [0.2, 0.8, 0.4], length = 0.05, radius = null }) {
    super(key, 'vector');
    this.mesh      = mesh;
    this.origins   = origins;   // arrow bases: vertices, points or face barycenters
    this.vectors   = vectors;
    this.definedOn = definedOn;
    this.color   = [...color];
    this.length  = length;
    this.radius  = radius ?? length * 0.04;
  }

  setColor(rgb) {
    this.color = [...rgb];
    if (this.mesh?.material) {
      this.mesh.material.color?.setRGB(rgb[0], rgb[1], rgb[2]);
    }
  }

  dispose(scene) {
    if (!this.mesh) return;
    scene.remove(this.mesh);
    this.mesh.geometry?.dispose();
    const mats = Array.isArray(this.mesh.material)
      ? this.mesh.material : [this.mesh.material];
    mats.forEach(m => m?.dispose());
    this.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.mesh = null;
  }
}

// ── ScalarChild ───────────────────────────────────────────────────────────────

/** Put back the indexed geometry a face scalar replaced (see ScalarChild.apply). */
function restoreIndexed(parentMesh, opts) {
  if (!opts._indexedGeo) return;
  const flat = parentMesh.geometry;
  parentMesh.geometry = opts._indexedGeo;
  flat.dispose();
  opts._indexedGeo = null;
  opts.nonIndexed  = false;
}

export class ScalarChild extends Child {
  constructor({ key, values, definedOn = 'vertices', cmap = 'viridis' }) {
    super(key, 'scalar');
    this.mesh      = null;   // scalar has no mesh
    this.values    = values;
    this.definedOn = definedOn;
    this.cmap      = cmap;
    // finite values only: one NaN must not make the whole range NaN
    [this.dataMin, this.dataMax] = finiteRange(values);
    this.vmin = this.dataMin;
    this.vmax = this.dataMax;
    this._priorMaterialColor = undefined;     // undefined = not applied
  }

  /**
   * Colour the parent mesh with this scalar. A face scalar needs one colour per
   * triangle corner, so the mesh shows a non-indexed copy of its geometry while it
   * is active; the indexed geometry is kept in opts._indexedGeo and comes back when
   * the face scalar is switched off or a vertex scalar takes over.
   */
  apply(parentMesh, parentEntry) {
    const opts = parentEntry.opts;
    if (this.definedOn === 'faces') {
      if (parentMesh.geometry.index !== null) {
        opts._indexedGeo    = parentMesh.geometry;
        parentMesh.geometry = parentMesh.geometry.toNonIndexed();
        opts.nonIndexed     = true;
      }
    } else {
      restoreIndexed(parentMesh, opts);
    }
    const mc = parentMesh.material.color;    // none on normal/depth/shader materials
    if (this._priorMaterialColor === undefined) this._priorMaterialColor = mc ? [mc.r, mc.g, mc.b] : null;
    mc?.setRGB(1, 1, 1);                       // vertex colours are multiplied by it
    this._writeColors(parentMesh, opts);
    parentMesh.material.vertexColors = true;
    parentMesh.material.needsUpdate  = true;
  }

  /** New vmin/vmax: rewrites the colours in place (no new GPU buffer). */
  setRange(vmin, vmax, parentMesh, parentEntry) {
    this.vmin = vmin;
    this.vmax = vmax;
    this._writeColors(parentMesh, parentEntry.opts);
  }

  _writeColors(parentMesh, opts) {
    const geo = parentMesh.geometry;
    const n   = geo.attributes.position.count;
    let attr  = geo.getAttribute('color');
    if (!attr || attr.count !== n) {
      if (attr) geo.deleteAttribute('color');
      attr = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
      geo.setAttribute('color', attr);
    }
    const cols = attr.array, L = lut(this.cmap), values = this.values;
    const lo = this.vmin, scale = 255 / ((this.vmax - this.vmin) || 1);
    const put = (k, v) => {
      if (Number.isFinite(v)) {
        const i = 3 * Math.round(Math.min(255, Math.max(0, (v - lo) * scale)));
        cols[3*k] = L[i]; cols[3*k + 1] = L[i + 1]; cols[3*k + 2] = L[i + 2];
      } else {                                  // NaN, ±Inf, or a missing value
        cols[3*k] = NAN_COLOR[0]; cols[3*k + 1] = NAN_COLOR[1]; cols[3*k + 2] = NAN_COLOR[2];
      }
    };
    if (this.definedOn === 'faces') {
      // non-indexed: the triangles of face fi follow each other, 3 corners each
      const tpf = opts.trisPerFace, perFace = Math.max(1, (opts.faceSize ?? 3) - 2);
      const nFaces = tpf ? tpf.length : Math.floor(n / 3 / perFace);
      let k = 0;
      for (let fi = 0; fi < nFaces && k < n; fi++) {
        const v = fi < values.length ? values[fi] : NaN;
        const corners = 3 * (tpf ? tpf[fi] : perFace);
        for (let c = 0; c < corners && k < n; c++) put(k++, v);
      }
      while (k < n) put(k++, NaN);
    } else {
      for (let i = 0; i < n; i++) put(i, i < values.length ? values[i] : NaN);
    }
    attr.needsUpdate = true;
  }

  /** Restore the parent mesh to its pre-scalar state (colours, material, geometry). */
  dispose(parentMesh, parentEntry) {
    if (this._priorMaterialColor === undefined) return;  // apply() was never called
    parentMesh.geometry.deleteAttribute('color');
    if (this.definedOn === 'faces') restoreIndexed(parentMesh, parentEntry.opts);
    if (this._priorMaterialColor) parentMesh.material.color?.setRGB(...this._priorMaterialColor);
    parentMesh.material.vertexColors = false;
    parentMesh.material.needsUpdate  = true;
    this._priorMaterialColor = undefined;
  }

  /**
   * Draw the value histogram and gradient bar into canvas elements.
   * @param {HTMLCanvasElement} canvas
   * @param {HTMLCanvasElement} gradCanvas
   */
  drawHistogram(canvas, gradCanvas) {
    const W    = canvas.width;
    const H    = canvas.height;
    const BINS = 32;
    const { values, dataMin, dataMax, vmin, vmax } = this;
    const range = dataMax - dataMin || 1;
    const effectiveRange = vmax - vmin || 1;
    const css = ([r, g, b]) => `rgb(${Math.round(r*255)},${Math.round(g*255)},${Math.round(b*255)})`;

    // Build bins (non-finite values are left out)
    const counts = new Array(BINS).fill(0);
    for (const v of values) {
      if (!Number.isFinite(v)) continue;
      const bin = Math.min(BINS - 1, Math.max(0, Math.floor((v - dataMin) / range * BINS)));
      counts[bin]++;
    }
    const maxCount = Math.max(...counts, 1);

    // Draw bars
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    const bw = W / BINS;
    for (let b = 0; b < BINS; b++) {
      const bVal  = dataMin + (b + 0.5) / BINS * range;
      const barH  = Math.round((counts[b] / maxCount) * (H - 2));
      ctx.fillStyle = css(sample((bVal - vmin) / effectiveRange, this.cmap));
      ctx.fillRect(Math.round(b * bw), H - barH, Math.ceil(bw) - 1, barH);
    }

    // Draw colormap gradient bar
    const gCtx = gradCanvas.getContext('2d');
    const gW   = gradCanvas.width;
    const grad = gCtx.createLinearGradient(0, 0, gW, 0);
    const stops = 16;
    for (let i = 0; i <= stops; i++) {
      const t    = i / stops;
      const bVal = vmin + t * effectiveRange;
      grad.addColorStop(t, css(sample((bVal - dataMin) / range, this.cmap)));
    }
    gCtx.fillStyle = grad;
    gCtx.fillRect(0, 0, gW, gradCanvas.height);
  }
}

// ── SceneEntry ────────────────────────────────────────────────────────────────

export class SceneEntry {
  constructor(type, mesh, opts = {}) {
    this.type         = type;
    this.mesh         = mesh;
    this.visible      = opts.visible      ?? true;
    this.color        = opts.color        ?? [0.8, 0.8, 0.8];
    this.opacity      = opts.opacity      ?? 1.0;
    this.radius       = opts.radius       ?? 0;
    this.children     = new Map();   // key → Child instance
    this.activeScalar = null;        // key of the currently applied ScalarChild
    this.opts         = opts;        // type-specific state

    if (type === 'surface_mesh') {
      if (this.opts.showVertexIndices === undefined) this.opts.showVertexIndices = false;
      if (this.opts.showFaceIndices   === undefined) this.opts.showFaceIndices   = false;
    }
    if (type === 'curve_network') {
      if (this.opts.showVertexIndices === undefined) this.opts.showVertexIndices = false;
      if (this.opts.showEdgeIndices   === undefined) this.opts.showEdgeIndices   = false;
    }
  }

  // ── Child management ────────────────────────────────────────────────────────

  /** Add or replace a child. Caller must have already added the child's mesh to the scene. */
  addChild(child) {
    this.children.set(child.key, child);
  }

  /** Remove a child — dispatches polymorphically to child.dispose(). */
  removeChild(key, scene, parentMesh) {
    const child = this.children.get(key);
    if (!child) return;
    if (child instanceof ScalarChild) {
      child.dispose(parentMesh, this);
    } else {
      child.dispose(scene);
    }
    if (key === this.activeScalar) this.activeScalar = null;
    this.children.delete(key);
  }

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  /** Remove self and all children from the scene and dispose all GPU resources. */
  dispose(scene) {
    // Dispose children first (ScalarChild mutates parent mesh — must run before parent is gone)
    for (const key of [...this.children.keys()]) this.removeChild(key, scene, this.mesh);
    scene.remove(this.mesh);
    this.mesh.geometry?.dispose();
    const mats = Array.isArray(this.mesh.material)
      ? this.mesh.material : [this.mesh.material];
    mats.forEach(m => m?.dispose());
    this.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
  }
}
