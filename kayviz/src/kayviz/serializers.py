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
from typing import NamedTuple

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
    """(N, 3) real coordinates -> flat float32 copy. Non-finite values warn.
    For directions (vectors); positions go through _positions."""
    return _f32(_checked_points(a, name, what))


# Positions travel relative to a scene origin, subtracted in float64 before the
# float32 cast: far from zero (geo-referenced data, 1e6 m) float32 keeps only
# ~0.06 m. Decided once, from the first positions of a scene (all later objects
# must share it, or they would be drawn in different frames): their rounded
# centre if they are far away, else none (nothing changes). kv.set_origin fixes
# it; set_origin(None) / kv.clear() start a new scene.
_origin: np.ndarray | None = None
_origin_decided = False
_origin_fixed = False           # set by the user: kept by kv.clear()
_origin_warned = False


def set_origin(origin) -> None:
    """Fix the scene origin (a 3D point), or None to decide it again from the next
    positions registered."""
    global _origin, _origin_decided, _origin_fixed
    global _origin_warned
    _origin_warned = False
    if origin is None:
        _origin, _origin_decided, _origin_fixed = None, False, False
        return
    o = np.asarray(origin, dtype=np.float64).reshape(-1)
    if o.shape != (3,) or not np.isfinite(o).all():
        raise ValueError(f"set_origin: a finite 3D point, got {origin!r}")
    _origin, _origin_decided, _origin_fixed = o, True, True


def _new_scene() -> None:
    """The scene was cleared: decide the origin again, unless the user fixed it."""
    global _origin, _origin_decided
    global _origin_warned
    if not _origin_fixed:
        _origin, _origin_decided, _origin_warned = None, False, False


def get_origin() -> np.ndarray | None:
    """The scene origin positions are sent relative to, or None."""
    return None if _origin is None else _origin.copy()


def _positions(a, name: str, what: str = "vertices") -> np.ndarray:
    """_points for positions: relative to the scene origin, which the first
    positions of a scene decide: their centre (rounded) when it is farther than
    max(1000 x their size, 1e4) from zero, else no origin."""
    global _origin, _origin_decided, _origin_warned
    arr = _checked_points(a, name, what)
    fin = arr[np.isfinite(arr).all(axis=1)] if len(arr) else arr
    if len(fin) and (not _origin_decided or (_origin is None and not _origin_warned)):
        lo, hi = fin.min(axis=0).astype(np.float64), fin.max(axis=0).astype(np.float64)
        centre, size = (lo + hi) / 2, float((hi - lo).max())
        far = np.abs(centre).max() > max(1000 * size, 1e4)
        if not _origin_decided:
            _origin_decided = True
            if far:
                step = 10.0 ** np.floor(np.log10(size)) if size > 0 else 1.0
                _origin = np.round(centre / step) * step
        elif far:
            _origin_warned = True
            warnings.warn(f"{name}: {what} around {np.abs(centre).max():.3g} lose precision "
                          f"in float32 (the scene's first objects chose no origin); call "
                          f"kv.set_origin(...) before registering, or kv.clear() first",
                          stacklevel=3)
    if _origin is not None:
        arr = np.asarray(arr, dtype=np.float64) - _origin
    return _f32(arr)


def _origin_entry() -> dict:
    """{"origin": [x, y, z]} for objects whose positions are shifted, else {}."""
    return {} if _origin is None else {"origin": _origin.tolist()}


def _checked_points(a, name: str, what: str) -> np.ndarray:
    """(N, 3) real coordinates, checked (not converted). Non-finite values warn."""
    arr = _array(a, name, what)
    if arr.ndim != 2 or arr.shape[1] != 3:
        hint = (" (2D points: add a zero z column, np.c_[P, np.zeros(len(P))])"
                if arr.ndim == 2 and arr.shape[1] == 2 else "")
        raise ValueError(f"{name}: {what} must have shape (N, 3), got {arr.shape}{hint}")
    bad = ~np.isfinite(arr).all(axis=1)
    if bad.any():
        warnings.warn(f"{name}: {int(bad.sum())} of {len(arr)} {what} are NaN or infinite",
                      stacklevel=4)
    return arr


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


class _Ragged(NamedTuple):
    """Polygons of different sizes: their indices one after another, and their sizes.
    One flat array instead of one small array per polygon keeps the work vectorized."""
    flat: np.ndarray        # int64
    lens: np.ndarray        # int64


def _polygons(faces, name: str, n: int):
    """Faces as a uniform (F, k) integer array, or _Ragged when sizes differ. In a 2D
    array, -1 at the end of a row pads a shorter polygon. A uniform array keeps its
    integer dtype (checking it needs no int64 copy, which is large for big meshes)."""
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
        if F.dtype.kind == "f":
            if not np.array_equal(F, np.round(F)):
                raise ValueError(f"{name}: faces must be integers")
            F = F.astype(np.int64)
        elif F.dtype.kind == "b":
            F = F.astype(np.int64)
        if F.dtype.kind == "u" or not (F < 0).any():
            if F.shape[1] < 3:
                raise ValueError(f"{name}: faces need at least 3 vertices, got {F.shape[1]}")
            _check_polygon_range(F, name, n)
            return F
        pad = F == -1
        # -1 pads the end of a row only: once -1, -1 up to the end of the row
        if (F < -1).any() or (pad[:, :-1] & ~pad[:, 1:]).any():
            raise ValueError(f"{name}: faces contain negative indices "
                             f"(-1 is allowed only as padding at the end of a row)")
        flat = F[~pad].astype(np.int64)
        lens = (~pad).sum(axis=1).astype(np.int64)
        _check_polygon_range(flat, name, n)
    else:
        parts = [np.asarray(f).ravel() for f in faces]
        lens = np.fromiter((len(p) for p in parts), np.int64, len(parts))
        flat = (_indices(np.concatenate(parts), name, "faces", n) if parts
                else np.zeros(0, np.int64))
    small = np.nonzero(lens < 3)[0]
    if len(small):
        raise ValueError(f"{name}: {len(small)} face(s) have fewer than 3 vertices "
                         f"(first: face {small[0]})")
    return _Ragged(flat, lens)


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

def _nonconvex(V: np.ndarray, F: np.ndarray, corners: int = 16384) -> np.ndarray:
    """(m,) True for the polygons F (m, k) of vertices V that are not convex in their
    plane (seen along the Newell normal). Degenerate polygons count as convex (fan).
    In blocks of about *corners* corners: the float64 temporaries are ~20 arrays of
    (m, k, 3), which peaked at 12x the mesh when done at once."""
    block = max(1, corners // max(1, F.shape[1]))
    return np.concatenate([_nonconvex_block(V[F[i:i + block]].astype(np.float64))
                           for i in range(0, len(F), block)] or [np.zeros(0, bool)])


def _nonconvex_block(Q: np.ndarray) -> np.ndarray:
    nxt = np.roll(Q, -1, axis=1)
    normal = np.cross(Q, nxt).sum(axis=1)                       # Newell: 2 x area normal
    turn = np.cross(Q - np.roll(Q, 1, axis=1), nxt - Q)          # at each vertex
    c = np.einsum("mkd,md->mk", turn, normal)
    tol = 1e-9 * np.abs(c).max(axis=1, keepdims=True)
    return (c < -tol).any(axis=1)


def _ear_clip(P: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangles (local indices) of one simple polygon P (k, 3), by ear clipping in
    its plane; a fan if the polygon is degenerate or not simple."""
    k = len(P)
    fan = [(0, t, t + 1) for t in range(1, k - 1)]
    n = np.cross(P, np.roll(P, -1, axis=0)).sum(axis=0)
    if not np.linalg.norm(n) > 0:
        return fan
    n = n / np.linalg.norm(n)
    u = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    Q = np.stack([P @ u, P @ np.cross(n, u)], axis=1)            # counter-clockwise
    cross = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    idx, tris = list(range(k)), []
    while len(idx) > 3:
        for j in range(len(idx)):
            a, b, c = idx[j - 1], idx[j], idx[(j + 1) % len(idx)]
            if cross(Q[a], Q[b], Q[c]) <= 0:
                continue                                         # reflex vertex
            if any(cross(Q[a], Q[b], Q[p]) >= 0 and cross(Q[b], Q[c], Q[p]) >= 0 and
                   cross(Q[c], Q[a], Q[p]) >= 0 for p in idx if p not in (a, b, c)):
                continue                                         # another vertex inside
            tris.append((a, b, c))
            idx.pop(j)
            break
        else:
            return fan                                           # not simple
    tris.append(tuple(idx))
    return tris


def _triangulate(polys, V: np.ndarray, name: str = "") -> tuple[np.ndarray, np.ndarray]:
    """Triangles (T, 3) in face order and triangles per face. Convex polygons are
    fanned from their first vertex; non-convex ones are ear-clipped (a fan would
    cover area outside them). Vectorized per polygon size; *polys* is a uniform
    (F, k) array or _Ragged."""
    uniform = isinstance(polys, np.ndarray)
    sizes = np.full(len(polys), polys.shape[1]) if uniform else polys.lens
    first = None if uniform else np.cumsum(sizes) - sizes
    tpf = sizes - 2
    start = np.concatenate([[0], np.cumsum(tpf)[:-1]])
    T = np.empty((int(tpf.sum()), 3), np.int64)
    for k in np.unique(sizes):
        rows = np.nonzero(sizes == k)[0]
        F = polys if uniform else polys.flat[first[rows][:, None] + np.arange(k)]
        t = np.arange(1, k - 1)
        tris = np.stack([np.repeat(F[:, :1], k - 2, axis=1), F[:, t], F[:, t + 1]], axis=-1)
        if k > 3:
            bad = np.nonzero(_nonconvex(V, F))[0]
            if len(bad) > max(1000, len(rows) // 5):
                # most of them: twisted (non-planar) faces rather than non-convex
                # panels; ear clipping in a plane means little there, and is slow
                warnings.warn(f"{name}: {len(bad)} of {len(rows)} faces with {k} vertices are "
                              f"not convex in their plane (or not planar); drawn as fans",
                              stacklevel=4)
                bad = bad[:0]
            for r in bad:
                tris[r] = F[r][np.array(_ear_clip(V[F[r]].astype(np.float64)))]
        T[(start[rows][:, None] + np.arange(k - 2)).ravel()] = tris.reshape(-1, 3)
    return T, tpf


def surface_mesh(name: str, vertices, faces, color=(0.8, 0.8, 0.8),
                 face_size=None, opacity=1.0, show_edges=False,
                 edge_color=(0.1, 0.1, 0.1), edge_radius: float = 0.0, show: bool = True,
                 material=None, shading: str = "auto"):
    """Mirrors ps.register_surface_mesh(). show=False registers the object hidden (its checkbox in the scene panel unticked).
    material (e.g. "glass") pins this mesh's shader; None follows the global Shader dropdown.

    Faces may be uniform (all same length) or ragged (polygons with different
    vertex counts).  Ragged faces are fan-triangulated for rendering.

    No edges are sent: the viewer finds the sides of the original polygons (not the
    diagonals of their triangulation) from the faces and ``tris_per_face``, only when
    they are shown, and draws them as tubes when show_edges=True or when "show edges"
    is ticked. edge_radius=0 means 3% of the median edge length.

    shading: "flat" (one normal per triangle: planar polygons look planar), "smooth"
    (vertex normals), or "auto" (default): flat for polygon meshes, smooth for triangle
    meshes.

    Arrays are numpy float32 / int32 (sent to the browser as binary, see
    kayviz.runtime.wire); ``kayviz.runtime.wire.jsonable`` turns them into lists.
    """
    verts = _positions(vertices, name)
    F = _polygons(faces, name, len(verts) // 3)
    uniform = isinstance(F, np.ndarray)
    first_len = F.shape[1] if uniform else 3
    triangles = uniform and first_len == 3
    V3 = verts.reshape(-1, 3)              # a view; checks convert blocks to float64
    tris_per_face = None
    # Uniform triangles and convex quads go as they are (the viewer fans the quads);
    # larger, mixed or non-convex polygons are triangulated here.
    quads_bent = uniform and first_len == 4 and face_size is None and _nonconvex(V3, F).any()
    if not uniform or (face_size is None and first_len > 4) or quads_bent:
        tris, tris_per_face = _triangulate(F, V3, name)
        faces_arr = _i32(tris)
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
    mesh_dict.update(_origin_entry())
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
    verts = _positions(vertices, name)
    return {
        "type":     "curve_network",
        "name":     name,
        "vertices": verts,
        "edges":    _i32(_indices(edges, name, "edges", len(verts) // 3, width=2)),
        "color":    _rgb(color, name),
        "radius":   _size(radius, name, "radius"),   # None: 0.15% of its size; 0: lines
        "show":     bool(show),
        **_origin_entry(),
    }


def point_cloud(name: str, points, color=(0.2, 0.5, 0.8), radius=None, show: bool = True,
                point_render: str = "sprite"):
    """Mirrors ps.register_point_cloud(). show=False registers the object hidden (its checkbox in the scene panel unticked).
    point_render: "sprite" (default; one quad per point, shaded as a sphere: fast for
    millions of points, no studio shadow/AO) or "sphere" (real sphere geometry)."""
    if point_render not in ("sprite", "sphere"):
        raise ValueError(f"{name}: point_render must be 'sprite' or 'sphere', got {point_render!r}")
    return {
        "type":   "point_cloud",
        "name":   name,
        "points": _positions(points, name, "points"),
        "color":  _rgb(color, name),
        "radius": _size(radius, name, "radius"),       # None: 0.5% of its size
        "show":   bool(show),
        "render": point_render,
        **_origin_entry(),
    }


def edge_child(target_name: str, vertices, edges,
               color=(0.1, 0.1, 0.1), radius: float = 0.0):
    """Edge overlay attached as a child of an existing surface_mesh."""
    verts = _positions(vertices, target_name)
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
    o, v = _positions(origins, name, "origins"), _points(vectors, name, "vectors")
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
        **_origin_entry(),
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
