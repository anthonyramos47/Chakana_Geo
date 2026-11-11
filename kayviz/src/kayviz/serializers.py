"""
Generic geometry serializers for kayviz.

Each function returns a plain dict that the WebSocket sends to the browser; its
arrays are numpy float32 / int32 and travel as binary (kayviz.webscope.wire).
The browser's viewer.js dispatches on obj.type to the correct Three.js call.

Everything here depends on numpy only and wraps arrays the caller already has;
nothing here generates geometry. Mesh data for spheres, circles, planes, cones,
… comes from the geometry side (e.g. hanan.glyphs) and is passed in as plain
(V, F) / (P, E) arrays. Domain-specific scene builders (e.g. an L-mesh scene)
belong in the project that defines the geometry and return lists of these dicts.
"""

from __future__ import annotations

import numpy as np


def _f32(a) -> np.ndarray:
    """Flat float32 copy. Always a copy: the dict is buffered and replayed on reload,
    so it must not change when the caller edits its array in place afterwards, nor
    keep memory owned by someone else (e.g. a C++ extension) alive."""
    return np.array(a, dtype=np.float32, copy=True).ravel()


def _i32(a) -> np.ndarray:
    """Flat int32 copy (see _f32)."""
    return np.array(a, dtype=np.int32, copy=True).ravel()


# ── Core geometry types ───────────────────────────────────────────────────────

def _polygon_edges(faces) -> np.ndarray:
    """Unique undirected edges (m, 2) of the polygons, int32."""
    try:
        F = np.asarray(faces, dtype=np.int64)
    except (ValueError, TypeError):
        F = None
    if F is not None and F.ndim == 2 and F.shape[0]:
        E = np.stack([F, np.roll(F, -1, axis=1)], axis=-1).reshape(-1, 2)
    else:                                       # ragged polygons
        E = np.array([(f[k], f[(k + 1) % len(f)])
                      for f in (np.asarray(f).ravel() for f in faces)
                      for k in range(len(f))], dtype=np.int64).reshape(-1, 2)
    E.sort(axis=1)
    if not len(E):
        return np.zeros((0, 2), np.int32)
    # unique on one int64 key per edge (faster than np.unique(axis=0))
    n = int(E.max()) + 1
    key = np.unique(E[:, 0] * n + E[:, 1])
    return np.stack([key // n, key % n], axis=1).astype(np.int32)


def surface_mesh(name: str, vertices, faces, color=(0.8, 0.8, 0.8),
                 face_size=None, opacity=1.0, show_edges=False,
                 edge_color=(0.1, 0.1, 0.1), edge_radius: float = 0.0, show: bool = True,
                 material=None):
    """Mirrors ps.register_surface_mesh(). show=False registers the object hidden (its checkbox in the scene panel unticked).
    material (e.g. "glass") pins this mesh's shader; None follows the global Shader dropdown.

    Faces may be uniform (all same length) or ragged (polygons with different
    vertex counts).  Ragged faces are fan-triangulated for rendering.

    The unique polygon edges (before triangulation) always travel with the mesh as
    ``poly_edges``, pairs of indices into its vertices; the viewer draws them as tubes
    when show_edges=True or when "show edges" is ticked. edge_radius=0 means 3% of the
    median edge length.

    Arrays are numpy float32 / int32 (sent to the browser as binary, see
    kayviz.webscope.wire); ``kayviz.webscope.wire.jsonable`` turns them into lists.
    """
    verts = _f32(vertices)
    poly_edges = _polygon_edges(faces)

    try:
        F = np.asarray(faces, dtype=np.int64)
        uniform = F.ndim == 2
    except (ValueError, TypeError):
        uniform = False
    first_len = F.shape[1] if uniform and F.size else (len(faces[0]) if len(faces) else 3)

    tris_per_face = None
    if not uniform or (face_size is None and first_len > 4):
        faces_list = [np.asarray(f).ravel().tolist() for f in faces]
        tris = []
        tris_per_face = []
        for f in faces_list:
            for t in range(1, len(f) - 1):
                tris.append([f[0], f[t], f[t + 1]])
            tris_per_face.append(len(f) - 2)
        faces_arr = np.array(tris, dtype=np.int32).reshape(-1)
        fs = 3
    else:
        faces_arr = _i32(F)
        fs = face_size or first_len

    mesh_dict = {
        "type":          "surface_mesh",
        "name":          name,
        "vertices":      verts,
        "faces":         faces_arr,
        "face_size":     int(fs),
        "tris_per_face": None if tris_per_face is None else np.array(tris_per_face, np.int32),
        "poly_edges":    poly_edges.ravel(),
        "color":         [float(c) for c in color],
        "opacity":       float(opacity),
        "show_edges":    bool(show_edges),
        "show":          bool(show),
    }
    if show_edges:
        mesh_dict["edge_color"]  = [float(c) for c in edge_color]
        mesh_dict["edge_radius"] = float(edge_radius)
    if material is not None:
        mesh_dict["material"] = str(material)
    return mesh_dict


def curve_network(name: str, vertices, edges, color=(0.8, 0.2, 0.2), radius: float = 0.002,
                  show: bool = True):
    """Mirrors ps.register_curve_network(). show=False registers the object hidden (its checkbox in the scene panel unticked)."""
    return {
        "type":     "curve_network",
        "name":     name,
        "vertices": _f32(vertices),
        "edges":    _i32(edges),
        "color":    [float(c) for c in color],
        "radius":   float(radius),
        "show":     bool(show),
    }


def point_cloud(name: str, points, color=(0.2, 0.5, 0.8), radius=0.0005, show: bool = True):
    """Mirrors ps.register_point_cloud(). show=False registers the object hidden (its checkbox in the scene panel unticked)."""
    return {
        "type":   "point_cloud",
        "name":   name,
        "points": _f32(points),
        "color":  [float(c) for c in color],
        "radius": float(radius),
        "show":   bool(show),
    }


def edge_child(target_name: str, vertices, edges,
               color=(0.1, 0.1, 0.1), radius: float = 0.0):
    """Edge overlay attached as a child of an existing surface_mesh."""
    return {
        "type":     "edge_child",
        "target":   target_name,
        "vertices": _f32(vertices),
        "edges":    _i32(edges),
        "color":    [float(c) for c in color],
        "radius":   float(radius),
    }


def scalar_quantity(target_name: str, field_name: str, values, defined_on="vertices",
                    show: bool | None = None):
    """Mirrors structure.add_scalar_quantity().

    show: None (default) follows the parent - hidden while the parent is hidden; True also
    shows the parent; False adds the quantity without displaying it.
    For a scalar, displaying it means colouring the mesh with it.
    """
    d = {
        "type":       "scalar_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": defined_on,
        "values":     _f32(values),
    }
    if show is not None:
        d["show"] = bool(show)
    return d


def vector_quantity(target_name: str, field_name: str, vectors, defined_on="vertices",
                    length: float = 0.05, radius: float = None, show: bool | None = None,
                    color=None):
    """Mirrors structure.add_vector_quantity().

    defined_on: "vertices" (arrows at the vertices / points) or "faces" (at the face
    barycenters).
    show: None (default) follows the parent - hidden while the parent is hidden; True also
    shows the parent; False adds the quantity without displaying it.
    color: [r, g, b] in 0-1; None lets the viewer pick the next colour of its palette
    that no other vector quantity of the same parent uses.
    """
    if radius is None:
        radius = length * 0.04
    d = {
        "type":       "vector_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": defined_on,
        "vectors":    _f32(vectors),
        "length":     float(length),
        "radius":     float(radius),
    }
    if show is not None:
        d["show"] = bool(show)
    if color is not None:
        d["color"] = [float(c) for c in color]
    return d


def vector_field(name: str, origins, vectors, length: float = 0.05,
                 radius: float = None, color=(0.2, 0.8, 0.4), show: bool = True):
    """Arrow vector field — origins + direction vectors, rendered as cylinder+cone arrows.

    show=False registers the object hidden (its checkbox in the scene panel unticked).
    """
    if radius is None:
        radius = length * 0.04
    return {
        "type":    "vector_field",
        "name":    name,
        "origins": _f32(origins),
        "vectors": _f32(vectors),
        "length":  float(length),
        "radius":  float(radius),
        "color":   [float(c) for c in color],
        "show":    bool(show),
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
        vector_quantity(mesh_name, key, v, defined_on="faces",
                        length=size, radius=rad, color=color)
        for key, v in ((name + "_vec1", vec1), (name + "_-vec1", -vec1),
                       (name + "_vec2", vec2), (name + "_-vec2", -vec2))
    ]
