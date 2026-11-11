# kayviz

A Polyscope-style 3D viewer that runs in the browser: register meshes, curves,
point clouds and their quantities from Python, build control panels with a
callback, and look at them in a browser tab. Made for geometry research.

```bash
pip install kayviz            # or, from the repository: pip install -e kayviz
```

```python
import numpy as np
import kayviz as kv

V = np.random.rand(100, 3)
kv.init()                         # a viewer server for this script / notebook
kv.register_point_cloud("Points", V)
kv.show()                         # opens the tab; in a script, returns when it closes
```

- Surface meshes with polygon faces, curve networks, point clouds, vector fields;
  scalar (12 colormaps) and vector quantities; flat or smooth shading; a studio
  render mode (ambient occlusion, soft shadows) and picture export.
- `kv.set_user_callback(gui)` with `kv.imgui` widgets, or `kv.GUIApp` for larger
  apps with streamed computations and custom panels.
- Works offline (three.js and lil-gui are bundled), behind HTTPS and path prefixes;
  only this machine and the viewer's own page can reach the server.

Documentation: `docs/kayviz/` in the repository (README, TUTORIAL, API, COOKBOOK,
FRONTEND_API). kayviz's API is modelled on [Polyscope](https://polyscope.run) by
Nicholas Sharp; kayviz is an independent implementation, not affiliated with it.

Frontend development (no build step): `npm install && npm test` runs the browser
code's tests under node; `npm run vendor` refreshes `static/vendor/`.
