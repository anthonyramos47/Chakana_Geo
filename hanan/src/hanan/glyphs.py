"""
Glyphs — mesh data for drawing geometric objects.

Every function returns plain arrays and draws nothing:

    surfaces -> (V, F)   V (n, 3) float, F (m, k) int
    curves   -> (P, E)   P (n, 3) float, E (m, 2) int

so the result goes to any viewer, e.g. kayviz::

    import kayviz as kv
    from hanan import glyphs
    kv.register_surface_mesh("Sphere", *glyphs.sphere(c, r))
    kv.register_curve_network("Contact circles", *glyphs.circles(C, N, R))

The plural functions (``spheres``, ``circles``, ``cone_strips``) merge many glyphs
into one mesh, which is much faster to display than one object per glyph.
"""

from functools import lru_cache

import numpy as np

from hanan.geometry.conical import oriented_cone
from hanan.geometry.primitives import plane_patch as _plane_patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _basis(normals):
    """Orthonormal (u, v) spanning the plane orthogonal to each normal (..., 3)."""
    n = _unit(normals)
    # helper axis: the coordinate axis least aligned with n, never parallel to it
    helper = np.zeros_like(n)
    np.put_along_axis(helper, np.argmin(np.abs(n), axis=-1)[..., None], 1.0, axis=-1)
    u = _unit(np.cross(n, helper))
    return u, np.cross(n, u)


def _circle_points(centers, normals, radii, n):
    """Points of closed circles, without repeating the first point: (k, n, 3)."""
    C = np.atleast_2d(np.asarray(centers, dtype=float))
    N = np.atleast_2d(np.asarray(normals, dtype=float))
    R = np.atleast_1d(np.asarray(radii, dtype=float))
    u, v = _basis(N)
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return (C[:, None, :]
            + R[:, None, None] * (np.cos(t)[None, :, None] * u[:, None, :]
                                  + np.sin(t)[None, :, None] * v[:, None, :]))


def _ring_edges(k, n):
    """Edges of k closed rings of n points each, stored one ring after another."""
    i = np.arange(n)
    ring = np.stack([i, np.roll(i, -1)], axis=1)
    return (ring[None] + n * np.arange(k)[:, None, None]).reshape(-1, 2)


@lru_cache(maxsize=None)
def _unit_icosphere(subdivisions):
    t = (1.0 + 5 ** 0.5) / 2.0
    V = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
         [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]
    F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9],
         [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2],
         [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10],
         [8, 6, 7], [9, 8, 1]]
    V = [list(_unit(v)) for v in V]
    for _ in range(subdivisions):
        cache, F2 = {}, []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                cache[key] = len(V)
                V.append(list(_unit((np.asarray(V[a]) + np.asarray(V[b])) / 2)))
            return cache[key]

        for a, b, c in F:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            F2 += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        F = F2
    V, F = np.asarray(V), np.asarray(F)
    V.setflags(write=False); F.setflags(write=False)
    return V, F


# ── spheres ───────────────────────────────────────────────────────────────────

def sphere(center, radius, subdivisions=3):
    """
    Triangle mesh of a sphere (subdivided icosahedron).

    Args:
        center:       Sphere center (3,).
        radius:       Sphere radius; the sign is ignored (oriented spheres).
        subdivisions: Subdivision levels; 20 * 4**subdivisions triangles (default 3: 1280).

    Returns:
        V (n, 3), F (m, 3).
    """
    U, F = _unit_icosphere(subdivisions)
    return np.asarray(center, dtype=float) + abs(radius) * U, F.copy()


def spheres(centers, radii, subdivisions=2):
    """
    Many spheres merged into one triangle mesh.

    Args:
        centers:      (k, 3).
        radii:        (k,); signs are ignored.
        subdivisions: Per sphere (default 2: 320 triangles each).

    Returns:
        V (k*n, 3), F (k*m, 3) — sphere i owns faces [i*m, (i+1)*m).
    """
    U, F = _unit_icosphere(subdivisions)
    C = np.atleast_2d(np.asarray(centers, dtype=float))
    R = np.abs(np.atleast_1d(np.asarray(radii, dtype=float)))
    V = (C[:, None, :] + R[:, None, None] * U[None]).reshape(-1, 3)
    F = (F[None] + len(U) * np.arange(len(C))[:, None, None]).reshape(-1, 3)
    return V, F


# ── curves ────────────────────────────────────────────────────────────────────

def circle(center, normal, radius, n=64):
    """
    Closed polyline of a circle in 3-D.

    Args:
        center: (3,).
        normal: Normal of the circle's plane (3,).
        radius: Circle radius.
        n:      Number of points (default 64); the first point is not repeated.

    Returns:
        P (n, 3), E (n, 2).
    """
    return _circle_points(center, normal, radius, n)[0], _ring_edges(1, n)


def circles(centers, normals, radii, n=64):
    """
    Many circles merged into one curve network.

    Returns:
        P (k*n, 3), E (k*n, 2) — circle i owns points [i*n, (i+1)*n).
    """
    P = _circle_points(centers, normals, radii, n)
    return P.reshape(-1, 3), _ring_edges(len(P), n)


def polyline(points, closed=False):
    """
    Curve network through ``points`` in order.

    Returns:
        P (n, 3), E (n - 1, 2), or (n, 2) when ``closed``.
    """
    P = np.asarray(points, dtype=float)
    i = np.arange(len(P))
    E = np.stack([i, np.roll(i, -1)], axis=1)
    return P, (E if closed else E[:-1])


def segments(starts, ends):
    """
    Independent line segments starts[i] -> ends[i].

    Returns:
        P (2k, 3), E (k, 2).
    """
    A = np.atleast_2d(np.asarray(starts, dtype=float))
    B = np.atleast_2d(np.asarray(ends, dtype=float))
    k = len(A)
    return np.vstack((A, B)), np.stack([np.arange(k), np.arange(k) + k], axis=1)


def cross_field(points, direction1, direction2, length):
    """
    A cross field as two sets of segments centered at ``points``.

    Args:
        points:     (k, 3).
        direction1: (k, 3), normalized here.
        direction2: (k, 3), normalized here.
        length:     Half-length of each arm.

    Returns:
        ((P1, E1), (P2, E2)) — one curve network per direction.
    """
    X = np.asarray(points, dtype=float)
    d1, d2 = _unit(direction1) * length, _unit(direction2) * length
    return segments(X - d1, X + d1), segments(X - d2, X + d2)


# ── planes ────────────────────────────────────────────────────────────────────

def plane_patch(point, normal, size=(1, 1)):
    """
    Rectangular patch of the plane through ``point`` with normal ``normal``.

    Args:
        point:  Center of the patch (3,).
        normal: Plane normal (3,).
        size:   Half-extents (a, b) along the two in-plane directions.

    Returns:
        V (4, 3), F (1, 4).
    """
    V, F = _plane_patch(np.asarray(point, dtype=float), normal, size)
    return V, np.asarray(F)


def plane(n, h, near=(0.0, 0.0, 0.0), size=(1, 1)):
    """
    Patch of the plane n·x + h = 0, centered at the point of the plane closest to ``near``.

    Returns:
        V (4, 3), F (1, 4).
    """
    n = np.asarray(n, dtype=float)
    q = np.asarray(near, dtype=float)
    center = q - (n @ q + h) / (n @ n) * n
    return plane_patch(center, n, size)


# ── cones ─────────────────────────────────────────────────────────────────────

def cone(apex, axis, half_angle, height, n=32):
    """
    Lateral surface of a cone of revolution (triangle fan, no base).

    Args:
        apex:       (3,).
        axis:       Opening direction (3,).
        half_angle: Half-aperture in radians.
        height:     Distance from the apex to the base along ``axis``.
        n:          Points on the base circle (default 32).

    Returns:
        V (n+1, 3), F (n, 3).
    """
    apex = np.asarray(apex, dtype=float)
    a = _unit(axis)
    base = _circle_points(apex + height * a, a, height * np.tan(half_angle), n)[0]
    i = np.arange(n)
    F = np.stack([np.zeros(n, dtype=int), 1 + i, 1 + (i + 1) % n], axis=1)
    return np.vstack((apex, base)), F


def _cone_strip_rings(ci, ri, cj, rj, n):
    kappai, kappaj, axis, _tip, _angle = oriented_cone(ci, ri, cj, rj)
    if kappai is None or kappaj is None:
        return None
    # both circles share the axis, so they share the basis: quads do not twist
    return _circle_points([kappai[0], kappaj[0]], [axis, axis], [kappai[1], kappaj[1]], n)


def _strip_faces(n, offset=0):
    i = np.arange(n)
    return np.stack([i, (i + 1) % n, n + (i + 1) % n, n + i], axis=1) + offset


def cone_strip(ci, ri, cj, rj, n=32):
    """
    Quad strip of the oriented cone tangent to two oriented spheres, between the
    two contact circles.

    Args:
        ci, cj: Sphere centers (3,).
        ri, rj: Signed sphere radii.
        n:      Points per contact circle (default 32).

    Returns:
        V (2n, 3), F (n, 4).

    Raises:
        ValueError: if no oriented cone touches both spheres.
    """
    rings = _cone_strip_rings(ci, ri, cj, rj, n)
    if rings is None:
        raise ValueError("no oriented cone is tangent to both spheres")
    return rings.reshape(-1, 3), _strip_faces(n)


def cone_strips(ci, ri, cj, rj, n=32):
    """
    Cone strips for many sphere pairs (ci[k], ri[k]) - (cj[k], rj[k]), merged.

    Pairs without an oriented cone are skipped.

    Returns:
        V, F, kept — ``kept`` holds the indices k of the pairs that were drawn;
        pair kept[m] owns faces [m*n, (m+1)*n).
    """
    Vs, kept = [], []
    for k, args in enumerate(zip(ci, ri, cj, rj)):
        rings = _cone_strip_rings(*args, n)
        if rings is not None:
            Vs.append(rings.reshape(-1, 3))
            kept.append(k)
    if not Vs:
        return np.zeros((0, 3)), np.zeros((0, 4), dtype=int), np.array(kept, dtype=int)
    F = np.vstack([_strip_faces(n, 2 * n * m) for m in range(len(Vs))])
    return np.vstack(Vs), F, np.array(kept, dtype=int)
