"""hanan.geometry.construction and hanan.geometry.measures."""

import numpy as np
import pytest

from hanan.geometry.construction import (
    catmull_clark_subdivision,
    cylinder,
    dodecahedron,
    interpolate_triangle_mesh,
    loft_curves,
    merge_curves,
    merge_meshes,
    normalize_vertices,
    offset_curve,
    polysphere,
)
from hanan.geometry.measures import (
    compute_circumcircles_quad_mesh,
    compute_face_normals,
    face_planarity,
    planarity_measure_quad_mesh,
)
from hanan.geometry.mesh import Mesh


def _grid(n=4, z=None):
    xs, ys = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    zs = np.zeros_like(xs) if z is None else z(xs, ys)
    V = np.column_stack([xs.ravel(), ys.ravel(), zs.ravel()])
    F = [[r * n + c, r * n + c + 1, (r + 1) * n + c + 1, (r + 1) * n + c]
         for r in range(n - 1) for c in range(n - 1)]
    return V, F


# ── construction ─────────────────────────────────────────────────────────────

def test_normalize_vertices_scales_longest_side():
    V = np.array([[0, 0, 0], [4, 1, 0], [2, 3, 1.0]])
    W = normalize_vertices(V)
    assert np.ptp(W, axis=0).max() == pytest.approx(1.0)


def test_dodecahedron_and_catmull_clark_counts():
    V, F = dodecahedron()
    assert np.shape(V) == (20, 3) and len(F) == 12
    V2, F2, parent = catmull_clark_subdivision(V, F)
    # one step: V + E + F vertices, one quad per face corner
    assert len(V2) == 20 + 30 + 12
    assert len(F2) == 12 * 5 and all(len(f) == 4 for f in F2)
    assert sorted(i for fs in parent.values() for i in fs) == list(range(len(F2)))


def test_polysphere_lies_near_sphere():
    c, r = np.array([1.0, 0, -1]), 0.5
    V, F = polysphere(c, r, 2)
    np.testing.assert_allclose(np.linalg.norm(np.asarray(V) - c, axis=1), r, rtol=1e-6)


def test_cylinder_radius():
    V, F = cylinder(np.zeros(3), 2.0, np.array([0, 0, 1.0]), 3.0, 12, 4)
    V = np.asarray(V)
    np.testing.assert_allclose(np.linalg.norm(V[:, :2], axis=1), 2.0, rtol=1e-9)
    assert all(len(f) == 4 for f in F)


def test_loft_and_offset_curves():
    c1 = np.column_stack([np.arange(5.0), np.zeros(5), np.zeros(5)])
    V, F = loft_curves(c1, c1 + [0, 1, 0])
    assert np.shape(V) == (10, 3) and len(F) == 4
    V, F = offset_curve(c1, np.array([0, 1.0, 0]), 0.2, 0.1)
    assert np.shape(V) == (10, 3) and len(F) == 4


def test_merge_meshes_reindexes_faces():
    V1, F1 = np.eye(3), [[0, 1, 2]]
    V, F = merge_meshes([V1, V1 + 5], [F1, F1])
    assert len(V) == 6
    assert [list(f) for f in F] == [[0, 1, 2], [3, 4, 5]]
    P, E = merge_curves([np.zeros((3, 3)), np.ones((2, 3))])
    assert len(P) == 5 and np.asarray(E).max() == 4


def test_interpolate_triangle_mesh_reproduces_linear_field():
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]])
    F = np.array([[0, 1, 2]])
    vals = V @ [2.0, 3.0, 0.0] + 1
    q = np.array([[0.2, 0.3, 0.0], [0.5, 0.1, 0.0]])
    np.testing.assert_allclose(interpolate_triangle_mesh(q, V, F, vals), q @ [2.0, 3.0, 0.0] + 1)


# ── measures ─────────────────────────────────────────────────────────────────

def test_planar_grid_is_planar():
    V, F = _grid()
    np.testing.assert_allclose(face_planarity(V, F), 0, atol=1e-12)
    N = compute_face_normals(V, F)
    np.testing.assert_allclose(np.abs(N[:, 2]), 1)
    mesh = Mesh(); mesh.make_mesh(V, F)
    np.testing.assert_allclose(planarity_measure_quad_mesh(mesh), 0, atol=1e-12)


def test_bent_grid_is_not_planar():
    V, F = _grid(z=lambda x, y: x * y)            # hyperbolic paraboloid
    assert np.all(face_planarity(V, F) > 1e-6)


def test_circumcircles_of_squares():
    V, F = _grid(3)
    centers, normals, radii = compute_circumcircles_quad_mesh(V, np.array(F))[:3]
    h = 0.5
    np.testing.assert_allclose(np.ravel(radii), h * np.sqrt(2) / 2)
    np.testing.assert_allclose(np.asarray(centers)[0], [h / 2, h / 2, 0])


# ── mesh areas (from the former hanan/geometry/test.py script) ───────────────

def test_vertex_areas_and_mass_matrix():
    m = Mesh()
    m.make_mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], [[0, 1, 2], [0, 2, 3]])
    A = m.vertex_areas()
    np.testing.assert_allclose(A.sum(), 1.0)
    np.testing.assert_allclose(A, [1 / 3, 1 / 6, 1 / 3, 1 / 6])
    M = m.mass_matrix()
    np.testing.assert_allclose(M.diagonal(), A)
    D = M.toarray(); np.fill_diagonal(D, 0)
    np.testing.assert_allclose(D, 0)


def test_quad_grid_vertex_areas():
    V, F = _grid(3)                                   # 2×2 quads of side 0.5
    m = Mesh(); m.make_mesh(V, F)
    A = m.vertex_areas()
    np.testing.assert_allclose(A[[0, 2, 6, 8]], 0.0625)
    np.testing.assert_allclose(A[[1, 3, 5, 7]], 0.125)
    np.testing.assert_allclose(A[4], 0.25)
    np.testing.assert_allclose(A.sum(), m.face_areas().sum())


# ── PH-CPF planarity measure and deviation from a reference mesh ─────────────

def _phcpf_planarity_general(V, F):
    """Line-by-line port of planarity_general in the PH-CPF code (MESHP.m), in percent."""
    out = np.zeros(len(F))
    for fid, f in enumerate(F):
        dim = len(f)
        quad = np.zeros(dim)
        for d in range(dim):
            v1, v2, v3, v4 = (V[f[(d + s) % dim]] for s in range(4))
            diag_cross = np.cross(v3 - v1, v4 - v2)
            denom = np.linalg.norm(diag_cross) * (np.linalg.norm(v3 - v1) + np.linalg.norm(v4 - v2)) / 2.0
            quad[d] = diag_cross @ (v2 - v1) / denom if abs(denom) > 10e-10 else 0.0
        out[fid] = 100 * np.sqrt(np.linalg.norm(quad) ** 2 / dim)
    return out


def test_planarity_measure_matches_phcpf_code():
    from hanan.geometry.measures import planarity_measure
    rng = np.random.default_rng(3)
    for d in (4, 5, 6, 7):
        t = np.linspace(0, 2 * np.pi, d, endpoint=False)
        V = np.c_[np.cos(t), np.sin(t), np.zeros(d)] + 0.05 * rng.standard_normal((d, 3))
        F = [list(range(d))]
        np.testing.assert_allclose(100 * planarity_measure(V, F), _phcpf_planarity_general(V, F), atol=1e-12)


def test_planarity_measure_planar_folded_and_bent():
    from hanan.geometry.measures import planarity_measure
    t = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    hexagon = np.c_[np.cos(t), np.sin(t), np.zeros(6)]
    folded = hexagon[[0, 3, 1, 4, 2, 5]]                     # same plane, outline crosses itself
    bent = hexagon.copy(); bent[2, 2] = 0.1
    F = [list(range(6))]
    assert planarity_measure(hexagon, F)[0] == pytest.approx(0, abs=1e-12)
    assert planarity_measure(folded, F)[0] == pytest.approx(0, abs=1e-12)
    assert planarity_measure(bent, F)[0] > 1e-3
    assert planarity_measure(hexagon[:3], [[0, 1, 2]])[0] == 0.0       # triangles are planar


def test_quad_planarity_is_diagonal_distance_over_mean_diagonal():
    from hanan.geometry.measures import planarity_measure, quadruplet_planarity
    q = np.random.default_rng(5).standard_normal((4, 3))
    d1, d2 = q[2] - q[0], q[3] - q[1]
    n = np.cross(d1, d2)
    expected = abs((q[1] - q[0]) @ n) / np.linalg.norm(n) / (0.5 * (np.linalg.norm(d1) + np.linalg.norm(d2)))
    assert quadruplet_planarity(*q) == pytest.approx(expected)
    assert planarity_measure(q, [[0, 1, 2, 3]])[0] == pytest.approx(expected)   # all 4 quadruplets agree


def test_deviation_from_reference():
    from hanan.geometry.measures import deviation_from_reference
    M_V = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], dtype=float)   # 2 x 1 rectangle
    M_F = [[0, 1, 2, 3]]
    diameter = np.sqrt(5.0)
    P = np.array([[1.0, 0.5, 0.0], [1.0, 0.5, 0.3], [3.0, 0.5, 0.0]])
    np.testing.assert_allclose(deviation_from_reference(P, M_V, M_F), [0.0, 0.3 / diameter, 1.0 / diameter])
