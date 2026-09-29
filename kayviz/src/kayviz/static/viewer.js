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

export class Viewer {
  constructor(scene, matLib = Materials) {
    this.scene    = scene;
    this.matLib   = matLib;
    this._objects = new Map();  // name → SceneEntry
  }

  // ── Registration ─────────────────────────────────────────────────────────

  registerSurfaceMesh(name, vertices, faces, faceSize = 3,
                      color = [0.8, 0.8, 0.8], opacity = 1.0,
                      material = 'physical') {
    this._remove(name);
    const geo  = this._buildMeshGeo(vertices, faces, faceSize);
    const mat  = this.matLib.build(material, color, opacity);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name  = name;
    this.scene.add(mesh);
    this._objects.set(name, new SceneEntry('surface_mesh', mesh, {
      color: [...color], opacity, material, visible: true,
      vertices, faceSize,
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
    e.mesh.material.color.setRGB(color[0], color[1], color[2]);
    e.mesh.material.needsUpdate = true;
  }

  setOpacity(name, t) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'surface_mesh') return;
    e.opacity                    = t;
    e.mesh.material.opacity      = t;
    e.mesh.material.transparent  = t < 1.0;
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
    this.scene.add(newMesh);
    e.mesh = newMesh;
  }

  setMaterial(name, matName) {
    const e = this._objects.get(name);
    if (!e || e.type !== 'surface_mesh') return;
    this.matLib.applyTo(e.mesh, matName, e.color, e.opacity);
    e.opts.material = matName;
    if (e.mesh.geometry.hasAttribute('color')) {
      e.mesh.material.vertexColors = true;
    }
    e.mesh.material.needsUpdate = true;
    this._emit();
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
    if (e.children.has('edges')) e.removeChild('edges', this.scene, e.mesh);
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
    this.addEdgeChild(parentName, e.opts.edgeVerts, e.opts.edgeIdx, [0.1, 0.1, 0.1], 0);
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
      child.apply(e.mesh, e, this._viridis.bind(this));
    }
    this._emit();
  }

  setScalarRange(parentName, key, vmin, vmax) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(key);
    if (!child || child.type !== 'scalar') return;
    child.setRange(vmin, vmax, e.mesh, e, this._viridis.bind(this));
  }

  // ── Vector quantity ───────────────────────────────────────────────────────

  /** Set the active vector child — hides all others. Pass null to hide all. */
  setActiveVector(parentName, key) {
    const e = this._objects.get(parentName); if (!e) return;
    for (const c of e.children.values()) {
      if (c.type !== 'vector') continue;
      c.setVisible(c.key === key);
    }
    e.activeVector = key;
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
    this.scene.add(newMesh);
    child.mesh   = newMesh;
    child.radius = radius;
    this._emit();
  }

  // ── Child proxies (called by scene panel) ────────────────────────────────

  /** Toggle visibility of a child. Vectors respect "active-of-kind" radio semantics. */
  setChildVisible(parentName, childKey, visible) {
    const e = this._objects.get(parentName);
    if (!e) return;
    const child = e.children.get(childKey);
    if (!child) return;
    if (child.type === 'vector') {
      if (visible) {
        // Hide all other vectors; make this one active
        for (const c of e.children.values()) {
          if (c.type === 'vector' && c !== child) c.setVisible(false);
        }
        e.activeVector = childKey;
      } else if (e.activeVector === childKey) {
        e.activeVector = null;
      }
    }
    child.setVisible(visible);
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
    for (const obj of (data.objects ?? [])) {
      // ws.clear() from inside a callback travels as a marker in the object
      // stream (rather than its own message) so it stays ordered with the
      // geometry pushed after it in the same callback.
      if (obj.action === 'clear') { this.clearAll(); continue; }
      switch (obj.type) {
        case 'surface_mesh': {
          this.registerSurfaceMesh(obj.name, obj.vertices, obj.faces,
                                   obj.face_size ?? 3, obj.color ?? [0.8,0.8,0.8],
                                   obj.opacity ?? 1.0, obj.material ?? 'physical');
          const en = this._objects.get(obj.name);
          if (en) {
            if (obj.tris_per_face)   en.opts.trisPerFace = obj.tris_per_face;
            if (obj.poly_edge_verts) en.opts.edgeVerts   = obj.poly_edge_verts;
            if (obj.poly_edge_conn)  en.opts.edgeIdx     = obj.poly_edge_conn;
            if (obj.show_edges)      this.toggleEdges(obj.name, true);
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
        case 'scalar_quantity':
          this.addScalarQuantity(obj.target, obj.name, obj.values,
                                 obj.defined_on ?? 'vertices');
          break;
        case 'vector_quantity': {
          const parent = this._objects.get(obj.target);
          if (!parent || parent.type !== 'surface_mesh') break;
          const origins = parent.opts.vertices;
          if (!origins) break;
          const key    = obj.name;
          const color  = obj.color  ?? [0.2, 0.8, 0.4];
          const length = obj.length ?? 0.05;
          const radius = obj.radius ?? length * 0.04;
          if (parent.children.has(key)) parent.removeChild(key, this.scene, parent.mesh);
          const mesh = this._buildArrowField(origins, obj.vectors, length, radius, color);
          mesh.name        = `${obj.target}::${key}`;
          mesh.renderOrder = 1;
          this.scene.add(mesh);
          const child = new VectorChild({ key, mesh, origins,
                                          vectors: obj.vectors, color: [...color], length, radius });
          parent.addChild(child);
          // Auto-activate if no vector active, or if replacing the currently active one
          if (parent.activeVector === null || parent.activeVector === key) {
            this.setActiveVector(obj.target, key);
          } else {
            // Arriving non-active vector starts hidden
            child.setVisible(false);
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
    }
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
    const mat = new THREE.LineBasicMaterial({ color: this._rgb(color), depthTest: false });
    return new THREE.LineSegments(geo, mat);
  }

  _buildTubeNetwork(vertices, edges, color, radius) {
    const segs = 6;
    const mat  = new THREE.MeshPhongMaterial({
      color: this._rgb(color), shininess: 30,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
    });

    const merged = [];
    const matrix = new THREE.Matrix4();
    const up     = new THREE.Vector3(0, 1, 0);

    for (let k = 0; k < edges.length; k += 2) {
      const i  = edges[k], j = edges[k + 1];
      const pa = new THREE.Vector3(vertices[i*3], vertices[i*3+1], vertices[i*3+2]);
      const pb = new THREE.Vector3(vertices[j*3], vertices[j*3+1], vertices[j*3+2]);
      const length = pa.distanceTo(pb);
      if (length < 1e-9) continue;
      const mid = pa.clone().add(pb).multiplyScalar(0.5);
      const dir = pb.clone().sub(pa).normalize();
      const quat = dir.dot(up) < -0.9999
        ? new THREE.Quaternion(1, 0, 0, 0)
        : new THREE.Quaternion().setFromUnitVectors(up, dir);
      matrix.compose(mid, quat, new THREE.Vector3(1, 1, 1));
      const cyl = new THREE.CylinderGeometry(radius, radius, length, segs, 1, false);
      cyl.applyMatrix4(matrix);
      merged.push(cyl);
    }

    if (merged.length === 0) return new THREE.Mesh(new THREE.BufferGeometry(), mat);
    const geo = mergeGeometries(merged, false);
    merged.forEach(g => g.dispose());
    return new THREE.Mesh(geo, mat);
  }

  _buildArrowField(origins, vectors, length, radius, color) {
    const SEGS   = 7;
    const shaftR = radius;
    const coneR  = radius * 2.5;
    const shaftL = length * 0.80;
    const coneL  = length * 0.20;

    const mat    = new THREE.MeshPhongMaterial({ color: this._rgb(color), shininess: 40 });
    const up     = new THREE.Vector3(0, 1, 0);
    const matrix = new THREE.Matrix4();
    const merged = [];
    const N      = origins.length / 3;

    for (let i = 0; i < N; i++) {
      const ox = origins[i*3], oy = origins[i*3+1], oz = origins[i*3+2];
      const vx = vectors[i*3], vy = vectors[i*3+1], vz = vectors[i*3+2];
      const len = Math.sqrt(vx*vx + vy*vy + vz*vz);
      if (len < 1e-9) continue;
      const dir  = new THREE.Vector3(vx/len, vy/len, vz/len);
      const quat = dir.dot(up) < -0.9999
        ? new THREE.Quaternion(1, 0, 0, 0)
        : new THREE.Quaternion().setFromUnitVectors(up, dir);

      const shaftCenter = new THREE.Vector3(
        ox + dir.x * shaftL * 0.5, oy + dir.y * shaftL * 0.5, oz + dir.z * shaftL * 0.5);
      matrix.compose(shaftCenter, quat, new THREE.Vector3(1, 1, 1));
      const shaft = new THREE.CylinderGeometry(shaftR, shaftR, shaftL, SEGS, 1, false);
      shaft.applyMatrix4(matrix);
      merged.push(shaft);

      const coneCenter = new THREE.Vector3(
        ox + dir.x * (shaftL + coneL * 0.5),
        oy + dir.y * (shaftL + coneL * 0.5),
        oz + dir.z * (shaftL + coneL * 0.5));
      matrix.compose(coneCenter, quat, new THREE.Vector3(1, 1, 1));
      const cone = new THREE.ConeGeometry(coneR, coneL, SEGS, 1, false);
      cone.applyMatrix4(matrix);
      merged.push(cone);
    }

    if (merged.length === 0) return new THREE.Mesh(new THREE.BufferGeometry(), mat);
    const geo = mergeGeometries(merged, false);
    merged.forEach(g => g.dispose());
    return new THREE.Mesh(geo, mat);
  }

  _buildMeshGeo(vertices, faces, faceSize) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    const indices = [];
    for (let i = 0; i < faces.length; i += faceSize) {
      for (let t = 1; t < faceSize - 1; t++)
        indices.push(faces[i], faces[i+t], faces[i+t+1]);
    }
    geo.setIndex(indices);
    geo.computeVertexNormals();
    return geo;
  }

  _rgb([r, g, b]) { return new THREE.Color(r, g, b); }

  _emit() { document.dispatchEvent(new CustomEvent('viewer-changed')); }

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

  _viridis(t) {
    const s = [[0.267,0.005,0.329],[0.190,0.407,0.574],[0.128,0.566,0.551],
               [0.208,0.718,0.473],[0.993,0.906,0.144]];
    const i = Math.min(Math.floor(t*(s.length-1)), s.length-2);
    const f = t*(s.length-1)-i;
    return s[i].map((c,k) => c + f*(s[i+1][k]-c));
  }
}
