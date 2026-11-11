"""Input checks of the serializers: wrong input raises ValueError naming the object."""

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
