# kayviz — Cookbook

Short, copy-pasteable recipes. `import kayviz as kv` throughout.

---

## Scripts and notebooks

### Push geometry from a notebook

```python
import kayviz as kv
from hanan import glyphs

kv.init()
kv.register_surface_mesh("Base Mesh", V, F, color=(0.5, 0.5, 0.5), show_edges=True)
kv.add_scalar_quantity("Base Mesh", "curvature", kappa, defined_on="faces")
kv.add_vector_quantity("Base Mesh", "normals", N, defined_on="vertices")
kv.register_surface_mesh("Spheres", *glyphs.spheres(C, R))
kv.register_curve_network("Circles", *glyphs.circles(C, N, R))
kv.show()            # returns immediately in Jupyter
```

The same calls in a script: `show()` blocks until the tab is closed.

### One window for several notebooks

```bash
python -m kayviz          # shared viewer on port 8000
```

Every `kv.init()` without its own GUI now attaches to it.

---

## Callback GUI

### Minimal callback app

```python
state = {"alpha": 0.5}

def on_load():
    kv.register_surface_mesh("Base", V, F, color=(0.5, 0.5, 0.5))

def gui():
    if kv.imgui.slider_float("Alpha", state, "alpha", 0, 1)[0]:
        recompute()
    if kv.imgui.button("Run"):
        heavy_work()

kv.set_user_callback(gui, app_name="myapp", on_load=on_load)
kv.show()
```

### Live update while dragging

```python
def gui():
    moved = False
    with kv.imgui.header("Pose"):
        moved |= kv.imgui.slider_float("Rot Y", state, "rot_y", -180, 180)[0]
        moved |= kv.imgui.slider_float("Rot Z", state, "rot_z", -180, 180)[0]
    if moved:
        update_scene()                 # recompute and push immediately
    if kv.imgui.button("Heavy Compute"):
        heavy_computation()
```

Each drag fires the callback with that slider as trigger; `changed` is True only for it.

### Compute only on a button

```python
def gui():
    with kv.imgui.header("Parameters"):
        kv.imgui.slider_float("Radius", state, "radius", 0.1, 10)
        kv.imgui.slider_float("Center X", state, "cx", -10, 10)
    kv.imgui.dropdown("Mode", state, "mode", ["A", "B", "C"])
    if kv.imgui.button("Apply"):
        compute_and_push()             # reads state["radius"], state["cx"], …
```

### Custom JS panel for a callback app

```python
kv.register_app(kv.CallbackApp(gui, app_name="myapp", on_load=on_load),
                panel_js="myapp_panel.js")
```

```js
import { Panel }              from 'kayviz/gui/panel.js';
import { buildSchemaWidgets } from 'kayviz/gui/auto_panel.js';

export default class MyAppPanel extends Panel {
  constructor(ws, schema) {
    super('My App', { width: 340 });
    this.state = {};
    buildSchemaWidgets(this.gui, schema, this.state, ws);
    // custom buttons, message hooks, …
  }
}
```

---

## `GUIApp`

### Reading client state in an action

The panel sends every widget change as `_set_state`, so `state.*` is current when the
handler runs.

```python
def _my_action(self, state, data):
    comp.run(state)                                     # state.max_iter, state.alpha, …
    return self._make_scene_update(comp.build_scene(state))
```

Overrides carried by the action payload come from `data`:
`thickness = float(data.get("thickness", state.support_thickness))`.

### Long-running optimisation with live updates

```python
async def _run(self, state, data, ws):
    state.is_running = True
    while state.is_running and state.iteration < state.max_iter:
        comp.step(state)
        await ws.send_json({"action": "scene_update",
                            "iteration": state.iteration,
                            "objects": comp.build_scene(state)})
    await ws.send_json(self._done("optimization_complete"))
```

A `stop` action sets `state.is_running = False`.

### No reply

Return `None` from a sync handler.

```python
def _update_weights(self, state, data):
    state.weight_config.update(data.get("weights", {}))
    return None
```

### Write results to disk

```python
def _export(self, state, data):
    out_dir = os.path.join(self.out_dir, state.experiment_name)
    os.makedirs(out_dir, exist_ok=True)
    comp.export(state, out_dir)
    return self._done("export_done", message=f"Exported to {out_dir}")
```

```js
ws.onMessage(data => {
  if (data.action === 'export_done') alert(data.message);
});
```

### Guard an action

```python
def _show_support(self, state, data):
    if state.mesh is None:
        return {"action": "error", "message": "No mesh loaded."}
    ...
```

### Status display in a custom panel

```js
this._status = { iteration: 0, energy: 0 };
const f = this.addSection('Status', false);
f.add(this._status, 'iteration').name('Iteration').disable();
f.add(this._status, 'energy'   ).name('Energy'   ).disable();

ws.onMessage(data => {
  if (data.action === 'scene_update') {
    if (data.iteration !== undefined) this._status.iteration = data.iteration;
    if (data.energy != null)          this._status.energy    = data.energy;
    this.refresh();
  }
});
```

### Custom material

```js
import { Materials } from 'kayviz/lib/MaterialLibrary.js';

Materials.register('gold', { type: 'physical', color: [1.0, 0.76, 0.33],
                             metalness: 1.0, roughness: 0.2 });
window.__viewer.setMaterial('Base', 'gold');
window.__viewer.setMaterial('Base', 'phong');      // built-ins: lambert, phong, matcap, normal,
                                                   // wireframe, flat, depth, toon, physical
```

Raw GLSL: `Materials.register('myShader', { type: 'shader', vertexShader, fragmentShader, uniforms })`.

### `Scene` or raw serializer dicts

```python
with kv.Scene() as s:                            # preferred
    s.register_surface_mesh("Base", V, F)
    s.register_curve_network("Edges", P, E, color=(0.8, 0.2, 0.2), radius=0.002)
    s.extend(objects)                            # merge pre-built dicts
return {"action": "scene_update", "objects": s.snapshot()}

from kayviz import serializers as ser            # raw dicts, still valid
return {"action": "scene_update", "objects": [ser.surface_mesh("Base", V, F),
                                              ser.curve_network("Edges", P, E)]}
```

---

## New app — file list

| File | Purpose |
|---|---|
| `state.py` | `@kv.gui_state @dataclass` |
| `app.py` | `kv.GUIApp` subclass |
| `myapp_panel.js` | custom panel (optional) |
| `run.py` | `kv.register_app(MyApp(), panel_js="myapp_panel.js")`; `kv.show()` |

A callback app is a single file: state dict + `gui()` + `on_load()` +
`kv.set_user_callback(...)` + `kv.show()`. See
[`examples/polyhedral_mesh`](../../examples/polyhedral_mesh) for a complete `GUIApp`.
