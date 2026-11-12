"""Input checks of the serializers: wrong input raises ValueError naming the object."""

import json

import numpy as np
import pytest

from kayviz import serializers as ser

V = np.zeros((6, 3))


@pytest.mark.parametrize("vertices, faces, match", [
    (V[:, :2], [[0, 1, 2]], r"shape \(N, 3\).*zero z column"),
    (V.T, [[0, 1, 2]], r"shape \(N, 3\)"),
    (V + 1j, [[0, 1, 2]], "complex"),
    (V, [[0, 1, 99]], "out of range"),
    (V, [0, 1, 2], "list of polygons"),
    (V, [[0, 1]], "at least 3"),
    (V, [[0, 1, 2], [3, 4]], "fewer than 3"),
    (V, [[0.0, 1.5, 2.0]], "integers"),
    (V, np.array([[0, -1, 2]]), "negative"),
    (V, None, "missing"),
])
def test_bad_meshes_raise(vertices, faces, match):
    with pytest.raises(ValueError, match=match):
        ser.surface_mesh("X", vertices, faces)


def test_minus_one_pads_shorter_polygons():
    d = ser.surface_mesh("P", V, np.array([[0, 1, 2, -1], [1, 2, 3, 4]]))
    assert d["tris_per_face"].tolist() == [1, 2]


def test_colours_and_opacity_are_checked():
    with pytest.raises(ValueError, match="divide by 255"):
        ser.surface_mesh("X", V, [[0, 1, 2]], color=(200, 100, 50))
    with pytest.raises(ValueError, match="opacity"):
        ser.surface_mesh("X", V, [[0, 1, 2]], opacity=5)


def test_nan_vertices_warn():
    W = V.copy(); W[0, 0] = np.nan
    with pytest.warns(UserWarning, match="NaN"):
        ser.point_cloud("P", W)


def test_other_structures_are_checked():
    with pytest.raises(ValueError, match="shape"):
        ser.point_cloud("P", np.zeros(10))
    with pytest.raises(ValueError, match=r"\(M, 2\)"):
        ser.curve_network("C", V, np.zeros((3, 3), int))
    with pytest.raises(ValueError, match="out of range"):
        ser.curve_network("C", V, [[0, 9]])
    with pytest.raises(ValueError, match="origins but"):
        ser.vector_field("F", V, V[:2])


def test_quantity_arguments_are_checked():
    with pytest.raises(ValueError, match="defined_on"):
        ser.scalar_quantity("M", "s", np.zeros(6), defined_on="vertex")
    with pytest.raises(ValueError, match="one number per"):
        ser.scalar_quantity("M", "s", np.zeros((6, 2)))
    with pytest.raises(ValueError, match="shape"):
        ser.vector_quantity("M", "v", np.zeros((6, 2)))
    assert np.isnan(ser.scalar_quantity("M", "s", [0, np.nan])["values"][1])   # NaN allowed


def test_scalar_cmap_and_range_are_checked():
    d = ser.scalar_quantity("M", "s", np.zeros(3), cmap="coolwarm", vminmax=(-1, 1))
    assert d["cmap"] == "coolwarm" and d["vminmax"] == [-1.0, 1.0]
    with pytest.raises(ValueError, match="unknown cmap"):
        ser.scalar_quantity("M", "s", np.zeros(3), cmap="jet")
    with pytest.raises(ValueError, match="vmin < vmax"):
        ser.scalar_quantity("M", "s", np.zeros(3), vminmax=(1, 1))


def test_vectortype_and_shading_are_checked():
    assert ser.vector_quantity("M", "v", np.zeros((2, 3)), vectortype="ambient")["vectortype"] == "ambient"
    with pytest.raises(ValueError, match="vectortype"):
        ser.vector_quantity("M", "v", np.zeros((2, 3)), vectortype="magnitude")
    tri = ser.surface_mesh("T", np.zeros((3, 3)), [[0, 1, 2]])
    quad = ser.surface_mesh("Q", np.zeros((4, 3)), [[0, 1, 2, 3]])
    assert tri["shading"] == "smooth" and quad["shading"] == "flat"
    assert ser.surface_mesh("Q", np.zeros((4, 3)), [[0, 1, 2, 3]], shading="smooth")["shading"] == "smooth"


def test_scene_and_kv_take_the_same_arguments():
    # The two front doors to the serializers must not drift apart.
    import inspect
    import kayviz as kv
    alias = {"target_name": "target"}
    for f in ["register_surface_mesh", "register_curve_network", "register_point_cloud",
              "register_vector_field", "add_scalar_quantity", "add_vector_quantity"]:
        a = set(inspect.signature(getattr(kv, f)).parameters)
        b = {alias.get(p, p) for p in list(inspect.signature(getattr(kv.Scene, f)).parameters)[1:]}
        assert a == b, (f, a ^ b)


def _areas(V, d):
    T = d["faces"].reshape(-1, 3)
    return 0.5 * np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])[:, 2]


@pytest.mark.parametrize("start", range(6))
def test_non_convex_polygons_are_triangulated_inside(start):
    # An L-shaped hexagon: a fan from a reflex vertex would cover area outside it.
    L = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0], [1, 2, 0], [0, 2, 0]], float)
    a = _areas(L, ser.surface_mesh("L", L, [list(np.roll(np.arange(6), -start))]))
    assert (a > 0).all() and a.sum() == pytest.approx(3.0)


def test_non_convex_quads_leave_the_quad_fast_path():
    dart = np.array([[0, 0, 0], [1, 0.4, 0], [2, 0, 0], [1, 2, 0]], float)
    d = ser.surface_mesh("D", dart, [[1, 2, 3, 0]])
    assert d["face_size"] == 3 and (_areas(dart, d) > 0).all()
    square = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    assert ser.surface_mesh("S", square, [[0, 1, 2, 3]])["face_size"] == 4


def test_scalars_on_points_and_curves_are_checked():
    import os, subprocess, sys, textwrap
    code = textwrap.dedent('''
        import json, numpy as np, kayviz as kv
        kv.init()
        kv.register_point_cloud("P", np.zeros((4, 3)))
        kv.register_curve_network("C", np.zeros((5, 3)), [[0, 1], [1, 2], [3, 4]])
        kv.register_surface_mesh("M", np.eye(3), [[0, 1, 2]])
        out = {}
        for label, call in [
            ("points", lambda: kv.add_scalar_quantity("P", "s", np.arange(4.0))),
            ("curve_vertices", lambda: kv.add_scalar_quantity("C", "s", np.arange(5.0))),
            ("curve_edges", lambda: kv.add_scalar_quantity("C", "e", np.arange(3.0), defined_on="edges")),
            ("points_wrong_count", lambda: kv.add_scalar_quantity("P", "s", np.arange(3.0))),
            ("edges_wrong_count", lambda: kv.add_scalar_quantity("C", "e", np.arange(5.0), defined_on="edges")),
            ("faces_on_curve", lambda: kv.add_scalar_quantity("C", "f", np.arange(3.0), defined_on="faces")),
            ("edges_on_mesh", lambda: kv.add_scalar_quantity("M", "e", np.arange(3.0), defined_on="edges")),
        ]:
            try:
                call(); out[label] = "ok"
            except ValueError as e:
                out[label] = str(e)
        print("RESULT" + json.dumps(out))
    ''')
    env = dict(os.environ, KAYVIZ_NO_BROWSER="1",
               KAYVIZ_PORT=str(int(os.environ.get("KAYVIZ_TEST_PORT_BASE", "18700")) + 125))
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.split("RESULT")[1])
    assert out["points"] == out["curve_vertices"] == out["curve_edges"] == "ok"
    assert "has 4 vertices" in out["points_wrong_count"]
    assert "has 3 edges" in out["edges_wrong_count"]
    assert "needs a surface_mesh" in out["faces_on_curve"]
    assert "needs a curve_network" in out["edges_on_mesh"]
