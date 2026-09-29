# REFACTOR_CHILDREN.md — Children-First Scene Model

> **Status:** implemented — `kayviz/src/kayviz/static/SceneEntry.js` defines `Child`,
> `EdgeChild`, `VectorChild` and `ScalarChild`. This is the design record; paths are
> the current kayviz ones (the frontend was `frontend/` and the Python side
> `server/webscope/` before the library split).

## 0. Goal & Scope

Refactor `kayviz/src/kayviz/static/SceneEntry.js`, `kayviz/src/kayviz/static/viewer.js`, `kayviz/src/kayviz/static/gui/scene_panel.js`, and `kayviz/src/kayviz/serializers.py` so that **edges, scalar quantities, and vector quantities are all polymorphic children of a parent surface_mesh entry**, with type-specific UI, "active-of-kind" semantics, and per-child lifecycle. Public Python API (`ws.register_surface_mesh(..., show_edges=True)`, `ws.add_scalar_quantity`, `ws.add_vector_quantity`) is unchanged.

Files in scope:

- `kayviz/src/kayviz/static/SceneEntry.js` — full rewrite.
- `kayviz/src/kayviz/static/viewer.js` — surgical edits (registration, dispatcher, helpers).
- `kayviz/src/kayviz/static/gui/scene_panel.js` — gut `_buildRow` scalar block; expand `_buildChildRow` to dispatch per child class.
- `kayviz/src/kayviz/serializers.py` — `surface_mesh()` now returns an `edge_child` dict (not a `curve_network`); add light helpers as needed.
- `kayviz/src/kayviz/webscope/scene.py` — no API change, but a one-line tweak to keep `register_surface_mesh` correct (already supports list returns).
- `kayviz/src/kayviz/webscope/script.py` — already supports list returns; verify path.

Files **not** changed: `kayviz/src/kayviz/static/main.js`, `kayviz/src/kayviz/static/app_loader.js`, `kayviz/src/kayviz/static/ws.js`, `kayviz/src/kayviz/static/lib/MaterialLibrary.js`, `kayviz/src/kayviz/static/gui/auto_panel.js`, `kayviz/src/kayviz/static/gui/lighting_panel.js`, all `Code/`, all `server/main.py`/`kayviz/src/kayviz/webscope/app.py`/`broadcast_mixin.py`/`callback_app.py` (the new wire shape `edge_child` flows through them transparently — they only forward JSON).

---

## 1. New Frontend Class Hierarchy

All child classes live in `kayviz/src/kayviz/static/SceneEntry.js`. They are exported from there alongside `SceneEntry`. Use ES-module class syntax (no TypeScript). Child constructors take only data; the **viewer** is responsible for adding/removing the child's mesh from `THREE.Scene`. Children themselves never reach into the viewer.

### 1.1 `class Child` (abstract base)

Fields:
- `key: string` — unique within parent (`'edges'`, scalar/vector field name).
- `type: string` — `'edges' | 'scalar' | 'vector'`. Used by panel for badge + dispatch.
- `visible: boolean` — last user-set visibility (separate from THREE `mesh.visible`, see §2.4).

Methods (no-ops in base; subclasses override):
- `dispose(scene, parentMesh)` — remove mesh from scene, dispose GPU resources, undo any parent-side mutations.
- `setVisible(visible)` — toggle `this.visible` AND `mesh.visible` if the child has a mesh.

### 1.2 `class EdgeChild extends Child`

Constructor: `new EdgeChild({ mesh, color, radius })`
- `key = 'edges'`, `type = 'edges'`.
- Fields: `mesh: THREE.Object3D` (LineSegments or merged tube Mesh), `color: [r,g,b]`, `radius: number` (0 = LineSegments, >0 = tube mesh).
- Stores no source verts/edges itself — when radius changes, the **viewer** must rebuild via `viewer._buildCurveObj(parent.opts.edgeVerts, parent.opts.edgeIdx, color, radius)` from the parent's stashed edge data (see §2.1). The new `EdgeChild` instance replaces the old.

Methods:
- `setColor(rgb)` — `mesh.material.color.setRGB(...rgb)`; sets `this.color`.
- `setVisible(v)` — base impl applies.
- `dispose(scene)` — `scene.remove(mesh)`; dispose geometry + materials.
- `setRadius` is **not** on the child — radius change requires geometry rebuild, so the panel calls `viewer.setEdgeRadius(parentName, radius)` which rebuilds + swaps in a new `EdgeChild`.

### 1.3 `class VectorChild extends Child`

Constructor: `new VectorChild({ key, mesh, origins, vectors, color, length })`
- `type = 'vector'`.
- Fields: `key, mesh, origins (Float32-like), vectors (Float32-like), color [r,g,b], length: number`.
- Stores `origins`/`vectors` so `length` changes can rebuild without round-tripping to the server.

Methods:
- `setColor(rgb)` — `mesh.material.color.setRGB(...)`; sets `this.color`.
- `setVisible(v)` — base.
- `dispose(scene)` — remove + dispose.
- `setLength(length, viewer)` — uses `viewer._buildArrowField(origins, vectors, length, color)`; the **viewer** wraps this in `viewer.setChildVectorLength(...)` (already present, restructure to delegate).

### 1.4 `class ScalarChild extends Child`

Constructor: `new ScalarChild({ key, values, definedOn, color = null })`
- `type = 'scalar'`. **Has no mesh** of its own.
- Fields:
  - `key: string`
  - `values: number[]` (vertex- or face-defined).
  - `definedOn: 'vertices' | 'faces'`.
  - `dataMin, dataMax: number` — computed in constructor with `Math.min(...values)` / `Math.max(...values)`.
  - `vmin, vmax: number` — initially `dataMin` / `dataMax`; mutated by user sliders.
  - `_colorAttrBackup: Float32BufferAttribute | null` — original parent color attribute (or `null` if parent had none); restored on `dispose`.
  - `_priorMaterialColor: [r,g,b] | null` — copy of parent material `color` so `dispose` can revert.

Methods:
- `apply(parentMesh, parentEntry, viridisFn)` — installs vertex colors on `parentMesh.geometry`; sets `parentMesh.material.vertexColors = true`. If `definedOn === 'faces'` and `parentMesh.geometry.index !== null`, first calls `parentMesh.geometry.toNonIndexed()` and swaps it in (also sets `parentEntry.opts.nonIndexed = true`); after geometry replacement the viewer must rebuild the edge child if present (see §2.5). Backs up the previous color attribute (if any) into `_colorAttrBackup` and the previous material color into `_priorMaterialColor` — but only on the very first `apply`; subsequent re-applies (e.g. range change) do NOT overwrite the backup.
- `setRange(vmin, vmax, parentMesh, viridisFn)` — recomputes the color buffer with new range; reuses the already-applied non-indexed geometry. Mirrors current `viewer.applyColormap` body.
- `dispose(parentMesh, parentEntry)` — restores `_colorAttrBackup` (deletes the `color` attribute if it was null); restores material color; sets `material.vertexColors = false`; flags `material.needsUpdate = true`. Does NOT undo `toNonIndexed` (irreversible without re-receiving the original faces — accept this trade-off, document in code comment).
- `drawHistogram(canvas, gradCanvas, viridisFn)` — same body as the current `drawHistogram` closure in scene_panel; uses `this.vmin`/`this.vmax`/`this.dataMin`/`this.dataMax`/`this.values`.

Note: `ScalarChild` is the only child with `mesh = null`. Code that iterates children must tolerate this (the viewer's parent-visibility-propagation loop must guard `if (child.mesh) child.mesh.visible = ...`).

### 1.5 Updated `class SceneEntry`

Fields after refactor:
- `type, mesh, visible, color, opacity, radius` — unchanged.
- `children: Map<string, Child>` — values are now `EdgeChild | ScalarChild | VectorChild` instances.
- `activeScalar: string | null` — key of the currently applied scalar child (null = parent shows its own flat color).
- `activeVector: string | null` — key of the currently visible vector child (null = none visible).
- `opts` — keep the same shape minus the dead fields (see §1.6). Keep:
  - `vertices, faceSize, material, trisPerFace, nonIndexed`
  - **NEW**: `edgeVerts, edgeIdx` — flat float/int arrays cached for tube-radius rebuilds. Set when the first `EdgeChild` arrives.

Updated methods:
- `constructor(type, mesh, opts)` — initialize `activeScalar = null`, `activeVector = null`.
- `addChild(child)` — `this.children.set(child.key, child)`. Replaces `setChild`.
- `removeChild(key, scene, parentMesh)` — fetch child; call `child.dispose(scene, parentMesh, this)` polymorphically; if `key === activeScalar` set `activeScalar = null`; if `key === activeVector` set `activeVector = null`; delete from map.
- `dispose(scene)` — for each child key, call `removeChild(key, scene, this.mesh)`; then dispose own mesh as today.

Remove from base class: `setChild` (renamed to `addChild`), `setChildVisible` (the per-class `setVisible` replaces it; the **viewer**'s `setChildVisible` proxy stays).

### 1.6 Dead fields / methods to delete from `SceneEntry`

- Header comment lines 9–10 mentioning `opts.scalar`, `opts.showEdges`, `opts.edgeColor`, `opts.edgeRadius`, `opts.edgeVerts`, `opts.edgeIdx` — rewrite to reflect new shape (keep `edgeVerts`/`edgeIdx` since we ARE keeping them; remove `scalar`, `showEdges`, `edgeColor`, `edgeRadius`).
- `setChild` (replaced by `addChild`).
- `setChildVisible` (children own this now).
- The bare `meta = {}` shape with `length`/`color`/`type` fields on the map values — replaced by typed `Child` instances.

---

## 2. Viewer changes (`kayviz/src/kayviz/static/viewer.js`)

### 2.1 `registerSurfaceMesh` (lines 23–39)

Drop the dead `scalar: null, ... showEdges: false` initializers. Replace the opts object with:

```js
this._objects.set(name, new SceneEntry('surface_mesh', mesh, {
  color: [...color], opacity, material, visible: true,
  vertices, faceSize,
  trisPerFace: null, nonIndexed: false,
  edgeVerts: null, edgeIdx: null,   // populated when first EdgeChild arrives
}));
```

### 2.2 `setEnabled` (lines 85–94)

Replace child loop with the null-mesh-safe form:

```js
for (const child of e.children.values()) {
  if (child.mesh && child.visible) child.mesh.visible = enabled;
}
```

ScalarChild has no mesh; nothing to do for it on parent visibility toggle.

### 2.3 `setChildVisible` / `removeChild` proxies (lines 189–202)

Keep both, but route through the new child API:

```js
setChildVisible(parentName, childKey, visible) {
  const e = this._objects.get(parentName);
  if (!e) return;
  const child = e.children.get(childKey);
  if (!child) return;
  // Vector "active" radio: if making one vector visible, hide all others.
  if (child.type === 'vector' && visible) {
    for (const c of e.children.values()) {
      if (c.type === 'vector' && c !== child) c.setVisible(false);
    }
    e.activeVector = childKey;
  } else if (child.type === 'vector' && !visible && e.activeVector === childKey) {
    e.activeVector = null;
  }
  child.setVisible(visible);
  this._emit();
}

removeChild(parentName, childKey) {
  const e = this._objects.get(parentName);
  if (!e) return;
  e.removeChild(childKey, this.scene, e.mesh);
  this._emit();
}
```

### 2.4 NEW: edge handling

Add the following methods (replace the broken `_rebuildEdgeOverlay` reference):

```js
/** Install an edge overlay child on a parent mesh. Replaces existing 'edges' child. */
addEdgeChild(parentName, edgeVerts, edgeIdx, color = [0.1,0.1,0.1], radius = 0) {
  const e = this._objects.get(parentName);
  if (!e || e.type !== 'surface_mesh') return;
  // Cache source data on parent so radius rebuilds work without server round-trip.
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
  const child = e.children.get('edges'); if (!child) return;
  child.setColor(rgb);
}

setEdgeRadius(parentName, radius) {
  const e = this._objects.get(parentName); if (!e) return;
  const child = e.children.get('edges'); if (!child) return;
  // Rebuild via _buildCurveObj using cached edgeVerts/edgeIdx.
  const color = child.color;
  const visible = child.visible;
  e.removeChild('edges', this.scene, e.mesh);
  const mesh = this._buildCurveObj(e.opts.edgeVerts, e.opts.edgeIdx, color, radius);
  mesh.name = `${parentName}::edges`;
  mesh.visible = visible;
  this.scene.add(mesh);
  const newChild = new EdgeChild({ mesh, color: [...color], radius });
  newChild.visible = visible;
  e.addChild(newChild);
  this._emit();
}
```

### 2.5 `addScalarQuantity` (lines 218–237) — full rewrite

```js
addScalarQuantity(parentName, key, values, definedOn = 'vertices') {
  const e = this._objects.get(parentName);
  if (!e || e.type !== 'surface_mesh') return;
  const wasActive = (e.activeScalar === key);
  // Replace existing child with the same key (re-registration).
  if (e.children.has(key)) e.removeChild(key, this.scene, e.mesh);
  const child = new ScalarChild({ key, values, definedOn });
  e.addChild(child);
  // Auto-activate behavior: new scalar becomes active if no scalar is currently
  // active OR if a stream replaces the previously-active one.
  if (wasActive || e.activeScalar === null) {
    this.setActiveScalar(parentName, key);
  }
  this._emit();
}

setActiveScalar(parentName, key /* string | null */) {
  const e = this._objects.get(parentName);
  if (!e) return;
  // Tear down current active scalar if any.
  if (e.activeScalar && e.activeScalar !== key) {
    const prev = e.children.get(e.activeScalar);
    if (prev && prev.type === 'scalar') prev.dispose(e.mesh, e);
  }
  e.activeScalar = key;
  if (key) {
    const child = e.children.get(key);
    if (!child || child.type !== 'scalar') { e.activeScalar = null; return; }
    child.apply(e.mesh, e, this._viridis.bind(this));
    // Edge child geometry is independent; placeholder for future hook.
    // if (e.children.has('edges') && e.opts.edgeVerts && e.opts.edgeIdx) { ... }
  }
  this._emit();
}

setScalarRange(parentName, key, vmin, vmax) {
  const e = this._objects.get(parentName);
  if (!e) return;
  const child = e.children.get(key);
  if (!child || child.type !== 'scalar') return;
  child.vmin = vmin; child.vmax = vmax;
  if (e.activeScalar === key) {
    child.setRange(vmin, vmax, e.mesh, this._viridis.bind(this));
  }
}
```

Delete the old `applyColormap(name, vmin, vmax)` method. The scene panel will call `viewer.setScalarRange(parentName, key, vmin, vmax)`.

### 2.6 `setChildVectorLength` (lines 172–187)

Rewrite to delegate to the child:

```js
setChildVectorLength(parentName, childKey, length) {
  const e = this._objects.get(parentName);
  if (!e) return;
  const child = e.children.get(childKey);
  if (!child || child.type !== 'vector') return;
  // Build new mesh via existing arrow builder.
  const newMesh = this._buildArrowField(child.origins, child.vectors, length, child.color);
  newMesh.name = `${parentName}::${childKey}`;
  newMesh.renderOrder = 1;
  newMesh.visible = child.visible;
  // Swap.
  this.scene.remove(child.mesh);
  child.mesh.geometry?.dispose();
  const mats = Array.isArray(child.mesh.material) ? child.mesh.material : [child.mesh.material];
  mats.forEach(m => m?.dispose());
  this.scene.add(newMesh);
  child.mesh = newMesh;
  child.length = length;
}
```

### 2.7 NEW vector helpers

```js
setVectorChildColor(parentName, childKey, rgb) {
  const e = this._objects.get(parentName); if (!e) return;
  const child = e.children.get(childKey);
  if (!child || child.type !== 'vector') return;
  child.setColor(rgb);
}

setActiveVector(parentName, key /* string | null */) {
  const e = this._objects.get(parentName); if (!e) return;
  // Hide all vector children except `key`; show `key` if non-null.
  for (const c of e.children.values()) {
    if (c.type !== 'vector') continue;
    c.setVisible(c.key === key);
  }
  e.activeVector = key;
  this._emit();
}
```

### 2.8 `applyMessage` dispatcher (lines 281–330)

Add three new cases; modify the existing `vector_quantity` case to delegate to a helper that creates a `VectorChild`; add the `edge_child` case for the new edge wire shape.

```js
case 'edge_child': {
  // { type:'edge_child', target, vertices, edges, color, radius }
  this.addEdgeChild(obj.target, obj.vertices, obj.edges,
                    obj.color ?? [0.1,0.1,0.1], obj.radius ?? 0);
  break;
}
case 'scalar_quantity':
  this.addScalarQuantity(obj.target, obj.name, obj.values, obj.defined_on ?? 'vertices');
  break;
case 'vector_quantity': {
  const parent = this._objects.get(obj.target);
  if (!parent || parent.type !== 'surface_mesh') break;
  // Use parent vertices as origins (current behavior).
  const origins = parent.opts.vertices;
  if (!origins) break;
  const key    = obj.name;
  const color  = obj.color  ?? [0.2, 0.8, 0.4];
  const length = obj.length ?? 0.05;
  if (parent.children.has(key)) parent.removeChild(key, this.scene, parent.mesh);
  const mesh = this._buildArrowField(origins, obj.vectors, length, color);
  mesh.name = `${obj.target}::${key}`;
  mesh.renderOrder = 1;
  this.scene.add(mesh);
  const child = new VectorChild({ key, mesh, origins, vectors: obj.vectors,
                                  color: [...color], length });
  parent.addChild(child);
  // Auto-activate vector only if none is currently active (stream-safe).
  if (parent.activeVector === null || parent.activeVector === key) {
    this.setActiveVector(obj.target, key);
  } else {
    // New non-active vector arrives hidden.
    child.setVisible(false);
  }
  this._emit();
  break;
}
```

### 2.9 Helpers to keep / remove

Keep: `_buildCurveObj`, `_buildTubeNetwork`, `_buildArrowField`, `_buildMeshGeo`, `_rgb`, `_emit`, `_viridis`, `_remove`, `setColor`, `setTransparency`, `setRadius`, `setCurveRadius`, `setVectorLength`, `setMaterial`, `setUniform`.

Remove: `applyColormap` (replaced by `setScalarRange`).

`_remove` body is unchanged; `e.dispose(this.scene)` already cascades children correctly because `SceneEntry.dispose` will call the polymorphic `removeChild` for each child key.

### 2.10 Imports at top of viewer.js

```js
import { SceneEntry, EdgeChild, ScalarChild, VectorChild } from './SceneEntry.js';
```

---

## 3. Server serializer changes (`kayviz/src/kayviz/serializers.py`)

### 3.1 New helper `edge_child` (insert near `vector_quantity`, ~line 127)

```python
def edge_child(target_name: str, vertices, edges,
               color=(0.1, 0.1, 0.1), radius: float = 0.0):
    """Edge overlay attached as a child of an existing surface_mesh."""
    return {
        "type":     "edge_child",
        "target":   target_name,
        "vertices": np.array(vertices, dtype=np.float32).flatten().tolist(),
        "edges":    np.array(edges,    dtype=np.int32).flatten().tolist(),
        "color":    [float(c) for c in color],
        "radius":   float(radius),
    }
```

### 3.2 Patch `surface_mesh` (lines 13–82)

- Drop the line `edges_dict = curve_network(name + "__edges", ...)`.
- Replace with `edges_dict = edge_child(name, edge_verts, edge_conn, color=edge_color)`.
- Concretely:

```python
if show_edges:
    seen = set()
    vi_list, vj_list = [], []
    for f in faces_list:
        n = len(f)
        for k in range(n):
            a, b = f[k], f[(k + 1) % n]
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                vi_list.append(a); vj_list.append(b)
    vi = np.array(vi_list, dtype=np.int32)
    vj = np.array(vj_list, dtype=np.int32)
    edge_verts = np.vstack((verts[vi], verts[vj]))      # (2E, 3)
    edge_conn  = np.column_stack(                        # (E, 2)
        [np.arange(len(vi)), np.arange(len(vi)) + len(vi)])
    edges_dict = edge_child(name, edge_verts, edge_conn, color=edge_color)
```

The dict order on return stays `[mesh_dict, edges_dict]` — the viewer's `applyMessage` loop processes the parent first, then the edge child registers against it.

### 3.3 No other serializer changes

`scalar_quantity` and `vector_quantity` already carry `target`/`name` — no wire change. The viewer interprets them as child registrations starting from this refactor.

### 3.4 Reset `__edges` cleanup callers (none exist)

`grep` confirms `__edges` only appears in `serializers.py`. Remove that token entirely.

### 3.5 `kayviz/src/kayviz/webscope/scene.py` and `script.py`

No changes: both already handle `result` being a list and forward through `_objects.extend` / `push_objects`. Just confirm.

---

## 4. Scene panel changes (`kayviz/src/kayviz/static/gui/scene_panel.js`)

### 4.1 `_buildRow` — strip child-specific UI

In `_buildRow(name, entry)` (lines 125–423):

- **Delete entirely** the scalar block (lines 247–380). All scalar UI moves into `_buildScalarChildRow` (§4.4).
- The "edges checkbox" never existed at the parent level (`show_edges` was only a backend flag — no parent-row UI), so nothing to delete there.
- Keep: visibility eye, color picker, opacity slider (surface_mesh), radius slider (point_cloud), vector_field length sub-row (top-level vector_field still exists), curve_network tube radius sub-row, material dropdown for surface_mesh.

After this, `_buildRow` length drops by ~135 lines.

### 4.2 `_rebuild` — child dispatch

Replace the inner loop (lines 117–122) with:

```js
for (const [name, entry] of this._viewer.objects) {
  body.appendChild(this._buildRow(name, entry));
  for (const [childKey, child] of entry.children) {
    let row;
    switch (child.type) {
      case 'edges':  row = this._buildEdgeChildRow(name, childKey, child, entry); break;
      case 'scalar': row = this._buildScalarChildRow(name, childKey, child, entry); break;
      case 'vector': row = this._buildVectorChildRow(name, childKey, child, entry); break;
      default:       row = this._buildGenericChildRow(name, childKey, child);
    }
    body.appendChild(row);
  }
}
```

### 4.3 `_buildChildRowSkeleton(parentName, childKey, child, opts)` — extract the shared head

Refactor the existing `_buildChildRow` body (lines 425–495) to expose just the head: container row + `topLine` (connector + visibility checkbox + label + badge + remove button). Returns `{ row, topLine }`. The visibility checkbox calls:

```js
eye.addEventListener('change', () =>
  this._viewer.setChildVisible(parentName, childKey, eye.checked));
```

The badge palette gets two new entries:
```js
const badgeInfo = {
  edges:  { text: 'edges',   bg: '#3a2a2a' },
  scalar: { text: 'scalar',  bg: '#2a4a3a' },
  vector: { text: 'vectors', bg: '#3a2a4a' },
}[child.type] ?? { text: child.type, bg: '#333' };
```

(Replaces the old `edge_overlay` / `vector_quantity` keys.)

### 4.4 `_buildScalarChildRow(parentName, childKey, child, parentEntry)`

```
1. row, topLine = _buildChildRowSkeleton(...)
2. The visibility checkbox is replaced/augmented by an "active" radio:
     - input.type = 'radio'; name = `scalar-active-${parentName}`
     - checked = (parentEntry.activeScalar === childKey)
     - on change: this._viewer.setActiveScalar(parentName, input.checked ? childKey : null)
   Also keep a small "make inactive" button (or use the radio's clickable behavior — clicking
   the already-checked radio sets active = null via a custom click handler).
3. Append vmin/vmax sliders + reset button + histogram canvas + gradient canvas
   (same DOM as today, but pulling values from `child.dataMin`, `child.dataMax`,
   `child.vmin`, `child.vmax`, `child.values`).
4. Slider handlers call this._viewer.setScalarRange(parentName, childKey, vmin, vmax)
   then child.drawHistogram(canvas, gradCanvas, this._viridis.bind(this)).
5. Reset button restores child.vmin = child.dataMin / vmax = dataMax and re-applies.
```

The histogram should redraw whenever the body is opened (collapsed by default per current UX), AND whenever a slider moves. Move the existing `drawHistogram` logic into `ScalarChild.drawHistogram` (signature `(canvas, gradCanvas, viridisFn)`); the row keeps its own canvas DOM and just calls into the child.

### 4.5 `_buildEdgeChildRow(parentName, childKey, child, parentEntry)`

```
1. row, topLine = _buildChildRowSkeleton(...)
2. Add a control sub-row with:
   - color picker (this._colorPicker(child.color, hex => this._viewer.setEdgeColor(parentName, this._hexToRgb(hex))))
   - tube radius slider: this._sliderOnly(child.radius, 0, 0.02, 0.0005,
       v => this._viewer.setEdgeRadius(parentName, v))
3. Mirrors today's curve_network sub-row in the parent.
```

### 4.6 `_buildVectorChildRow(parentName, childKey, child, parentEntry)`

```
1. row, topLine = _buildChildRowSkeleton(...) — but replace the visibility CHECKBOX with a RADIO
   (name = `vector-active-${parentName}`, checked = parentEntry.activeVector === childKey).
   Clicking an already-checked radio deactivates (calls setActiveVector(parentName, null)).
2. Sub-row:
   - color picker (this._viewer.setVectorChildColor(parentName, childKey, rgb))
   - length slider: this._sliderOnly(child.length, 0.001, 0.5, 0.001,
       v => this._viewer.setChildVectorLength(parentName, childKey, v))
```

### 4.7 `_buildGenericChildRow` — fallback

Keep it minimal: skeleton + nothing. Used if a future child type appears with no UI yet.

### 4.8 Helpers to delete

- The huge inline scalar block in `_buildRow` (lines 247–380).
- Nothing else to delete in scene_panel — `_subRow`, `_label`, `_sliderOnly`, `_colorPicker`, `_slider`, `_viridis`, `_rgbToHex`, `_hexToRgb` all stay.

---

## 5. Active-of-kind semantics — definitive rules

| Action | Effect |
|---|---|
| New `addScalarQuantity` arrives | Child registered. Becomes active if previously active (same key replaced) OR no scalar was active. |
| User clicks a scalar's "active" radio | `setActiveScalar(parent, key)` runs. Old active is disposed; new is applied. |
| User unchecks the active scalar's radio | `setActiveScalar(parent, null)` — dispose old, parent reverts to its own flat color. |
| User removes a scalar child via × | If it was active, parent reverts; child is dropped from map. |
| New `vector_quantity` arrives | Child registered. Becomes active if none currently active OR same key replaced. Otherwise arrives hidden. |
| User toggles a vector's "active" radio on | All other vectors hidden; this one shown; `activeVector = key`. |
| User toggles the active vector's radio off | All vectors hidden; `activeVector = null`. |
| Edges arrive | Single child at key `'edges'`; replaces any existing one. No "active" concept (always rendered when `visible`). |
| Parent visibility toggled OFF | All children with their own mesh hidden in scene; their `visible` state unchanged so they restore on parent ON. ScalarChild ignored (no mesh). |
| Parent removed | `entry.dispose(scene)` cascades — all children disposed via polymorphic `dispose`. |

---

## 6. Wire format summary (after refactor)

| Type | Direction | Shape |
|---|---|---|
| `surface_mesh` | server → client | unchanged |
| `curve_network` | server → client | unchanged (top-level only) |
| `point_cloud` | server → client | unchanged |
| `vector_field` | server → client | unchanged |
| `set_enabled` | server → client | unchanged |
| `scalar_quantity` | server → client | unchanged shape `{type, target, name, defined_on, values}` — semantics now: register as child, auto-activate. |
| `vector_quantity` | server → client | unchanged shape `{type, target, name, defined_on, vectors[, color, length]}` — semantics: register as child, auto-activate. |
| `edge_child` | server → client | **NEW** `{type:'edge_child', target, vertices, edges, color, radius}` — replaces the old `__edges` curve_network. |

---

## 7. Sequencing — step-by-step plan

The refactor must keep the dev server runnable after each step. Order:

**Step 1 (sequential, foundation).** Rewrite `kayviz/src/kayviz/static/SceneEntry.js`:
- Add `Child`, `EdgeChild`, `ScalarChild`, `VectorChild` exported classes.
- Update `SceneEntry` (rename `setChild` → `addChild`; remove `setChildVisible`; add `activeScalar`/`activeVector`; rewrite `removeChild` to dispatch on child instance; rewrite `dispose` to use new `removeChild`).
- Update header comment.
- This step alone will break the viewer (it still calls `setChild` / `setChildVisible` on entries) — go fast through Step 2.

**Step 2 (sequential, after Step 1).** Rewrite `kayviz/src/kayviz/static/viewer.js`:
- Update import from `SceneEntry.js`.
- Rewrite `addScalarQuantity`, delete `applyColormap`, add `setScalarRange`/`setActiveScalar`.
- Add `addEdgeChild`/`setEdgeColor`/`setEdgeRadius`.
- Add `setVectorChildColor`/`setActiveVector`.
- Update `setChildVisible` proxy to handle vector radio + scalar active semantics.
- Rewrite `setChildVectorLength` to act on `VectorChild` instance.
- Update `applyMessage` dispatcher: add `edge_child` case; rewrite `vector_quantity` case to construct `VectorChild`; rewrite `scalar_quantity` case to dispatch via `addScalarQuantity` (signature gains `key` param).
- Update `setEnabled` child loop to guard `child.mesh`.
- After this step the viewer compiles AND old `__edges` curve_networks (if still being sent) will still register as standalone curves — harmless.

**Step 3 (sequential, after Step 2).** Patch `kayviz/src/kayviz/serializers.py`:
- Add `edge_child(...)`.
- Modify `surface_mesh`: emit `edge_child` instead of `curve_network` for `show_edges=True`.
- Now reload: `Base Mesh__edges` disappears as a top-level entry; an indented `edges` child appears under `Base Mesh`.

**Step 4 (sequential, after Step 3).** Rewrite `kayviz/src/kayviz/static/gui/scene_panel.js`:
- Delete the inline scalar block in `_buildRow`.
- Refactor `_buildChildRow` into `_buildChildRowSkeleton` + per-type builders.
- Update `_rebuild` loop to dispatch on `child.type`.
- Move `drawHistogram` into `ScalarChild.drawHistogram` and update the row to call it.

**Steps that can be done in parallel:** none — each step depends on the previous (ScenePanel needs the new viewer API; viewer needs the new SceneEntry classes; serializer change requires the viewer's new `edge_child` case).

**Verification after each step:**
- After Step 2: hard-reload `?app=lmesh`. Existing scenes should render (no scalars/edges yet under new model). Check console for "setChild is not a function" — implies a missed call site.
- After Step 3: re-run a script that uses `show_edges=True`. The edges should be a child entry.
- After Step 4: verify scalar UI appears under the parent as a child row; verify radio behavior on multiple vectors; verify visibility cascade on parent toggle.

---

## 8. Pitfalls

1. **Face scalar requires `toNonIndexed`.** The current code mutates `e.mesh.geometry` once per first scalar add. After the refactor, each `ScalarChild.apply` must check `parentMesh.geometry.index !== null && definedOn === 'faces'` before calling `toNonIndexed()`. Once a parent geometry is non-indexed, switching to a different scalar (even vertex-defined) is fine: re-applying just rewrites the `color` attribute. Switching back to NO scalar via `setActiveScalar(null)` cannot restore the indexed geometry — only the color attribute and material color. Document this in code: the geometry stays non-indexed for the rest of the parent's life. Acceptable trade-off.

2. **`_colorAttrBackup` lifecycle.** The very first `apply` snapshots whatever `color` attribute existed (probably none for surface meshes). `dispose` restores or removes that attribute. If two scalars are applied in sequence (A then B), only A's `apply` records the backup; B's `apply` reads the existing color attribute (which is A's mapped colors) and **must not** overwrite the backup. Implement as: `if (this._colorAttrBackup === undefined) { this._colorAttrBackup = ...; this._priorMaterialColor = ...; }`. (Use `undefined` as the "uninitialized" sentinel since `null` is a valid backup value meaning "no prior attribute".)

   Subtle: when a scalar is `dispose`d (made inactive) and a different scalar is then activated, the second scalar's `apply` runs against the parent that's already been reverted — so its backup snapshot captures the *flat-color* state, which is correct. Each scalar tracks its own backup independently.

3. **Edge child after `toNonIndexed`.** Edge child geometry is independent (built from `edgeVerts`/`edgeIdx` cached on the parent), so flipping the parent to non-indexed does NOT affect it. The hook in `setActiveScalar` is a no-op for now — leave the `if (e.children.has('edges') && ...)` block as a comment placeholder; do not rebuild edges on scalar apply.

4. **Re-registering a parent surface_mesh.** When the server sends a fresh `surface_mesh` for the same name, `_remove(name)` runs and cascades `dispose` over all children. If the same scene update also re-sends scalars/vectors/edges (typical optimization step), they re-register correctly. But the `vmin`/`vmax` user-tweaked range will be reset to `dataMin`/`dataMax` because the child is rebuilt — acceptable; matches Polyscope behavior.

5. **Vector "auto-activate on arrival" interacts with optimization-loop streaming.** Each `scene_update` re-pushes the same vector children, which would re-trigger auto-activate every frame and clobber any user-chosen active vector. **Mitigation:** in the `vector_quantity` case, only call `setActiveVector` if `parent.activeVector === null` (no active selection yet) OR if the same key is being replaced. For the first arrival this auto-activates; subsequent re-pushes (same key) preserve the user's choice. Apply the same logic to scalar.

6. **`ScalarChild.dispose` must run before parent geometry is disposed.** When `SceneEntry.dispose` runs, iterate children FIRST, then dispose own mesh. Current `dispose` already does this — keep that order. ScalarChild's `dispose` mutates `parentMesh.material` / `parentMesh.geometry.attributes.color`; if the parent mesh is already gone, that crashes. Order matters.

7. **`_emit()` after every child mutation.** The scene panel only rebuilds on `viewer-changed`. Every viewer method that adds/removes/toggles a child or changes `activeScalar`/`activeVector` MUST emit. Add `this._emit()` to all of: `setChildVisible`, `setActiveScalar`, `setActiveVector`, `setEdgeColor`, `setEdgeRadius`, `setVectorChildColor`, `setChildVectorLength`. (Some are no-ops re: panel layout but the radios need to re-render.)

8. **`_viridis` is duplicated** in `viewer.js` and `scene_panel.js`. After the refactor, the panel calls `child.drawHistogram(canvas, gradCanvas, this._viridis.bind(this))`; the viewer calls `child.apply(parent, entry, this._viridis.bind(this))`. Both already have their own copy — fine. Optionally extract to `kayviz/src/kayviz/static/lib/colormap.js` later (out of scope).

9. **Z-fighting between edge child and parent surface.** The current `_buildCurveObj` for `radius=0` already sets `depthTest: false` on the LineBasicMaterial; for `radius>0` the tube uses `polygonOffset`. Both already mitigate z-fighting without Three.js parenting. No change needed.

10. **`mesh.userData` on vector children was used as a closet for origins/vectors.** Drop reliance on `mesh.userData` once `VectorChild` stores them on the instance. Remove the `mesh.userData = {...}` line from `applyMessage`.

---

## 9. Dead code to remove (final list)

In `kayviz/src/kayviz/static/SceneEntry.js`:
- Header comment lines mentioning `opts.scalar`, `opts.showEdges`, `opts.edgeColor`, `opts.edgeRadius` (keep `edgeVerts`, `edgeIdx`).
- `setChild(key, mesh, meta)` method.
- `setChildVisible(key, visible)` method.

In `kayviz/src/kayviz/static/viewer.js`:
- The `scalar: null, ... showEdges: false` initializers in `registerSurfaceMesh` opts.
- The `_rebuildEdgeOverlay(e)` call inside `addScalarQuantity` (line 231) — there is no such method (already broken).
- The `applyColormap` method.
- The `mesh.userData = { origins, vectors, color, length }` line in `applyMessage`'s `vector_quantity` case (and in `setChildVectorLength` — replaced by `VectorChild` fields).

In `kayviz/src/kayviz/static/gui/scene_panel.js`:
- The entire scalar block in `_buildRow` (lines 247–380).
- The badge keys `edge_overlay` and `vector_quantity` in `_buildChildRow` (replaced by `edges`/`vector` after the rewrite — `scalar` added).

In `kayviz/src/kayviz/serializers.py`:
- The string `name + "__edges"` (replaced by edge_child wire shape).

---

## 10. Critical Files for Implementation

- `kayviz/src/kayviz/static/SceneEntry.js`
- `kayviz/src/kayviz/static/viewer.js`
- `kayviz/src/kayviz/static/gui/scene_panel.js`
- `kayviz/src/kayviz/serializers.py`
