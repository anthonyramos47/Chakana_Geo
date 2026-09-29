"""hanan.glyphs — mesh data for spheres, circles, planes, cones and curves."""

import numpy as np
import pytest

from hanan import glyphs
from hanan.geometry.primitives import plane_patch as primitive_plane_patch

AXES = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
RNG = np.random.default_rng(7)


def _normals():
    return [np.array(a, dtype=float) for a in AXES] + list(RNG.standard_normal((5, 3)))


# ── spheres ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("r", [0.7, -0.7])
def test_sphere_on_surface_and_outward(r):
    c = np.array([1.0, -2.0, 0.5])
    V, F = glyphs.sphere(c, r, subdivisions=2)
    assert F.shape == (20 * 4 ** 2, 3)
    assert np.allclose(np.linalg.norm(V - c, axis=1), abs(r))
    tri = V[F]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    assert np.all(np.einsum("ij,ij->i", normals, tri.mean(axis=1) - c) > 0)


def test_sphere_does_not_share_cached_arrays():
    V, F = glyphs.sphere((0, 0, 0), 1.0, 1)
    V[:] = 0.0; F[:] = 0
    V2, F2 = glyphs.sphere((0, 0, 0), 1.0, 1)
    assert np.allclose(np.linalg.norm(V2, axis=1), 1.0) and F2.max() > 0


def test_spheres_equal_individual_spheres():
    C, R = RNG.standard_normal((4, 3)), np.array([0.1, -0.2, 0.3, 0.4])
    V, F = glyphs.spheres(C, R, subdivisions=1)
    m = 20 * 4
    for i in range(4):
        Vi, Fi = glyphs.sphere(C[i], R[i], subdivisions=1)
        assert np.allclose(V[F[i * m:(i + 1) * m]], Vi[Fi])


# ── curves ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("normal", _normals())
def test_circle_on_circle_no_duplicate(normal):
    c, r, n = np.array([0.3, 0.1, -0.4]), 0.8, 16
    P, E = glyphs.circle(c, normal, r, n)
    assert P.shape == (n, 3) and E.shape == (n, 2)
    assert np.all(np.isfinite(P))
    assert np.allclose(np.linalg.norm(P - c, axis=1), r)
    assert np.allclose((P - c) @ (normal / np.linalg.norm(normal)), 0.0)
    assert not np.allclose(P[0], P[-1])
    assert np.array_equal(E[-1], [n - 1, 0])                       # closed


def test_circles_equal_individual_circles():
    C, N, R = RNG.standard_normal((3, 3)), RNG.standard_normal((3, 3)), np.array([0.5, 1.0, 2.0])
    P, E = glyphs.circles(C, N, R, n=10)
    assert P.shape == (30, 3) and E.shape == (30, 2)
    for i in range(3):
        Pi, Ei = glyphs.circle(C[i], N[i], R[i], n=10)
        assert np.allclose(P[10 * i:10 * (i + 1)], Pi)
        assert np.array_equal(E[10 * i:10 * (i + 1)], Ei + 10 * i)


def test_polyline_and_segments():
    pts = RNG.standard_normal((5, 3))
    assert glyphs.polyline(pts)[1].tolist() == [[0, 1], [1, 2], [2, 3], [3, 4]]
    assert glyphs.polyline(pts, closed=True)[1][-1].tolist() == [4, 0]
    P, E = glyphs.segments(pts[:2], pts[2:4])
    assert np.allclose(P[E[:, 0]], pts[:2]) and np.allclose(P[E[:, 1]], pts[2:4])


def test_cross_field_centered_arms():
    X, d1, d2 = RNG.standard_normal((6, 3)), RNG.standard_normal((6, 3)), RNG.standard_normal((6, 3))
    for (P, E), d in zip(glyphs.cross_field(X, d1, d2, 0.1), (d1, d2)):
        a, b = P[E[:, 0]], P[E[:, 1]]
        assert np.allclose((a + b) / 2, X)
        assert np.allclose(np.linalg.norm(b - a, axis=1), 0.2)
        assert np.allclose(np.cross(b - a, d), 0.0)


# ── planes ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("normal", _normals())
def test_plane_patch_every_normal(normal):
    p = np.array([0.2, 0.4, -1.0])
    V, F = glyphs.plane_patch(p, normal, size=(0.5, 2.0))
    assert np.all(np.isfinite(V)) and F.tolist() == [[0, 1, 2, 3]]
    n = normal / np.linalg.norm(normal)
    assert np.allclose((V - p) @ n, 0.0)
    assert np.allclose(V.mean(axis=0), p)
    assert np.isclose(np.linalg.norm(V[0] - V[1]), 2 * 2.0)
    assert np.isclose(np.linalg.norm(V[1] - V[2]), 2 * 0.5)


def test_primitive_plane_patch_unchanged_for_regular_normals():
    """The ±x fallback must not change patches for normals that already worked."""
    from hanan.geometry.algebraic import unit, orth_proj
    for n in RNG.standard_normal((20, 3)):
        p0, size = RNG.standard_normal(3), (0.3, 0.7)
        nu = unit(n)
        v1 = unit(orth_proj(nu + np.array([1.0, 0.0, 0.0]), nu)) * size[0]   # formula before the fix
        v2 = unit(np.cross(nu, v1 / size[0])) * size[1]
        old = np.array([p0 + v1 + v2, p0 + v1 - v2, p0 - v1 - v2, p0 - v1 + v2])
        assert np.allclose(primitive_plane_patch(p0, n, size)[0], old)


def test_plane_nh():
    n, h, near = np.array([1.0, 2.0, 2.0]), -3.0, np.array([5.0, -1.0, 0.0])
    V, _ = glyphs.plane(n, h, near, size=(1, 1))
    assert np.allclose(V @ n + h, 0.0)
    c = V.mean(axis=0)
    assert np.allclose(np.cross(near - c, n), 0.0)                  # center = closest point


# ── cones ─────────────────────────────────────────────────────────────────────

def test_cone_fan():
    apex, axis, theta, height, n = np.array([0.0, 0.0, 1.0]), np.array([0, 0, -2.0]), 0.4, 1.5, 12
    V, F = glyphs.cone(apex, axis, theta, height, n)
    assert V.shape == (n + 1, 3) and F.shape == (n, 3)
    assert np.all(F[:, 0] == 0)
    base = V[1:]
    assert np.allclose(base[:, 2], apex[2] - height)
    assert np.allclose(np.linalg.norm(base[:, :2], axis=1), height * np.tan(theta))


def test_cone_strip_contact_circles_on_spheres():
    ci, ri, cj, rj, n = np.zeros(3), 0.5, np.array([2.0, 0.3, 0.1]), 0.8, 16
    V, F = glyphs.cone_strip(ci, ri, cj, rj, n)
    assert V.shape == (2 * n, 3) and F.shape == (n, 4)
    assert np.allclose(np.linalg.norm(V[:n] - ci, axis=1), abs(ri))
    assert np.allclose(np.linalg.norm(V[n:] - cj, axis=1), abs(rj))
    # quads do not twist: rulings V[k] -> V[n+k] are parallel to the cone's generators
    rul = V[n:] - V[:n]
    assert np.allclose(np.linalg.norm(rul, axis=1), np.linalg.norm(rul[0]))


def test_cone_strip_nested_spheres():
    with pytest.raises(ValueError):
        glyphs.cone_strip(np.zeros(3), 2.0, np.array([0.1, 0, 0]), 0.5)


def test_cone_strips_skip_invalid_pairs():
    ci = np.array([[0, 0, 0], [0, 0, 0], [5, 0, 0]], dtype=float)
    cj = np.array([[2, 0, 0], [0.1, 0, 0], [7, 1, 0]], dtype=float)
    ri, rj = np.array([0.5, 2.0, 0.3]), np.array([0.8, 0.5, 0.2])
    V, F, kept = glyphs.cone_strips(ci, ri, cj, rj, n=8)
    assert kept.tolist() == [0, 2]
    assert V.shape == (2 * 16, 3) and F.shape == (16, 4) and F.max() == 31
    V2, _ = glyphs.cone_strip(ci[2], ri[2], cj[2], rj[2], n=8)
    assert np.allclose(V[16:], V2)
