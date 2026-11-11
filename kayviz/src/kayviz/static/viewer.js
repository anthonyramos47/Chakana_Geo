/**
 * viewer.js — Three.js scene manager.
 *
 * Each registered object is stored as a SceneEntry in this._objects.
 * Type-specific state lives in entry.opts; children (edge overlay,
 * vector quantities, scalar quantities) are polymorphic Child instances
 * owned by entry.children.
 */

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { Materials } from './lib/MaterialLibrary.js';
import { SceneEntry, EdgeChild, ScalarChild, VectorChild } from './SceneEntry.js';

// Default colours of vector quantities, in the order they are handed out
// (the first one is the former single default).
const VECTOR_PALETTE = [
  [0.20, 0.80, 0.40],  // green
  [0.90, 0.30, 0.20],  // red
  [0.20, 0.45, 0.90],  // blue
  [0.95, 0.65, 0.10],  // orange
  [0.60, 0.30, 0.80],  // purple
  [0.10, 0.75, 0.80],  // cyan
  [0.90, 0.35, 0.65],  // pink
  [0.55, 0.40, 0.25],  // brown
];

export class Viewer {
  constructor(scene, matLib = Materials) {
    this.scene    = scene;
    this.matLib   = matLib;
    this._objects = new Map();  // name → SceneEntry
    this.errors   = [];         // objects of the last messages that could not be shown
    this._batch   = 0;          // > 0 inside applyMessage: one 'viewer-changed' at the end
    this._emitDue = false;
    // one shader for every surface mesh (scene panel "Shader"); kept across reloads
    let saved = null;
    try { saved = localStorage.getItem('kayviz.material'); } catch (_) {}
    this.material = (saved && matLib.has(saved)) ? saved : 'physical';
  }

  // ── Registration ─────────────────────────────────────────────────────────

  registerSurfaceMesh(name, vertices, faces, faceSize = 3,
                      color = [0.8, 0.8, 0.8], opacity = 1.0,
                      material = null) {
    this._remove(name);
    // a material named at registration (python material=...) is pinned: the global
    // Shader dropdown leaves it alone
    const pinned = !!material && this.matLib.has(material);
    material = pinned ? material : this.material;
    const geo  = this._buildMeshGeo(vertices, faces, faceSize);
    const mat  = this.matLib.build(material, color, opacity);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name  = name;
    this.scene.add(mesh);
    this._objects.set(name, new SceneEntry('surface_mesh', mesh, {
      color: [...color], opacity, material, pinned, visible: true,
      vertices, faces, faceSize,
      trisPerFace: null, nonIndexed: false,
      edgeVerts: null, edgeIdx: null,
    }));
    this._emit();
    return mesh;
  }

  registerCurveNetwork(name, vertices, edges, color = [0.8, 0.2, 0.2], radius = 0.002) {
    this._remove(name);
    const obj = this._buildCurveObj(vertices, edges, color, radius);
    obj.name  = name;
    this.scene.add(obj);
    this._objects.set(name, new SceneEntry('curve_network', obj, {
      color: [...color], opacity: 1.0, radius, visible: true,
      verts: vertices, edges,
    }));
    this._emit();
    return obj;
  }

  registerVectorField(name, origins, vectors, length = 0.05, radius = null, color = [0.2, 0.8, 0.4]) {
    this._remove(name);
    radius = radius ?? length * 0.04;
    const mesh = this._buildArrowField(origins, vectors, length, radius, color);
    mesh.name  = name;
    this.scene.add(mesh);
    this._objects.set(name, new SceneEntry('vector_field', mesh, {
      color: [...color], opacity: 1.0, visible: true,
      origins, vectors, length, radius,
    }));
    this._emit();
    return mesh;
  }

  registerPointCloud(name, points, color = [0.2, 0.5, 0.8], radius = 0.0005) {
    this._remove(name);
    const pts = new Float32Array(points);
    const count = pts.length / 3;
    const obj = this._buildSphereInstances(pts, count, color, radius);
    obj.name = name;
    this.scene.add(obj);
    this._objects.set(name, new SceneEntry('point_cloud', obj, {
      color: [...color], opacity: 1.0, radius, points: pts, visible: true,
    }));
    this._emit();
    return obj;
  }

  // ── Mutation ──────────────────────────────────────────────────────────────

  setEnabled(name, enabled) {
    const e = this._objects.get(name);
    if (!e) return;
    e.mesh.visible = enabled;
    e.visible      = enabled;
    // Propagate to children that have a mesh (ScalarChild has none)
    for (const child of e.children.values()) {
      if (child.mesh && child.visible) child.mesh.visible = enabled;
    }
  }

  setColor(name, color) {
    const e = this._objects.get(name);
    if (!e) return;
    e.color = [...color];
    const scalar = e.activeScalar && e.children.get(e.activeScalar);
    if (scalar) {
      // the material stays white under the colormap; this colour comes back with it
      scalar._priorMaterialColor = [...color];
      return;
    }
    // normal / depth / custom shader materials have no colour (the shader may take uColor)
    e.mesh.material.color?.setRGB(color[0], color[1], color[2]);
    e.mesh.material.uniforms?.uColor?.value.setRGB(color[0], color[1], color[2]);
    e.mesh.material.needsUpdate = true;
  }

  setOpacity(name, t) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'surface_mesh') return;
    e.opacity                    = t;
    e.mesh.material.opacity      = t;
    const glass = !!e.mesh.material.userData.glass;   // glass always blends
    e.mesh.material.transparent  = glass || t < 1.0;
    e.mesh.material.depthWrite   = !glass && t >= 1.0;   // translucent meshes must not hide what is behind them
    e.mesh.material.needsUpdate  = true;
  }

  setRadius(name, r) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'point_cloud') return;
    e.opts.radius = r;
    const newObj = this._buildSphereInstances(e.opts.points, e.opts.points.length / 3, e.opts.color, r);
    newObj.name    = name;
    newObj.visible = e.mesh.visible;
    this.scene.remove(e.mesh);
    this.scene.add(newObj);
    e.mesh = newObj;
  }

  setCurveRadius(name, radius) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'curve_network') return;
    e.radius = radius;
    const newObj = this._buildCurveObj(e.opts.verts, e.opts.edges, e.color, radius);
    newObj.name    = name;
    newObj.visible = e.visible;
    this.scene.remove(e.mesh);
    e.mesh.geometry?.dispose();
    const mats = Array.isArray(e.mesh.material) ? e.mesh.material : [e.mesh.material];
    mats.forEach(m => m?.dispose());
    e.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.scene.add(newObj);
    e.mesh = newObj;
    this._emit();
  }

  setVectorLength(name, length) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'vector_field') return;
    e.opts.length = length;
    const newMesh = this._buildArrowField(e.opts.origins, e.opts.vectors, length, e.opts.radius, e.color);
    newMesh.name    = name;
    newMesh.visible = e.visible;
    this.scene.remove(e.mesh);
    e.mesh.geometry?.dispose();
    const mats = Array.isArray(e.mesh.material) ? e.mesh.material : [e.mesh.material];
    mats.forEach(m => m?.dispose());
    e.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.scene.add(newMesh);
    e.mesh = newMesh;
  }

  setVectorRadius(name, radius) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'vector_field') return;
    e.opts.radius = radius;
    const newMesh = this._buildArrowField(e.opts.origins, e.opts.vectors, e.opts.length, radius, e.color);
    newMesh.name    = name;
    newMesh.visible = e.visible;
    this.scene.remove(e.mesh);
    e.mesh.geometry?.dispose();
    const mats = Array.isArray(e.mesh.material) ? e.mesh.material : [e.mesh.material];
    mats.forEach(m => m?.dispose());
    e.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.scene.add(newMesh);
    e.mesh = newMesh;
  }

  setMaterial(name, matName) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'surface_mesh') return;
    this.matLib.applyTo(e.mesh, matName, e.color, e.opacity);
    e.opts.material = matName;
    e.opts.pinned   = true;          // a per-mesh choice survives the global Shader dropdown
    this._reapplyScalar(e);
    e.mesh.material.needsUpdate = true;
    this._emit();
  }

  /** Switch every surface mesh (and the ones registered later) to the shader `matName`. */
  setGlobalMaterial(matName) {
    if (!this.matLib.has(matName)) return;
    this.material = matName;
    try { localStorage.setItem('kayviz.material', matName); } catch (_) {}
    for (const [name, e] of this._objects) {
      if (e.type !== 'surface_mesh' || e.opts.pinned) continue;
      this.matLib.applyTo(e.mesh, matName, e.color, e.opacity);
      e.opts.material = matName;
      this._reapplyScalar(e);
      e.mesh.material.needsUpdate = true;
    }
    this._emit();
  }

  /** After a material swap: colour the new material with the active scalar again. */
  _reapplyScalar(e) {
    const child = e.activeScalar && e.children.get(e.activeScalar);
    if (!child) return;
    child._priorMaterialColor = undefined;   // the new material holds e.color
    child.apply(e.mesh, e);
  }

  setUniform(name, uniformName, value) {
    const e = this._objects.get(name);
    if (!e || !(e.mesh.material instanceof THREE.ShaderMaterial)) return;
    const u = e.mesh.material.uniforms[uniformName];
    if (u) u.value = value;
  }

  // ── Edge child ────────────────────────────────────────────────────────────

  /** Install an edge overlay child on a parent surface_mesh. Replaces any existing 'edges' child. */
  addEdgeChild(parentName, edgeVerts, edgeIdx, color = [0.1, 0.1, 0.1], radius = 0) {
    const e = this._objects.get(parentName);
    if (!e || e.type !== 'surface_mesh') return;
    // Cache source data on parent for radius-change rebuilds
    e.opts.edgeVerts = edgeVerts;
    e.opts.edgeIdx   = edgeIdx;
    e.opts.edgeAutoRadius = null;     // recomputed from these edges
    if (e.children.has('edges')) e.removeChild('edges', this.scene, e.mesh);
    radius = this._edgeRadius(e, radius);
    const mesh = this._buildCurveObj(edgeVerts, edgeIdx, color, radius);
    mesh.name = `${parentName}::edges`;
    this.scene.add(mesh);
    e.addChild(new EdgeChild({ mesh, color: [...color], radius }));
    this._emit();
  }

  setEdgeColor(parentName, rgb) {
    const e = this._objects.get(parentName); if (!e) return;
    const child = e.children.get('edges');   if (!child) return;
    child.setColor(rgb);
    this._emit();
  }

  setEdgeRadius(parentName, radius) {
    const e = this._objects.get(parentName); if (!e) return;
    const child = e.children.get('edges');   if (!child) return;
    const { color, visible } = child;
    e.removeChild('edges', this.scene, e.mesh);
    radius = this._edgeRadius(e, radius);
    const mesh = this._buildCurveObj(e.opts.edgeVerts, e.opts.edgeIdx, color, radius);
    mesh.name    = `${parentName}::edges`;
    mesh.visible = visible;
    this.scene.add(mesh);
    const newChild = new EdgeChild({ mesh, color: [...color], radius });
    newChild.visible = visible;
    e.addChild(newChild);
    this._emit();
  }

  /** Toggle edge overlay on a surface_mesh. Uses polygon edges pre-computed by the server. */
  toggleEdges(parentName, enabled) {
    const e = this._objects.get(parentName);
    if (!e || e.type !== 'surface_mesh') return;
    if (!enabled) {
      if (e.children.has('edges')) {
        e.removeChild('edges', this.scene, e.mesh);
        this._emit();
      }
      return;
    }
    // Already has edges — just show it
    if (e.children.has('edges')) {
      e.children.get('edges').setVisible(true);
      this._emit();
      return;
    }
    if (!e.opts.edgeVerts || !e.opts.edgeIdx) return;
    this.addEdgeChild(parentName, e.opts.edgeVerts, e.opts.edgeIdx, [0.1, 0.1, 0.1], 0);   // 0: automatic radius
  }

  // ── Scalar quantity ───────────────────────────────────────────────────────

  addScalarQuantity(parentName, key, values, definedOn = 'vertices') {
    const e = this._objects.get(parentName);
    if (!e || e.type !== 'surface_mesh') return;
    const wasActive = (e.activeScalar === key);
    if (e.children.has(key)) e.removeChild(key, this.scene, e.mesh);
    const child = new ScalarChild({ key, values, definedOn });
    e.addChild(child);
    // Auto-activate if no scalar active, or if replacing the currently active one
    if (wasActive || e.activeScalar === null) {
      this.setActiveScalar(parentName, key);
    }
    this._emit();
  }

  setActiveScalar(parentName, key) {
    const e = this._objects.get(parentName);
    if (!e) return;
    // Tear down the current active scalar (if different from the new one)
    if (e.activeScalar && e.activeScalar !== key) {
      const prev = e.children.get(e.activeScalar);
      if (prev && prev.type === 'scalar') prev.dispose(e.mesh, e);
    }
    e.activeScalar = key;
    if (key) {
      const child = e.children.get(key);
      if (!child || child.type !== 'scalar') { e.activeScalar = null; return; }
      child.apply(e.mesh, e);
    }
    this._emit();
  }

  setScalarRange(parentName, key, vmin, vmax) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(key);
    if (!child || child.type !== 'scalar') return;
    child.setRange(vmin, vmax, e.mesh, e);
  }

  // ── Vector quantity ───────────────────────────────────────────────────────

  /**
   * Add (or replace) a vector quantity on a surface mesh or point cloud.
   * Unlike scalars, any number of vector quantities can be visible at once.
   * Without a color, the next palette colour not used by the parent's other
   * vector quantities is taken (a replaced quantity keeps its colour).
   */
  addVectorQuantity(parentName, key, vectors, definedOn = 'vertices',
                    { color = null, length = 0.05, radius = null, show = null } = {}) {
    const parent = this._objects.get(parentName);
    if (!parent || (parent.type !== 'surface_mesh' && parent.type !== 'point_cloud')) return;
    const origins = this._vectorOrigins(parent, definedOn);
    if (!origins) return;
    if (origins.length !== vectors.length) {
      console.warn(`[kayviz] vector quantity '${key}' on '${parentName}': ` +
                   `${vectors.length / 3} vectors for ${origins.length / 3} ${definedOn}`);
    }
    const prev = parent.children.get(key);
    color  = color ?? (prev?.type === 'vector' ? prev.color : this._nextVectorColor(parent));
    radius = radius ?? length * 0.04;
    // A replaced quantity keeps its visibility unless show says otherwise
    const visible = show ?? (prev?.type === 'vector' ? prev.visible : true);
    if (prev) parent.removeChild(key, this.scene, parent.mesh);
    const mesh = this._buildArrowField(origins, vectors, length, radius, color);
    mesh.name        = `${parentName}::${key}`;
    mesh.renderOrder = 1;
    this.scene.add(mesh);
    const child = new VectorChild({ key, mesh, origins, vectors, definedOn,
                                    color: [...color], length, radius });
    parent.addChild(child);
    child.setVisible(visible);
    // Inherit a hidden parent; ticking the parent shows it (setEnabled
    // restores the meshes of children with child.visible).
    if (!parent.visible) mesh.visible = false;
    this._emit();
  }

  setVectorChildColor(parentName, childKey, rgb) {
    const e = this._objects.get(parentName); if (!e) return;
    const child = e.children.get(childKey);
    if (!child || child.type !== 'vector') return;
    child.setColor(rgb);
    this._emit();
  }

  /** Rebuild a vector child with a new arrow length. */
  setChildVectorLength(parentName, childKey, length) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(childKey);
    if (!child || child.type !== 'vector') return;
    const { origins, vectors, color, radius, visible } = child;
    const newMesh = this._buildArrowField(origins, vectors, length, radius, color);
    newMesh.name        = `${parentName}::${childKey}`;
    newMesh.renderOrder = 1;
    newMesh.visible     = visible;
    this.scene.remove(child.mesh);
    child.mesh.geometry?.dispose();
    const mats = Array.isArray(child.mesh.material) ? child.mesh.material : [child.mesh.material];
    mats.forEach(m => m?.dispose());
    child.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.scene.add(newMesh);
    child.mesh   = newMesh;
    child.length = length;
    this._emit();
  }

  /** Rebuild a vector child with a new arrow radius. */
  setChildVectorRadius(parentName, childKey, radius) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(childKey);
    if (!child || child.type !== 'vector') return;
    const { origins, vectors, color, length, visible } = child;
    const newMesh = this._buildArrowField(origins, vectors, length, radius, color);
    newMesh.name        = `${parentName}::${childKey}`;
    newMesh.renderOrder = 1;
    newMesh.visible     = visible;
    this.scene.remove(child.mesh);
    child.mesh.geometry?.dispose();
    const mats = Array.isArray(child.mesh.material) ? child.mesh.material : [child.mesh.material];
    mats.forEach(m => m?.dispose());
    child.mesh.dispose?.();   // InstancedMesh: frees its instance buffers
    this.scene.add(newMesh);
    child.mesh   = newMesh;
    child.radius = radius;
    this._emit();
  }

  // ── Child proxies (called by scene panel) ────────────────────────────────

  /** Toggle visibility of a child (vectors are independent of each other). */
  setChildVisible(parentName, childKey, visible) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(childKey);
    if (!child) return;
    child.setVisible(visible);
    if (child.mesh && !e.visible) child.mesh.visible = false;
    this._emit();
  }

  /** Remove a single child from a parent entry. */
  removeChild(parentName, childKey) {
    const e = this._objects.get(parentName);
    if (!e) return;
    e.removeChild(childKey, this.scene, e.mesh);
    this._emit();
  }

  remove(name) {
    this._remove(name);
    this._emit();
  }

  clearAll() {
    for (const name of [...this._objects.keys()]) this._remove(name);
    this._emit();
  }

  get objects() { return this._objects; }

  /** Set a label-visibility flag on a scene entry (used by scene panel checkboxes). */
  setLabelVisible(name, kind, visible) {
    const e = this._objects.get(name);
    if (!e) return;
    e.opts[kind] = visible;
    this._emit();
  }

  // ── Server message dispatcher ─────────────────────────────────────────────

  applyMessage(data) {
    this._batch++;
    try { this._applyObjects(data); }
    finally {
      this._batch--;
      if (!this._batch && this._emitDue) { this._emitDue = false; this._emit(); }
    }
  }

  _applyObjects(data) {
    // Objects registered with show=false; hidden after the whole batch so the
    // children that arrive after them (e.g. the edge_child of show_edges) hide too.
    // A quantity with show=true takes its target off that list and shows it.
    const hide = new Set();
    let shown = false;
    for (const obj of (data.objects ?? [])) {
      if (obj.show === false && obj.name && !obj.target) hide.add(obj.name);
      // ws.clear() from inside a callback travels as a marker in the object
      // stream (rather than its own message) so it stays ordered with the
      // geometry pushed after it in the same callback.
      if (obj.action === 'clear') { this.clearAll(); continue; }
      try { shown = this._applyObject(obj, hide) || shown; }
      catch (err) {
        // one bad object must not lose the rest of the message
        console.error(`[kayviz] could not show '${obj.name ?? obj.target}':`, err);
        this.errors.push(`${obj.name ?? obj.target}: ${err.message}`);
      }
    }
    for (const name of hide) this.setEnabled(name, false);
    if (hide.size || shown) this._emit();    // refresh the scene panel's checkboxes
  }

  /** One object of a message; returns true if it showed its (hidden) target. */
  _applyObject(obj, hide) {
    let shown = false;
    switch (obj.type) {
      case 'surface_mesh': {
        this.registerSurfaceMesh(obj.name, obj.vertices, obj.faces,
                                 obj.face_size ?? 3, obj.color ?? [0.8,0.8,0.8],
                                 obj.opacity ?? 1.0, obj.material ?? null);
        const en = this._objects.get(obj.name);
        if (en) {
          if (obj.tris_per_face) en.opts.trisPerFace = obj.tris_per_face;
          if (obj.poly_edges) {
            // index pairs into the mesh's own vertices
            en.opts.edgeVerts = en.opts.vertices;
            en.opts.edgeIdx   = obj.poly_edges;
          } else if (obj.poly_edge_verts) {
            // older servers: coordinates of both ends per edge
            en.opts.edgeVerts = obj.poly_edge_verts;
            en.opts.edgeIdx   = obj.poly_edge_conn;
          }
          if (obj.show_edges && en.opts.edgeIdx) {
            this.addEdgeChild(obj.name, en.opts.edgeVerts, en.opts.edgeIdx,
                              obj.edge_color ?? [0.1, 0.1, 0.1], obj.edge_radius ?? 0);
          }
        }
        break;
      }
      case 'curve_network':
        this.registerCurveNetwork(obj.name, obj.vertices, obj.edges,
                                  obj.color ?? [0.8,0.2,0.2], obj.radius ?? 0.002);
        break;
      case 'point_cloud':
        this.registerPointCloud(obj.name, obj.points,
                                obj.color ?? [0.2,0.5,0.8], obj.radius ?? 0.0005);
        break;
      case 'edge_child':
        // { type:'edge_child', target, vertices, edges, color, radius }
        this.addEdgeChild(obj.target, obj.vertices, obj.edges,
                          obj.color ?? [0.1,0.1,0.1], obj.radius ?? 0);
        break;
      case 'scalar_quantity': {
        this.addScalarQuantity(obj.target, obj.name, obj.values,
                               obj.defined_on ?? 'vertices');
        const parent = this._objects.get(obj.target);
        if (!parent || !parent.children.has(obj.name)) break;
        if (obj.show === true) {
          this.setActiveScalar(obj.target, obj.name);
          hide.delete(obj.target);
          this.setEnabled(obj.target, true);
          shown = true;
        } else if (obj.show === false && parent.activeScalar === obj.name) {
          this.setActiveScalar(obj.target, null);
        }
        break;
      }
      case 'vector_quantity': {
        this.addVectorQuantity(obj.target, obj.name, obj.vectors,
                               obj.defined_on ?? 'vertices', {
                                 color: obj.color ?? null, length: obj.length ?? 0.05,
                                 radius: obj.radius ?? null, show: obj.show ?? null,
                               });
        const parent = this._objects.get(obj.target);
        if (obj.show === true && parent?.children.has(obj.name)) {
          hide.delete(obj.target);
          this.setEnabled(obj.target, true);
          shown = true;
        }
        break;
      }
      case 'vector_field':
        this.registerVectorField(obj.name, obj.origins, obj.vectors,
                                 obj.length ?? 0.05, obj.radius ?? null, obj.color ?? [0.2, 0.8, 0.4]);
        break;
      case 'set_enabled':
        this.setEnabled(obj.name, obj.enabled);
        break;
    }
    return shown;
  }

  // ── Internals ─────────────────────────────────────────────────────────────

  _remove(name) {
    const e = this._objects.get(name);
    if (e) e.dispose(this.scene);
    this._objects.delete(name);
  }

  _buildCurveObj(vertices, edges, color, radius) {
    if (radius > 0) return this._buildTubeNetwork(vertices, edges, color, radius);
    const positions = [];
    for (let k = 0; k < edges.length; k += 2) {
      const i = edges[k], j = edges[k + 1];
      positions.push(vertices[i*3], vertices[i*3+1], vertices[i*3+2],
                     vertices[j*3], vertices[j*3+1], vertices[j*3+2]);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({ color: this._rgb(color) });
    return new THREE.LineSegments(geo, mat);
  }

  /**
   * Radius of an edge overlay: `radius` if > 0, else 3% of the median edge length.
   * Edges are always tubes: zero-width lines can't be occluded reliably and showed through objects.
   */
  _edgeRadius(e, radius) {
    e.opts.edgeAutoRadius ??= this._autoEdgeRadius(e.opts.edgeVerts, e.opts.edgeIdx);
    return radius > 0 ? radius : e.opts.edgeAutoRadius;
  }

  _autoEdgeRadius(V, E) {
    const m = E.length / 2;
    if (!m) return 1e-3;
    const step = Math.max(1, Math.floor(m / 2000));       // a sample is enough for the median
    const L = [];
    for (let k = 0; k < m; k += step) {
      const i = E[2*k] * 3, j = E[2*k + 1] * 3;
      L.push(Math.hypot(V[i] - V[j], V[i+1] - V[j+1], V[i+2] - V[j+2]));
    }
    L.sort((a, b) => a - b);
    return Math.max(0.03 * L[L.length >> 1], 1e-6);
  }

  _buildTubeNetwork(vertices, edges, color, radius) {
    // open prisms (no caps), written straight into typed arrays: fast enough for ~10^5 edges
    const mat  = new THREE.MeshPhongMaterial({
      color: this._rgb(color), shininess: 30,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
    });
    const m    = edges.length / 2;
    const segs = m > 20000 ? 4 : 6;
    const pos  = new Float32Array(m * 2 * segs * 3);
    const nrm  = new Float32Array(m * 2 * segs * 3);
    const idx  = new Uint32Array(m * segs * 6);
    const cs   = Array.from({ length: segs }, (_, s) => Math.cos(2 * Math.PI * s / segs));
    const sn   = Array.from({ length: segs }, (_, s) => Math.sin(2 * Math.PI * s / segs));
    let nv = 0, ni = 0;
    for (let k = 0; k < m; k++) {
      const i = edges[2*k] * 3, j = edges[2*k + 1] * 3;
      const ax = vertices[i], ay = vertices[i+1], az = vertices[i+2];
      let dx = vertices[j] - ax, dy = vertices[j+1] - ay, dz = vertices[j+2] - az;
      const len = Math.hypot(dx, dy, dz);
      if (len < 1e-12) continue;
      dx /= len; dy /= len; dz /= len;
      // u ⟂ d (cross with the axis least aligned with d), w = d × u
      let ux, uy, uz;
      if (Math.abs(dx) < 0.9) { ux = 0; uy = dz; uz = -dy; } else { ux = -dz; uy = 0; uz = dx; }
      const ul = Math.hypot(ux, uy, uz); ux /= ul; uy /= ul; uz /= ul;
      const wx = dy*uz - dz*uy, wy = dz*ux - dx*uz, wz = dx*uy - dy*ux;
      for (let end = 0; end < 2; end++) {
        const px = end ? vertices[j] : ax, py = end ? vertices[j+1] : ay, pz = end ? vertices[j+2] : az;
        for (let s = 0; s < segs; s++) {
          const nx = cs[s]*ux + sn[s]*wx, ny = cs[s]*uy + sn[s]*wy, nz = cs[s]*uz + sn[s]*wz;
          const o = (nv + end*segs + s) * 3;
          pos[o] = px + radius*nx; pos[o+1] = py + radius*ny; pos[o+2] = pz + radius*nz;
          nrm[o] = nx; nrm[o+1] = ny; nrm[o+2] = nz;
        }
      }
      for (let s = 0; s < segs; s++) {
        const a = nv + s, b = nv + (s + 1) % segs, c = a + segs, d = b + segs;
        idx[ni++] = a; idx[ni++] = b; idx[ni++] = d;
        idx[ni++] = a; idx[ni++] = d; idx[ni++] = c;
      }
      nv += 2 * segs;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos.subarray(0, nv * 3), 3));
    geo.setAttribute('normal',   new THREE.BufferAttribute(nrm.subarray(0, nv * 3), 3));
    geo.setIndex(new THREE.BufferAttribute(idx.subarray(0, ni), 1));
    return new THREE.Mesh(geo, mat);
  }

  _buildArrowField(origins, vectors, length, radius, color) {
    // One shaft + cone geometry along +y, instanced per arrow (rotation + origin):
    // geometry memory and build time no longer grow with the number of arrows.
    const SEGS   = 7;
    const shaftL = length * 0.80, coneL = length * 0.20;
    const shaft  = new THREE.CylinderGeometry(radius, radius, shaftL, SEGS, 1, false);
    shaft.translate(0, shaftL / 2, 0);
    const cone   = new THREE.ConeGeometry(radius * 2.5, coneL, SEGS, 1, false);
    cone.translate(0, shaftL + coneL / 2, 0);
    const geo = mergeGeometries([shaft, cone], false);
    shaft.dispose(); cone.dispose();

    const mat  = new THREE.MeshPhongMaterial({ color: this._rgb(color), shininess: 40 });
    const N    = Math.floor(origins.length / 3);
    const up   = new THREE.Vector3(0, 1, 0), dir = new THREE.Vector3();
    const quat = new THREE.Quaternion(), pos = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1);
    const m    = new THREE.Matrix4();
    const mesh = new THREE.InstancedMesh(geo, mat, N);
    let k = 0;
    for (let i = 0; i < N; i++) {
      dir.set(vectors[i*3], vectors[i*3+1], vectors[i*3+2]);
      const len = dir.length();
      if (!(len > 1e-9)) continue;
      dir.divideScalar(len);
      if (dir.dot(up) < -0.9999) quat.set(1, 0, 0, 0);
      else quat.setFromUnitVectors(up, dir);
      pos.set(origins[i*3], origins[i*3+1], origins[i*3+2]);
      mesh.setMatrixAt(k++, m.compose(pos, quat, one));
    }
    mesh.count = k;                      // zero-length vectors are skipped
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
    return mesh;
  }

  _buildMeshGeo(vertices, faces, faceSize) {
    const geo = new THREE.BufferGeometry();
    // a Float32Array from a binary frame is used as is (Float32BufferAttribute would copy it)
    const pos = vertices instanceof Float32Array ? vertices : new Float32Array(vertices);
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    let indices;
    if (faceSize === 3) {
      indices = faces instanceof Int32Array
        ? new Uint32Array(faces.buffer, faces.byteOffset, faces.length)
        : Uint32Array.from(faces);
    } else {
      const k = faceSize - 2, n = faces.length / faceSize;
      indices = new Uint32Array(n * k * 3);
      let o = 0;
      for (let i = 0; i < faces.length; i += faceSize)
        for (let t = 1; t < faceSize - 1; t++) {
          indices[o++] = faces[i]; indices[o++] = faces[i+t]; indices[o++] = faces[i+t+1];
        }
    }
    geo.setIndex(new THREE.BufferAttribute(indices, 1));
    geo.computeVertexNormals();
    return geo;
  }

  /** Polygon centroids of a surface mesh (cached; used by labels and face vectors). */
  faceCentroids(e) {
    return (e.opts._centroids ??= this._vectorOrigins(e, 'faces'));
  }

  /**
   * Arrow base points of a vector quantity: the vertices / points, or the face
   * barycenters (vertex average of each original polygon). Polygons that the
   * server fan-triangulated are rebuilt from trisPerFace.
   */
  _vectorOrigins(e, definedOn) {
    if (e.type === 'point_cloud') return e.opts.points;
    const V = e.opts.vertices;
    if (definedOn !== 'faces') return V;
    const F = e.opts.faces, fs = e.opts.faceSize;
    if (!V || !F) return null;
    const polys = [];
    if (e.opts.trisPerFace) {
      let t = 0;
      for (const n of e.opts.trisPerFace) {
        const p = [F[3*t], F[3*t + 1], F[3*t + 2]];
        for (let k = 1; k < n; k++) p.push(F[3*(t + k) + 2]);
        polys.push(p);
        t += n;
      }
    } else {
      for (let i = 0; i < F.length; i += fs) polys.push(Array.from(F.slice(i, i + fs)));
    }
    const out = new Float32Array(polys.length * 3);
    polys.forEach((p, i) => {
      for (const v of p) {
        out[3*i] += V[3*v]; out[3*i + 1] += V[3*v + 1]; out[3*i + 2] += V[3*v + 2];
      }
      out[3*i] /= p.length; out[3*i + 1] /= p.length; out[3*i + 2] /= p.length;
    });
    return out;
  }

  /** First VECTOR_PALETTE colour not used by e's vector children (cycles when all are used). */
  _nextVectorColor(e) {
    const used = [...e.children.values()].filter(c => c.type === 'vector').map(c => c.color);
    const same = (a, b) => a.every((x, i) => Math.abs(x - b[i]) < 1e-6);
    const free = VECTOR_PALETTE.find(c => !used.some(u => same(u, c)));
    return [...(free ?? VECTOR_PALETTE[used.length % VECTOR_PALETTE.length])];
  }

  _rgb([r, g, b]) { return new THREE.Color(r, g, b); }

  _emit() {
    if (this._batch) { this._emitDue = true; return; }
    document.dispatchEvent(new CustomEvent('viewer-changed'));
  }

  _buildSphereInstances(pts, count, color, radius) {
    const geo = new THREE.SphereGeometry(radius, 12, 8);
    const mat = new THREE.MeshPhongMaterial({ color: this._rgb(color) });
    const mesh = new THREE.InstancedMesh(geo, mat, count);
    const m = new THREE.Matrix4();
    for (let i = 0; i < count; i++) {
      m.setPosition(pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2]);
      mesh.setMatrixAt(i, m);
    }
    mesh.instanceMatrix.needsUpdate = true;
    return mesh;
  }

}
