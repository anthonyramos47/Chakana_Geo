"""
Generic geometry serializers for kayviz.

Each function returns a plain dict that the WebSocket sends to the browser.
The browser's viewer.js dispatches on obj.type to the correct Three.js call.

Everything here depends on numpy only and wraps arrays the caller already has;
nothing here generates geometry. Mesh data for spheres, circles, planes, cones,
… comes from the geometry side (e.g. hanan.glyphs) and is passed in as plain
(V, F) / (P, E) arrays. Domain-specific scene builders (e.g. an L-mesh scene)
belong in the project that defines the geometry and return lists of these dicts.
"""

import numpy as np


# ── Core geometry types ───────────────────────────────────────────────────────

def surface_mesh(name: str, vertices, faces, color=(0.8, 0.8, 0.8),
                 face_size=None, opacity=1.0, show_edges=False,
                 edge_color=(0.8, 0.8, 0.8), edge_radius: float = 0.0):
    """Mirrors ps.register_surface_mesh().

    Faces may be uniform (all same length) or ragged (polygons with different
    vertex counts).  Ragged faces are fan-triangulated for rendering.

    If show_edges=True the unique polygon boundary edges are extracted from the
    original face list (before triangulation) and returned as a second dict of
    type 'edge_child' targeting this mesh by name.  The caller must send both
    dicts to the viewer (the viewer registers the edge as a child of the mesh).
    """
    verts = np.array(vertices, dtype=np.float32)
    faces_list = [np.asarray(f).flatten().tolist() for f in faces]

    # Always extract unique polygon edges from original faces (before triangulation).
    seen = set()
    vi_list, vj_list = [], []
    for f in faces_list:
        n = len(f)
        for k in range(n):
            a, b = f[k], f[(k + 1) % n]
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                vi_list.append(a)
                vj_list.append(b)
    vi = np.array(vi_list, dtype=np.int32)
    vj = np.array(vj_list, dtype=np.int32)
    poly_edge_verts = np.vstack((verts[vi], verts[vj]))
    poly_edge_conn  = np.column_stack([np.arange(len(vi)), np.arange(len(vi)) + len(vi)])

    if show_edges:
        edges_dict = edge_child(name, poly_edge_verts, poly_edge_conn, color=edge_color, radius=edge_radius)

    first_len = len(faces_list[0]) if faces_list else 3
    is_ragged = any(len(f) != first_len for f in faces_list)

    tris_per_face = None
    if is_ragged or (face_size is None and first_len > 4):
        tris = []
        tris_per_face = []
        for f in faces_list:
            n_tris = len(f) - 2
            for t in range(1, len(f) - 1):
                tris.append([f[0], f[t], f[t + 1]])
            tris_per_face.append(n_tris)
        faces_list = tris
        fs = 3
    else:
        fs = face_size or first_len

    faces_arr = np.array(faces_list, dtype=np.int32)
    mesh_dict = {
        "type":            "surface_mesh",
        "name":            name,
        "vertices":        verts.flatten().tolist(),
        "faces":           faces_arr.flatten().tolist(),
        "face_size":       int(fs),
        "tris_per_face":   tris_per_face,
        "poly_edge_verts": poly_edge_verts.flatten().tolist(),
        "poly_edge_conn":  poly_edge_conn.flatten().tolist(),
        "color":           [float(c) for c in color],
        "opacity":         float(opacity),
        "show_edges":      bool(show_edges),
    }

    if show_edges:
        return [mesh_dict, edges_dict]
    return mesh_dict


def curve_network(name: str, vertices, edges, color=(0.8, 0.2, 0.2), radius: float = 0.002):
    """Mirrors ps.register_curve_network()."""
    return {
        "type":     "curve_network",
        "name":     name,
        "vertices": np.array(vertices, dtype=np.float32).flatten().tolist(),
        "edges":    np.array(edges,    dtype=np.int32).flatten().tolist(),
        "color":    [float(c) for c in color],
        "radius":   float(radius),
    }


def point_cloud(name: str, points, color=(0.2, 0.5, 0.8), radius=0.0005):
    """Mirrors ps.register_point_cloud()."""
    return {
        "type":   "point_cloud",
        "name":   name,
        "points": np.array(points, dtype=np.float32).flatten().tolist(),
        "color":  [float(c) for c in color],
        "radius": float(radius),
    }


def edge_child(target_name: str, vertices, edges,
               color=(0.1, 0.1, 0.1), radius: float = 0.0):
    """Edge overlay attached as a child of an existing surface_mesh."""
    return {
        "type":     "edge_child",
        "target":   target_name,
        "vertices": np.array(vertices, dtype=np.float32).flatten().tolist(),
        "edges":    np.array(edges,    dtype=np.int32).flatten().tolist(),
        "color":    [float(c) for c in color],
        "radius":   float(radius),
    }


def scalar_quantity(target_name: str, field_name: str, values, defined_on="vertices"):
    """Mirrors structure.add_scalar_quantity()."""
    return {
        "type":       "scalar_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": defined_on,
        "values":     np.array(values, dtype=np.float32).tolist(),
    }


def vector_quantity(target_name: str, field_name: str, vectors, defined_on="vertices",
                    length: float = 0.05, radius: float = None):
    """Mirrors structure.add_vector_quantity()."""
    if radius is None:
        radius = length * 0.04
    return {
        "type":       "vector_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": defined_on,
        "vectors":    np.array(vectors, dtype=np.float32).flatten().tolist(),
        "length":     float(length),
        "radius":     float(radius),
    }


def vector_field(name: str, origins, vectors, length: float = 0.05,
                 radius: float = None, color=(0.2, 0.8, 0.4)):
    """Arrow vector field — origins + direction vectors, rendered as cylinder+cone arrows."""
    if radius is None:
        radius = length * 0.04
    return {
        "type":    "vector_field",
        "name":    name,
        "origins": np.array(origins, dtype=np.float32).flatten().tolist(),
        "vectors": np.array(vectors, dtype=np.float32).flatten().tolist(),
        "length":  float(length),
        "radius":  float(radius),
        "color":   [float(c) for c in color],
    }


def set_enabled(name: str, enabled: bool):
    """Mirrors structure.set_enabled()."""
    return {"type": "set_enabled", "name": name, "enabled": enabled}


# ── Vector-quantity helpers ───────────────────────────────────────────────────

def visualize_frame(name, points, e1, e2, n):
    """A per-point frame: [point_cloud, vector e1, vector e2, vector n]."""
    pc = point_cloud(name + "Frame", points, color=(0, 0, 0), radius=0.002)
    return [
        pc,
        vector_quantity(name + "Frame", "e1", e1),
        vector_quantity(name + "Frame", "e2", e2),
        vector_quantity(name + "Frame", "n",  n),
    ]


def add_cross_field(mesh_name, vec1, vec2, name="", rad=0.002, size=0.04,
                    color=(0.8, 0.2, 0.2)):
    """A 4-direction cross field on a mesh's faces: four vector_quantity dicts."""
    return [
        vector_quantity(mesh_name, name + "_vec1",  vec1,  defined_on="faces"),
        vector_quantity(mesh_name, name + "_-vec1", -vec1, defined_on="faces"),
        vector_quantity(mesh_name, name + "_vec2",  vec2,  defined_on="faces"),
        vector_quantity(mesh_name, name + "_-vec2", -vec2, defined_on="faces"),
    ]
