"""hanan.geometry.conical, hanan.geometry.lie and hanan.optimization.indexing."""

import numpy as np
import pytest

from hanan.geometry.conical import (
    compute_cone_axes,
    cone_axis_from_planes,
    cone_strip_mesh,
    half_angle_rotational_cone,
    oriented_cone,
)
from hanan.geometry.lie import (
    lie_inner_prod,
    map_lie_s_to_sphere,
    normalize_lie_sphere,
    set_lie_coordinates,
)
from hanan.geometry.mesh import Mesh
from hanan.optimization.indexing import interleave_indices_dim


# ── cones ────────────────────────────────────────────────────────────────────

def test_oriented_cone_touches_both_spheres():
    ci, ri = np.zeros(3), 1.0
    cj, rj = np.array([4.0, 0, 0]), 0.5
    kappai, kappaj, axis, tip, angle = oriented_cone(ci, ri, cj, rj)
    np.testing.assert_allclose(abs(np.ravel(axis) @ [1, 0, 0]), 1)
    # contact circles lie on their spheres: |center - c|² + radius² = r²
    for (cc, cr), c, r in ((kappai, ci, ri), (kappaj, cj, rj)):
        assert np.sum((np.ravel(cc) - c) ** 2) + float(cr) ** 2 == pytest.approx(r ** 2)
    V, F = cone_strip_mesh(ci, ri, cj, rj, n=12)
    assert len(V) == 24 and len(F) == 12


def test_cone_axis_from_tangent_plane_normals():
    alpha = 0.4                                   # normals make angle π/2 - α with the axis
    t = np.linspace(0, 2 * np.pi, 7, endpoint=False)
    normals = np.column_stack([np.cos(alpha) * np.cos(t), np.cos(alpha) * np.sin(t),
                               np.full_like(t, np.sin(alpha))])
    ax = cone_axis_from_planes(normals)
    assert abs(abs(ax @ [0, 0, 1]) - 1) < 1e-10
    half = half_angle_rotational_cone(ax * np.sign(ax[2]), normals)
    assert half == pytest.approx(np.pi / 2 - alpha) or half == pytest.approx(alpha)


def test_compute_cone_axes_on_rotational_mesh():
    # rotational quad mesh (meridians × parallels) is conical
    nu, nv = 12, 5
    u = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v = np.linspace(0.3, 1.2, nv)
    V = np.array([[(2 + np.cos(b)) * np.cos(a), (2 + np.cos(b)) * np.sin(a), np.sin(b)]
                  for b in v for a in u])
    F = [[j * nu + i, j * nu + (i + 1) % nu, (j + 1) * nu + (i + 1) % nu, (j + 1) * nu + i]
         for j in range(nv - 1) for i in range(nu)]
    mesh = Mesh(); mesh.make_mesh(V, F)
    axes, angles = compute_cone_axes(mesh)
    inner = mesh.inner_vertices()
    assert len(inner) > 0
    np.testing.assert_allclose(np.linalg.norm(axes[inner], axis=1), 1, atol=1e-8)
    assert np.all((angles[inner] > 0) & (angles[inner] <= np.pi / 2 + 1e-9))
    # by symmetry every axis lies in its meridian plane (no azimuthal component)
    az = np.column_stack([-np.sin(np.arctan2(V[:, 1], V[:, 0])), np.cos(np.arctan2(V[:, 1], V[:, 0])),
                          np.zeros(len(V))])
    np.testing.assert_allclose(np.sum(axes[inner] * az[inner], axis=1), 0, atol=1e-8)


# ── Lie sphere geometry ──────────────────────────────────────────────────────

def _lie(c, r):
    # same convention as lie.py: point spheres are set_lie_coordinates(y, 1, y·y, 0)
    c = np.asarray(c, float)
    return normalize_lie_sphere(set_lie_coordinates(c, 1.0, c @ c - r * r, r))


def test_lie_sphere_round_trip():
    c, r = np.array([1.0, -2, 0.5]), 0.75
    c2, r2 = map_lie_s_to_sphere(_lie(c, r))
    np.testing.assert_allclose(c2, c)
    assert abs(r2) == pytest.approx(r)


def test_lie_quadric_and_oriented_contact():
    s1 = _lie([0, 0, 0], 1.0)
    s2 = _lie([3, 0, 0], 2.0)          # externally tangent, oriented contact (r1 + r2 = d)
    s3 = _lie([5, 0, 0], 1.0)          # disjoint
    assert lie_inner_prod(s1, s1) == pytest.approx(0, abs=1e-12)
    # oriented contact ⇔ Lie product 0; which orientation touches is a sign convention
    assert min(abs(lie_inner_prod(s1, s2)), abs(lie_inner_prod(s1, _lie([3, 0, 0], -2.0)))) < 1e-12
    assert abs(lie_inner_prod(s1, s3)) > 1e-3


# ── optimizer indexing ───────────────────────────────────────────────────────

def test_interleave_indices_dim():
    np.testing.assert_array_equal(interleave_indices_dim(np.array([0, 2]), 3), [0, 1, 2, 6, 7, 8])
