"""
Building meshes and curves: normalization, primitive solids, subdivision,
lofting, offsets, barycentric interpolation, and merging pieces into one mesh.
"""

import numpy as np
from typing import Tuple, List, Dict
import igl
from hanan.geometry.algebraic import orth_proj, unit
from hanan.geometry.primitives import project_to_sphere


def normalize_vertices(v, factor=1):
    """
    Translate and scale vertices so the longest bounding-box dimension equals factor.

    Args:
        v: Vertex positions (V, 3).
        factor: Target longest dimension (default: 1).

    Returns:
        Normalized vertex array (V, 3).
    """
    min_v = np.min(v, axis=0)
    max_v = np.max(v, axis=0)
    size = max_v - min_v
    scale = factor / max(size)

    return (v - 0.5*(min_v + max_v)) * scale


def cylinder(center, radius, normal, height, numPtsCircumference=20, numPtsHeight=20):
    """
    Generate a quad-mesh cylinder aligned with normal.

    Args:
        center: Center of the cylinder base (3,).
        radius: Cylinder radius.
        normal: Axis direction (3,).
        height: Cylinder height.
        numPtsCircumference: Circumference sample count (default: 20).
        numPtsHeight: Height sample count (default: 20).

    Returns:
        V: Vertex positions (V, 3).
        F: Quad face indices (F, 4).
    """


    center = np.array(center)
    normal = np.array(normal)

    normal = unit(normal)
    ortho_vec = orth_proj(np.array([1, 0, 0]), normal)
    if np.linalg.norm(ortho_vec) < 1e-6:
        ortho_vec = orth_proj(np.array([0, 1, 0]), normal)
    ortho_vec = unit(ortho_vec)
    ortho_vec2 = unit(np.cross(normal, ortho_vec))

    angle_step = 2 * np.pi / numPtsCircumference
    height_step = height / (numPtsHeight - 1)

    # Vertices
    angles  = np.arange(numPtsCircumference) * angle_step          # (C,)
    heights = np.arange(numPtsHeight) * height_step                 # (H,)

    dirs           = np.cos(angles)[:, None] * ortho_vec + np.sin(angles)[:, None] * ortho_vec2  # (C, 3)
    height_offsets = heights[:, None] * normal                      # (H, 3)

    V = center + radius * dirs[None, :, :] + height_offsets[:, None, :]  # (H, C, 3)
    V = V.reshape(-1, 3)

    # Faces
    J, I = np.meshgrid(np.arange(numPtsHeight - 1), np.arange(numPtsCircumference), indexing='ij')  # (H-1, C)

    C = numPtsCircumference
    v0 = J * C + I
    v1 = J * C + (I + 1) % C
    v2 = (J + 1) * C + (I + 1) % C
    v3 = (J + 1) * C + I

    F = np.stack([v0, v1, v2, v3], axis=-1).reshape(-1, 4)
    return V, F


def loft_curves(c1, c2):
    """
    Loft two curves into a quad mesh.

    Given two curves of N points each, builds N-1 quads connecting them:
        face k = [c1[k], c1[k+1], c2[k+1], c2[k]]

    Args:
        c1: First curve, (N, 3) array or list of points.
        c2: Second curve, (N, 3) array or list of points.

    Returns:
        vertices: (2*N, 3) array — c1 points followed by c2 points.
        faces: list of (N-1) quad index lists.
    """
    c1 = np.asarray(c1, dtype=float)
    c2 = np.asarray(c2, dtype=float)
    if len(c1) != len(c2):
        raise ValueError(f"Curves must have the same number of points ({len(c1)} vs {len(c2)})")

    n        = len(c1)
    vertices = np.vstack([c1, c2])   # c1: indices 0..n-1, c2: indices n..2n-1
    faces    = [[k, k + 1, n + k + 1, n + k] for k in range(n - 1)]
    return vertices, faces


def catmull_clark_subdivision(vertices, faces) -> Tuple[np.ndarray, List[List[int]], Dict[int, List[int]]]:
    """
    One level of Catmull-Clark subdivision for general polygonal meshes.

    Args:
        vertices: Vertex positions (V, 3) or list of (3,) points.
        faces: Face index lists (each element is a list of vertex indices).

    Returns:
        new_vertices: Subdivided vertex positions as ndarray.
        new_faces: Subdivided quad face index lists.
        parent_map: Dict mapping original face index to list of new face indices.
    """
    vertices = np.array(vertices, dtype=float)
    num_old_verts = len(vertices)

    # 1) Compute face points
    face_points = []
    for face in faces:
        face_points.append(np.mean(vertices[face], axis=0))
    face_points = np.array(face_points)

    # 2) Build edge-to-faces map
    edge_to_faces = {}
    for fi, face in enumerate(faces):
        n = len(face)
        for i in range(n):
            edge = tuple(sorted((face[i], face[(i+1)%n])))
            edge_to_faces.setdefault(edge, []).append(fi)

    # Add face points to new vertices list
    new_vertices = vertices.tolist()
    face_point_indices = []
    for fp in face_points:
        new_vertices.append(fp.tolist())
        face_point_indices.append(len(new_vertices) - 1)

    # 3) Compute edge points
    edge_point_dict = {}
    for edge, adj_faces in edge_to_faces.items():
        v0, v1 = edge
        p0, p1 = vertices[v0], vertices[v1]
        if len(adj_faces) == 2:
            f0 = face_points[adj_faces[0]]
            f1 = face_points[adj_faces[1]]
            ept = (p0 + p1 + f0 + f1) / 4.0
        else:
            ept = (p0 + p1) / 2.0
        new_vertices.append(ept.tolist())
        edge_point_dict[edge] = len(new_vertices) - 1

    # 4) Build vertex-to-faces and vertex-to-edges maps
    vert_to_faces = {i: [] for i in range(num_old_verts)}
    vert_to_edges = {i: set() for i in range(num_old_verts)}

    for fi, face in enumerate(faces):
        n = len(face)
        for i in range(n):
            v0 = face[i]
            v1 = face[(i+1)%n]
            vert_to_faces[v0].append(fi)
            edge = tuple(sorted((v0, v1)))
            vert_to_edges[v0].add(edge)
            vert_to_edges[v1].add(edge)

    # 5) Reposition original vertices
    for i in range(num_old_verts):
        faces_of_v = vert_to_faces[i]
        edges_of_v = list(vert_to_edges[i])
        n = len(faces_of_v)

        if n == 0:
            continue

        boundary_edges = [e for e in edges_of_v if len(edge_to_faces[e]) == 1]
        is_boundary = len(boundary_edges) > 0

        if is_boundary:
            if len(boundary_edges) >= 2:
                e1, e2 = boundary_edges[0], boundary_edges[1]
                e1_neighbor = e1[0] if e1[1] == i else e1[1]
                e2_neighbor = e2[0] if e2[1] == i else e2[1]
                newP = 0.75 * vertices[i] + 0.125 * (vertices[e1_neighbor] + vertices[e2_neighbor])
            else:
                newP = vertices[i]
        else:
            F = np.mean([face_points[fi] for fi in faces_of_v], axis=0)
            R = np.mean([(vertices[e[0]] + vertices[e[1]]) / 2.0 for e in edges_of_v], axis=0)
            P = vertices[i]
            newP = (F + 2 * R + (n - 3) * P) / n

        new_vertices[i] = newP.tolist()

    # 6) Build new faces + track parent mapping
    new_faces = []
    # parent_map[original_face_index] = [new_face_indices...]
    parent_map: Dict[int, List[int]] = {fi: [] for fi in range(len(faces))}

    for fi, face in enumerate(faces):
        n = len(face)
        f_idx = face_point_indices[fi]
        for i in range(n):
            v0 = face[i]
            v1 = face[(i+1)%n]
            v_minus = face[(i-1)%n]
            e0 = tuple(sorted((v0, v1)))
            e_minus = tuple(sorted((v_minus, v0)))

            new_face_idx = len(new_faces)          # index this quad will get
            parent_map[fi].append(new_face_idx)    # record it

            new_faces.append([
                v0,
                edge_point_dict[e0],
                f_idx,
                edge_point_dict[e_minus]
            ])

    return np.array(new_vertices), new_faces, parent_map


def dodecahedron():
    """
    Dodecahedron mesh with 20 vertices and 12 pentagonal faces.

    Returns:
        vertices: Vertex positions (20, 3).
        faces: List of 12 pentagonal face index lists.
    """

    phi = (1 + np.sqrt(5)) / 2  # Golden ratio ≈ 1.618
    a = 1 / phi               # Reciprocal of phi ≈ 0.618
    vertices = np.array([
                [ 0.0,   a,  phi],  # index 0
                [ 0.0,  -a,  phi],  # index 1
                [ 0.0,  -a, -phi],  # index 2
                [ 0.0,   a, -phi],  # index 3
                [ phi,  0.0,   a],  # index 4
                [-phi,  0.0,   a],  # index 5
                [-phi,  0.0,  -a],  # index 6
                [ phi,  0.0,  -a],  # index 7
                [  a,  phi,  0.0],  # index 8
                [ -a,  phi,  0.0],  # index 9
                [ -a, -phi,  0.0],  # index 10
                [  a, -phi,  0.0],  # index 11
                [ 1.0,  1.0,  1.0], # index 12
                [-1.0,  1.0,  1.0], # index 13
                [-1.0, -1.0,  1.0], # index 14
                [ 1.0, -1.0,  1.0], # index 15
                [ 1.0, -1.0, -1.0], # index 16
                [ 1.0,  1.0, -1.0], # index 17
                [-1.0,  1.0, -1.0], # index 18
                [-1.0, -1.0, -1.0]  # index 19
            ], dtype=float)

    # Faces
    faces = [
        [0,  1, 15,  4, 12],
        [0, 12,  8,  9, 13],
        [0, 13,  5, 14,  1],
        [1, 14, 10, 11, 15],
        [2,  3, 17,  7, 16],
        [2, 16, 11, 10, 19],
        [2, 19,  6, 18,  3],
        [18,  9,  8, 17,  3],
        [15, 11, 16,  7,  4],
        [4,  7, 17,  8, 12],
        [13,  9, 18,  6,  5],
        [5,  6, 19, 10, 14]
    ]
    

    return vertices, faces


def polysphere(center, radius, subdivision=2):
    """
    Mesh approximation of a sphere (dodecahedron + Catmull-Clark subdivision, projected).

    Args:
        center: Sphere center (3,).
        radius: Sphere radius.
        subdivision: Number of Catmull-Clark subdivision levels (default: 2).

    Returns:
        vertices: Vertex positions (V, 3).
        faces: Quad face index lists.
    """
    from hanan.geometry.construction import catmull_clark_subdivision

    # Create an icosahedron
    vertices, faces = dodecahedron()

    # Subdivide the icosahedron
    for _ in range(subdivision):
        vertices, faces, _ = catmull_clark_subdivision(vertices, faces)

    vertices = vertices + center
            
    # Project vertices to the sphere
    vertices = project_to_sphere(vertices, center, abs(radius)) 

    return vertices, faces


def get_barycentric_coords(points, vertices, faces):
    """
    Barycentric coordinates of arbitrary points projected onto a triangle mesh.

    Args:
        points: Query points (N, 3).
        vertices: Mesh vertex positions (V, 3).
        faces: Triangle face indices (F, 3) as a NumPy array.

    Returns:
        bary_coords: Barycentric coordinates (N, 3).
        idi: First vertex indices of the closest face (N,).
        idj: Second vertex indices of the closest face (N,).
        idk: Third vertex indices of the closest face (N,).
    """
    # First, project points onto the mesh surface
    distance, face_indices, points_on_mesh = igl.point_mesh_squared_distance(points, vertices, faces)

    vi, vj, vk = vertices[faces[face_indices].T]
    idi, idj, idk = faces[face_indices].T

    bary_coords = igl.barycentric_coordinates(points_on_mesh, vi, vj, vk)
   
    return bary_coords, idi, idj, idk


def interpolate_triangle_mesh(points, vertices, faces, values):
    """
    Interpolate scalar or vector values at arbitrary points using barycentric coordinates.

    Args:
        points: Query points (N, 3).
        vertices: Mesh vertex positions (V, 3).
        faces: Triangle face indices (F, 3) as a NumPy array.
        values: Per-vertex values (V,) or (V, D).

    Returns:
        Interpolated values at each query point (N,) or (N, D).
    """
    if len(values.shape) != 2:
        values = values[:, None]
    bary_coords, idi, idj, idk = get_barycentric_coords(points, vertices, faces)

    interpolated_values = (bary_coords[:, 0][:, np.newaxis] * values[idi] +
                           bary_coords[:, 1][:, np.newaxis] * values[idj] +
                           bary_coords[:, 2][:, np.newaxis] * values[idk])
    if interpolated_values.shape[1] == 1:
        interpolated_values = interpolated_values[:, 0]

    return interpolated_values


def merge_meshes(V_list, F_list):
    """
    Merge a list of meshes into a single mesh with re-indexed faces.

    Args:
        V_list: List of vertex arrays, each of shape (n_i, 3).
        F_list: List of face arrays; each element can be a NumPy array or list of index lists.

    Returns:
        V_merged: Concatenated vertex array (V_total, 3).
        F_merged: Face index list with globally re-indexed vertices.
    """
    if len(V_list) != len(F_list):
        raise ValueError("V_list and F_list must have the same length")

    if len(V_list) == 0:
        raise ValueError("At least one mesh must be provided")

    # Initialize lists to store vertices and faces
    all_vertices = []
    all_faces = []

    # Track the current vertex offset
    vertex_offset = 0

    for V, F in zip(V_list, F_list):
        # Convert vertices to numpy array
        V = np.asarray(V, dtype=np.float64)

        # Add vertices
        all_vertices.append(V)

        # Handle faces - they might be lists or arrays
        if isinstance(F, np.ndarray):
            F_adjusted = F + vertex_offset
            all_faces.extend(F_adjusted.tolist())
        elif isinstance(F, list):
            # Handle list of faces
            for face in F:
                face_array = np.asarray(face, dtype=np.int32) + vertex_offset
                all_faces.append(face_array.tolist())
        else:
            raise ValueError(f"Unsupported face type: {type(F)}")

        # Update the vertex offset for the next mesh
        vertex_offset += len(V)


    # Concatenate all vertices
    V_merged = np.vstack(all_vertices)
    F_merged = all_faces


    return V_merged, F_merged


def merge_curves(curve_list):
    """
    Merge a list of curves into a single curve network with re-indexed edges.

    Args:
        curve_list: List of curve point arrays, each of shape (n_i, 3).

    Returns:
        merged_points: All points concatenated (total_points, 3).
        edges: Edge index array (E, 2) with globally re-indexed endpoints.
    """
    if len(curve_list) == 0:
        raise ValueError("At least one curve must be provided")

    # Concatenate all curves
    merged_points = np.vstack(curve_list)

    edge_offset = 0
    edges = []
    for i, curve in enumerate(curve_list):
        edges.extend([[j + edge_offset, j + 1 + edge_offset] for j in range(len(curve) - 1)])
        edge_offset += len(curve)

    edges = np.array(edges, dtype=np.int32)    

    return merged_points, edges


def offset_curve(curve, direction, offset_distance_out=1.0, offset_distance_in=1.0):
    """
    Offset a curve in both directions and build connecting quad faces.

    Args:
        curve: Curve points (N, 3).
        direction: Per-point offset directions (N, 3).
        offset_distance_out: Outward offset distance (default: 1.0).
        offset_distance_in: Inward offset distance (default: 1.0).

    Returns:
        vertices: Offset vertices (2*N, 3) — outward then inward.
        faces: Quad face index lists connecting the two offset curves.
    """

    curve = np.array(curve)
    vertices = []


    offsetPos = curve + offset_distance_out * direction
    offsetNeg = curve - offset_distance_in  * direction

    vertices.extend(offsetPos)
    vertices.extend(offsetNeg)
    
    faces = [[k, k + len(curve), (k + 1) + len(curve), (k + 1) ] for k in range(len(curve)-1)]

    return vertices, faces
