# kayviz

A Polyscope-style 3D viewer that runs in the browser. You register geometry and
build control panels from Python; the viewer (Three.js) opens in a browser tab.

kayviz's API is modelled on [Polyscope](https://polyscope.run) by Nicholas Sharp; kayviz is an independent implementation and is not affiliated with Polyscope.

Each script or notebook runs its own viewer, so a project is a single Python
file with no separate server to configure.

```bash
pip install -e kayviz          # from this repository
```

## Quick start

```python
import numpy as np
import kayviz as kv

V = np.random.rand(100, 3)

kv.init()                                   # viewer server in a background thread
kv.register_point_cloud("Points", V, radius=0.01)
kv.show()                                   # opens the tab; returns when it is closed
```

`init()` serves on the first free port from 8000 and prints the URL. In a
plain script `show()` blocks until the tab is closed. In Jupyter it returns
immediately and the viewer stays alive with the kernel.

## Geometry

| Function | Polyscope equivalent |
|---|---|
| `register_surface_mesh(name, V, F, color, opacity, show_edges)` | `ps.register_surface_mesh` |
| `register_curve_network(name, V, E, color, radius)` | `ps.register_curve_network` |
| `register_point_cloud(name, P, color, radius)` | `ps.register_point_cloud` |
| `register_vector_field(name, origins, vectors, length)` | — |
| `add_scalar_quantity(target, name, values, defined_on)` | `structure.add_scalar_quantity` |
| `add_vector_quantity(target, name, vectors, defined_on)` | `structure.add_vector_quantity` |
| `set_enabled(name, bool)`, `remove(name)`, `clear()` | `set_enabled`, `remove_all_structures` |
| `screenshot(path)`, `screenshot_views()`, `save_grid()` | `ps.screenshot` |

Faces may be ragged polygons; they are fan-triangulated for rendering while
the polygon edges are kept for the "show edges" overlay.

## A GUI in the same script

```python
state = {"scale": 1.0}

def gui():
    kv.imgui.slider_float("Scale", state, "scale", 0.1, 5.0)
    if kv.imgui.button("Apply"):
        kv.register_point_cloud("Points", V * state["scale"])

kv.set_user_callback(gui)
kv.show()
```

`kv.imgui` provides `slider_float`, `slider_int`, `checkbox`, `dropdown`,
`text_input`, `button` and `header`. The callback runs again on every widget
event; geometry registered inside it is sent to the open tab.

The GUI can equally live in its own module; import it and call
`set_user_callback` from the main script.

## Larger apps: `GUIApp`

For apps with many actions, long-running (streamed) computations or a
hand-written panel, subclass `GUIApp`:

```python
from dataclasses import dataclass
import kayviz as kv

@kv.gui_state
@dataclass
class State:
    weight:   kv.slider(0.0, 10.0, 0.1, "Weight") = 1.0
    max_iter: kv.int_slider(1, 500, 1, "Max Iterations") = 50

class MyApp(kv.GUIApp):
    name = "myapp"
    state_cls = State

    def initial_scene(self, mesh_name=""):
        return {"objects": [kv.serializers.surface_mesh("Mesh", V, F)]}

    def register_actions(self):
        self.action("step", self.step)          # sync:  (state, data) -> message
        self.action("run", self.run)            # async: (state, data, ws) streams

    def step(self, state, data):
        ...
        return {"action": "scene_update", "objects": [...]}

    async def run(self, state, data, ws):
        for _ in range(state.max_iter):
            ...
            await ws.send_json({"action": "scene_update", "objects": [...]})

kv.register_app(MyApp(), panel_js="my_panel.js")   # panel_js is optional
kv.show()
```

Widget-annotated state fields render automatically. A custom panel is an ES
module that imports the base class with
`import { Panel } from 'kayviz/gui/panel.js'`; see
[`examples/polyhedral_mesh`](../../examples/polyhedral_mesh) for a complete app.

## A shared viewer for several processes

```bash
python -m kayviz            # or: kayviz --port 8000
```

While a shared viewer is running on the default port, `kv.init()` attaches to
it and pushes geometry there, so several notebooks can feed one window.
`kv.init(url=...)` or `KAYVIZ_URL` attaches to a specific server. GUIs
(`set_user_callback`, `register_app`) need the process's own viewer.

To host several apps in one server under your own uvicorn:

```python
from kayviz.server import create_app
app = create_app(apps=[MyApp(), OtherApp()], shared=True)
```

| Environment variable | Effect |
|---|---|
| `KAYVIZ_URL` | Attach to this server instead of starting one |
| `KAYVIZ_PORT` | First port tried for the in-process server (default 8000) |
| `KAYVIZ_NO_BROWSER=1` | Never open a browser tab (CI, remote machines) |

## Tests

```bash
cd kayviz && python -m pytest
```
