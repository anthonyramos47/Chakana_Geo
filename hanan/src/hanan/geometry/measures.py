"""
Per-face quality measures: normals, planarity, circularity, circumcircles.
"""

import numpy as np
from hanan.geometry.algebraic import unit, vec_dot
from hanan.geometry.primitives import circle_3pts, clst_point_lines


def compute_face_normals(vertices, faces):
    """
    Unit normals at each face for triangle, quad, and general n-gon meshes.

    - Triangles : cross product of the two edge vectors from vertex 0.
    - Quads     : cross product of the two diagonals (more robust than one triangle).
    - n-gons    : mean of cross products over consecutive edge triplets.

    Args:
        vertices : (V, 3) vertex positions.
        faces    : list of face index lists (variable valence) or (F, K) int array.

    Returns:
        normals  : (F, 3) unit face normals.
    """

    V = np.asarray(vertices, dtype=float)
    faces = list(faces)
    F = len(faces)
    normals = np.zeros((F, 3))

    for fi, face in enumerate(faces):
        verts = V[face]
        n = len(face)
        if n == 3:
            normals[fi] = np.cross(verts[1] - verts[0], verts[2] - verts[0])
        elif n == 4:
            normals[fi] = np.cross(verts[2] - verts[0], verts[3] - verts[1])
        else:
            # Newell's method: exact for planar n-gons, least-squares approximation otherwise
            acc = np.zeros(3)
            for k in range(n):
                acc += np.cross(verts[k], verts[(k + 1) % n])
            normals[fi] = acc

    return unit(normals)


def face_planarity(vertices, faces):
    """
    Per-face planarity measure for a polygon mesh.

    For each face the best-fit normal is computed via Newell's method, then
    planarity is the maximum absolute distance from any vertex to that plane,
    normalised by the mean edge length of the face.  A value of 0 means
    perfectly planar.

    Args:
        vertices: (V, 3) array of vertex positions.
        faces:    list of index arrays, one per face (triangles, quads, n-gons).

    Returns:
        planarity: (F,) array, one scalar per face.
    """
    vertices = np.asarray(vertices, dtype=float)
    planarity = np.zeros(len(faces))

    for fi, face in enumerate(faces):
        verts = vertices[face]
        n = len(face)

        # Newell normal (unnormalised)
        acc = np.zeros(3)
        for k in range(n):
            acc += np.cross(verts[k], verts[(k + 1) % n])
        norm_len = np.linalg.norm(acc)
        if norm_len < 1e-12:
            continue
        normal = acc / norm_len

        # Mean edge length for normalisation
        edges = np.linalg.norm(np.roll(verts, -1, axis=0) - verts, axis=1)
        mean_edge = edges.mean()
        if mean_edge < 1e-12:
            continue

        # Max deviation from the plane defined by the first vertex
        deviations = np.abs((verts - verts[0]) @ normal)
        planarity[fi] = deviations.max() / mean_edge

    return planarity


def compute_planarity(p1, p2, p3, p4):
    """
    Planarity of a quad via normal-edge dot product.

    Args:
        p1: First quad vertex (N, 3).
        p2: Second quad vertex (N, 3).
        p3: Third quad vertex (N, 3).
        p4: Fourth quad vertex (N, 3).

    Returns:
        Planarity value array (N,); 0 means perfectly planar.
    """
    from hanan.geometry.algebraic import unit, vec_dot
    v0 = unit(p2 - p1)
    v1 = unit(p4 - p1)
    v2 = unit(p3 - p4)
    n = np.cross(v0, v1)
    return np.abs(vec_dot(n, v2))


def planarity_measure_quad_mesh(quad_mesh):
    """
    Planarity per face: diagonal closest-point gap divided by average edge length.

    Args:
        quad_mesh: Mesh object with vertices, faces, and edge_vertices() method.

    Returns:
        Planarity measure array (F,).
    """
    from hanan.geometry.algebraic import unit, vec_dot

    vertices = quad_mesh.vertices
    faces = quad_mesh.faces
    # Measure edge lengths 

    ei, ej = quad_mesh.edge_vertices()

    edge_length = 0 

    for i, j in zip(ei, ej):
        edge_length += np.linalg.norm(vertices[i] - vertices[j])
        # Store edge lengths for normalization if needed
    average_edge_length = edge_length / len(ei)
    
    planarity_measures = []
    for face in faces:
        v0, v1, v2, v3 = vertices[face]
        diag1 = unit(v2 - v0)
        diag2 = unit(v3 - v1)
        point_diag_1, point_diag_2, _ = clst_point_lines(v0, diag1, v1, diag2)
        planarity_measures.append(np.linalg.norm(point_diag_1 - point_diag_2)/average_edge_length)

    return np.array(planarity_measures)


def compute_circumcircles_quad_mesh(vertices, faces):
    """
    Compute circumcenters, normals, and radii for each face of a quad mesh.

    Args:
        vertices: Vertex positions (N, 3).
        faces: Quad face index array (M, 4).

    Returns:
        centers: Circumcenter positions (M, 3).
        normals: Face normals (M, 3).
        radii: Circumcircle radii (M,).
    """
    

    centers = np.zeros((len(faces), 3))
    normals = np.zeros((len(faces), 3))
    radii   = np.zeros(len(faces))


    filer_faces = [f for f in faces if len(set(f)) == 4]

    for i, f in enumerate(filer_faces):

        v0, v1, v2, v3 = vertices[f]

        center0, normal0, radius0 = circle_3pts(v0,v1,v2)
        center1, normal1, radius1 = circle_3pts(v0,v1,v3)
        center2, normal2, radius2 = circle_3pts(v0,v2,v3)
        center3, normal3, radius3 = circle_3pts(v1,v2,v3)

        center = (center0 + center1 + center2 + center3) / 4
        normal = (normal0 + normal1 + normal2 + normal3) / 4
        
        radius = np.linalg.norm(center - v0) + np.linalg.norm(center - v1) + np.linalg.norm(center - v2) + np.linalg.norm(center - v3)
        radius /= 4

        centers[i] = center
        normals[i] = normal
        radii[i]   = radius
    
    return centers, normals, radii
