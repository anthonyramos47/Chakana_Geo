"""
Synthetic benchmark scenes for kayviz.evaluate.

Every scene generator is deterministic (seeded with np.random.default_rng(0)),
uses numpy only, and returns a list of ``(kind, kwargs)`` pairs matching the
functions in ``kayviz.serializers``.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from kayviz import serializers as ser


def _icosphere(subdivisions: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Unit icosphere: 12 vertices / 20 triangles at level 0; 642 vertices /
    1,280 triangles at level 3."""
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = np.array([
        [-1,  t,  0], [ 1,  t,  0], [-1, -t,  0], [ 1, -t,  0],
        [ 0, -1,  t], [ 0,  1,  t], [ 0, -1, -t], [ 0,  1, -t],
        [ t,  0, -1], [ t,  0,  1], [-t,  0, -1], [-t,  0,  1],
    ], dtype=np.float64)
    verts /= np.linalg.norm(verts, axis=1, keepdims=True)
    faces = np.array([
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ], dtype=np.int32)

    for _ in range(subdivisions):
        edges = np.stack([
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ], axis=1).reshape(-1, 2)
        undirected = np.sort(edges, axis=1)
        unique_edges, inv = np.unique(undirected, axis=0, return_inverse=True)
        mids = verts[unique_edges[:, 0]] + verts[unique_edges[:, 1]]
        mids /= np.linalg.norm(mids, axis=1, keepdims=True)
        mid_idx = (len(verts) + inv).astype(np.int32).reshape(-1, 3)
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        m0, m1, m2 = mid_idx[:, 0], mid_idx[:, 1], mid_idx[:, 2]
        verts = np.vstack([verts, mids])
        faces = np.concatenate([
            np.stack([a, m0, m2], axis=1),
            np.stack([b, m1, m0], axis=1),
            np.stack([c, m2, m1], axis=1),
            np.stack([m0, m1, m2], axis=1),
        ], axis=0)

    return verts.astype(np.float32), faces.astype(np.int32)


def _grid_mesh(nx: int, ny: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Subdivided (nx x ny) grid surface with 2 * nx * ny triangles."""
    x = np.linspace(-1.0, 1.0, nx + 1, dtype=np.float32)
    y = np.linspace(-1.0, 1.0, ny + 1, dtype=np.float32)
    xx, yy = np.meshgrid(x, y, indexing="ij")
    noise = rng.normal(0.0, 1e-3, size=xx.shape).astype(np.float32)
    zz = (0.15 * np.sin(3.0 * xx) * np.cos(3.0 * yy) + noise).astype(np.float32)
    verts = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)

    row = np.arange(nx, dtype=np.int32)[:, None] * (ny + 1)
    col = np.arange(ny, dtype=np.int32)[None, :]
    i0 = (row + col).ravel()
    i1 = i0 + (ny + 1)
    i2 = i1 + 1
    i3 = i0 + 1

    faces = np.empty((2 * nx * ny, 3), dtype=np.int32)
    faces[0::2, 0] = i0
    faces[0::2, 1] = i1
    faces[0::2, 2] = i2
    faces[1::2, 0] = i0
    faces[1::2, 1] = i2
    faces[1::2, 2] = i3
    return verts, faces


def _scene_empty() -> list[tuple[str, dict]]:
    np.random.default_rng(0)
    return []


def _scene_objects_1k() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    v0, f0 = _icosphere(3)
    centers = rng.uniform(-10.0, 10.0, size=(1000, 3)).astype(np.float32)
    radii = rng.uniform(0.1, 0.3, size=1000).astype(np.float32)
    return [
        ("surface_mesh", {
            "name": f"sphere_{i}",
            "vertices": v0 * radii[i] + centers[i],
            "faces": f0.copy(),
        })
        for i in range(1000)
    ]


def _scene_mesh_100k() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    verts, faces = _grid_mesh(250, 200, rng)
    return [("surface_mesh", {"name": "mesh", "vertices": verts, "faces": faces})]


def _scene_mesh_2m() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    verts, faces = _grid_mesh(1000, 1000, rng)
    return [("surface_mesh", {"name": "mesh", "vertices": verts, "faces": faces})]


def _scene_merged_12m() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    v0, f0 = _icosphere(3)
    n = 10_000
    centers = rng.uniform(-50.0, 50.0, size=(n, 3)).astype(np.float32)
    verts = (v0[None, :, :] * np.float32(0.2) + centers[:, None, :]).reshape(-1, 3)
    offsets = (np.arange(n, dtype=np.int32) * len(v0))[:, None, None]
    faces = (f0[None, :, :] + offsets).reshape(-1, 3)
    return [("surface_mesh", {"name": "merged", "vertices": verts, "faces": faces})]


def _scene_ngon_200k() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    n_quads = 50_000
    n_hex = 24_500
    n_l = 500

    q_tpl = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32)
    ang = np.linspace(0.0, 2.0 * np.pi, 6, endpoint=False, dtype=np.float32)
    h_tpl = np.stack([np.cos(ang), np.sin(ang), np.zeros(6, dtype=np.float32)], axis=1)
    l_tpl = np.array([
        [0, 0, 0], [2, 0, 0], [2, 1, 0],
        [1, 1, 0], [1, 2, 0], [0, 2, 0],
    ], dtype=np.float32)

    q_centers = rng.uniform(-50.0, 50.0, size=(n_quads, 1, 3)).astype(np.float32)
    h_centers = rng.uniform(-50.0, 50.0, size=(n_hex, 1, 3)).astype(np.float32)
    l_centers = rng.uniform(-50.0, 50.0, size=(n_l, 1, 3)).astype(np.float32)

    vq = (q_tpl[None, :, :] + q_centers).reshape(-1, 3)
    vh = (h_tpl[None, :, :] + h_centers).reshape(-1, 3)
    vl = (l_tpl[None, :, :] + l_centers).reshape(-1, 3)
    verts = np.vstack([vq, vh, vl])

    fq = np.arange(4 * n_quads, dtype=np.int32).reshape(n_quads, 4)
    fh = (4 * n_quads + np.arange(6 * n_hex, dtype=np.int32)).reshape(n_hex, 6)
    fl = (4 * n_quads + 6 * n_hex + np.arange(6 * n_l, dtype=np.int32)).reshape(n_l, 6)
    faces = list(fq) + list(fh) + list(fl)
    return [("surface_mesh", {"name": "ngons", "vertices": verts, "faces": faces})]


def _scene_points_1m() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    pts = rng.standard_normal((1_000_000, 3), dtype=np.float32)
    return [("point_cloud", {"name": "points", "points": pts})]


def _scene_curves_200k() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    n_edges = 200_000
    t = np.linspace(0.0, 200.0 * np.pi, n_edges + 1, dtype=np.float32)
    verts = np.stack([np.cos(t), np.sin(t), t * np.float32(0.01)], axis=1)
    verts += rng.normal(0.0, 1e-3, size=verts.shape).astype(np.float32)
    idx = np.arange(n_edges, dtype=np.int32)
    edges = np.stack([idx, idx + 1], axis=1)
    return [("curve_network", {"name": "curves", "vertices": verts, "edges": edges})]


def _scene_quantities() -> list[tuple[str, dict]]:
    rng = np.random.default_rng(0)
    verts, faces = _grid_mesh(1000, 1000, rng)
    v_scalar = verts[:, 2].copy()
    f_scalar = verts[faces[:, 0], 2].copy()
    v_vectors = rng.standard_normal(verts.shape, dtype=np.float32)
    return [
        ("surface_mesh", {"name": "mesh", "vertices": verts, "faces": faces}),
        ("scalar_quantity", {
            "target_name": "mesh",
            "field_name": "v_scalar",
            "values": v_scalar,
            "defined_on": "vertices",
        }),
        ("scalar_quantity", {
            "target_name": "mesh",
            "field_name": "f_scalar",
            "values": f_scalar,
            "defined_on": "faces",
        }),
        ("vector_quantity", {
            "target_name": "mesh",
            "field_name": "v_vectors",
            "vectors": v_vectors,
            "defined_on": "vertices",
        }),
    ]


SCENES: dict[str, Callable[[], list[tuple[str, dict]]]] = {
    "empty":       _scene_empty,
    "objects-1k":  _scene_objects_1k,
    "mesh-100k":   _scene_mesh_100k,
    "mesh-2M":     _scene_mesh_2m,
    "merged-12M":  _scene_merged_12m,
    "ngon-200k":   _scene_ngon_200k,
    "points-1M":   _scene_points_1m,
    "curves-200k": _scene_curves_200k,
    "quantities":  _scene_quantities,
}

SMALL_SCENES: tuple[str, ...] = (
    "empty",
    "objects-1k",
    "mesh-100k",
    "ngon-200k",
    "curves-200k",
)

LARGE_SCENES: tuple[str, ...] = tuple(SCENES.keys())


def resolve_scenes(spec: str = "small") -> list[str]:
    """Turn 'small', 'large' or a comma-separated list of scene ids into a list."""
    out: list[str] = []
    for part in (spec or "small").split(","):
        token = part.strip()
        if not token:
            continue
        if token == "small":
            names = SMALL_SCENES
        elif token in ("large", "all"):
            names = LARGE_SCENES
        elif token in SCENES:
            names = (token,)
        else:
            raise ValueError(f"unknown scene {token!r} (known: {', '.join(SCENES)})")
        for n in names:
            if n not in out:
                out.append(n)
    return out


def serialize_call(kind: str, kwargs: dict) -> dict:
    """Run the matching kayviz.serializers function on one (kind, kwargs) pair."""
    fn = getattr(ser, kind, None)
    if fn is None:
        raise ValueError(f"unknown serializer kind {kind!r}")
    return fn(**kwargs)


def serialize_scene(calls: list[tuple[str, dict]]) -> list[dict]:
    """Serialize every registration call of a scene."""
    return [serialize_call(kind, kw) for kind, kw in calls]


def register_call(kind: str, kwargs: dict) -> None:
    """Register one (kind, kwargs) pair through the public kayviz scripting API."""
    import kayviz as kv

    if kind == "surface_mesh":
        kv.register_surface_mesh(**kwargs)
    elif kind == "curve_network":
        kv.register_curve_network(**kwargs)
    elif kind == "point_cloud":
        kv.register_point_cloud(**kwargs)
    elif kind == "vector_field":
        kv.register_vector_field(**kwargs)
    elif kind == "scalar_quantity":
        kw = dict(kwargs)
        target = kw.pop("target_name", kw.pop("target", None))
        kv.add_scalar_quantity(target, **kw)
    elif kind == "vector_quantity":
        kw = dict(kwargs)
        target = kw.pop("target_name", kw.pop("target", None))
        kv.add_vector_quantity(target, **kw)
    else:
        raise ValueError(f"unknown registration kind {kind!r}")


def register_scene(calls: list[tuple[str, dict]]) -> None:
    """Register every call of a scene into the active kayviz server."""
    for kind, kw in calls:
        register_call(kind, kw)


def raw_geometry_bytes(calls: list[tuple[str, dict]]) -> int:
    """Raw geometry size in bytes (float32 coordinates/scalars + int32 indices)."""
    total = 0
    for kind, kw in calls:
        if kind == "surface_mesh":
            verts = np.asarray(kw["vertices"])
            total += int(verts.size) * 4
            faces = kw["faces"]
            if isinstance(faces, np.ndarray):
                total += int(faces.size) * 4
            else:
                total += sum(len(f) for f in faces) * 4
        elif kind == "point_cloud":
            pts = np.asarray(kw["points"])
            total += int(pts.size) * 4
        elif kind == "curve_network":
            verts = np.asarray(kw["vertices"])
            edges = np.asarray(kw["edges"])
            total += int(verts.size) * 4 + int(edges.size) * 4
        elif kind == "vector_field":
            origins = np.asarray(kw["origins"])
            vectors = np.asarray(kw["vectors"])
            total += (int(origins.size) + int(vectors.size)) * 4
        elif kind == "scalar_quantity":
            vals = np.asarray(kw["values"])
            total += int(vals.size) * 4
        elif kind == "vector_quantity":
            vecs = np.asarray(kw["vectors"])
            total += int(vecs.size) * 4
    return total
