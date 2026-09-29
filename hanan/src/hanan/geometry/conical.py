"""
Cones of revolution and conical meshes: cones tangent to sphere pairs,
cone strips, vertex cone axes and curvature spheres of conical meshes.
"""

import numpy as np
from hanan.geometry.algebraic import unit
from hanan.geometry.primitives import (
    circle_3d,
    circle_3pts,
    clst_point_lines,
    dist_point_plane,
)


def oriented_cone(ci, ri, cj, rj):
    """
    Oriented cone tangent to two spheres.

    Args:
        ci: Center of sphere i (3,).
        ri: Radius of sphere i.
        cj: Center of sphere j (3,).
        rj: Radius of sphere j.

    Returns:
        kappai: Contact circle on sphere i as (center, radius).
        kappaj: Contact circle on sphere j as (center, radius).
        axis: Cone axis unit vector (3,).
        tip: Cone apex (3,).
        angle: Half-aperture angle in radians.
    """



    # Vector between centers
    cn = unit(cj - ci)
    d  = np.linalg.norm(cj - ci)

    if d**2 < (ri - rj)**2:
        print("Spheres are nested; no cone possible")
        return None, None, None, None, None

    factor = (ri - rj)/d 

    discriminant = np.sqrt(d**2 - (ri - rj)**2) # Tangential distance

    ki = ci + factor * ri * cn  
    kj = cj + factor * rj * cn

    ti = np.abs(ri)/d * discriminant
    tj = np.abs(rj)/d * discriminant

    if np.isclose(np.abs(ri - rj), 0): 
        tip = None
        angle = None
    else:
        tip = ci + (ri/(ri - rj))*(cj - ci)
        angle = np.arcsin((ri - rj)/d)

    return (ki, ti), (kj, tj), cn, tip, angle


def cone_strip(kappai, kappaj, axis, n=20):
    """
    Quad mesh of the ruled strip between two contact circles.

    Args:
        kappai: Contact circle on sphere i as (center, radius).
        kappaj: Contact circle on sphere j as (center, radius).
        axis: Cone axis unit vector (3,).
        n: Number of circumference points (default: 20).

    Returns:
        vertices: Strip vertex positions (2*n, 3).
        faces: Quad face index lists.
    """
    
    circlei = circle_3d(kappai[0], axis, kappai[1], pts=n)
    circlej = circle_3d(kappaj[0], axis, kappaj[1], pts=n)

    vertices = np.concat((circlei, circlej), axis=0)

    faces = [ [i, (i+1)%n, n + (i+1)%n, n + i] for i in range(n)]

    return vertices, faces


def cone_strip_mesh(ci, ri, cj, rj, n=20):
    """
    Convenience wrapper: oriented cone + strip mesh in one call.

    Args:
        ci: Center of sphere i (3,).
        ri: Radius of sphere i.
        cj: Center of sphere j (3,).
        rj: Radius of sphere j.
        n: Number of circumference points (default: 20).

    Returns:
        V: Vertex positions (2*n, 3).
        F: Quad face index lists.
    """
    kappai, kappaj, axis, tip, angle = oriented_cone(ci, ri, cj, rj)

    if kappai is None or kappaj is None:
        print("No cone possible")
        V = None 
        F = None 
    else:
        V, F = cone_strip(kappai, kappaj, axis, n=n)
    return V, F


def rotational_cone_radius(vertex, axis, half_angle, radius, n=50):
    """
    Mesh of a rotational cone given apex, axis, half-angle and base circle radius.

    Args:
        vertex: Apex of the cone (3,).
        axis: Cone axis direction (3,).
        half_angle: Half-aperture angle in radians.
        radius: Base circle radius.
        n: Number of circumference points (default: 50).

    Returns:
        vertices: Vertex positions (n+1, 3).
        faces: Fan face index lists.
    """


    axis = unit(axis)

    # Compute the radius of the base of the cone
    if np.isclose(np.tan(half_angle), 0):
        height = 0
        radius = 0
    else:
        height = radius / (np.tan(half_angle)) 

    # Compute the center of the base of the cone
    base_center = vertex + height * axis

    base_circle = circle_3d(base_center, axis, radius, pts=n)

    # Combine vertex and circle points to form the cone mesh
    vertices = np.vstack((vertex, base_circle))
    faces = [[0] + [i for i in range(1, n+1)]]

    return vertices, faces


def half_angle_rotational_cone(axe, normals):
    """
    Mean half-aperture angle between a cone axis and a set of face normals.

    Args:
        axe: Cone axis (3,).
        normals: Face normals (F, 3).

    Returns:
        Mean half-aperture angle in radians.
    """

    return np.arcsin( np.mean(np.abs(np.einsum('j,ij->i', unit(axe), unit(normals)))))


def cone_axis_from_planes(normals):
    """
    Best-fit cone axis for a set of plane normals via SVD.

    Args:
        normals: Array of plane normals (N, 3).

    Returns:
        Unit cone axis vector (3,).
    """
    n = unit(normals)

    # Compute barycenter of the normals
    c = np.mean(n, axis=0)

    if n.shape[0] == 3:
        n0, n1, n2 = n
        axis, _, _ = circle_3pts(n0, n1, n2)

        axis = unit(axis)
    else:
        # Compute difference
        diff = n - c

        # Compute SVD 
        _, _, vh = np.linalg.svd(diff)

        axis = vh[-1]
        
    sign = np.sign(axis @ c)

    return sign*unit(axis)


def compute_cone_axes(mesh):
    """
    Cone axes and half-angles at every inner vertex of a conical quad mesh.

    Boundary vertices use vertex normals with angle = -1 (ignored in optimisation).

    Args:
        mesh: Mesh object with vertices, face normals, and adjacency methods.

    Returns:
        axes: Cone axis at each vertex (V, 3).
        angle: Half-aperture angle in radians (V,); -1 for boundary vertices.
    """    
    v = mesh.vertices

    # Get vertex_face_adjacency_list
    vf_adj = mesh.vertex_face_adjacency_list()

    # Get inner vertices
    in_v = mesh.inner_vertices()

    # Axes of the cones
    axes  = mesh.vertex_normals.copy()
    angle = np.pi/2 * np.ones(len(v))

    # Face normals
    n = mesh.face_normals

    #Construct the axis of the cones
    for i in in_v:
        faces    = vf_adj[i]
        normals  = n[faces]
        axes[i]  = cone_axis_from_planes(np.array(normals))
        angle[i] = half_angle_rotational_cone(axes[i], normals)

    return axes, angle


def sphere_center_on_cone_axis(cone, radius):
    """
    Center of a sphere tangent to a cone's lateral surface, constrained to lie on the axis.

    Args:
        cone: Tuple (axis, half_angle, vertex) where axis is (..., 3), half_angle is (...,), and vertex is (..., 3).
        radius: Sphere radius (...,).

    Returns:
        Sphere center positions (..., 3).
    """
    axis, half_angle, vertex = cone
    # Distance from vertex to sphere center along the axis:
    # the sphere touches the cone surface, so sin(half_angle) = radius / dist
    dist = abs(radius / np.sin(half_angle))
    return vertex + dist[:, None] * axis


def mesh_axes_intersections(vertices, axes, adjacent_vertices):
    """
    Pairwise axis closest-point pairs used to estimate curvature sphere centers.

    Args:
        vertices: Vertex positions (V, 3).
        axes: Cone axis directions at each vertex (V, 3).
        adjacent_vertices: List of adjacency index lists, one per vertex.

    Returns:
        pts_u: List of lists of closest points in the u-direction (even neighbours).
        pts_v: List of lists of closest points in the v-direction (odd neighbours).
    """

    pts_u, pts_v = [], []

    for i in range(len(vertices)):

        pts_u_i, pts_v_i = [], []
        for j, adj_idx in enumerate(adjacent_vertices[i]):
            
            p, _, _ = clst_point_lines(vertices[i], axes[i], vertices[adj_idx], axes[adj_idx])

            if j % 2 == 0:
                pts_u_i.append(p)
            else:
                pts_v_i.append(p)

        pts_u.append(pts_u_i)
        pts_v.append(pts_v_i)

    return pts_u, pts_v


def conical_mesh_smallest_curvature_sphere(vertices, axes, half_angles, adjacent_vertices):
    """
    Smallest curvature sphere at each vertex using cone half-angles to compute radii.

    Args:
        vertices: Vertex positions (V, 3).
        axes: Cone axis directions (V, 3).
        half_angles: Half-aperture angles (V,).
        adjacent_vertices: List of adjacency index lists, one per vertex.

    Returns:
        centers: Sphere centers (V, 3).
        radii: Sphere radii (V,) computed as distance * sin(half_angle).
    """
    centers = []
    radii = []

    pts_u, pts_v = mesh_axes_intersections(vertices, axes, adjacent_vertices)

    
    for i in range(len(vertices)):   
        
        # merge pts_u and pts_v
        pts = np.vstack((pts_u[i], pts_v[i]))

        # Get the closest point to the vertex
        if len(pts) > 0:
            closest_pt = pts[np.argmin(np.linalg.norm(pts - vertices[i], axis=1))]
            centers.append(closest_pt)
            distance_cls_pt = np.linalg.norm(closest_pt - vertices[i])
            radii.append(distance_cls_pt * np.sin(half_angles[i]))
        else:
            centers.append(vertices[i])
            radii.append(0)

    return np.array(centers), np.array(radii)


def mesh_cone_axis_smallest_sphere(vertices, axes, adjacent_vertices):
    """
    Nearest sphere at each vertex from axis-axis closest points, using distance as radius.

    For each vertex, finds the closest footpoint between its axis and each adjacent axis.
    The sphere center is at this footpoint and the radius is its distance to the vertex.
    Unlike conical_mesh_smallest_curvature_sphere, this does not use half-angle information.

    Args:
        vertices: Vertex positions (V, 3).
        axes: Axis directions at each vertex (V, 3).
        adjacent_vertices: List of adjacency index lists, one per vertex.

    Returns:
        centers: Sphere centers (V, 3).
        radii: Sphere radii (V,).
    """
    centers = []
    radii = []

    pts_u, pts_v = mesh_axes_intersections(vertices, axes, adjacent_vertices)

    
    for i in range(len(vertices)):   
        
        # merge pts_u and pts_v
        pts = np.vstack((pts_u[i], pts_v[i]))

        # Get the closest point to the vertex
        if len(pts) > 0:
            closest_pt = pts[np.argmin(np.linalg.norm(pts - vertices[i], axis=1))]
            centers.append(closest_pt)
            radii.append(np.linalg.norm(closest_pt - vertices[i]))
        else:
            centers.append(vertices[i])
            radii.append(0)

    return np.array(centers), np.array(radii)
