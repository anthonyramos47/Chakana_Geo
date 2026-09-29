"""hanan.geometry.primitives — points, lines, planes, circles, spheres."""

import numpy as np
import pytest

from hanan.geometry.primitives import (
    circle_3d,
    circle_3pts,
    circular_arc,
    clip_line_to_convex_face,
    clst_point_lines,
    dist_point_line,
    dist_point_plane,
    distance_point_plane,
    foot_point_line,
    line_plane_inter,
    plane_normal,
    plane_patch,
    plane_plane_intersection,
    project_point_plane,
    project_to_sphere,
    reflect_plane,
    reflect_point,
    reflect_point_line,
    reflect_point_plane,
    sphere_inversion,
)

Z = np.array([0.0, 0.0, 1.0])


def test_point_plane_functions():
    # every plane in hanan is (n, h) with n · x + h = 0; the plane z = 2 is (Z, -2)
    p = np.array([1.0, 2.0, 5.0])
    assert dist_point_plane(p, Z, -2.0) == pytest.approx(3.0)
    assert distance_point_plane(p, Z, -2.0) == pytest.approx(3.0)
    np.testing.assert_allclose(project_point_plane(p, Z, -2.0), [1, 2, 2])
    np.testing.assert_allclose(reflect_point(p, Z, -2.0), [1, 2, -1])
    np.testing.assert_allclose(reflect_point_plane(p, Z, -2.0), [1, 2, -1])


def test_point_plane_batched():
    P = np.array([[0, 0, 1.0], [0, 0, -2.0]])
    np.testing.assert_allclose(dist_point_plane(P, Z, 0.0), [1, -2])
    np.testing.assert_allclose(dist_point_plane(P, Z, -1.0), [0, -3])


def test_line_queries():
    p, q, d = np.array([3.0, 4.0, 0.0]), np.zeros(3), np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(foot_point_line(p, q, d), [3, 0, 0])
    assert dist_point_line(p, q, d) == pytest.approx(4.0)


def test_reflect_point_line():
    p, q, d = np.array([3.0, 4.0, 0.0]), np.zeros(3), np.array([2.0, 0.0, 0.0])   # d need not be unit
    np.testing.assert_allclose(reflect_point_line(p, q, d), [3, -4, 0])
    # batched, oblique line not through the origin; reflecting twice is the identity
    P = np.random.default_rng(3).normal(size=(10, 3))
    q, d = np.array([1.0, -2, 0.5]), np.array([1.0, 1, 2])
    R = reflect_point_line(P, q, d)
    np.testing.assert_allclose(reflect_point_line(R, q, d), P, atol=1e-12)
    np.testing.assert_allclose(dist_point_line(R, q, d), dist_point_line(P, q, d), atol=1e-12)


def test_closest_points_of_skew_lines():
    f1, f2 = clst_point_lines(np.zeros(3), np.array([1.0, 0, 0]),
                              np.array([0, 0, 1.0]), np.array([0, 1.0, 0]))[:2]
    np.testing.assert_allclose(f1, [0, 0, 0], atol=1e-12)
    np.testing.assert_allclose(f2, [0, 0, 1], atol=1e-12)


def test_line_plane_inter():
    x = line_plane_inter((np.array([0, 0, 5.0]), np.array([0, 0, -1.0])), (Z, 1.0))   # plane z = -1
    np.testing.assert_allclose(x, [0, 0, -1])
    # oblique line and plane: the result satisfies n · x + h = 0 and lies on the line
    n, h = np.array([1.0, 2, 2]) / 3, 0.7
    p, v = np.array([0.3, -1, 2]), np.array([0.5, 0.2, -1])
    x = line_plane_inter((p, v), (n, h))
    assert n @ x + h == pytest.approx(0, abs=1e-12)
    np.testing.assert_allclose(np.cross(x - p, v), 0, atol=1e-12)
    assert line_plane_inter((p, np.array([2.0, -1, 0])), (n, h)) is None      # parallel


def test_plane_plane_intersection():
    point, direction = plane_plane_intersection(Z, 0.0, np.array([1.0, 0, 0]), -2.0)   # z = 0, x = 2
    assert abs(np.dot(point, Z)) < 1e-12 and point[0] == pytest.approx(2.0)
    # a point on each plane gives the same line as the scalar offsets
    p2, d2 = plane_plane_intersection(Z, np.array([5.0, 1, 0]), np.array([1.0, 0, 0]), np.array([2.0, 3, 4]))
    np.testing.assert_allclose(np.cross(p2 - point, direction), 0, atol=1e-12)
    assert abs(np.dot(direction, Z)) < 1e-12 and abs(direction[0]) < 1e-12


def test_clip_line_to_square():
    square = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]])
    t = clip_line_to_convex_face(np.array([-1.0, 0.5, 0]), np.array([1.0, 0, 0]), square)
    assert t == pytest.approx((1.0, 2.0))
    assert clip_line_to_convex_face(np.array([-1.0, 5, 0]), np.array([1.0, 0, 0]), square) == (None, None)


def test_reflect_plane():
    n, h = np.array([0.0, 0.6, 0.8]), 1.5
    m, j = np.array([1.0, 0, 0]), 0.3
    n2, h2 = reflect_plane(*reflect_plane(n, h, m, j), m, j)          # involution
    np.testing.assert_allclose(n2, n, atol=1e-12)
    assert h2 == pytest.approx(h)
    # batched: a point of each plane, reflected across the mirror, lies on the reflected plane
    rng = np.random.default_rng(0)
    N = rng.normal(size=(20, 3)); N /= np.linalg.norm(N, axis=1)[:, None]
    H = rng.normal(size=20)
    nr, hr = reflect_plane(N, H, m, j)
    P = -H[:, None] * N + np.cross(N, rng.normal(size=(20, 3)))       # n · p + h = 0
    Pr = np.array([reflect_point(q, m, j) for q in P])
    np.testing.assert_allclose(np.einsum("ij,ij->i", Pr, nr) + hr, 0, atol=1e-12)


def test_circles():
    c, r = np.array([1.0, 2, 3]), 2.0
    pts = circle_3d(c, Z, r, 16)                 # normal ∥ z used to give NaN
    assert not np.isnan(pts).any()
    np.testing.assert_allclose(np.linalg.norm(pts - c, axis=1), r)
    np.testing.assert_allclose((pts - c) @ Z, 0, atol=1e-12)
    center, normal, radius = circle_3pts(pts[0], pts[5], pts[11])[:3]
    np.testing.assert_allclose(np.ravel(center), c, atol=1e-10)
    assert float(np.ravel(radius)[0]) == pytest.approx(r)
    assert abs(abs(np.ravel(normal) @ Z) - 1) < 1e-10
    arc = circular_arc(c, Z, r, pts[0], pts[4], num_points=5)
    assert len(arc) == 5
    np.testing.assert_allclose(np.linalg.norm(arc - c, axis=1), r)


def test_plane_normal_and_patch():
    pts = np.array([[0, 0, 1.0], [1, 0, 1], [1, 1, 1], [0, 1, 1]])      # cyclic order
    assert abs(abs(plane_normal(pts) @ Z) - 1) < 1e-12
    V, F = plane_patch(np.array([0, 0, 2.0]), Z, size=(1, 1))
    assert np.shape(V) == (4, 3) and len(F) == 1
    np.testing.assert_allclose(np.asarray(V)[:, 2], 2.0)


def test_sphere_maps():  # projection onto a sphere and inversion
    rng = np.random.default_rng(1)
    c, r = np.array([0.5, -1.0, 2.0]), 1.5
    P = c + rng.normal(size=(20, 3))
    S = project_to_sphere(P, c, r)
    np.testing.assert_allclose(np.linalg.norm(S - c, axis=1), r)
    # inversion fixes the sphere and is an involution
    np.testing.assert_allclose(sphere_inversion(S, c, r), S, atol=1e-12)
    np.testing.assert_allclose(sphere_inversion(sphere_inversion(P, c, r), c, r), P, atol=1e-10)

