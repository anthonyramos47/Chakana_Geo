"""Positions far from zero travel relative to a scene origin (float64 subtraction
before the float32 cast)."""

import numpy as np
import pytest

from kayviz import serializers as ser


@pytest.fixture(autouse=True)
def fresh_origin():
    ser.set_origin(None)
    yield
    ser.set_origin(None)


def _square(offset, size=1.0):
    V = np.array([[0, 0, 0], [size, 0, 0], [size, size, 0], [0, size, 0.1 * size]]) + offset
    return V, [[0, 1, 2, 3]]


def test_ordinary_coordinates_are_unchanged():
    V, F = _square([5.0, -3.0, 2.0])
    d = ser.surface_mesh("M", V, F)
    assert "origin" not in d and ser.get_origin() is None
    assert np.array_equal(d["vertices"], V.astype(np.float32).ravel())


def test_far_coordinates_keep_their_shape():
    far = np.array([4_512_345.678, 1_234_567.891, 312.5])         # e.g. UTM metres
    V, F = _square(far, size=0.5)
    d = ser.surface_mesh("M", V, F)
    o = np.array(d["origin"])
    back = d["vertices"].reshape(-1, 3).astype(np.float64) + o
    assert np.abs(back - V).max() < 1e-6                            # micrometres
    naive = V.astype(np.float32).astype(np.float64)
    assert np.abs(naive - V).max() > 0.05                           # what float32 alone does
    assert np.abs(o - far).max() < 1.0                              # a rounded centre


def test_later_objects_share_the_origin_and_vectors_are_not_shifted():
    far = np.array([1e7, 0.0, 0.0])
    ser.surface_mesh("M", *_square(far))
    o = ser.get_origin()
    p = ser.point_cloud("P", far[None] + [[0.25, 0, 0]])
    vf = ser.vector_field("V", far[None], [[0.0, 0.0, 1.0]])
    q = ser.vector_quantity("M", "n", np.tile([0.0, 0.0, 1.0], (4, 1)))
    assert p["origin"] == o.tolist() and vf["origin"] == o.tolist()
    assert np.allclose(p["points"], far + [0.25, 0, 0] - o)
    assert vf["vectors"].tolist() == [0.0, 0.0, 1.0]
    assert q["vectors"].tolist()[:3] == [0.0, 0.0, 1.0]


def test_the_first_positions_decide_for_the_whole_scene():
    # a small object first: no origin, and a far one later must not get one either
    # (it would be drawn in another frame than the first)
    ser.point_cloud("A", [[1.0, 2.0, 3.0]])
    with pytest.warns(UserWarning, match="kv.set_origin"):
        far = ser.point_cloud("B", [[5e6, 0.0, 0.0], [5e6 + 1, 0.0, 0.0]])
    assert "origin" not in far
    # a single far point decides too
    ser.set_origin(None)
    one = ser.point_cloud("C", [[5e6, 1.0, 2.0]])
    assert one["origin"] == [5e6, 1.0, 2.0] and one["points"].tolist() == [0.0, 0.0, 0.0]


def test_clear_starts_a_new_decision_unless_the_origin_was_set(monkeypatch):
    from kayviz.runtime import script
    monkeypatch.setattr(script, "_send", lambda *a, **k: None)
    ser.point_cloud("A", [[5e6, 0.0, 0.0], [5e6 + 1, 0.0, 0.0]])
    assert ser.get_origin() is not None
    script.clear()
    assert ser.get_origin() is None
    ser.set_origin([1.0, 1.0, 1.0])
    script.clear()
    assert ser.get_origin().tolist() == [1.0, 1.0, 1.0]


def test_set_origin_overrides_and_none_restores_automatic():
    ser.set_origin([10.0, 20.0, 30.0])
    d = ser.point_cloud("P", [[11.0, 20.0, 30.0]])
    assert d["origin"] == [10.0, 20.0, 30.0] and d["points"].tolist() == [1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="set_origin"):
        ser.set_origin([1.0, 2.0])
    ser.set_origin(None)
    assert "origin" not in ser.point_cloud("P", [[1.0, 2.0, 3.0]])


def test_look_at_and_get_camera_use_the_users_coordinates(monkeypatch):
    from kayviz.runtime import script
    sent = []
    monkeypatch.setattr(script, "_view", sent.append)
    ser.set_origin([1000.0, 0.0, 0.0])
    script.look_at((1010.0, 5.0, 0.0), target=(1000.0, 0.0, 0.0))
    assert sent[-1]["camera"] == {"position": [10.0, 5.0, 0.0], "target": [0.0, 0.0, 0.0]}
    monkeypatch.setattr(script, "_last_camera", {"position": [10.0, 5.0, 0.0],
                                                  "target": [0.0, 0.0, 0.0], "fov": 50})
    cam = script.get_camera()
    assert cam["position"] == [1010.0, 5.0, 0.0] and cam["target"] == [1000.0, 0.0, 0.0]
