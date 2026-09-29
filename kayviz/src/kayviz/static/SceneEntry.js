/**
 * SceneEntry — owns one registered scene object and all its children.
 *
 * Universal fields (all types):
 *   type, mesh, visible, color, opacity, radius, children, activeScalar, activeVector
 *
 * Type-specific state lives in opts:
 *   surface_mesh  — opts.vertices, opts.faceSize, opts.material, opts.trisPerFace,
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
      this.mesh.material.color.setRGB(rgb[0], rgb[1], rgb[2]);
    }
  }

  dispose(scene) {
    if (!this.mesh) return;
    scene.remove(this.mesh);
    this.mesh.geometry?.dispose();
    const mats = Array.isArray(this.mesh.material)
      ? this.mesh.material : [this.mesh.material];
    mats.forEach(m => m?.dispose());
    this.mesh = null;
  }
}

// ── VectorChild ───────────────────────────────────────────────────────────────

export class VectorChild extends Child {
  constructor({ key, mesh, origins, vectors, color = [0.2, 0.8, 0.4], length = 0.05, radius = null }) {
    super(key, 'vector');
    this.mesh    = mesh;
    this.origins = origins;
    this.vectors = vectors;
    this.color   = [...color];
    this.length  = length;
    this.radius  = radius ?? length * 0.04;
  }

  setColor(rgb) {
    this.color = [...rgb];
    if (this.mesh?.material) {
      this.mesh.material.color.setRGB(rgb[0], rgb[1], rgb[2]);
    }
  }

  dispose(scene) {
    if (!this.mesh) return;
    scene.remove(this.mesh);
    this.mesh.geometry?.dispose();
    const mats = Array.isArray(this.mesh.material)
      ? this.mesh.material : [this.mesh.material];
    mats.forEach(m => m?.dispose());
    this.mesh = null;
  }
}

// ── ScalarChild ───────────────────────────────────────────────────────────────

export class ScalarChild extends Child {
  constructor({ key, values, definedOn = 'vertices' }) {
    super(key, 'scalar');
    this.mesh       = null;   // scalar has no mesh
    this.values     = values;
    this.definedOn  = definedOn;
    this.dataMin    = Math.min(...values);
    this.dataMax    = Math.max(...values);
    this.vmin       = this.dataMin;
    this.vmax       = this.dataMax;
    // Backup state — undefined = uninitialized (null = valid "no prior attr" backup)
    this._colorAttrBackup   = undefined;
    this._priorMaterialColor = undefined;
  }

  /**
   * Install vertex colors on parentMesh. If faces-defined and geometry is indexed,
   * converts to non-indexed first (irreversible for the parent's lifetime).
   * Backs up prior color attr and material color on first call only.
   */
  apply(parentMesh, parentEntry, viridisFn) {
    const geo = parentMesh.geometry;

    // Convert to non-indexed for face scalars
    if (this.definedOn === 'faces' && geo.index !== null) {
      const nonIdx = geo.toNonIndexed();
      geo.dispose();
      parentMesh.geometry = nonIdx;
      parentEntry.opts.nonIndexed = true;
    }

    // Snapshot backup only once (before first color write)
    if (this._colorAttrBackup === undefined) {
      const existing = parentMesh.geometry.attributes.color;
      this._colorAttrBackup    = existing ? existing.clone() : null;
      const mc = parentMesh.material.color;
      this._priorMaterialColor = [mc.r, mc.g, mc.b];
    }

    this._writeColors(parentMesh, parentEntry, viridisFn, this.vmin, this.vmax);
    parentMesh.material.vertexColors = true;
    parentMesh.material.needsUpdate  = true;
  }

  /**
   * Recompute the color buffer for a new vmin/vmax range.
   * Assumes apply() has already been called.
   */
  setRange(vmin, vmax, parentMesh, parentEntry, viridisFn) {
    this.vmin = vmin;
    this.vmax = vmax;
    this._writeColors(parentMesh, parentEntry, viridisFn, vmin, vmax);
    parentMesh.material.needsUpdate = true;
  }

  _writeColors(parentMesh, parentEntry, viridisFn, vmin, vmax) {
    const geo    = parentMesh.geometry;
    const values = this.values;
    const range  = vmax - vmin || 1;
    let cols;

    if (this.definedOn === 'faces') {
      const nTriVerts = geo.attributes.position.count;
      cols = new Float32Array(nTriVerts * 3);
      const tpf = parentEntry.opts.trisPerFace;
      let vi = 0;
      for (let fi = 0; fi < values.length; fi++) {
        const t      = Math.max(0, Math.min(1, (values[fi] - vmin) / range));
        const c      = viridisFn(t);
        const nTris  = tpf ? tpf[fi] : Math.round(nTriVerts / values.length / 3);
        const nVerts = nTris * 3;
        for (let k = 0; k < nVerts; k++) {
          cols[vi*3]     = c[0];
          cols[vi*3 + 1] = c[1];
          cols[vi*3 + 2] = c[2];
          vi++;
        }
      }
    } else {
      cols = new Float32Array(values.length * 3);
      values.forEach((v, i) => {
        const t = Math.max(0, Math.min(1, (v - vmin) / range));
        const c = viridisFn(t);
        cols[i*3] = c[0]; cols[i*3+1] = c[1]; cols[i*3+2] = c[2];
      });
    }

    geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
  }

  /**
   * Restore the parent mesh to its pre-scalar state.
   * NOTE: toNonIndexed() is irreversible — the geometry stays non-indexed.
   */
  dispose(parentMesh, parentEntry) {
    if (this._colorAttrBackup === undefined) return;  // apply() was never called

    const geo = parentMesh.geometry;
    if (this._colorAttrBackup === null) {
      geo.deleteAttribute('color');
    } else {
      geo.setAttribute('color', this._colorAttrBackup);
    }

    if (this._priorMaterialColor) {
      parentMesh.material.color.setRGB(...this._priorMaterialColor);
    }
    parentMesh.material.vertexColors = false;
    parentMesh.material.needsUpdate  = true;
  }

  /**
   * Draw the value histogram and gradient bar into canvas elements.
   * @param {HTMLCanvasElement} canvas
   * @param {HTMLCanvasElement} gradCanvas
   * @param {function} viridisFn
   */
  drawHistogram(canvas, gradCanvas, viridisFn) {
    const W    = canvas.width;
    const H    = canvas.height;
    const BINS = 32;
    const { values, dataMin, dataMax, vmin, vmax } = this;
    const range = dataMax - dataMin || 1;
    const effectiveRange = vmax - vmin || 1;

    // Build bins
    const counts = new Array(BINS).fill(0);
    for (const v of values) {
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
      const t     = Math.max(0, Math.min(1, (bVal - vmin) / effectiveRange));
      const [r, g, bl] = viridisFn(t);
      const barH  = Math.round((counts[b] / maxCount) * (H - 2));
      ctx.fillStyle = `rgb(${Math.round(r*255)},${Math.round(g*255)},${Math.round(bl*255)})`;
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
      const tt   = Math.max(0, Math.min(1, (bVal - dataMin) / range));
      const [r, g, bl] = viridisFn(tt);
      grad.addColorStop(t, `rgb(${Math.round(r*255)},${Math.round(g*255)},${Math.round(bl*255)})`);
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
    this.activeVector = null;        // key of the currently visible VectorChild
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
    if (key === this.activeVector) this.activeVector = null;
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
  }
}
