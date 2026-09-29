"""OBJ round-trip and a small Gauss-Newton planarity optimization."""

import numpy as np

from hanan.geometry.io import read_obj, write_obj
from hanan.geometry.mesh import Mesh
from hanan.geometry.measures import planarity_measure_quad_mesh
from hanan.optimization import Optimizer, Planarity

N = 5


def _grid(noise=0.0, seed=0):
    xs, ys = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
    zs = np.random.default_rng(seed).normal(scale=noise, size=xs.shape)
    V = np.column_stack([xs.ravel(), ys.ravel(), zs.ravel()])
    F = [[r * N + c, r * N + c + 1, (r + 1) * N + c + 1, (r + 1) * N + c]
         for r in range(N - 1) for c in range(N - 1)]
    return V, F


def test_obj_roundtrip(tmp_path):
    V, F = _grid(noise=0.05)
    path = tmp_path / "grid.obj"
    write_obj(str(path), V, F)
    V2, F2 = read_obj(str(path))
    np.testing.assert_allclose(V2, V, atol=1e-6)
    assert [list(f) for f in F2] == F


def test_planarity_optimization_reduces_nonplanarity():
    V, F = _grid(noise=0.05)
    mesh = Mesh()
    mesh.make_mesh(V, F)
    before = np.mean(planarity_measure_quad_mesh(mesh))

    opt = Optimizer()
    opt.add_variable("v", mesh.vertices.flatten())
    opt.add_variable("n_f", mesh.face_normals.flatten())
    term = Planarity()
    term.name = "Planarity"
    opt.add_objective_term(term, args=([mesh.faces]), w=1.0, ce=True)
    opt.unitize_variable("n_f", 3, w=5)
    opt.edge_length("v", mesh.edge_vertices(), target_length=None, w=0.1)
    opt.initialize_optimizer(verbose=False, adaptive_mu=False)
    for _ in range(10):
        opt.get_gradients()
        opt.optimize_step()

    mesh.vertices = opt.unpack("v").reshape(-1, 3)
    mesh.update_mesh()
    after = np.mean(planarity_measure_quad_mesh(mesh))
    assert after < 0.1 * before
