"""
exporter.py — write what the viewer shows to OBJ or PLY, from the Python side.

Works on serializer dicts (the scene buffer holds them; kv.export looks them up by
name), so no browser is needed. Surface meshes come out as the polygons that
were registered: polygons Python triangulated are rebuilt from their triangles
(``tris_per_face``) by walking each polygon's boundary in the triangles' winding
(a diagonal is shared by two triangles of its polygon, a side by one). Positions
get the scene origin added back (see serializers.set_origin).

OBJ: ``v`` lines, ``f`` polygons (surface meshes), ``l`` segments (curves).
PLY (binary little endian): x, y, z (double when an origin was used, else float),
vertex and face scalars as properties, faces as index lists, curve edges as an
``edge`` element.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def polygons(obj: dict) -> list[np.ndarray]:
    """The polygons of a surface_mesh dict, as registered (vertex index arrays)."""
    F = np.asarray(obj["faces"], dtype=np.int64)
    tpf = obj.get("tris_per_face")
    if tpf is None:
        k = int(obj.get("face_size", 3))
        return list(F.reshape(-1, k))
    T = F.reshape(-1, 3)
    out, t = [], 0
    for n in np.asarray(tpf, dtype=np.int64):
        out.append(_boundary(T[t:t + n]))
        t += n
    return out


def _boundary(tris: np.ndarray) -> np.ndarray:
    """Vertex cycle of the polygon triangulated by *tris*, in their winding."""
    if len(tris) == 1:
        return tris[0].copy()
    directed = [(a, b) for tri in tris for a, b in ((tri[0], tri[1]), (tri[1], tri[2]),
                                                    (tri[2], tri[0]))]
    count: dict[tuple, int] = {}
    for a, b in directed:
        key = (a, b) if a < b else (b, a)
        count[key] = count.get(key, 0) + 1
    nxt = {a: b for a, b in directed if count[(a, b) if a < b else (b, a)] == 1}
    start = tris[0][0]
    cycle = [start]
    while len(cycle) <= len(nxt):
        v = nxt.get(cycle[-1])
        if v is None or v == start:
            break
        cycle.append(v)
    return np.asarray(cycle, dtype=np.int64)


def _positions(obj: dict, key: str) -> np.ndarray:
    P = np.asarray(obj[key], dtype=np.float64).reshape(-1, 3)
    if obj.get("origin") is not None:
        P = P + np.asarray(obj["origin"], dtype=np.float64)
    return P


def write(path, obj: dict, quantities: list[dict] = (), fmt: str | None = None) -> Path:
    """Write one serializer dict (surface_mesh, curve_network or point_cloud) and its
    scalar quantities to *path* (.obj or .ply, or *fmt*)."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in ("obj", "ply"):
        raise ValueError(f"export: unknown format {fmt!r} (obj or ply)")
    kind, name = obj.get("type"), obj.get("name")
    if kind == "surface_mesh":
        V, faces, edges = _positions(obj, "vertices"), polygons(obj), None
    elif kind == "curve_network":
        V, faces = _positions(obj, "vertices"), None
        edges = np.asarray(obj["edges"], dtype=np.int64).reshape(-1, 2)
    elif kind == "point_cloud":
        V, faces, edges = _positions(obj, "points"), None, None
    else:
        raise ValueError(f"export: {name!r} is a {kind}; only surface meshes, curve "
                         f"networks and point clouds can be exported")
    if fmt == "obj":
        _write_obj(path, name, V, faces, edges)
    else:
        _write_ply(path, V, faces, edges, list(quantities), obj.get("origin") is not None)
    return path


def _write_obj(path, name, V, faces, edges):
    with open(path, "w") as f:
        f.write(f"# kayviz export: {name}\no {name}\n")
        np.savetxt(f, V, fmt="v %.17g %.17g %.17g")
        if faces is not None:
            f.writelines("f " + " ".join(str(int(i) + 1) for i in p) + "\n" for p in faces)
        if edges is not None:
            np.savetxt(f, edges + 1, fmt="l %d %d")


def _write_ply(path, V, faces, edges, quantities, double):
    scal = {"vertices": [], "faces": []}
    for q in quantities:
        if q.get("type") == "scalar_quantity" and q.get("defined_on") in scal:
            scal[q["defined_on"]].append(q)
    n_faces = 0 if faces is None else len(faces)
    for on, n in (("vertices", len(V)), ("faces", n_faces)):
        for q in scal[on]:
            if len(q["values"]) != n:
                raise ValueError(f"export: {q['target']}::{q['name']} has {len(q['values'])} "
                                 f"values for {n} {on}")
    ftype, fdt = ("double", "<f8") if double else ("float", "<f4")
    head = ["ply", "format binary_little_endian 1.0", "comment kayviz export",
            f"element vertex {len(V)}", f"property {ftype} x", f"property {ftype} y",
            f"property {ftype} z"]
    head += [f"property float {_prop(q['name'])}" for q in scal["vertices"]]
    if faces is not None:
        head += [f"element face {n_faces}", "property list uchar int vertex_indices"]
        head += [f"property float {_prop(q['name'])}" for q in scal["faces"]]
    if edges is not None:
        head += [f"element edge {len(edges)}", "property int vertex1", "property int vertex2"]
    head.append("end_header")
    with open(path, "wb") as f:
        f.write(("\n".join(head) + "\n").encode())
        vt = np.dtype([("p", fdt, 3)] + [(f"s{i}", "<f4") for i in range(len(scal["vertices"]))])
        vrec = np.empty(len(V), vt)
        vrec["p"] = V
        for i, q in enumerate(scal["vertices"]):
            vrec[f"s{i}"] = q["values"]
        f.write(vrec.tobytes())
        if faces is not None:
            fq = [np.asarray(q["values"], "<f4") for q in scal["faces"]]
            for j, p in enumerate(faces):
                if len(p) > 255:
                    raise ValueError("export: PLY face lists hold at most 255 vertices")
                f.write(np.uint8(len(p)).tobytes() + np.asarray(p, "<i4").tobytes()
                        + b"".join(v[j].tobytes() for v in fq))
        if edges is not None:
            f.write(np.asarray(edges, "<i4").tobytes())


def _prop(name: str) -> str:
    """A PLY property name: no spaces."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name) or "scalar"
