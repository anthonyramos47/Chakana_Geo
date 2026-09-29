# kayviz frontend — API Reference

The browser side of kayviz: Three.js + lil-gui, loaded from a CDN through the import map
in `index.html` (no build step). Paths below are relative to `kayviz/src/kayviz/`; custom
panels import these modules through the alias `kayviz/` → `/static/`.

---

## Architecture

```
static/
├── index.html            import map (three, lil-gui, kayviz/)
├── main.js               renderer, camera, controls, lights, render loop
├── app_loader.js         resolves ?app=, fetches the schema, opens the WebSockets, loads the panel
├── viewer.js             scene object registry (Viewer class)
├── SceneEntry.js         per-object entries and their children (edges, scalars, vectors)
├── ws.js                 WebSocket client (WSClient class)
├── screenshot.js, LabelRenderer.js
├── lib/
│   └── MaterialLibrary.js  named material / shader registry
└── gui/
    ├── panel.js          base panel class (lil-gui wrapper)
    ├── auto_panel.js     buildSchemaWidgets: widgets from the server schema
    ├── auto_callback_panel.js  generated panel for apps without panel_js
    ├── scene_panel.js    left-side structure list
    ├── energy_panel.js, lighting_panel.js, script_panel.js
```

**Data flow:**
```
Python (FastAPI)  ──WebSocket──►  WSClient  ──►  Viewer  ──►  THREE.Scene
                                               ▲
                                         MaterialLibrary
```

---

## Viewer

`static/viewer.js` — scene object registry. Mirrors `ps.register_*`.

### Constructor

```javascript
import { Viewer } from './viewer.js';
const viewer = new Viewer(scene);                    // uses shared Materials singleton
const viewer = new Viewer(scene, customMatLib);      // inject a custom MaterialLibrary
```

### Registration

```javascript
// Mirrors ps.register_surface_mesh()
viewer.registerSurfaceMesh(
  name,          // string — unique key
  vertices,      // Float32 flat array [x,y,z, ...]
  faces,         // Int32  flat array  [i,j,k, ...]  triangles or quads
  faceSize,      // 3 = triangles (default), 4 = quads
  color,         // [r,g,b] in 0-1, default [0.8,0.8,0.8]
  opacity,       // 0-1, default 1.0 (opaque)
  material,      // material name from MaterialLibrary, default 'lambert'
);

// Mirrors ps.register_curve_network()
viewer.registerCurveNetwork(
  name,          // string
  vertices,      // Float32 flat array [x,y,z, ...]
  edges,         // Int32  flat array  [i,j, i,j, ...]
  color,         // [r,g,b] in 0-1, default [0.8,0.2,0.2]
);

// Mirrors ps.register_point_cloud()
viewer.registerPointCloud(
  name,          // string
  points,        // Float32 flat array [x,y,z, ...]
  color,         // [r,g,b] in 0-1, default [0.2,0.5,0.8]
  radius,        // point size in scene units, default 0.01
);
```

### Mutation

```javascript
viewer.setEnabled(name, true|false);        // toggle visibility
viewer.setColor(name, [r,g,b]);             // change color (0-1)
viewer.setOpacity(name, 0.5);              // surface meshes only
viewer.setRadius(name, 0.02);               // point clouds only
viewer.remove(name);                        // remove from scene + dispose
```

### Material hot-swap (Option B)

```javascript
// Swap the shader on any surface mesh without re-uploading geometry.
// Color and opacity are preserved from the registration call.
viewer.setMaterial('Base mesh', 'phong');
viewer.setMaterial('Base mesh', 'blinn_phong');
viewer.setMaterial('Base mesh', 'matcap');
viewer.setMaterial('Base mesh', 'myCustomShader');

// Update a GLSL uniform at runtime (ShaderMaterials only)
viewer.setUniform('Base mesh', 'uTime', performance.now() / 1000);
viewer.setUniform('Base mesh', 'uColor', new THREE.Color(1, 0.5, 0));
```

### Scalar quantities

```javascript
// Mirrors structure.add_scalar_quantity()
// Colors vertices with the viridis colormap
viewer.addScalarQuantity('Base mesh', valuesArray);
```

### Server message dispatcher

```javascript
// Apply a batch of geometry objects sent from the Python backend
viewer.applyMessage({ objects: [ ... ] });
```

Each object in the `objects` array uses one of these shapes:
```json
{ "type": "surface_mesh",  "name": "...", "vertices": [...], "faces": [...],
  "face_size": 3, "color": [r,g,b], "opacity": 1.0, "material": "lambert" }

{ "type": "curve_network", "name": "...", "vertices": [...], "edges": [...],
  "color": [r,g,b] }

{ "type": "point_cloud",   "name": "...", "points": [...],
  "color": [r,g,b], "radius": 0.01 }

{ "type": "scalar_quantity", "target": "mesh name", "values": [...] }

{ "type": "set_enabled", "name": "...", "enabled": true }
```

### Read-only properties

```javascript
viewer.objects   // Map<name, entry> — snapshot for the ScenePanel
```

---

## MaterialLibrary

`static/lib/MaterialLibrary.js` — named material and shader registry.

### Singleton

```javascript
import { Materials } from './lib/MaterialLibrary.js';
```

Pass a custom instance to `Viewer` if you need isolated registries:
```javascript
import { MaterialLibrary } from './lib/MaterialLibrary.js';
const myLib = new MaterialLibrary();
const viewer = new Viewer(scene, myLib);
```

### Built-in materials

| Name          | THREE class              | Notes                              |
|---------------|--------------------------|------------------------------------|
| `lambert`     | MeshLambertMaterial      | Fast diffuse, no specular. Default.|
| `phong`       | MeshPhongMaterial        | Diffuse + specular highlights.     |
| `blinn_phong` | ShaderMaterial           | Custom GLSL Blinn-Phong, two lights|
| `matcap`      | ShaderMaterial           | View-space warm-cool gradient      |
| `physical`    | MeshPhysicalMaterial     | PBR metalness/roughness            |
| `toon`        | MeshToonMaterial         | Cel-shaded cartoon                 |
| `wireframe`   | MeshBasicMaterial        | Wireframe overlay                  |
| `flat`        | MeshBasicMaterial        | Unlit flat color                   |
| `normal`      | MeshNormalMaterial       | RGB = world-space normals (debug)  |
| `depth`       | MeshDepthMaterial        | Depth visualization (debug)        |

### Register a parameterised built-in

```javascript
Materials.register('gold', {
  type: 'physical',
  color: [1.0, 0.76, 0.33],
  metalness: 1.0,
  roughness: 0.2,
});

Materials.register('soft_blue', {
  type: 'phong',
  color: [0.2, 0.4, 0.8],
  shininess: 30,
});
```

### Register a custom GLSL shader

```javascript
Materials.register('myShader', {
  type: 'shader',
  vertexShader: `
    varying vec3 vNormal;
    void main() {
      vNormal     = normalMatrix * normal;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform vec3  uColor;
    uniform float uTime;
    varying vec3  vNormal;
    void main() {
      float pulse = 0.5 + 0.5 * sin(uTime * 2.0);
      gl_FragColor = vec4(uColor * pulse, 1.0);
    }
  `,
  uniforms: {
    uColor: { value: new THREE.Color(0.2, 0.6, 1.0) },
    uTime:  { value: 0.0 },
  },
  side: 'double',    // 'front' | 'back' | 'double'
});

// Apply it
viewer.setMaterial('Base mesh', 'myShader');

// Animate uniforms in the render loop
function animate() {
  requestAnimationFrame(animate);
  viewer.setUniform('Base mesh', 'uTime', performance.now() / 1000);
  renderer.render(scene, camera);
}
```

### API

```javascript
Materials.register(name, def);         // add or overwrite a definition
Materials.has(name);                   // → boolean
Materials.list();                      // → string[] of all names
Materials.build(name, color, opacity); // → THREE.Material instance
Materials.applyTo(mesh, name, color, opacity); // swap + dispose old
```

---

## WSClient

`static/ws.js` — WebSocket client. Replaces `ps.set_user_callback()`.

```javascript
import { WSClient } from './ws.js';
const ws = new WSClient('ws://localhost:8000/api/myapp/ws', viewer, statusEl);

// Send an action to the backend
ws.send('step');
ws.send('update_weights', { weights: { Or_Contact: 1.0 } });

// Subscribe to all server messages (called after viewer.applyMessage)
ws.onMessage(data => {
  if (data.action === 'scene_update') console.log(data.iteration);
});
```

Auto-reconnects with exponential backoff on disconnect.

---

## Panel (GUI base class)

`static/gui/panel.js` — wraps lil-gui. All panels extend this.

```javascript
import { Panel } from './gui/panel.js';

class MyPanel extends Panel {
  constructor(ws) {
    super('My Panel', { width: 300 });
    this.ws    = ws;
    this.state = { value: 0.5, flag: false, choice: 'a' };
    this._buildSection();
  }

  _buildSection() {
    const f = this.addSection('Controls');          // collapsible section
    f.add(this.state, 'value', 0, 1, 0.01).name('My Slider');
    f.add(this.state, 'flag').name('Toggle');
    f.add(this.state, 'choice', ['a', 'b', 'c']).name('Dropdown');
    f.add({ fn: () => this.ws.send('my_action', { v: this.state.value }) },
          'fn').name('Do Thing');
  }
}
```

### Control reference

| What you want       | Code                                                   | Polyscope equivalent         |
|---------------------|--------------------------------------------------------|------------------------------|
| Float slider        | `f.add(state, 'key', min, max, step).name('Label')`   | `psim.SliderFloat`           |
| Int slider          | `f.add(state, 'key', min, max, 1).name('Label')`      | `psim.SliderInt`             |
| Checkbox            | `f.add(state, 'boolKey').name('Label')`               | `psim.Checkbox`              |
| Text input          | `f.add(state, 'strKey').name('Label')`                | `psim.InputText`             |
| Button              | `f.add({ fn: () => doSomething() }, 'fn').name('...')` | `psim.Button`               |
| Dropdown / radio    | `f.add(state, 'key', ['opt1', 'opt2']).name('Label')` | `psim.RadioButton`           |
| Color picker        | `f.addColor(state, 'colorKey').name('Label')`         | —                            |
| Read-only text      | `f.add(state, 'key').name('Label').disable()`         | `psim.Text`                  |
| Separator           | `f.addFolder('──────────────')`                       | `psim.Separator`             |
| Collapsible section | `this.addSection('Name', open=true)`                  | `psim.CollapsingHeader`      |
| Hide entire panel   | `panel.setVisible(false)`                             | —                            |
| Force display update| `panel.refresh()`                                     | —                            |

---

## ScenePanel

`static/gui/scene_panel.js` — left-side structure list.

Automatically reflects every object registered in the `Viewer`. No configuration needed.

Each row provides:
- Visibility checkbox
- Color picker
- Opacity slider (surface meshes)
- Radius slider (point clouds)
- **Shader / material dropdown** (surface meshes — lists all `MaterialLibrary` names)
- Remove button

```javascript
import { ScenePanel } from './gui/scene_panel.js';
const scenePanel = new ScenePanel(viewer, { width: 280 });
```

---

## Adding a new backend action

**Frontend** — add a button in any panel:
```javascript
f.add({ fn: () => this.ws.send('my_action', { param: this.state.value }) },
      'fn').name('Do Thing');
```

**Backend** — register a handler in your `kv.GUIApp` subclass:
```python
def register_actions(self):
    self.action("my_action", self._my_action)

def _my_action(self, state, data):
    param = data.get("param", 1.0)
    V, F = compute(param)
    return self._make_scene_update([ser.surface_mesh("Result", V, F)])
```

---

## Adding a new geometry type

**1.** Add a method to `Viewer`:
```javascript
registerWireframe(name, vertices, faces, color = [0.3, 0.3, 0.3]) { ... }
```

**2.** Add a case to `Viewer.applyMessage()`:
```javascript
case 'wireframe': this.registerWireframe(obj.name, obj.vertices, obj.faces, obj.color); break;
```

**3.** Add a serializer to `serializers.py`:
```python
def wireframe(name, vertices, faces, color=(0.3, 0.3, 0.3)):
    return { "type": "wireframe", "name": name,
             "vertices": np.array(vertices, dtype=np.float32).flatten().tolist(),
             "faces":    np.array(faces,    dtype=np.int32).flatten().tolist(),
             "color": list(color) }
```

---

## Polyscope → Three.js quick reference

| Polyscope                              | This library                                      |
|----------------------------------------|---------------------------------------------------|
| `ps.register_surface_mesh(n, V, F)`    | `viewer.registerSurfaceMesh(n, V, F)`             |
| `ps.register_curve_network(n, V, E)`   | `viewer.registerCurveNetwork(n, V, E)`            |
| `ps.register_point_cloud(n, P)`        | `viewer.registerPointCloud(n, P)`                 |
| `mesh.add_scalar_quantity(n, vals)`    | `viewer.addScalarQuantity(mesh, n, vals)`         |
| `ps.get_surface_mesh(n).set_enabled(b)`| `viewer.setEnabled(n, b)`                         |
| `ps.set_user_callback(fn)`             | `ws.onMessage(fn)`                                |
| `psim.SliderFloat`                     | `f.add(state, 'key', min, max, step)`             |
| `psim.Button`                          | `f.add({fn: ()=>{}}, 'fn').name('Label')`         |
| `psim.CollapsingHeader`                | `this.addSection('Name')`                         |
| `psim.Separator`                       | `f.addFolder('──────')`                           |
| Change material at runtime             | `viewer.setMaterial(name, 'phong')`               |
| Custom GLSL shader                     | `Materials.register(name, {type:'shader', ...})`  |
| Animate GLSL uniform                   | `viewer.setUniform(name, 'uTime', t)`             |
