# kayviz — Tutorial

kayviz is a Polyscope-style viewer that runs in the browser. Every script or notebook
starts its own viewer (a FastAPI server in a background thread), so a project is one
Python file: no server to configure, nothing to register elsewhere.

Three ways to use it. Pick the one that fits.

| | Scripting / notebook | Callback GUI | `GUIApp` |
|---|---|---|---|
| **Code** | a script or notebook cell | one Python file, no JS | state class + `GUIApp` subclass + optional panel JS |
| **Panel** | none — push geometry only | generated from the callback | generated from the state, or your own JS |
| **Best for** | exploring, notebooks | quick interactive experiments | apps with many actions and streamed optimisation |

```bash
pip install -e hanan -e kayviz      # editable installs from this repository
```

---

## Path 0 — Scripting / notebook (push geometry only)

```python
import kayviz as kv
from hanan import glyphs               # mesh data for spheres, circles, cones, …

kv.init()                              # own viewer on the first free port from 8000
kv.register_surface_mesh("Base", V, F, color=(0.5, 0.5, 0.5), show_edges=True)
kv.register_curve_network("Edges", P, E, color=(0.8, 0.2, 0.2), radius=0.002)
kv.register_point_cloud("Points", X, radius=0.01)
kv.add_scalar_quantity("Base", "curvature", K, defined_on="faces")
kv.add_vector_quantity("Base", "normals", N, defined_on="vertices")
kv.register_surface_mesh("Sphere", *glyphs.sphere(c, r))
kv.set_enabled("Edges", False)
kv.remove("Points")
kv.clear()                             # remove everything
kv.show()                              # opens the tab; blocks in scripts, returns in notebooks
```

- `init()` prints the URL. In a plain script `show()` blocks until the tab is closed; in
  Jupyter it returns at once and the viewer lives as long as the kernel.
- The scene is buffered on the server, so a reloaded tab shows it again.
- A pre-built list of serializer dicts goes in with `kv.push_objects(objects)`.

**Several notebooks, one window.** Start a shared viewer with `python -m kayviz`; while it
runs on the default port, `kv.init()` in any notebook attaches to it instead of starting
its own. `kv.init(url=...)` or `KAYVIZ_URL` attaches to a specific server.

---

## Path A — Callback GUI (no JS)

Describe the widgets in a function; kayviz runs it once to build the panel and again on
every widget event.

```python
import kayviz as kv

state = {"radius": 4.0, "cx": -2.0, "mode": "T2"}

def on_load():
    """Push the initial scene once."""
    kv.register_surface_mesh("Base", V, F, color=(0.5, 0.5, 0.5), show_edges=True)

def gui():
    with kv.imgui.header("Parameters"):
        moved  = kv.imgui.slider_float("Center X", state, "cx", -10, 10)[0]
        moved |= kv.imgui.slider_float("Radius",   state, "radius", 0.1, 10)[0]
    kv.imgui.dropdown("Mode", state, "mode", ["Base", "T1", "T2"])
    if moved:
        update_scene()               # live update while a slider is dragged
    if kv.imgui.button("Run Computation"):
        heavy_computation()          # only on click

kv.set_user_callback(gui, app_name="myapp", on_load=on_load)
kv.show()
```

**Widget return values**
- `slider_float / slider_int / checkbox / dropdown / text_input` → `(changed: bool, value)`
- `button` → `bool` (True when clicked)
- Every widget updates `state[key]` in place, so you can just read `state["key"]`.

Geometry registered inside the callback goes to the open tab. The callback can live in
its own module; import it and call `set_user_callback` from the main script.

**Custom panel.** To replace the generated panel with your own JS, register the callback
app explicitly:

```python
kv.register_app(kv.CallbackApp(gui, app_name="myapp", on_load=on_load),
                panel_js="myapp_panel.js")      # path relative to this file
```

The panel module is written as in Path B, step 3.

---

## Path B — `GUIApp` (full apps)

Use it when you need a dataclass state, several actions, streamed optimisation loops or a
hand-written panel. [`examples/polyhedral_mesh`](../../examples/polyhedral_mesh) is a
complete app (`run.py`, `app.py`, `state.py`, `computations.py`, `polyhedral_panel.js`).

### Step 1 — State

```python
from dataclasses import dataclass, field
import kayviz as kv

@kv.gui_state
@dataclass
class MyState:
    experiment_name: kv.text_field("Experiment Name")          = "exp0"
    max_iter:        kv.int_slider(1, 200, 1, "Max Iterations") = 50
    alpha:           kv.slider(0.0, 1.0, 0.01, "Alpha")        = 0.5
    mode:            kv.dropdown(["primal", "dual"], "Mode")   = "primal"
    show_mesh:       kv.checkbox("Show Mesh")                  = True

    # Internal — plain annotations, not rendered as widgets
    iteration:  int    = 0
    is_running: bool   = False
    data:       dict   = field(default_factory=dict)
```

- `@kv.gui_state` goes on top of `@dataclass`.
- Only widget-annotated fields appear in the panel; fields sharing a prefix
  (`sphere_radius`, `sphere_center`) are grouped in one folder.

### Step 2 — The app

```python
import kayviz as kv
import computations as comp

class MyApp(kv.GUIApp):
    name      = "myapp"              # URL: ?app=myapp
    state_cls = MyState
    out_dir   = "out"

    def initial_scene(self):
        with kv.Scene() as s:
            s.register_surface_mesh("Base", V, F)
        return {"objects": s.snapshot()}

    def register_actions(self):
        self.action("setup", self._setup)
        self.action("run",   self._run)          # async → streams
        self.action("stop",  self._stop)

    def _setup(self, state, data):
        comp.setup(state)
        return self._make_scene_update(comp.build_scene(state))

    async def _run(self, state, data, ws):
        state.is_running = True
        while state.is_running and state.iteration < state.max_iter:
            comp.step(state)
            await ws.send_json({"action": "scene_update",
                                "iteration": state.iteration,
                                "objects": comp.build_scene(state)})
        await ws.send_json(self._done("optimization_complete"))

    def _stop(self, state, data):
        state.is_running = False

kv.register_app(MyApp(), panel_js="myapp_panel.js")   # panel_js is optional
kv.show()
```

**Sync vs async handlers**
- Sync `fn(state, data)` returns a dict to send, or `None` for no reply.
- Async `async fn(state, data, ws)` sends as many messages as it likes with
  `await ws.send_json(...)`. kayviz tells them apart by the `ws` parameter.

The panel keeps `state` current: every widget change is sent as `_set_state` before your
handler runs.

### Step 3 — Custom panel (optional)

Without `panel_js` the panel is generated from the state. A custom panel is an ES module
whose default export takes `(ws, schema)`; kayviz modules are imported through the
`kayviz/` alias:

```js
import { Panel }              from 'kayviz/gui/panel.js';
import { buildSchemaWidgets } from 'kayviz/gui/auto_panel.js';

export default class MyAppPanel extends Panel {
  constructor(ws, schema) {
    super('My App', { width: 340 });
    this.state = {};
    buildSchemaWidgets(this.gui, schema, this.state, ws);   // widgets from the state

    const f = this.addSection('Actions');
    f.add({ fn: () => ws.send('setup', { ...this.state }) }, 'fn').name('Setup');
    f.add({ fn: () => ws.send('run',   { ...this.state }) }, 'fn').name('Run');
    f.add({ fn: () => ws.send('stop') },                      'fn').name('Stop');

    this._status = { iteration: 0 };
    this.addSection('Status', false).add(this._status, 'iteration').name('Iteration').disable();
    ws.onMessage(data => {
      if (data.action === 'scene_update' && data.iteration !== undefined) {
        this._status.iteration = data.iteration;
        this.refresh();
      }
    });
  }
}
```

### Step 4 — Run

```bash
python my_app.py          # starts its own viewer and opens ?app=myapp
```

---

## Checklist — `GUIApp`

| Step | File |
|---|---|
| 1. State | `state.py` — `@kv.gui_state @dataclass` |
| 2. App | `app.py` — `kv.GUIApp` subclass |
| 3. Panel (optional) | `myapp_panel.js`, passed as `panel_js` |
| 4. Entry point | `run.py` — `kv.register_app(MyApp(), panel_js=...)`, `kv.show()` |
