"""Binary message format (kayviz.runtime.wire) and the array-based serializers."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from kayviz import serializers as ser
from kayviz.runtime.wire import decode, encode, jsonable


def test_message_without_arrays_is_json_text():
    msg = {"action": "clear", "objects": [{"name": "A", "color": [1.0, 0.0, 0.0]}]}
    out = encode(msg)
    assert isinstance(out, str) and json.loads(out) == msg


def test_arrays_round_trip_as_4_byte_types():
    msg = {"action": "scene_update", "objects": [
        {"name": "M", "vertices": np.arange(7, dtype=np.float64) / 3,   # -> f32
         "faces": np.arange(5, dtype=np.int64),                         # -> i32
         "flags": np.array([1, 2], dtype=np.uint32), "color": [0.1, 0.2, 0.3]}]}
    out = encode(msg)
    assert isinstance(out, (bytes, bytearray))
    back = decode(out)["objects"][0]
    assert back["vertices"].dtype == np.float32
    np.testing.assert_allclose(back["vertices"], np.arange(7) / 3, rtol=1e-6)
    assert back["faces"].dtype == np.int32 and back["faces"].tolist() == [0, 1, 2, 3, 4]
    assert back["flags"].dtype == np.uint32
    assert back["color"] == [0.1, 0.2, 0.3]


def test_arrays_are_8_byte_aligned():
    # Float32Array views need 4-byte alignment; the format pads every array to 8.
    out = encode({"a": np.ones(3, np.float32), "b": np.ones(1, np.int32)})
    header = json.loads(out[4:4 + int.from_bytes(out[:4], "little")])
    assert header["a"]["__b"] % 8 == 0 and header["b"]["__b"] % 8 == 0


def test_jsonable_turns_arrays_into_lists():
    d = jsonable({"v": np.zeros(2, np.float32), "n": np.int32(3), "l": [np.ones(1)]})
    assert d == {"v": [0.0, 0.0], "n": 3, "l": [[1.0]]}
    json.dumps(d)


def _grid(n):
    V = np.array([[i, j, 0.0] for i in range(n) for j in range(n)])
    F = [[i * n + j, (i + 1) * n + j, (i + 1) * n + j + 1, i * n + j + 1]
         for i in range(n - 1) for j in range(n - 1)]
    return V, F


def test_no_edges_are_sent():
    # The viewer finds the polygon sides itself (static/lib/edges.js).
    V, F = _grid(3)
    d = ser.surface_mesh("Q", V, F)
    assert "poly_edges" not in d and "poly_edge_verts" not in d


def test_ragged_faces_triangulation():
    V = np.zeros((5, 3))
    d = ser.surface_mesh("R", V, [[0, 1, 2], [0, 2, 3, 4]])
    assert d["tris_per_face"].tolist() == [1, 2] and d["face_size"] == 3


def _reference_edges(polys):
    return {tuple(sorted((int(f[i]), int(f[(i + 1) % len(f)])))) for f in polys for i in range(len(f))}


def _viewer_edges(d):
    """Edges the viewer finds (static/lib/edges.js, run with node) for mesh dict *d*."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    edges_js = Path(ser.__file__).parent / "static" / "lib" / "edges.js"
    tpf = d.get("tris_per_face")
    script = (f"import {{ polygonEdges }} from {json.dumps(edges_js.as_uri())};\n"
              f"const E = polygonEdges({json.dumps(d['faces'].tolist())}, {d['face_size']}, "
              f"{json.dumps(None if tpf is None else tpf.tolist())});\n"
              f"console.log(JSON.stringify(Array.from(E)));")
    out = subprocess.run([node, "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True).stdout
    return np.array(json.loads(out), np.int64).reshape(-1, 2)


def _star(c, k, r_in, r_out):
    t = np.arange(2 * k) * np.pi / k
    r = np.where(np.arange(2 * k) % 2, r_in, r_out)
    return np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t), np.zeros(2 * k)]


@pytest.mark.parametrize("kind", ["triangles", "quads", "ragged", "padded", "hexagons", "stars"])
def test_viewer_finds_the_polygon_sides(kind):
    rng = np.random.default_rng(1)
    n = 40
    V = rng.random((n, 3))
    if kind == "triangles":
        polys = [rng.choice(n, 3, replace=False) for _ in range(30)]
        faces = np.array(polys)
    elif kind == "quads":                        # sent as quads (or triangulated if bent)
        polys = [rng.choice(n, 4, replace=False) for _ in range(30)]
        faces = np.array(polys)
    elif kind == "hexagons":
        polys = [rng.choice(n, 6, replace=False) for _ in range(30)]
        faces = np.array(polys)
    elif kind == "stars":                        # non-convex: ear clipped, not fanned
        V = np.vstack([_star((3 * i, 0), 5, 0.4, 1.0) for i in range(4)])
        polys = [np.arange(10) + 10 * i for i in range(4)]
        faces = np.array(polys)
    else:
        polys = [rng.choice(n, k, replace=False) for k in rng.integers(3, 7, 30)]
        faces = (polys if kind == "ragged" else
                 np.array([np.r_[p, [-1] * (6 - len(p))] for p in polys]))
    E = _viewer_edges(ser.surface_mesh("P", V, faces))
    assert {tuple(e) for e in E.tolist()} == _reference_edges(polys)
    assert len(E) == len(_reference_edges(polys)) and (E[:, 0] < E[:, 1]).all()


@pytest.mark.parametrize("faces, match", [
    ([[0, 1, 2], [0, 1.5, 2, 3]], "integers"),
    ([[0, 1, 2], [0, 1, 2, 9]], "out of range"),
    ([[0, 1, 2], ["a", "b", "c", "d"]], "numeric"),
    ([[0, 1, 2], [0, 1]], "fewer than 3"),
])
def test_ragged_faces_are_checked(faces, match):
    with pytest.raises(ValueError, match=match):
        ser.surface_mesh("R", np.zeros((5, 3)), faces)


def test_show_edges_travels_inside_the_mesh_dict():
    V, F = _grid(3)
    d = ser.surface_mesh("Q", V, F, show_edges=True, edge_color=(0, 0, 0), edge_radius=0.001)
    assert isinstance(d, dict)
    assert d["show_edges"] and d["edge_color"] == [0.0, 0.0, 0.0] and d["edge_radius"] == 0.001


def test_binary_scene_is_much_smaller_than_the_old_json():
    V, F = _grid(120)
    d = ser.surface_mesh("G", V, F, show_edges=True)
    binary = len(encode({"objects": [d]}))
    # The previous format: everything as JSON lists, edge end coordinates in the
    # mesh dict (poly_edge_verts) and again in a separate edge_child dict.
    E = np.array(sorted(_reference_edges(F)))
    ends = np.vstack([V[E[:, 0]], V[E[:, 1]]]).astype(np.float32).ravel().tolist()
    conn = np.arange(2 * len(E)).tolist()
    old = [{**jsonable(d), "poly_edge_verts": ends, "poly_edge_conn": conn},
           {"type": "edge_child", "vertices": ends, "edges": conn}]
    legacy = len(json.dumps({"objects": old}))
    assert binary * 4 < legacy


def test_numpy_scalars_and_mixed_lists_encode():
    out = encode({"color": [np.float32(0.5), 1, 1], "l": [1.0, np.zeros(2)], "n": np.int64(3)})
    back = decode(out)
    assert back["color"] == [0.5, 1, 1] and back["n"] == 3
    assert back["l"][0] == 1.0 and back["l"][1].tolist() == [0.0, 0.0]


def test_non_finite_numbers_become_null():
    # JSON has no NaN; the browser's JSON.parse would reject the whole message.
    out = encode({"energy": float("nan"), "r": [np.float64("inf"), 1.0]})
    assert json.loads(out) == {"energy": None, "r": [None, 1.0]}
    assert jsonable({"v": np.array([1.0, np.nan])}) == {"v": [1.0, None]}


def test_integers_that_do_not_fit_int32_raise():
    import pytest
    with pytest.raises(ValueError, match="does not fit"):
        encode({"a": np.array([2**31 + 5])})
    assert decode(encode({"a": np.array([-5, 2**31 - 1])}))["a"].tolist() == [-5, 2**31 - 1]


def test_show_edges_default_colour_is_dark():
    V, F = _grid(3)
    assert ser.surface_mesh("Q", V, F, show_edges=True)["edge_color"] == [0.1, 0.1, 0.1]
