# kayviz — API Reference

`import kayviz as kv`. The package is `kayviz/src/kayviz/`; the browser side (Three.js,
lil-gui, no build step) is in `kayviz/src/kayviz/static/`. kayviz depends on
numpy/fastapi/uvicorn only — geometry such as spheres or circles comes from
`hanan.glyphs` as plain arrays.

```
Entry point            When to use
─────────────────────  ─────────────────────────────────────────────────────
kv.register_*          scripts / notebooks: push geometry only
kv.set_user_callback   one callback function describes the panel, no JS
kv.GUIApp subclass     full apps: dataclass state, actions, streamed loops
```

All three share the viewer, the WebSocket protocol and the serializer layer.

---

## Viewer lifecycle

| Function | Description |
|---|---|
| `kv.init(url=None, port=None)` | Start this process's viewer (first free port from `KAYVIZ_PORT`/8000), or attach to a shared one. A second call is a no-op. |
| `kv.show(block="auto", app=None)` | Open the tab. `"auto"` blocks in plain scripts and returns in IPython. `app` defaults to the last registered app, else the script viewer. |
| `kv.url()` | URL of the viewer in use. |

Modes: **local** — the process runs its own server; **attached** — a shared server
(`python -m kayviz`, or `KAYVIZ_URL`) answers on the default port and geometry is pushed
over HTTP; **hosted** — the process *is* a server (`kayviz.server.create_app`). A process
that registered its own apps always starts its own viewer.

| Environment variable | Effect |
|---|---|
| `KAYVIZ_URL` | Attach to this server instead of starting one |
| `KAYVIZ_PORT` | First port tried for the in-process server (default 8000) |
| `KAYVIZ_NO_BROWSER=1` | Never open a browser tab (CI, remote machines) |

---

## Scripting API

```python
kv.register_surface_mesh("Mesh", V, F, color=(0.5, 0.5, 0.5), opacity=1.0, show_edges=True)
kv.register_surface_mesh("Shell", V, F, material="glass")   # pin a shader for this mesh
kv.register_curve_network("Edges", P, E, color=(0.8, 0.2, 0.2), radius=0.002)
kv.register_point_cloud("Points", X, color=(0.2, 0.5, 0.8), radius=0.01)
kv.register_vector_field("Normals", origins, vectors, length=0.05, color=(0.2, 0.8, 0.4))
kv.add_scalar_quantity("Mesh", "curvature", values, defined_on="faces")
kv.add_vector_quantity("Mesh", "normals", N, defined_on="vertices")
kv.push_objects(objects)          # pre-built serializer dicts
kv.set_enabled("Edges", False)
kv.remove("Edges")
kv.clear()                        # like ps.remove_all_structures()
```

Screenshots of the open tab: `kv.screenshot(path, views=None)`,
`kv.screenshot_views(views=kv.TIGHT_VIEWS)` (also `DEFAULT_VIEWS`, `FITTED_VIEWS`),
`kv.save_grid(path, rows)`, `kv.get_camera()`.

#### `show_edges=True`

Unique polygon edges are taken from the faces *before* fan-triangulation and sent with the
mesh as `poly_edges` (index pairs into its vertices), so quad or hex meshes show polygon
edges, not triangle diagonals. The "show edges" checkbox in the scene panel toggles the same overlay without a
server round trip.

#### `add_scalar_quantity(..., defined_on="faces")`

The viewer converts the mesh to non-indexed geometry the first time a face scalar is added
(`tris_per_face` maps polygon values to triangles); the edge overlay is rebuilt.

---

## `Scene` — collect objects, send once

```python
with kv.Scene() as s:
    s.register_surface_mesh("Base", V, F, color=(0.8, 0.8, 0.8))
    s.register_curve_network("Edges", P, E, color=(0.8, 0.2, 0.2), radius=0.002)
    s.add_vector_quantity("Base", "normals", N, defined_on="vertices")
    s.extend(objects)                      # pre-built serializer dicts
return {"action": "scene_update", "objects": s.snapshot()}
```

| Method | Polyscope equivalent |
|---|---|
| `register_surface_mesh(name, V, F, color, face_size, opacity, show_edges, edge_color, material)` | `ps.register_surface_mesh` |
| `register_curve_network(name, P, E, color, radius)` — `radius=0` flat lines, `>0` tubes | `ps.register_curve_network` |
| `register_point_cloud(name, X, color, radius)` | `ps.register_point_cloud` |
| `register_vector_field(name, origins, vectors, length, radius, color)` | — |
| `add_scalar_quantity(target, field, values, defined_on)` | `structure.add_scalar_quantity` |
| `add_vector_quantity(target, field, vectors, defined_on, length, radius)` | `structure.add_vector_quantity` |
| `set_enabled(name, enabled)` | `structure.set_enabled` |
| `visualize_frame(name, points, e1, e2, n)` / `add_cross_field(mesh, v1, v2, …)` | — |
| `extend(list_of_dicts)`, `snapshot()`, `clear()` | — |

Methods return `self`, so calls chain.

**Glyphs.** kayviz does not generate geometry. Spheres, circles, plane patches, cones,
cone strips and cross fields come from `hanan.glyphs` as `(V, F)` / `(P, E)`:
`s.register_surface_mesh("S", *glyphs.sphere(c, r))`,
`s.register_curve_network("Circles", *glyphs.circles(C, N, R))`.

---

## Callback API — `kv.set_user_callback(fn, app_name="callback", on_load=None)`

| Argument | Description |
|---|---|
| `fn` | Zero-argument callback. Run once in schema mode to capture the widgets, then again on every browser event. |
| `app_name` | URL segment: `?app=<app_name>`. |
| `on_load` | Optional zero-argument callable that pushes the initial scene. |

### `kv.imgui` — widgets

Each widget takes a mutable `state` dict and a `key`, updates `state[key]` in place and
returns `(changed, value)`; `button` returns `bool`.

```python
changed, v = kv.imgui.slider_float("Label", state, "key", vmin, vmax)
changed, v = kv.imgui.slider_int  ("Label", state, "key", vmin, vmax)
changed, v = kv.imgui.checkbox    ("Label", state, "key")
changed, v = kv.imgui.dropdown    ("Label", state, "key", ["a", "b"])
changed, v = kv.imgui.text_input  ("Label", state, "key")
clicked    = kv.imgui.button      ("Label")

with kv.imgui.header("Section"):          # collapsible folder
    kv.imgui.slider_float(...)
```

In schema mode every widget returns `(False, current value)`. In live mode every widget
the user edited since the previous event returns `changed=True` (two sliders moved in quick
succession both report), and a button returns `True` only when it was clicked. Dropdown
values keep the type of the option (`[1, 2, 3]` gives ints). `slider_float` / `slider_int`
take an optional `step`.

After each callback the panel shows the values your callback left in `state` (a "Reset"
button moves the sliders back), and widgets created under a condition appear or go away.
Widget keys and button labels should be unique (a warning lists duplicates).

In GUI apps (`kv.GUIApp`), a streaming (async) action runs once at a time: a second "run"
while one is running is refused with an error message.

A callback app with a custom panel:
`kv.register_app(kv.CallbackApp(fn, app_name=..., on_load=...), panel_js="panel.js")`.

**Threads inside callbacks.** Geometry pushed inside a callback is captured into the
callback app's buffer through a `contextvars.ContextVar` push sink. To start a helper
thread whose pushes go where the caller's pushes go, use
`kv.thread(fn, *args, **kwargs) -> threading.Thread` (started, daemon; runs `fn` in a
copy of the current context). A plain `threading.Thread` starts with an empty context, so
pushes from it go to the script channel.

---

## `GUIApp`

```python
class MyApp(kv.GUIApp):
    name      = "myapp"          # URL segment
    state_cls = MyState          # @kv.gui_state @dataclass
    out_dir   = "out"
    panel_js  = None             # or a path; kv.register_app(..., panel_js=...) sets it

    def initial_scene(self) -> dict:
        return {"objects": [...]}

    def register_actions(self):
        self.action("step", self._step)      # sync:  (state, data) -> dict | None
        self.action("run",  self._run)       # async: (state, data, ws), streams

kv.register_app(MyApp(), panel_js="my_panel.js")
```

| Helper | Returns | Purpose |
|---|---|---|
| `_make_scene_update(objects, **extra)` | `dict` | `{"action": "scene_update", "objects": …}` |
| `_done(action_name, **extra)` | `dict` | lifecycle event, e.g. `"optimization_complete"` |
| `_apply_client_state(payload)` | `None` | apply a dict to `self.state` by hand |
| `extra_routes(router)` | — | override to add HTTP routes under `/api/<name>` |

`register_app` may be called at any time, also after the server started; registering a
name again (a re-run notebook cell) replaces the app.

**Routes per app** (prefix `/api/<name>`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/schema` | widget schema, action list, whether a custom panel exists |
| `POST` | `/load` | initial scene |
| `GET` | `/panel.js` | the app's custom panel module (if any) |
| `WS` | `/ws` | actions and streamed updates |

`/api/_info` names the default app that `/` opens without `?app=`.

To host several apps in one server under your own uvicorn:
`from kayviz.server import create_app; app = create_app(apps=[A(), B()], shared=True)`.

---

## `@kv.gui_state` and widget annotations

```python
@kv.gui_state
@dataclass
class MyState:
    experiment_name: kv.text_field("Experiment Name")      = "exp0"
    max_iter:        kv.int_slider(1, 200, 1, "Max Iter")  = 50
    alpha:           kv.slider(0.0, 1.0, 0.01, "Alpha")    = 0.5
    mode:            kv.dropdown(["a", "b", "c"], "Mode")  = "a"
    show_mesh:       kv.checkbox("Show Mesh")              = True
    result: object = None                                  # internal, not rendered
```

| Helper | Widget | Type |
|---|---|---|
| `slider(min, max, step, label)` | float slider | `float` |
| `int_slider(min, max, step, label)` | integer slider | `int` |
| `dropdown(options, label)` | select | any |
| `checkbox(label)` | checkbox | `bool` |
| `text_field(label)` | text input | `str` |

Fields sharing a prefix (`sphere_radius`, `sphere_center`) are grouped in one folder.

---

## WebSocket protocol

**Client → server**
```json
{ "action": "my_action", "...": "params" }
{ "action": "_set_state", "state": { "key": "value" } }
{ "action": "_callback",  "trigger": "key_or_label", "state": { "key": "value" } }
```

**Server → client**
```json
{ "action": "scene_update", "objects": [], "iteration": 5, "energy": 0.023 }
{ "action": "setup_done" }
{ "action": "optimization_complete" }
{ "action": "error", "message": "…" }
```

**Viewing.** z is up by default (`kv.set_up_dir("y")` switches; open tabs reload). The view
fits the scene when the first geometry arrives; **F** frames the scene from the current
direction, **R** (or the ⤢ button) resets the view; `kv.look_at(position, target)` and
`kv.reset_camera()` drive the camera from Python. Clip planes and the grid follow the scene
size, so any unit works. Default sizes are relative: point radius 0.5% and curve tube radius
0.15% of the object's size, arrow length 4% of the target's size (pass a number to fix one).
Surface meshes take `shading="auto" | "flat" | "smooth"` (auto: flat for polygon meshes,
smooth for triangle meshes; also a "flat shading" checkbox in the scene panel).
Scalars take `cmap=` (viridis, plasma, inferno, magma, cividis, coolwarm, rdbu, piyg,
twilight, turbo, gray, blues) and `vminmax=(vmin, vmax)`. Vectors take
`vectortype="standard"` (length × |v| / max|v|, the default), `"ambient"` (|v| in scene
units) or `"unit"` (all the same length).

**Panels.** The Scene panel, the app's control panel, the Energy panel and the benchmark
panel are anchored (docked at their edge) by default; the 📌 in a title bar makes the panel
loose: a floating window to drag by its title and resize from its corner (📍 anchors it
back). The choice, position and size are remembered.

**Benchmark.** The 📊 button, or `kv.benchmark(frames=60)` from Python (prints a table and
returns a dict), renders the current scene in plain and in studio mode and reports frame
times (median, 95th percentile; each frame timed until the GPU finished it), triangles,
draw calls, and memory: geometry buffers exactly; screen, studio and shadow buffers as
estimates from their formats; the browser's JavaScript heap. For offline Python-side speed
and memory evaluation across standard synthetic scenes, run `python -m kayviz.evaluate`
(`--suite speed,memory`, `--scenes small|large|<id>`, `--out DIR`, `--compare baseline.json`,
`--quick`), which writes `evaluate-<date>-<host>.json` and `.md`.

**Access.** The viewer answers only this machine's programs and its own page: other web
pages open in your browser cannot read the scene, run callbacks or stop the server
(Host, Origin and Sec-Fetch-Site checks, `kayviz/security.py`). Behind a proxy (JupyterHub,
remote port forwarding under another name) add the name to `KAYVIZ_ALLOWED_HOSTS`
(comma-separated). To serve other machines: `python -m kayviz --host 0.0.0.0
--allow-network` — anyone who reaches the port sees the scene and can run its actions.

**Input checks.** The serializers raise `ValueError` naming the object for wrong input:
vertices / points / vectors not `(N, 3)` (2D points get a hint to add a z column), complex
or non-numeric arrays, face or edge indices out of range or not integers, faces with fewer
than 3 vertices, a flat index list instead of polygons, colours outside [0, 1] (0-255 values
get a hint), opacity outside [0, 1], `defined_on` other than `"vertices"` / `"faces"`. In a 2D
faces array, `-1` at the end of a row pads a shorter polygon. NaN vertices only warn; NaN
scalar values are drawn in a grey NaN colour. `kv.add_*_quantity` also checks the target:
it must be registered (removed or cleared ones are gone), of a fitting type (scalars on
surface meshes; vectors on meshes or point clouds) and have one value per vertex / face.
Re-registering a structure replaces it with its quantities, as `kv.remove` drops them.
Convex polygons are fanned; non-convex ones (e.g. L-shaped panels) are ear-clipped in their
plane so no triangle lies outside the polygon. When most faces of a mesh are not convex in
their plane (twisted, non-planar faces), they are fanned and a warning says so.

Object dicts in `"objects"` (built by `kayviz.serializers`). Arrays are numpy float32 / int32
(always copies of the caller's arrays). On the WebSocket a message with arrays is one
binary frame (JSON header + raw arrays, see `kayviz/runtime/wire.py`); over HTTP they
are lists (`wire.jsonable`).

| `"type"` | Fields |
|---|---|
| `surface_mesh` | `name`, `vertices`, `faces`, `face_size`, `color`, `opacity`, `show_edges` (+ `edge_color`, `edge_radius`), `tris_per_face`, `poly_edges`, `material` |
| `curve_network` | `name`, `vertices`, `edges`, `color`, `radius` |
| `point_cloud` | `name`, `points`, `color`, `radius` |
| `scalar_quantity` | `target`, `name`, `defined_on`, `values` |
| `vector_quantity` | `target`, `name`, `defined_on`, `vectors`, `length`, `radius` |
| `vector_field` | `name`, `origins`, `vectors`, `length`, `radius`, `color` |
| `edge_child` | `target`, `vertices`, `edges`, `color`, `radius` (custom overlays; `surface_mesh` no longer emits it) |
| `set_enabled` | `name`, `enabled` |

---

## Browser side (`kayviz/src/kayviz/static/`)

Custom panels import kayviz modules through the import-map alias `kayviz/` → `/static/`.

### `Panel` (`gui/panel.js`)

| Method | psim equivalent |
|---|---|
| `addSection(name, open=true)` | `psim.CollapsingHeader()` |
| `removeSection(name)` | — |
| `setVisible(bool)`, `refresh()`, `destroy()` | — |

```js
import { Panel } from 'kayviz/gui/panel.js';
const f = this.addSection('My Section');
f.add(state, 'alpha', 0, 1, 0.01).name('Alpha');
f.add(state, 'mode', ['a', 'b']).name('Mode');
f.add({ fn: () => ws.send('my_action', state) }, 'fn').name('Run');
```

A custom panel module's default export is constructed as `new Panel(ws, schema)`.

### `buildSchemaWidgets` (`gui/auto_panel.js`)

`buildSchemaWidgets(gui, schema, state, ws)` fills a lil-gui folder from the server schema
and sends `_set_state` on changes — schema widgets plus hand-made buttons in one panel.
`AutoCallbackPanel` (`gui/auto_callback_panel.js`) is the generated panel used when an app
has no `panel_js`.

### `Viewer` (`viewer.js`, `window.__viewer`)

- `registerSurfaceMesh`, `registerCurveNetwork` (`radius=0` flat lines, `>0` tubes),
  `registerPointCloud` (instanced spheres), `registerVectorField` (instanced arrows)
- `addScalarQuantity(parent, key, values, definedOn)`, `setActiveScalar`, `setScalarRange`
- `addEdgeChild(parent, edgeVerts, edgeIdx, color, radius)`, `toggleEdges(parent, enabled)`
- `setEnabled`, `setColor`, `setOpacity`, `setRadius`, `setCurveRadius`, `setVectorLength`
- `setMaterial(name, matName)` — hot-swap from `lib/MaterialLibrary.js`
- `remove(name)`, `clearAll()`, `applyMessage(data)` (dispatch on `type`)

### `WSClient` (`ws.js`)

```js
const ws = new WSClient(url, viewer, statusEl);
ws.send('my_action', { key: value });
ws.onMessage(data => { /* … */ });
```

Reconnects with exponential backoff. Every page also subscribes to `/api/script/ws`, so
`kv.register_*` from any process shows up in whichever app is open.
