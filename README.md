# Chakana-Geo

**hanan** and **kayviz**: two independent Python libraries for geometry processing research:

- **hanan**: discrete differential geometry. It provides a half-edge `Mesh` (a modified
  version of [Davide Pellis](https://scholar.google.com/citations?user=JnocFM4AAAAJ&hl=en)'s mesh code), the geometry
  of points, lines, planes, circles, spheres and cones, Lie sphere and isotropic geometry,
  and a Gauss–Newton / Levenberg–Marquardt `Optimizer` with ready-made objective terms
  (planarity, cyclicity, fairness, edge length, closeness to a reference surface, …).
- **kayviz**: a Polyscope-style 3D viewer that runs in the browser. Register meshes,
  curves, point clouds and scalar or vector quantities from Python, and build control
  panels from a callback or a state dataclass. It works in plain scripts and in Jupyter.

Each library can be installed and used without the other. hanan has no viewer dependency,
and kayviz does not import hanan. They connect through plain NumPy arrays:
`kv.register_surface_mesh("Sphere", *glyphs.sphere(center, radius))`.

## Installation

Python ≥ 3.9. From a clone of this repository:

```bash
pip install -e hanan            # numpy, scipy, pandas, matplotlib, libigl
pip install -e kayviz           # numpy, fastapi, uvicorn, requests, pydantic
```

Install only the one you need, or both. Optional extras:

| Extra | Adds |
|---|---|
| `pip install -e "hanan[jax]"` | JAX, for autodiff objective terms |
| `pip install -e "hanan[fast]"` | numba, for JIT-compiled terms |
| `pip install -e "kayviz[screenshots]"` | Pillow, for `kv.save_grid` contact sheets |
| `[test]` on either | pytest (and httpx for kayviz) |

## hanan at a glance

```python
from hanan.geometry.io import read_obj
from hanan.geometry.mesh import Mesh
from hanan.optimization import Optimizer, Planarity

V, F = read_obj("mesh.obj")
mesh = Mesh()
mesh.make_mesh(V, F)                               # half-edge structure
mesh.vertex_adjacency_list(); mesh.face_normals    # adjacency, normals, boundaries, …

opt = Optimizer()                                  # variables + weighted residual terms
opt.add_variable("v", mesh.vertices.flatten())
opt.add_variable("n_f", mesh.face_normals.flatten())
term = Planarity(); term.name = "planarity"
opt.add_objective_term(term, args=([mesh.faces]), w=1.0, ce=True)
opt.unitize_variable("n_f", 3, w=5)
opt.initialize_optimizer()
for _ in range(20):
    opt.get_gradients(); opt.optimize_step()
V_planar = opt.unpack("v").reshape(-1, 3)
```

| Module | Contents |
|---|---|
| `hanan.geometry.mesh` | `Mesh`: half-edge structure, adjacency, boundaries, normals, Laplacians |
| `hanan.geometry.*` | `algebraic`, `primitives`, `construction`, `measures`, `conical`, `lie`, `isotropic_geometry`, `io` (all re-exported by `hanan.geometry.utils`) |
| `hanan.glyphs` | mesh data for drawing: spheres, circles, planes, cones, cone strips, polylines, cross fields, returned as `(V, F)` / `(P, E)` |
| `hanan.optimization` | `Optimizer` and terms: `Planarity`, `Cyclicity`, `EdgeLength`, `LaplacianFairness`, `QuadFairness`, `ProximityReference`, … |

Planes are always `(n, h)` with `n · x + h = 0`.

## kayviz at a glance

```python
import kayviz as kv

kv.init()                                          # viewer in a background thread
kv.register_surface_mesh("Mesh", V, F, show_edges=True)
kv.add_scalar_quantity("Mesh", "height", V[:, 2])
kv.register_curve_network("Curve", P, E, radius=0.002)
kv.show()                                          # blocks in scripts, returns in Jupyter
```

A control panel from a callback, with no JavaScript:

```python
state = {"scale": 1.0}

def gui():
    kv.imgui.slider_float("Scale", state, "scale", 0.1, 5.0)
    if kv.imgui.button("Apply"):
        kv.register_surface_mesh("Mesh", V * state["scale"], F)

kv.set_user_callback(gui)
kv.show()
```

Larger apps subclass `kv.GUIApp` (a state dataclass with widget annotations, action
handlers, streamed updates, and an optional custom JS panel). `python -m kayviz` starts
a shared viewer that several notebooks can push to.

## Examples

| Example | What it shows |
|---|---|
| [`examples/polyhedral_mesh/circular_mesh.ipynb`](examples/polyhedral_mesh/circular_mesh.ipynb) | notebook: optimize a noisy quad mesh into a circular mesh (planar faces inscribed in circles), shown in kayviz |
| [`examples/polyhedral_mesh/run.py`](examples/polyhedral_mesh) | interactive app: planarity and cyclicity optimization with sliders, live updates, custom panel and export |

```bash
python examples/polyhedral_mesh/run.py
```

## Documentation

| | |
|---|---|
| hanan | [overview](docs/hanan/README.md) · [geometry API](docs/hanan/GEOMETRY_API.md) · [mesh API](docs/hanan/MESH_API.md) · [optimization API](docs/hanan/OPTIMIZATION_API.md) (solver, built-in terms, writing your own term) |
| kayviz | [overview](docs/kayviz/README.md) · [tutorial](docs/kayviz/TUTORIAL.md) · [API reference](docs/kayviz/API.md) · [cookbook](docs/kayviz/COOKBOOK.md) · [frontend (JS) API](docs/kayviz/FRONTEND_API.md) |

## Repository layout

| Path | Contents |
|---|---|
| `hanan/` | package source (`src/hanan`), tests, Polyscope demos and notebooks (to be ported to kayviz) |
| `kayviz/` | package source (`src/kayviz`, browser frontend in `src/kayviz/static`), tests |
| `examples/` | examples that use both libraries |
| `docs/` | documentation of both libraries |

## Tests

```bash
(cd hanan  && python -m pytest)
(cd kayviz && python -m pytest)
```

## Acknowledgements

kayviz's API is inspired by [Polyscope](https://polyscope.run) by Nicholas Sharp; kayviz is an independent implementation and is not affiliated with Polyscope.

## AI assistance

Parts of this repository were developed with AI assistance (Anthropic's Claude Opus 5 and
Opus 5.5): the kayviz viewer, the cleanup and restructuring of the code into the two
libraries (including fixes to the optimizer and the tests that check them), and the
documentation and examples. The geometric and optimization methods and the design
decisions are by the authors. The AI-assisted changes were checked with tests and with
comparisons against the previous behaviour, and reviewed by the authors.

## Authors and license

hanan: Anthony Ramos-Cisneros and Davide Pellis. kayviz: Anthony Ramos-Cisneros.

The half-edge `Mesh` class in hanan (`hanan.geometry.mesh`, documented in the
[mesh API](docs/hanan/MESH_API.md)) is a modification of the mesh code that
**[Davide Pellis](https://scholar.google.com/citations?user=JnocFM4AAAAJ&hl=en)** wrote in *geometrylab*; the original design and core
implementation are his. The same code is the basis of
[ArchGeo](https://www.huiwang.me/mkdocs-archgeo/2.about/) by Hui Wang
([code](https://github.com/WWmore/DOS)).

Both libraries are released under the **GNU General Public License v3.0 or later**
([`LICENSE`](LICENSE); each package also ships its own copy). The code derived from
geometrylab keeps its original MIT notice, in
[`hanan/THIRD_PARTY_NOTICES.md`](hanan/THIRD_PARTY_NOTICES.md).
