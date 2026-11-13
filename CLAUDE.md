# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

Two independent libraries, prepared for a public release (branch `libs-split`):

| Path | What | Depends on |
|---|---|---|
| `hanan/` | geometry + optimization library (`src/hanan`, `tests/`, `examples/`, `notebooks/`) | numpy/scipy/libigl — **no viewer** |
| `kayviz/` | browser viewer library (`src/kayviz`, frontend in `src/kayviz/static/`, `tests/`) | fastapi/uvicorn/numpy — **no hanan** |
| `examples/polyhedral_mesh/` | example app (`run.py`) and notebook (`circular_mesh.ipynb`) combining both | hanan + kayviz |
| `docs/hanan/`, `docs/kayviz/` | user documentation of each library (moved out of the package folders) | — |

Keep those dependency directions: hanan must not import kayviz or polyscope; kayviz must not import hanan. They meet only through plain arrays (`kv.register_surface_mesh("S", *glyphs.sphere(c, r))`).

The research code that uses both libraries (L-mesh, Dupin, L-conjugacy: former `Code/`, `notebooks/`, `server/`, root `tests/`) moved to `../Sphere_meshes_projects` on 2026-09-29, to be restructured into per-paper projects. It uses the editable installs from this repository.

## Setup and Commands

All Python must run under the activated conda env **`Lproj`** — base Python is numpy 2.x and breaks the imports.

```bash
pip install -e hanan -e kayviz          # editable installs (src layout)
```

```bash
# Tests — each package has its own suite
(cd hanan  && python -m pytest)         # mesh, geometry, glyphs, optimization
(cd kayviz && python -m pytest)         # serializers, state schema, ScriptApp, in-process runtime (test_runtime.py)
python -m pytest kayviz/tests/test_runtime.py -k callback -q   # single case
```

`kayviz/tests/test_runtime.py` runs each scenario in a subprocess (the scripting module holds process-global state) with `KAYVIZ_NO_BROWSER=1`.
`hanan/examples/polyscope_demos/` are interactive Polyscope scripts, not tests — they call `ps.show()` at import and will hang pytest. They, `hanan/examples/optimization_template_polyscope.py` and `hanan/notebooks/` still use Polyscope (kept on purpose, to be converted to kayviz later; their data paths are stale).

### Running things

```bash
python examples/polyhedral_mesh/run.py  # a standalone project: own server, opens its tab
python -m kayviz                        # shared viewer; notebooks' kv.init() attach to it
python -m kayviz.evaluate --quick       # speed + memory evaluation -> evaluate-<date>-<host>.{json,md}
python -m kayviz.evaluate --suite browser   # opens a tab: delivery, frames, toggles, tab memory
python -m kayviz.evaluate --suite robustness   # fuzzing, protocol, lifecycle, leaks
(cd kayviz && python -m pytest -m slow)     # the long robustness checks (excluded by default)
```

A process that registered its own apps always starts its own viewer (next free port) even if a shared one is running.

## Architecture

### kayviz runtime (`kayviz/src/kayviz/`)

`import kayviz as kv` exposes the Polyscope-style API from `runtime/script.py`, which holds the state and plumbing and re-exports the API from `runtime/register.py` (structures, quantities, remove/clear, export, origin), `view.py` (camera, up axis), `capture.py` (screenshots, benchmark, save_grid) and `lifecycle.py` (apps, show, kill_servers). Those modules reach shared names as `_s.name` (`from . import script as _s`) at call time: monkeypatching `script.X` and other modules reading `script._state` keep working. The key design:

- **`kv.init()` modes** (`script._mode`): `"local"` — starts `server.BackgroundServer` (uvicorn in a daemon thread, first free port from `KAYVIZ_PORT`/8000); `"attached"` — a *shared* kayviz server answers `/api/script/ping` with `shared: true` (or `KAYVIZ_URL` is set), pushes go over HTTP; `"hosted"` — this process *is* a server, set by the `create_app` lifespan via `script._bind_loop`.
- **Pushes in local/hosted mode never go over HTTP.** `_send()` runs `ScriptApp.push` on the server loop: `run_coroutine_threadsafe` from other threads, `loop.create_task` when already on the loop (async handlers run there — blocking would deadlock).
- **Handlers never run on the event loop.** User callbacks and sync GUIApp actions run in a worker thread (`asyncio.to_thread`, one at a time per app; pushes inside are captured by a `ContextVar` sink, and `kv.thread(fn, *args, **kwargs)` copies the context for child threads while plain `threading.Thread` pushes to the script channel); async streaming actions run as tasks so the connection keeps reading ("stop" during "run"). Queued events of one slider are replaced by the newest (`CallbackApp._enqueue`). A GUIApp streaming action runs once at a time (a second "run" is refused); `_set_state` takes the handler lock. The CallbackApp lock is held until the worker thread returns, even when the tab closes mid-callback. Messages are encoded off the loop, once per broadcast.
- **Outbound path** (`BroadcastMixin`): every tab has a queue and one sender task; pushes, clear/remove and a new tab's snapshot are published under one order lock, so messages arrive in order and a snapshot never overtakes an update; producers return once queued, and a tab more than `MAX_PENDING` messages behind is dropped (it reloads the snapshot). uvicorn's websockets-sansio protocol never waits for the socket, so the sender itself waits while more than `MAX_UNSENT` (32 MB) written bytes are not taken by the tab (the transport reaches the app through `server._TransportMiddleware`, `scope["kayviz.transport"]`); a stuck tab is dropped after `SEND_TIMEOUT` instead of the server keeping every message for it. Asyncio primitives are per serving loop (`_prims`, `GUIApp._lock`), so a server restarted in the same process works. uvicorn runs the `websockets-sansio` protocol.
- **Tab reuse.** `/api/_info` carries a server `instance` id; a tab that reconnects to a new instance reloads (switching to the new server's app if its own is gone), and `show()` waits for such a tab before opening one (`_wait_for_tab`). Tabs retry every ≤ 2 s and give up after 15 min. The viewer renders on demand (`window.__invalidate()`).
- **Registry** (`runtime/registry.py`): routes look the app up by name per request, and `register_app` after `mount_all` mounts on live servers — so apps can be added at runtime and re-registering a name (notebook cell re-run) replaces it. `kv.register_app` / `kv.set_user_callback` only record the app; they refuse in attached mode. The server starts at `show()`/first push.
- **Every browser page also subscribes to `/api/script/ws`** (see `static/app_loader.js`), so `kv.register_*` from anywhere shows up in whatever app is open, and `show(block=True)` / screenshots (which track ScriptApp clients) work for all app types. `/api/script/wait` waits for a first client, then for all to leave with a 3 s reload grace.
- **Custom panels ship with the app**: `GUIApp.panel_js` (or `kv.register_app(app, panel_js=...)`, resolved relative to the caller) is served at `/api/<app>/panel.js`; panels import kayviz modules through the import-map alias `kayviz/` → `/static/` (`import { Panel } from 'kayviz/gui/panel.js'`). Without one, `AutoCallbackPanel` renders the schema.
- **Viewing** (`main.js`): up axis from `script._up` (default "z", `kv.set_up_dir`), written into index.html as `<meta name="kayviz-up">` because OrbitControls fixes its up at construction; `fitView`, dynamic clip planes and grid from `sceneBounds()`; F/R keys; `{action: "view"}` messages carry look_at / fit / up. Studio places floor and key light relative to the scene and the up axis. Default point/curve/vector sizes are `None` in Python and relative to the object in `viewer._size`.
- **Access** (`kayviz/security.py`, `LocalOnlyMiddleware`, ASGI so it covers WebSocket handshakes): requests must address this machine (Host 127.0.0.1/localhost/::1, plus `KAYVIZ_ALLOWED_HOSTS`), an `Origin` header must be the viewer itself, and cross-site `Sec-Fetch-Site` is refused except for top-level navigation. Python clients send none of these headers. `python -m kayviz --host 0.0.0.0` needs `--allow-network` (prints a warning; Host check off). WS messages from browsers are capped at 4 MB; screenshots at 12 Mpx.
- `/api/_info` names the default app (last user-registered app) that `/` opens without `?app=`.

App kinds: `ScriptApp` (always registered; buffer + broadcast of pushed objects, screenshot handshake), `CallbackApp` (`set_user_callback`; runs `gui()` once in schema mode to capture widgets, again in live mode per browser event; pushes inside the callback or a `kv.thread` it starts are captured into its own buffer via the `ContextVar` `script._set_push_sink`), `GUIApp` subclasses (state dataclass + action handlers). The WebSocket loop is generic in `GUIApp.handle_websocket`.

### hanan geometry layout

`hanan.geometry` = `mesh` (`Mesh`), `algebraic` (vector algebra), `primitives` (points/lines/planes/circles/spheres), `construction`, `measures`, `conical`, `lie`, `isotropic_geometry`, `io`; `hanan.geometry.utils` re-exports all of them. `interleave_indices_dim` lives in `hanan.optimization.indexing` (it can't be re-exported from `geometry.utils` — `hanan.optimization` imports `hanan.geometry`, so that would be a cycle). **Planes are always `(n, h)` with `n·x + h = 0`**; the plane through point `c` with normal `n` is `(n, -n·c)`. `hanan.glyphs` (outside `hanan.geometry`) returns mesh data for drawing — spheres, circles, plane patches, cones, cone strips — and draws nothing. `docs/hanan/GEOMETRY_API.md` is generated from docstrings (glyphs included).

`hanan.optimization`: one snake_case module per class (`optimizer.py` → `Optimizer`, `edge_length.py` → `EdgeLength`, `laplacian_fairness.py` → `LaplacianFairness`, `step_control.py` → `StepControl`, `proximity_reference.py` → `ProximityReference`, …); `term.name` strings (weight-dict keys) kept their old values. Terms implement `res()` (must be pure — it is also evaluated at rejected trial points), `grad()`, optional `accept_step(X)` for iterate-tracking state; legacy `compute()`/`func()` still supported. See `docs/hanan/OPTIMIZATION_API.md`.

### Frontend (`kayviz/src/kayviz/static/`, no build step)

- `main.js` — renderer, camera, OrbitControls, lighting; `window.__scene`, `window.__lights`
- `app_loader.js` — resolves the app, fetches `/api/<app>/schema`, opens the app WS plus the script WS, loads the panel, POSTs `/api/<app>/load`
- `viewer.js` — `Viewer`: object registry; `applyMessage(data)` dispatches on `type`; emits `viewer-changed`
- `ws.js` — `WSClient` with reconnect/backoff
- `gui/panel.js` (base), `gui/auto_panel.js`, `gui/auto_callback_panel.js`, `gui/scene_panel.js` (object list, colour/opacity/shader, "show edges"), `gui/energy_panel.js`, `lib/MaterialLibrary.js`, `lib/PointSprites.js` (point clouds as sphere impostors: an instanced camera-facing quad per point, ray-sphere hit, depth and normal written in the fragment shader of a patched MeshPhongMaterial; radius is a uniform; no studio shadow/AO), `lib/Studio.js` (studio render mode: GTAO + soft floor shadow + backdrop, toggled by the bulb button; see docs/kayviz/FRONTEND_API.md); `main.js` also has the save-picture camera button (`window.__savePicture`)

Three.js 0.165 (+ the add-ons used) and lil-gui are bundled in `static/vendor/` (`npm run vendor` in `kayviz/` refreshes them from `package.json`); the import map in `index.html` points there with `./static/...` addresses (an import-map address must start with `/`, `./` or `../`). All server URLs are page-relative (`static/urls.js`: `api()`, `wsUrl()`), so the viewer works behind path prefixes and HTTPS. Screenshot jobs travel over the script WebSocket to the newest tab (`{action: "screenshot"}`); re-registering an app closes its tabs with code 4000, which reloads them. `npm test` in `kayviz/` runs the frontend tests (`tests/js/`, node + three). `npm run typecheck` type-checks every frontend module (all start with `// @ts-check`; JSDoc types; `kayviz/jsconfig.json`, page globals and Chrome-only APIs in `kayviz/types/globals.d.ts`). Keep new modules opted in.

### Scripting API

```python
import kayviz as kv
from hanan import glyphs

kv.init()                                            # own server, or attach to a shared one
kv.register_surface_mesh("Mesh", V, F, color=(0.5, 0.5, 0.5), show_edges=True)
kv.register_curve_network("Edges", v, e)
kv.register_surface_mesh("Sphere", *glyphs.sphere(c, r))
kv.add_scalar_quantity("Mesh", "values", vals, defined_on="faces")
kv.add_vector_quantity("Mesh", "normals", N, defined_on="vertices")
kv.push_objects(objects)                             # pre-built serializer lists
kv.set_enabled("Edges", False); kv.remove("Edges"); kv.clear()
kv.screenshot_views(views=kv.TIGHT_VIEWS); kv.save_grid(path, rows)
kv.show()                                            # blocks in scripts, returns in notebooks
```

### Adding a New GUI (a project is one script — no server file edits)

```python
import kayviz as kv
state = {"radius": 1.0}
def gui():
    kv.imgui.slider_float("Radius", state, "radius", 0.1, 5)
    if kv.imgui.button("Run"):
        kv.register_surface_mesh("Result", *compute(state["radius"]))
kv.register_surface_mesh("Base", V, F)
kv.set_user_callback(gui, app_name="myapp")
kv.show()
```

For a full app: `state.py` (`@gui_state` dataclass) + a `kv.GUIApp` subclass + optional panel JS, then `kv.register_app(MyApp(), panel_js="my_panel.js"); kv.show()`. See `examples/polyhedral_mesh/` and `docs/kayviz/README.md`.

### `@gui_state` Widget Pattern

State fields with widget annotations auto-render in the browser's AutoPanel; plain-typed fields are internal only:

```python
from kayviz import gui_state, slider, int_slider, dropdown, checkbox, text_field

@gui_state
@dataclass
class MyState:
    alpha:    slider(0.0, 1.0, 0.01, "Alpha")         = 0.5
    max_iter: int_slider(1, 200, 1, "Max Iter")        = 50
    mode:     dropdown(["sphere", "plane"], "Mode")    = "sphere"
    show:     checkbox("Show Mesh")                    = True
    name:     text_field("Experiment Name")            = "exp0"

    # Internal — NOT rendered (plain type annotations)
    result: object = None
    data:  dict   = field(default_factory=dict)
```

AutoPanel groups fields by name prefix: fields starting with `sphere_` auto-collapse under a "Sphere" section.

### Action Handlers: Sync vs. Streaming

**Sync** (returns one dict, sent immediately):
```python
def _my_action(self, state, data):
    with Scene() as s:
        s.register_surface_mesh("Base", V, F)
    return {"action": "scene_update", "objects": s.snapshot()}
```

**Async/Streaming** (receives `ws`, sends multiple messages — used for optimization loops):
```python
async def _run(self, state, data, ws):
    state.is_running = True
    for _ in range(state.max_iterations):
        if not state.is_running:
            break
        await asyncio.to_thread(comp.optimization_step, state)   # off the event loop
        await ws.send_json(comp.scene_snapshot(state))
    await ws.send_json(self._done("optimization_complete"))
```

The framework detects async handlers by signature (presence of `ws` parameter) and routes them accordingly.

### Serializer Contract

When adding a new visualization, return serializer dicts with a `"type"` field. `viewer.js:applyMessage()` dispatches on this field. Supported types: `surface_mesh`, `curve_network`, `point_cloud`, `scalar_quantity`, `vector_quantity`, `vector_field`, `edge_child`, `set_enabled`. Use the `Scene()` builder or call `kayviz.serializers.*` directly. `kayviz.serializers` is numpy-only and generates no geometry: it wraps arrays the caller already has. Glyph geometry (spheres, circles, plane patches, cones, cone strips, polylines, segments, cross fields) comes from `hanan.glyphs`, which returns plain `(V, F)` / `(P, E)` and draws nothing, e.g. `kv.register_surface_mesh("S", *glyphs.sphere(c, r))`. hanan has no `draw_*` functions.

Ragged polygon faces are **fan-triangulated** in `serializers.surface_mesh()` before serialization. The dict includes `tris_per_face: list[int]|null` for exact per-face scalar color mapping.

Serializers validate their input and raise `ValueError` naming the object (shapes, index ranges, polygon sizes, `-1` padding, colours, `defined_on`); `script._track` records the structures pushed from the process so `kv.add_*_quantity` rejects unknown targets and wrong lengths (skipped in attach mode). In the buffers (`BroadcastMixin._buffer_objects`) re-registering or removing a structure drops its `name::*` quantities; `kv.remove`/`kv.clear` inside a callback travel as markers through the sink and are mirrored into the script buffer.

Serializer arrays are numpy float32 / int32 copies (never views of the caller's arrays). Positions (`serializers._positions`: vertices, points, vector-field origins; never vectors) are relative to a scene origin subtracted in float64 (`serializers._origin`, decided by the first positions of a scene, `kv.set_origin`, reset by `kv.clear()`); objects then carry `origin`, which the viewer keeps in `opts.origin` for readouts. `kayviz/runtime/wire.py` sends a message containing arrays as one binary WebSocket frame — `uint32` header length, JSON header with each array replaced by `{"__b": offset, "t": "f32"|"i32"|"u32", "n": length}`, then the 8-byte-aligned arrays — which `static/ws.js` (`decodeFrame`) turns into typed arrays; `wire.decode` is the Python inverse (tests). The same frame travels over HTTP (`Content-Type: application/x-kayviz-frame`, `wire.FRAME_TYPE`, at most 1 GB): attach-mode pushes POST it to `/api/script/push` (which still accepts JSON), and the page asks `/api/<app>/load?format=binary` for a GUIApp's initial scene (without `format` the route answers JSON, `wire.jsonable`). `objects` may be one serializer dict instead of a list. Streaming handlers get a `wire.Socket`, so their `ws.send_json(scene)` goes through the same encoder.

No edges travel with a `surface_mesh`: computing them was most of the serializer's work and up to 40% of the bytes sent. The viewer finds the sides of the **original polygons** itself (`static/lib/edges.js` `polygonEdges`, called by `viewer._edges` only when the overlay is first shown): the faces as sent if uniform polygons, else the triangles grouped by `tris_per_face`, where a diagonal is shared by two triangles of its polygon and a side by one (true for the fan and for ear clipping). A `poly_edges` index array from older servers, or `poly_edge_verts`/`poly_edge_conn` coordinates, are still accepted. The viewer stores them in `opts.edgeVerts` (= the mesh vertices) / `opts.edgeIdx`. In Python, ragged faces are handled as one flat index array plus sizes (`serializers._Ragged`), never one array per polygon. This powers the **"show edges"** checkbox in the scene panel: toggling it on calls `viewer.toggleEdges(name, true)`, which creates an `EdgeChild` (thin tubes — radius 0 means 3% of the median edge length — never `LineSegments`, which showed through objects; tubes, here and for curve networks, are one open cylinder instanced per edge, so click-to-inspect reads the edge from `instanceId`) without any server round-trip. For hex or n-gon meshes this correctly shows polygon edges, not triangle diagonals.

Pass `show_edges=True` (with `edge_color`, `edge_radius`) to `register_surface_mesh` / `Scene.register_surface_mesh` to overlay edges on initial load; they travel inside the mesh dict. `edge_child` remains for custom overlays.

`scalar_quantity` with `defined_on="faces"` is supported. The viewer auto-converts indexed geometry to non-indexed form the first time a face scalar is added.

### WebSocket Message Protocol

Client → server: `{ "action": "<name>", ...params }`
- `_set_state` is built-in: `{ "action": "_set_state", "state": { key: value, … } }` — sent automatically by AutoPanel on every slider change.

Server → client:
- `{ "action": "scene_update", "iteration": int, "energy": float|null, "objects": [...] }` — after each step
- `{ "action": "setup_done" | "export_done" | "save_done" | "optimization_complete" }` — lifecycle events
- `{ "action": "error", "message": str }` — error reporting
