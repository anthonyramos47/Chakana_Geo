# hanan

Discrete differential geometry in Python: a half-edge mesh, geometry
processing utilities, and a Gauss-Newton / Levenberg-Marquardt optimizer
built from composable energy terms.

```bash
pip install -e hanan                 # from this repository
pip install -e "hanan[jax,fast]"     # autodiff / numba-accelerated terms
```

## Modules

| Module | Contents |
|---|---|
| `hanan.geometry.mesh` | `Mesh`: half-edge structure, adjacency queries, boundaries, normals, areas, Laplacians, Gauss image, quad strips |
| `hanan.geometry.algebraic` | vector algebra: normalisation, projections, rotations, barycenters |
| `hanan.geometry.primitives` | points, lines, planes, circles, spheres: distances, projections, reflections, intersections, circle fits, sphere inversion |
| `hanan.geometry.construction` | building meshes and curves: primitive solids, Catmull-Clark subdivision, lofting, offsets, merging |
| `hanan.geometry.measures` | per-face normals, planarity, circularity, circumcircles |
| `hanan.geometry.conical` | cones tangent to sphere pairs, cone strips, cone axes and curvature spheres of conical meshes |
| `hanan.geometry.lie` | Lie sphere geometry: oriented spheres on the Lie quadric, cyclidic families, envelopes |
| `hanan.geometry.isotropic_geometry` | isotropic / cylindrical sphere representations |
| `hanan.geometry.io` | OBJ/OFF read and write, colormaps |
| `hanan.geometry.utils` | convenience namespace re-exporting all of the above |
| `hanan.glyphs` | mesh data for drawing: spheres, circles, plane patches, cones, cone strips, polylines, segments, cross fields — returns `(V, F)` or `(P, E)`, draws nothing |
| `hanan.optimization` | `Optimizer` plus terms: `Planarity`, `Cyclicity`, `EdgeLength`, `LaplacianFairness`, `QuadFairness`, `Corner`, `Unit`, `TargetValue`, … |

See [MESH_API.md](MESH_API.md), [GEOMETRY_API.md](GEOMETRY_API.md) and
[OPTIMIZATION_API.md](OPTIMIZATION_API.md) (solver model, built-in terms, writing
your own term) for the full reference.

## Example: make a quad mesh planar

```python
from hanan.geometry.io import read_obj
from hanan.geometry.mesh import Mesh
from hanan.optimization import Optimizer, Planarity

V, F = read_obj("mesh.obj")
mesh = Mesh()
mesh.make_mesh(V, F)

opt = Optimizer()
opt.add_variable("v", mesh.vertices.flatten())
opt.add_variable("n_f", mesh.face_normals.flatten())
term = Planarity()
term.name = "Planarity"
opt.add_objective_term(term, args=([mesh.faces]), w=1.0, ce=True)
opt.unitize_variable("n_f", 3, w=5)
opt.initialize_optimizer()

for _ in range(20):
    opt.get_gradients()
    opt.optimize_step()

V_planar = opt.unpack("v").reshape(-1, 3)
```

hanan has no viewer dependency. Every result is plain arrays, so any viewer
shows it — for example [kayviz](../kayviz/README.md) (browser):

```python
import kayviz as kv
from hanan import glyphs

kv.register_surface_mesh("Planar mesh", V_planar, mesh.faces)
kv.register_surface_mesh("Sphere", *glyphs.sphere(center, radius))
kv.register_curve_network("Circles", *glyphs.circles(centers, normals, radii))
kv.show()
```

The [`examples/polyhedral_mesh`](../../examples/polyhedral_mesh) app combines both.
`examples/polyscope_demos` holds older interactive demos that use Polyscope.

## Tests

```bash
cd hanan && python -m pytest
```
