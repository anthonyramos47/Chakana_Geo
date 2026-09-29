# Polyhedral mesh optimization (hanan + kayviz)

Makes a quad mesh planar and circular (every face on a circle) with the hanan
optimizer, and shows every step live in the kayviz viewer.

```bash
python examples/polyhedral_mesh/run.py                  # bundled data/pq_mesh.obj
python examples/polyhedral_mesh/run.py my_quads.obj
```

In the browser: set the weights, **Initialize Optimizer**, then **Step** or
**Run All**. The scene shows the mesh coloured by planarity error, its Gauss
image and the face circumcircles. **Export OBJ** writes to `out/`.

| File | Role |
|---|---|
| `run.py` | entry point: registers the app with kayviz and opens the viewer |
| `app.py` | `PolyhedralMeshApp(kv.GUIApp)`: actions, including the streamed `run` |
| `state.py` | `@gui_state` dataclass; annotated fields become panel widgets |
| `computations.py` | hanan: mesh loading, energy setup, optimization step, scene snapshot |
| `polyhedral_panel.js` | custom panel: widgets plus the action buttons |
