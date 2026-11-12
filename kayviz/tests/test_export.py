"""kayviz.exporter / kv.export: OBJ and PLY round trips."""

import numpy as np
import pytest

from kayviz import exporter
from kayviz import serializers as ser


@pytest.fixture(autouse=True)
def fresh_origin():
    ser.set_origin(None)
    yield
    ser.set_origin(None)


def _star(c, k=5, r_in=0.4, r_out=1.0):
    t = np.arange(2 * k) * np.pi / k
    r = np.where(np.arange(2 * k) % 2, r_in, r_out)
    return np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t), np.zeros(2 * k)]


def _mixed():
    """A triangle, a quad, a hexagon and two non-convex stars (ear clipped)."""
    V = [np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float),
         np.array([[2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0]], float),
         np.c_[4 + np.cos(np.arange(6) / 6 * 2 * np.pi), np.sin(np.arange(6) / 6 * 2 * np.pi),
               np.zeros(6)], _star((8, 0)), _star((11, 0))]
    sizes = [len(v) for v in V]
    start = np.cumsum([0] + sizes[:-1])
    return np.vstack(V), [list(range(s, s + n)) for s, n in zip(start, sizes)]


def _same_cycle(a, b):
    a, b = list(a), list(b)
    return len(a) == len(b) and any(a[i:] + a[:i] == b for i in range(len(a)))


def read_obj(path):
    V, F, L = [], [], []
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            V.append([float(x) for x in p[1:4]])
        elif p[0] == "f":
            F.append([int(x) - 1 for x in p[1:]])
        elif p[0] == "l":
            L.append([int(x) - 1 for x in p[1:]])
    return np.array(V), F, L


def read_ply(path):
    data = open(path, "rb").read()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    head = data[:end].decode().splitlines()
    elements, cur = [], None
    for line in head:
        p = line.split()
        if p[0] == "element":
            cur = (p[1], int(p[2]), []); elements.append(cur)
        elif p[0] == "property":
            cur[2].append(p[1:])
    types = {"float": "<f4", "double": "<f8", "int": "<i4", "uchar": "u1"}
    off, out = end, {}
    for name, n, props in elements:
        rows = []
        for _ in range(n):
            row = {}
            for prop in props:
                if prop[0] == "list":
                    k = int(np.frombuffer(data, types[prop[1]], 1, off)[0]); off += 1
                    row[prop[3]] = np.frombuffer(data, types[prop[2]], k, off).tolist(); off += 4 * k
                else:
                    dt = np.dtype(types[prop[0]])
                    row[prop[1]] = np.frombuffer(data, dt, 1, off)[0].item(); off += dt.itemsize
            rows.append(row)
        out[name] = rows
    assert off == len(data)
    return out


def test_obj_keeps_the_registered_polygons(tmp_path):
    V, F = _mixed()
    d = ser.surface_mesh("M", V, F)
    assert d["tris_per_face"] is not None                 # triangulated in Python
    Vb, Fb, _ = read_obj(exporter.write(tmp_path / "m.obj", d))
    assert np.allclose(Vb, V, atol=1e-6)
    assert len(Fb) == len(F) and all(_same_cycle(a, b) for a, b in zip(F, Fb))


@pytest.mark.parametrize("faces", ["quads", "padded"])
def test_uniform_and_padded_faces(tmp_path, faces):
    V = np.random.default_rng(0).random((9, 3)) * [1, 1, 0]
    quads = [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]]
    F = np.array(quads) if faces == "quads" else np.array([[0, 1, 3, -1]] + quads[1:])
    want = [[0, 1, 3]] + quads[1:] if faces == "padded" else quads
    _, Fb, _ = read_obj(exporter.write(tmp_path / "q.obj", ser.surface_mesh("Q", V, F)))
    assert all(_same_cycle(a, b) for a, b in zip(want, Fb))


def test_ply_far_coordinates_and_scalars(tmp_path):
    V, F = _mixed()
    V = V + [4_512_345.0, 1_234_567.0, 312.0]
    d = ser.surface_mesh("M", V, F)
    vs = ser.scalar_quantity("M", "height", np.arange(len(V), dtype=float))
    fs = ser.scalar_quantity("M", "area ratio", np.arange(len(F), dtype=float) / 10,
                             defined_on="faces")
    ply = read_ply(exporter.write(tmp_path / "m.ply", d, [vs, fs]))
    P = np.array([[r["x"], r["y"], r["z"]] for r in ply["vertex"]])
    assert np.abs(P - V).max() < 1e-6                     # doubles, origin added back
    assert [r["height"] for r in ply["vertex"]] == list(range(len(V)))
    assert all(_same_cycle(a, r["vertex_indices"]) for a, r in zip(F, ply["face"]))
    assert np.allclose([r["area_ratio"] for r in ply["face"]], np.arange(len(F)) / 10)


def test_curves_and_points(tmp_path):
    P = np.random.default_rng(1).random((5, 3))
    E = np.array([[0, 1], [1, 2], [3, 4]])
    Vb, _, L = read_obj(exporter.write(tmp_path / "c.obj", ser.curve_network("C", P, E)))
    assert np.allclose(Vb, P, atol=1e-6) and L == E.tolist()
    ply = read_ply(exporter.write(tmp_path / "c.ply", ser.curve_network("C", P, E)))
    assert [[r["vertex1"], r["vertex2"]] for r in ply["edge"]] == E.tolist()
    ply = read_ply(exporter.write(tmp_path / "p.ply", ser.point_cloud("P", P)))
    assert len(ply["vertex"]) == 5 and "face" not in ply


def test_kv_export_finds_the_object_and_refuses_unknown(tmp_path):
    import os, subprocess, sys, textwrap
    code = textwrap.dedent(f'''
        import numpy as np, kayviz as kv
        kv.init()
        kv.register_surface_mesh("Sq", np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0.]]), [[0,1,2,3]])
        kv.add_scalar_quantity("Sq", "h", np.arange(4.0))
        print(kv.export("Sq", r"{tmp_path / 'sq.ply'}"))
        try:
            kv.export("Nope", r"{tmp_path / 'x.obj'}")
        except ValueError as e:
            print("refused", e)
    ''')
    env = dict(os.environ, KAYVIZ_NO_BROWSER="1",
               KAYVIZ_PORT=str(int(os.environ.get("KAYVIZ_TEST_PORT_BASE", "18700")) + 120))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "refused" in out.stdout and "Nope" in out.stdout
    ply = read_ply(tmp_path / "sq.ply")
    assert [r["h"] for r in ply["vertex"]] == [0, 1, 2, 3]
    assert _same_cycle([0, 1, 2, 3], ply["face"][0]["vertex_indices"])
