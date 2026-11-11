"""Binary message format (kayviz.webscope.wire) and the array-based serializers."""

import json

import numpy as np

from kayviz import serializers as ser
from kayviz.webscope.wire import decode, encode, jsonable


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
    assert isinstance(out, bytes)
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


def test_poly_edges_are_unique_index_pairs():
    V, F = _grid(3)                         # 2x2 quads: 12 edges
    d = ser.surface_mesh("Q", V, F)
    E = d["poly_edges"].reshape(-1, 2)
    assert E.dtype == np.int32 and len(E) == 12
    assert len({tuple(e) for e in E}) == 12 and (E[:, 0] < E[:, 1]).all()
    assert "poly_edge_verts" not in d


def test_ragged_faces_edges_and_triangulation():
    V = np.zeros((5, 3))
    d = ser.surface_mesh("R", V, [[0, 1, 2], [0, 2, 3, 4]])
    assert len(d["poly_edges"]) // 2 == 6           # triangle + quad sharing (0, 2)
    assert d["tris_per_face"].tolist() == [1, 2] and d["face_size"] == 3


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
    E = d["poly_edges"].reshape(-1, 2)
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
