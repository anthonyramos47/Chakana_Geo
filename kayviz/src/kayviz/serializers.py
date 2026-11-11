"""
Generic geometry serializers for kayviz.

Each function returns a plain dict that the WebSocket sends to the browser; its
arrays are numpy float32 / int32 and travel as binary (kayviz.runtime.wire).
The browser's viewer.js dispatches on obj.type to the correct Three.js call.

Everything here depends on numpy only and wraps arrays the caller already has;
nothing here generates geometry. Mesh data for spheres, circles, planes, cones,
… comes from the geometry side (e.g. hanan.glyphs) and is passed in as plain
(V, F) / (P, E) arrays. Domain-specific scene builders (e.g. an L-mesh scene)
belong in the project that defines the geometry and return lists of these dicts.
"""

from __future__ import annotations

import warnings

import numpy as np


def _f32(a) -> np.ndarray:
    """Flat float32 copy. Always a copy: the dict is buffered and replayed on reload,
    so it must not change when the caller edits its array in place afterwards, nor
    keep memory owned by someone else (e.g. a C++ extension) alive."""
    return np.array(a, dtype=np.float32, copy=True).ravel()


def _i32(a) -> np.ndarray:
    """Flat int32 copy (see _f32)."""
    return np.array(a, dtype=np.int32, copy=True).ravel()


# ── Input checks ──────────────────────────────────────────────────────────────
# Wrong input used to reach the browser and draw garbage (or nothing) without a
# word. These raise ValueError naming the object, before anything is sent.

def _array(a, name: str, what: str) -> np.ndarray:
    try:
        arr = np.asarray(a)
    except ValueError as e:                     # ragged nested lists
        raise ValueError(f"{name}: {what} must be a numeric array ({e})") from None
    if arr.dtype.kind == "c":
        raise ValueError(f"{name}: {what} must be real, got complex values")
    if arr.dtype.kind not in "biuf":
        raise ValueError(f"{name}: {what} must be numeric, got dtype {arr.dtype}")
    return arr


def _points(a, name: str, what: str = "vertices") -> np.ndarray:
    """(N, 3) real coordinates -> flat float32 copy. Non-finite values warn."""
    arr = _array(a, name, what)
    if arr.ndim != 2 or arr.shape[1] != 3:
        hint = (" (2D points: add a zero z column, np.c_[P, np.zeros(len(P))])"
                if arr.ndim == 2 and arr.shape[1] == 2 else "")
        raise ValueError(f"{name}: {what} must have shape (N, 3), got {arr.shape}{hint}")
    bad = ~np.isfinite(arr).all(axis=1)
    if bad.any():
        warnings.warn(f"{name}: {int(bad.sum())} of {len(arr)} {what} are NaN or infinite",
                      stacklevel=3)
    return _f32(arr)


def _indices(a, name: str, what: str, n: int, width: int | None = None) -> np.ndarray:
    """Integer index array (int64), every entry in [0, n)."""
    arr = _array(a, name, what)
    if arr.dtype.kind == "f":
        if not np.array_equal(arr, np.round(arr)):
            raise ValueError(f"{name}: {what} must be integers")
        arr = arr.astype(np.int64)
    arr = arr.astype(np.int64, copy=False)
    if width is not None and (arr.ndim != 2 or arr.shape[1] != width):
        raise ValueError(f"{name}: {what} must have shape (M, {width}), got {arr.shape}")
    if arr.size and (arr.min() < 0 or arr.max() >= n):
        raise ValueError(f"{name}: {what} index out of range: values in "
                         f"[{arr.min()}, {arr.max()}] for {n} vertices")
    return arr


def _polygons(faces, name: str, n: int):
    """Faces as a uniform (F, k) int64 array, or a list of int64 polygons when sizes
    differ. In a 2D array, -1 at the end of a row pads a shorter polygon."""
    if faces is None:
        raise ValueError(f"{name}: faces are missing")
    try:
        F = _array(faces, name, "faces")
    except ValueError:
        F = None                                # ragged list of polygons
    if F is not None and F.ndim == 1 and len(F) and F.dtype != object:
        raise ValueError(f"{name}: faces must be a list of polygons, e.g. [[0, 1, 2]], "
                         f"not a flat list of indices")

    if F is not None and F.ndim == 2:
        if F.dtype.kind == "f" and not np.array_equal(F, np.round(F)):
            raise ValueError(f"{name}: faces must be integers")
        F = F.astype(np.int64, copy=False)
        if not (F < 0).any():
            if F.shape[1] < 3:
                raise ValueError(f"{name}: faces need at least 3 vertices, got {F.shape[1]}")
            _check_polygon_range(F, name, n)
            return F
        pad = F == -1
        # -1 pads the end of a row only: once -1, -1 up to the end of the row
        if (F < -1).any() or (pad[:, :-1] & ~pad[:, 1:]).any():
            raise ValueError(f"{name}: faces contain negative indices "
                             f"(-1 is allowed only as padding at the end of a row)")
        faces = [row[row >= 0] for row in F]

    polys = [_indices(f, name, "faces", n).ravel() for f in faces]
    small = [i for i, f in enumerate(polys) if len(f) < 3]
    if small:
        raise ValueError(f"{name}: {len(small)} face(s) have fewer than 3 vertices "
                         f"(first: face {small[0]})")
    return polys


def _check_polygon_range(F, name, n):
    if F.size and (F.min() < 0 or F.max() >= n):
        raise ValueError(f"{name}: faces index out of range: values in "
                         f"[{F.min()}, {F.max()}] for {n} vertices")


def _rgb(c, name: str, what: str = "color") -> list:
    """Colour as 3 floats in [0, 1]."""
    try:
        rgb = [float(x) for x in c]
    except (TypeError, ValueError):
        raise ValueError(f"{name}: {what} must be 3 numbers in [0, 1], got {c!r}") from None
    if len(rgb) != 3:
        raise ValueError(f"{name}: {what} must have 3 components, got {len(rgb)}")
    if any(x < 0 or x > 1 for x in rgb):
        hint = " (0-255 values: divide by 255)" if all(0 <= x <= 255 for x in rgb) else ""
        raise ValueError(f"{name}: {what} components must be in [0, 1], got {tuple(rgb)}{hint}")
    return rgb


def _unit(x, name: str, what: str) -> float:
    x = float(x)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"{name}: {what} must be in [0, 1], got {x}")
    return x


DEFINED_ON = ("vertices", "faces")

def _shading(s, name, polygons: bool) -> str:
    if s not in ("auto", "flat", "smooth"):
        raise ValueError(f"{name}: shading must be 'auto', 'flat' or 'smooth', got {s!r}")
    return ("flat" if polygons else "smooth") if s == "auto" else s


VECTOR_TYPES = ("standard", "ambient", "unit")


def _vectortype(t, name):
    if t not in VECTOR_TYPES:
        raise ValueError(f"{name}: vectortype must be 'standard', 'ambient' or 'unit', got {t!r}")
    return t


# static/lib/colormap.js
COLORMAPS = ("viridis", "plasma", "inferno", "magma", "cividis", "coolwarm", "rdbu", "piyg",
             "twilight", "turbo", "gray", "blues")


def _defined_on(d, name):
    if d not in DEFINED_ON:
        raise ValueError(f"{name}: defined_on must be 'vertices' or 'faces', got {d!r}")
    return d


# ── Core geometry types ───────────────────────────────────────────────────────

def _polygon_edges(F) -> np.ndarray:
    """Unique undirected edges (m, 2) of validated polygons (see _polygons), int32."""
    if isinstance(F, np.ndarray):
        E = np.stack([F, np.roll(F, -1, axis=1)], axis=-1).reshape(-1, 2)
    else:                                       # ragged polygons
        E = np.concatenate([np.stack([f, np.roll(f, -1)], axis=1) for f in F]) \
            if len(F) else np.zeros((0, 2), np.int64)
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
                 material=None, shading: str = "auto"):
    """Mirrors ps.register_surface_mesh(). show=False registers the object hidden (its checkbox in the scene panel unticked).
    material (e.g. "glass") pins this mesh's shader; None follows the global Shader dropdown.

    Faces may be uniform (all same length) or ragged (polygons with different
    vertex counts).  Ragged faces are fan-triangulated for rendering.

    The unique polygon edges (before triangulation) always travel with the mesh as
    ``poly_edges``, pairs of indices into its vertices; the viewer draws them as tubes
    when show_edges=True or when "show edges" is ticked. edge_radius=0 means 3% of the
    median edge length.

    shading: "flat" (one normal per triangle: planar polygons look planar), "smooth"
    (vertex normals), or "auto" (default): flat for polygon meshes, smooth for triangle
    meshes.

    Arrays are numpy float32 / int32 (sent to the browser as binary, see
    kayviz.runtime.wire); ``kayviz.runtime.wire.jsonable`` turns them into lists.
    """
    verts = _points(vertices, name)
    F = _polygons(faces, name, len(verts) // 3)
    poly_edges = _polygon_edges(F)
    uniform = isinstance(F, np.ndarray)
    first_len = F.shape[1] if uniform else 3

    tris_per_face = None
    if not uniform or (face_size is None and first_len > 4):
        polys = F if not uniform else list(F)
        tris = [(f[0], f[t], f[t + 1]) for f in polys for t in range(1, len(f) - 1)]
        tris_per_face = [len(f) - 2 for f in polys]
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
        "color":         _rgb(color, name),
        "opacity":       _unit(opacity, name, "opacity"),
        "show_edges":    bool(show_edges),
        "show":          bool(show),
        "shading":       _shading(shading, name, polygons=not uniform or first_len > 3),
    }
    if show_edges:
        mesh_dict["edge_color"]  = _rgb(edge_color, name, "edge_color")
        mesh_dict["edge_radius"] = float(edge_radius)
    if material is not None:
        mesh_dict["material"] = str(material)
    return mesh_dict


def _size(x, name, what):
    """None (the viewer picks a size relative to the object) or a positive float."""
    if x is None:
        return None
    x = float(x)
    if not x >= 0:
        raise ValueError(f"{name}: {what} must be >= 0, got {x}")
    return x


def curve_network(name: str, vertices, edges, color=(0.8, 0.2, 0.2), radius: float | None = None,
                  show: bool = True):
    """Mirrors ps.register_curve_network(). show=False registers the object hidden (its checkbox in the scene panel unticked)."""
    verts = _points(vertices, name)
    return {
        "type":     "curve_network",
        "name":     name,
        "vertices": verts,
        "edges":    _i32(_indices(edges, name, "edges", len(verts) // 3, width=2)),
        "color":    _rgb(color, name),
        "radius":   _size(radius, name, "radius"),   # None: 0.15% of its size; 0: lines
        "show":     bool(show),
    }


def point_cloud(name: str, points, color=(0.2, 0.5, 0.8), radius=None, show: bool = True):
    """Mirrors ps.register_point_cloud(). show=False registers the object hidden (its checkbox in the scene panel unticked)."""
    return {
        "type":   "point_cloud",
        "name":   name,
        "points": _points(points, name, "points"),
        "color":  _rgb(color, name),
        "radius": _size(radius, name, "radius"),       # None: 0.5% of its size
        "show":   bool(show),
    }


def edge_child(target_name: str, vertices, edges,
               color=(0.1, 0.1, 0.1), radius: float = 0.0):
    """Edge overlay attached as a child of an existing surface_mesh."""
    verts = _points(vertices, target_name)
    return {
        "type":     "edge_child",
        "target":   target_name,
        "vertices": verts,
        "edges":    _i32(_indices(edges, target_name, "edges", len(verts) // 3, width=2)),
        "color":    _rgb(color, target_name, "edge color"),
        "radius":   float(radius),
    }


def scalar_quantity(target_name: str, field_name: str, values, defined_on="vertices",
                    show: bool | None = None, cmap: str = "viridis", vminmax=None):
    """Mirrors structure.add_scalar_quantity().

    cmap: one of COLORMAPS (diverging coolwarm / rdbu / piyg for signed data, cyclic
    twilight for angles). vminmax: (vmin, vmax) of the colour range; default the data
    range (finite values).

    show: None (default) follows the parent - hidden while the parent is hidden; True also
    shows the parent; False adds the quantity without displaying it.
    For a scalar, displaying it means colouring the mesh with it.
    """
    vals = _array(values, f"{target_name}::{field_name}", "values")
    if vals.ndim != 1:
        raise ValueError(f"{target_name}::{field_name}: values must be one number per "
                         f"{defined_on[:-1]}, got shape {vals.shape}")
    d = {
        "type":       "scalar_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": _defined_on(defined_on, f"{target_name}::{field_name}"),
        "values":     _f32(vals),          # NaN allowed: drawn in the NaN colour
    }
    q = f"{target_name}::{field_name}"
    if cmap not in COLORMAPS:
        raise ValueError(f"{q}: unknown cmap {cmap!r} (one of {', '.join(COLORMAPS)})")
    d["cmap"] = cmap
    if vminmax is not None:
        lo, hi = (float(x) for x in vminmax)
        if not lo < hi:
            raise ValueError(f"{q}: vminmax needs vmin < vmax, got {vminmax}")
        d["vminmax"] = [lo, hi]
    if show is not None:
        d["show"] = bool(show)
    return d


def vector_quantity(target_name: str, field_name: str, vectors, defined_on="vertices",
                    length: float | None = None, radius: float = None, show: bool | None = None,
                    color=None, vectortype: str = "standard"):
    """Mirrors structure.add_vector_quantity().

    defined_on: "vertices" (arrows at the vertices / points) or "faces" (at the face
    barycenters).
    show: None (default) follows the parent - hidden while the parent is hidden; True also
    shows the parent; False adds the quantity without displaying it.
    color: [r, g, b] in 0-1; None lets the viewer pick the next colour of its palette
    that no other vector quantity of the same parent uses.
    vectortype (as Polyscope): "standard" — arrows length × |v| / max|v|, so magnitudes
    compare; "ambient" — |v| in scene units (length is ignored); "unit" — all `length`.
    """
    q = f"{target_name}::{field_name}"
    d = {
        "type":       "vector_quantity",
        "target":     target_name,
        "name":       field_name,
        "defined_on": _defined_on(defined_on, q),
        "vectors":    _points(vectors, q, "vectors"),
        "vectortype": _vectortype(vectortype, q),
        "length":     _size(length, q, "length"),   # None: 4% of the parent's size
        "radius":     _size(radius, q, "radius"),   # None: 4% of the length
    }
    if show is not None:
        d["show"] = bool(show)
    if color is not None:
        d["color"] = _rgb(color, q)
    return d


def vector_field(name: str, origins, vectors, length: float | None = None,
                 radius: float = None, color=(0.2, 0.8, 0.4), show: bool = True,
                 vectortype: str = "standard"):
    """Arrow vector field — origins + direction vectors, rendered as cylinder+cone arrows.

    show=False registers the object hidden (its checkbox in the scene panel unticked).
    """
    o, v = _points(origins, name, "origins"), _points(vectors, name, "vectors")
    if len(o) != len(v):
        raise ValueError(f"{name}: {len(o) // 3} origins but {len(v) // 3} vectors")
    return {
        "type":    "vector_field",
        "name":    name,
        "origins": o,
        "vectors": v,
        "vectortype": _vectortype(vectortype, name),
        "length":  _size(length, name, "length"),
        "radius":  _size(radius, name, "radius"),
        "color":   _rgb(color, name),
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
