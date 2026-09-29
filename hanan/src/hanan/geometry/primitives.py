"""
Points, lines, planes, circles and spheres: distances, projections,
reflections, intersections, circle fits, sphere inversion.
"""

import numpy as np
from hanan.geometry.algebraic import (
    orth_proj,
    proj,
    unit,
    vec_dot,
)


def distance_point_plane(point, normal, plane_distance):
    """
    Signed distance from a point to the plane normal · x + h = 0.

    Same as dist_point_plane (kept for existing callers).

    Args:
        point: Query point (3,).
        normal: Plane normal (3,).
        plane_distance: Plane offset h in n · x + h = 0.

    Returns:
        Signed distance as a float.
    """

    return point @ unit(normal) + plane_distance


def circle_3pts(p1, p2, p3):
    """
    Circumcircle of three points (or batches of three points).

    Args:
        p1: First point (3,) or (N, 3).
        p2: Second point (3,) or (N, 3).
        p3: Third point (3,) or (N, 3).

    Returns:
        center: Circumcenter (N, 3).
        normal: Circle plane normal (N, 3).
        radius: Circumradius (N,).
    """
    if len(p1.shape) == 1:
        p1 = p1[None, :]
    if len(p2.shape) == 1:
        p2 = p2[None, :]
    if len(p3.shape) == 1:
        p3 = p3[None, :]

    u1 = unit(p2 - p1)
    u2 = unit(np.cross(p3 - p1, u1))
    u3 = np.cross(u2, u1)

    bx = np.sum((p2 - p1) * u1, axis=1)
    cx = np.sum((p3 - p1) * u1, axis=1)
    cy = np.sum((p3 - p1) * u3, axis=1)
    h = ((cx - bx/2)**2 + cy**2 - (bx/2)**2) / (2 * cy)
    bx /= 2

    radius = np.linalg.norm(np.vstack((bx, h)), axis=0)
    center = p1 + bx[:, None] * u1 + h[:, None] * u3
    return center, u2, radius


def plane_plane_intersection(n1, d1, n2, d2):
    """
    Line of intersection of two planes n1 · x + d1 = 0 and n2 · x + d2 = 0.

    Args:
        n1: Normal of plane 1 (3,).
        d1: Offset of plane 1 (scalar h in n · x + h = 0), or a point on the plane (3,).
        n2: Normal of plane 2 (3,).
        d2: Offset of plane 2 (scalar h in n · x + h = 0), or a point on the plane (3,).

    Returns:
        (point_on_line, direction) tuple, or (None, None) if planes are parallel.
    """
    n1 = unit(n1)
    n2 = unit(n2)
    
    # Check if planes are parallel
    if np.isclose(vec_dot(n1, n2), 1.0):
        return None  # No intersection, planes are parallel
    
    # --- turn the 2nd parameter into the value of n · x on the plane ---------
    def _distance(n, d_or_p):
        arr = np.asarray(d_or_p)
        if arr.ndim == 0:                  # scalar offset h: n · x = -h
            return -float(arr)
        if arr.shape == (3,):              # 3-vector → treat as point
            return float(np.dot(n, arr))
        raise ValueError("distance must be a scalar or a 3-vector point")

    d1 = _distance(n1, d1)
    d2 = _distance(n2, d2)

    
    # Direction of the line of intersection
    direction = np.cross(n1, n2)
    
    # Point on the line of intersection
    A = np.array([[n1[0], n1[1], n1[2]],
                  [n2[0], n2[1], n2[2]],
                  [direction[0], direction[1], direction[2]]])
    
    b = np.array([d1, d2, 0])
    
    point = np.linalg.solve(A, b)
    
    return point, unit(direction)


def clip_line_to_convex_face(point, direction, verts, *, eps=1e-12):
    """
    Sutherland-Hodgman clipping of line point + t*direction against a convex polygon.

    Args:
        point: 3-vector lying in the face plane.
        direction: 3-vector lying in the face plane (non-zero).
        verts: (M, 3) array of face vertices in CCW or CW order.
        eps: Tolerance for zero/parallel detection (default: 1e-12).

    Returns:
        (t_min, t_max) parameter interval, or (None, None) if the line misses the face.
    """
    p = np.asarray(point, dtype=float)
    d = np.asarray(direction, dtype=float)
    if np.linalg.norm(d) < eps:
        raise ValueError("direction must be non-zero")

    verts = np.asarray(verts, dtype=float)
    m = len(verts)
    if m < 3:
        raise ValueError("a face needs at least three vertices")

    # ----------------------------------------------------------------------
    # 1. face normal  (not necessarily unit, but consistent)
    n = np.cross(verts[1]-verts[0], verts[2]-verts[0])
    if np.linalg.norm(n) < eps:
        raise ValueError("vertices are collinear")
    # ----------------------------------------------------------------------
    # 2. clip against every edge half-plane  (Sutherland–Hodgman in 1-D)
    t_min, t_max = -np.inf, np.inf

    # Pre-compute a point strictly inside for orientation (face centroid)
    inside_ref = verts.mean(axis=0)

    for i in range(m):
        a, b = verts[i], verts[(i+1) % m]
        e = b - a                           # edge vector in the plane
        n_edge = np.cross(n, e)             # ⟂ to plane *and* edge
        # make n_edge point to the interior
        if np.dot(n_edge, inside_ref - a) > 0:
            n_edge = -n_edge

        num   = np.dot(n_edge, p - a)
        denom = np.dot(n_edge, d)

        if abs(denom) < eps:                # line ‖ edge
            if num > 0:                     # outside this half-plane
                return None, None                 # → no intersection at all
            else:
                continue                    # no constraint from this edge

        t_hit = -num / denom                # where g(t)=0
        if denom > 0:                       # we exit the half-plane
            t_max = min(t_max, t_hit)
        else:                               # we enter the half-plane
            t_min = max(t_min, t_hit)

        if t_min - t_max > eps:             # interval has vanished
            return None, None

    return t_min, t_max                     # segment is  p + t d


def reflect_point_line(point, line_point, line_direction):
    """
    Reflect point(s) across a line defined by a point and a direction.

    The reflection is 2·f − p, where f is the foot of p on the line.

    Args:
        point: Point to reflect (3,), or points (N, 3).
        line_point: A point on the line (3,).
        line_direction: Direction of the line (3,); need not be unit length.

    Returns:
        Reflected point (3,), or (N, 3) for batched input.
    """
    point = np.asarray(point, dtype=float)
    line_point = np.asarray(line_point, dtype=float)
    d = unit(np.asarray(line_direction, dtype=float))
    foot = line_point + np.multiply.outer((point - line_point) @ d, d)
    return 2.0 * foot - point


def reflect_point_plane(point, plane_normal, plane_distance):
        """
        Reflect a point across the plane n · x + h = 0.

        Args:
            point: Point to reflect (3,).
            plane_normal: Unit normal of the plane (3,).
            plane_distance: Plane offset h in n · x + h = 0.

        Returns:
            Reflected point (3,).
        """
        # Compute the distance from the point to the plane
        distance = np.dot(point, plane_normal) + plane_distance

        # Reflect the point across the plane
        reflected_point = point - 2.0 * distance * plane_normal

        return reflected_point


def plane_normal(points: np.ndarray) -> np.ndarray:
    """
    Compute the unit normal of a plane through N >= 3 points.

    With exactly 4 points they must be in cyclic (quad) order: the normal is the
    cross product of the diagonals p0→p2 and p1→p3.

    - N == 3: cross product of the two edge vectors from the first point.
    - N == 4: cross product of the two diagonals (robust for quads).
    - N  > 4: SVD best-fit normal (least-squares plane).

    Args:
        points: (N, 3) array of 3-D points.

    Returns:
        Unit normal vector, shape (3,).

    Raises:
        ValueError: if fewer than 3 points or points are not 3-D.
    """
    pts = np.asarray(points, dtype=float)

    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"Expected shape (N, 3), got {pts.shape}")
    if len(pts) < 3:
        raise ValueError("Need at least 3 points to define a plane.")

    n = len(pts)

    if n == 3:
        normal = np.cross(pts[1] - pts[0], pts[2] - pts[0])

    elif n == 4:
        # Cross product of the two diagonals: robust for planar quads
        normal = np.cross(pts[2] - pts[0], pts[3] - pts[1])

    else:
        # SVD best-fit for N > 4
        centered = pts - pts.mean(axis=0)
        _, _, Vt = np.linalg.svd(centered, full_matrices=False)
        normal = Vt[-1]

    norm = np.linalg.norm(normal)
    if norm < 1e-12:
        raise ValueError("Points are collinear — plane normal is undefined.")
    return normal / norm


def dist_point_plane(p, n, h):
    """
    Signed distance from point(s) p to the plane n · x + h = 0.

    Args:
        p: Point (3,) or point cloud (N, 3).
        n: Plane normal (3,).
        h: Plane offset scalar, plane n · x + h = 0.

    Returns:
        Signed distance as a float for single points, or (N,) array for point clouds.
    """
    
    n = unit(n)

    if len(p.shape) == 1:
        return np.dot(p, n) + h
    else:
        # 'ij,j->i': dot each row of p with n, then add the offset
        return np.einsum('ij,j->i', p, n) + h


def project_point_plane(p, n, h):
    """
    Project point(s) p onto the plane n · x + h = 0.

    Args:
        p: Point (3,) or point cloud (N, 3).
        n: Plane normal (3,).
        h: Plane offset scalar, plane n · x + h = 0.

    Returns:
        Projected point(s), same shape as p.
    """
    
    n = unit(n)

    if len(p.shape) == 1:
        d = np.dot(p, n) + h
        return p - d * n
    else:
        d = np.einsum('ij,ij->j',p,n) + h
        return p - orth_proj(d, n)


def clst_point_lines(p1, d1, p2, d2, tol=1e-10):
    """
    Closest points between two lines; returns their intersection when lines are coplanar.

    Args:
        p1: Point on line 1 (3,).
        d1: Direction of line 1 (3,).
        p2: Point on line 2 (3,).
        d2: Direction of line 2 (3,).
        tol: Tolerance for zero/parallel detection (default: 1e-10).

    Returns:
        f1: Closest point on line 1 (3,).
        f2: Closest point on line 2 (3,).
        m: Midpoint of f1 and f2 (3,).
    """
    # Guard against zero direction vectors
    norm_d1 = np.linalg.norm(d1)
    norm_d2 = np.linalg.norm(d2)
    assert norm_d1 > tol, f"d1 is a zero (or near-zero) vector: norm={norm_d1}"
    assert norm_d2 > tol, f"d2 is a zero (or near-zero) vector: norm={norm_d2}"

    d1 = d1 / norm_d1
    d2 = d2 / norm_d2

    # Common perpendicular direction
    n_l = np.cross(d1, d2)
    norm_nl = np.linalg.norm(n_l)

    # Vector connecting base points
    v = p2 - p1

    if norm_nl < tol:
        # Lines are parallel: project p2 onto line 1 as the closest point
        f1 = p1 + np.dot(v, d1) * d1
        f2 = p2
        m  = 0.5 * (f1 + f2)
        return f1, f2, m

    # General case: skew or intersecting (coplanar) lines
    # When coplanar: v · n_l == 0  →  f1 == f2 == intersection point
    norm_nl_sq = norm_nl ** 2
    f1 = p1 + (np.dot(v, np.cross(d2, n_l)) / norm_nl_sq) * d1
    f2 = p2 + (np.dot(v, np.cross(d1, n_l)) / norm_nl_sq) * d2

    m = 0.5 * (f1 + f2)

    return f1, f2, m


def foot_point_line(point, line_point, line_dir):
    """
    Foot (closest point) on a line to a given point.

    Args:
        point: Query point (3,) or (N, 3).
        line_point: A point on the line (3,).
        line_dir: Direction vector of the line (3,); need not be unit length.

    Returns:
        Foot point (3,), or (N, 3) array for batched input.
    """
    d    = line_dir / np.linalg.norm(line_dir)
    diff = np.asarray(point) - line_point
    if diff.ndim == 1:
        return line_point + np.dot(diff, d) * d
    return line_point + (diff @ d)[:, None] * d


def dist_point_line(point, line_point, line_dir):
    """
    Distance from a point to a line defined by a point and direction.

    Args:
        point: Query point (3,) or (N, 3).
        line_point: A point on the line (3,).
        line_dir: Direction vector of the line (3,); need not be unit length.

    Returns:
        Scalar distance, or (N,) array for batched input.
    """
    d = line_dir / np.linalg.norm(line_dir)
    diff = np.asarray(point) - line_point
    if diff.ndim == 1:
        return np.linalg.norm(diff - np.dot(diff, d) * d)
    return np.linalg.norm(diff - (diff @ d)[:, None] * d, axis=1)


def line_plane_inter(line, plane):
    """
    Intersection of a line with a plane.

    Args:
        line: (p, v) tuple — point on the line (3,) and direction (3,).
        plane: (n, h) tuple — plane n · x + h = 0 (normal (3,) and offset scalar).

    Returns:
        Intersection point (3,), or None if the line is parallel to the plane.
    """
    p, v = line
    n, h = plane

    # Parallel line: no intersection
    if np.isclose(n@v, 0):
        return None
    # n·(p + t v) + h = 0  ⇒  t = -(n·p + h) / (n·v)
    return p - (n@p + h)/(n@v) * v


def reflect_plane(n, h, m, j):
    """
    Reflect plane (n, h) across mirror plane (m, j).

    Planes are n · x + h = 0 (n unit normal). The reflection of a point p across
    the mirror plane m · x + j = 0 is
        p' = p - 2*(m·p + j)*m
    Applying this to the foot point p0 = -h*n (on the original plane) and to the
    direction n gives the reflected plane.

    Args:
        n: Normal of the plane to reflect (3,) or (N, 3).
        h: Offset of the plane to reflect, scalar or (N,).
        m: Normal of the mirror plane (3,), unit vector.
        j: Offset of the mirror plane, scalar.

    Returns:
        n_r: Reflected plane normal, same shape as n.
        h_r: Reflected plane offset, same shape as h.
    """

    m = unit(np.asarray(m, dtype=float))
    n = np.asarray(n, dtype=float)
    h = np.asarray(h, dtype=float)

    batch = n.ndim == 2

    if batch:
        # n: (N, 3), h: (N,)
        # n_r = n - 2*(n·m)*m
        dot_nm = np.einsum('ij,j->i', n, m)          # (N,)
        n_r = n - 2 * dot_nm[:, None] * m            # (N, 3)
        # foot point p0 = -h * n; its reflection: p0' = p0 - 2*(m·p0 + j)*m
        p0 = -h[:, None] * n                                  # (N, 3)
        dot_mp0 = np.einsum('ij,j->i', p0, m)                 # (N,)
        p0_r = p0 - 2 * (dot_mp0 + j)[:, None] * m
        h_r = -np.einsum('ij,ij->i', p0_r, n_r)
    else:
        # n: (3,), h: scalar
        n_r = n - 2 * np.dot(n, m) * m
        p0 = -h * n
        p0_r = p0 - 2 * (np.dot(m, p0) + j) * m
        h_r = -np.dot(p0_r, n_r)

    return n_r, h_r


def reflect_point(p, n, h):
    """
    Reflect point(s) p across the plane n · x + h = 0.

    Args:
        p: Point (3,) or point cloud (N, 3).
        n: Plane unit normal (3,).
        h: Plane offset scalar, plane n · x + h = 0.

    Returns:
        Reflected point(s), same shape as p.
    """

    n = unit(np.asarray(n, dtype=float))
    p = np.asarray(p, dtype=float)

    if p.ndim == 1:
        return p - 2 * (np.dot(p, n) + h) * n
    else:
        dist = np.einsum('ij,j->i', p, n) + h   # (N,)
        return p - 2 * dist[:, None] * n


def circle_3d(center, normal, radius, pts=100):
    """
    Sample points on a 3-D circle.

    Args:
        center: Circle center (3,).
        normal: Circle plane normal (3,).
        radius: Circle radius.
        pts: Number of sample points (default: 100).

    Returns:
        Circle points (pts, 3).
    """
    from hanan.geometry.algebraic import unit, proj
    normal = np.asarray(normal).flatten()
    u1 = unit(normal)
    if np.allclose(u1, np.array([1,0,0])) or np.isclose(abs(u1[2]), 1.0):
        # z cannot serve as the helper axis when the normal is (anti)parallel to it
        u2 = unit(np.array([0,1,0]) - proj(np.array([0,1,0]), u1))
    else:
        u2 = unit(np.array([0,0,1]) - proj(np.array([0,0,1]), u1))
    u3 = np.cross(u1, u2)
    theta = np.linspace(0, 2 * np.pi, pts)
    return center + radius * (np.cos(theta)[:, None] * u2 + np.sin(theta)[:, None] * u3)


def circular_arc(center, normal, radius, p0, p1, num_points=20):
    """
    Points along the arc from p0 to p1 on a circle.

    Args:
        center: Circle center (3,).
        normal: Circle plane normal (3,).
        radius: Circle radius.
        p0: Start point on the circle (3,).
        p1: End point on the circle (3,).
        num_points: Number of sample points (default: 20).

    Returns:
        Arc points (num_points, 3).
    """
    from hanan.geometry.algebraic import unit, proj

    if np.isclose(radius, 0):
        return [center]

    v1 = unit(p0 - center)
    v2 = unit(p1 - center)
    
    # Project v2 and v1 to the plane
    v2 = unit(v2 - proj(v2, normal))
    v1 = unit(v1 - proj(v1, normal))

    angle = np.arccos(np.dot(v1, v2)) if not np.isclose(np.dot(v1, v2), 1) else 0
    u2 = unit(v2 - proj(v2, v1) - proj(v2, normal))
    theta = np.linspace(0, angle, num_points)

    return center + radius * (np.cos(theta)[:, None] * v1 + np.sin(theta)[:, None] * u2)


def plane_patch(p0, n, size=(1, 1)):
    """
    Build a finite rectangular plane patch as a mesh.

    Args:
        p0:   Center of the patch (3,).
        n:    Plane normal (3,).
        size: (width, height) of the patch (default: (1, 1)).

    Returns:
        vertices: (4, 3) corner positions.
        faces:    [[0, 1, 2, 3]] single quad face.
    """
    from hanan.geometry.algebraic import unit, orth_proj
    n = unit(np.asarray(n, dtype=float))
    aux = orth_proj(n + np.array([1.0, 0.0, 0.0]), n)
    if np.linalg.norm(aux) < 1e-8:
        # n is ±x: the x helper projects to zero, use y instead
        aux = orth_proj(np.array([0.0, 1.0, 0.0]), n)
    v1 = unit(aux) * size[0]
    v2 = unit(np.cross(n, v1 / size[0])) * size[1]
    vertices = np.array([p0 + v1 + v2, p0 + v1 - v2,
                         p0 - v1 - v2, p0 - v1 + v2])
    return vertices, [[0, 1, 2, 3]]


def project_to_sphere(vertices, center, radius=1):
    """
    Project vertices onto a sphere by normalising each offset from center.

    Args:
        vertices: Vertex positions (V, 3).
        center: Sphere center (3,).
        radius: Target sphere radius (default: 1).

    Returns:
        Projected vertex positions (V, 3).
    """

    return center + radius * unit(vertices-center)


def sphere_inversion(points, center, radius):
    """
    Möbius inversion of points with respect to a sphere.

    Args:
        points: Points to invert (N, 3).
        center: Sphere center (3,).
        radius: Sphere radius.

    Returns:
        Inverted points (N, 3).
    """

    # Compute the distance from the center
    d = np.linalg.norm(points - center, axis=1)

    # Compute the inverted points
    inverted_points = center + (radius**2 / d**2)[:, None] * (points - center)

    return inverted_points


