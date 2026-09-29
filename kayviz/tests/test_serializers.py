"""
Unit tests for server/serializers.py.

Tests that each serializer produces the right dict shape and that
fan-triangulation works correctly for ragged faces.

Run:
    pytest tests/test_serializers.py
"""

import numpy as np
import pytest

from kayviz import serializers as ser


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def triangle_mesh():
    V = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]], dtype=np.float32)
    F = np.array([[0,1,2],[0,1,3]], dtype=np.int32)
    return V, F

@pytest.fixture
def quad_mesh():
    V = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], dtype=np.float32)
    F = np.array([[0,1,2,3]], dtype=np.int32)
    return V, F

@pytest.fixture
def pentagon_mesh():
    """Single pentagon face — should be fan-triangulated to 3 triangles."""
    V = np.array([[0,0,0],[1,0,0],[1.5,1,0],[0.5,1.5,0],[-0.5,1,0]], dtype=np.float32)
    F = [list(range(5))]
    return V, F

@pytest.fixture
def ragged_mesh():
    """Mix of triangle and quad — ragged, must fan-triangulate."""
    V = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0.5,2,0]], dtype=np.float32)
    F = [[0,1,2], [0,2,3,4]]
    return V, F


# ── surface_mesh ─────────────────────────────────────────────────────────────

class TestSurfaceMesh:
    def test_required_keys(self, triangle_mesh):
        V, F = triangle_mesh
        d = ser.surface_mesh("A", V, F)
        assert d["type"] == "surface_mesh"
        assert d["name"] == "A"
        assert "vertices" in d and "faces" in d
        assert "color" in d and "opacity" in d

    def test_vertices_flat(self, triangle_mesh):
        V, F = triangle_mesh
        d = ser.surface_mesh("A", V, F)
        assert len(d["vertices"]) == V.shape[0] * 3

    def test_triangles_preserved(self, triangle_mesh):
        V, F = triangle_mesh
        d = ser.surface_mesh("A", V, F)
        assert d["face_size"] == 3
        assert len(d["faces"]) == len(F) * 3

    def test_quads_preserved(self, quad_mesh):
        V, F = quad_mesh
        d = ser.surface_mesh("A", V, F)
        assert d["face_size"] == 4
        assert len(d["faces"]) == 4

    def test_pentagon_fan_triangulated(self, pentagon_mesh):
        V, F = pentagon_mesh
        d = ser.surface_mesh("A", V, F)
        # 1 pentagon → 3 triangles → 9 indices
        assert d["face_size"] == 3
        assert len(d["faces"]) == 9

    def test_ragged_fan_triangulated(self, ragged_mesh):
        V, F = ragged_mesh
        d = ser.surface_mesh("A", V, F)
        # triangle (1 tri) + quad (2 tris) = 3 triangles → 9 indices
        assert d["face_size"] == 3
        assert len(d["faces"]) == 9

    def test_color_passed_through(self, triangle_mesh):
        V, F = triangle_mesh
        color = (0.1, 0.5, 0.9)
        d = ser.surface_mesh("A", V, F, color=color)
        assert d["color"] == pytest.approx(list(color))

    def test_opacity_default(self, triangle_mesh):
        V, F = triangle_mesh
        d = ser.surface_mesh("A", V, F)
        assert d["opacity"] == pytest.approx(1.0)

    def test_opacity_custom(self, triangle_mesh):
        V, F = triangle_mesh
        d = ser.surface_mesh("A", V, F, opacity=0.3)
        assert d["opacity"] == pytest.approx(0.3)


# ── curve_network ─────────────────────────────────────────────────────────────

class TestCurveNetwork:
    def test_required_keys(self):
        V = np.array([[0,0,0],[1,0,0],[1,1,0]])
        E = np.array([[0,1],[1,2]])
        d = ser.curve_network("net", V, E)
        assert d["type"] == "curve_network"
        assert d["name"] == "net"
        assert "vertices" in d and "edges" in d and "color" in d

    def test_flat_layout(self):
        V = np.array([[0,0,0],[1,0,0]])
        E = np.array([[0,1]])
        d = ser.curve_network("net", V, E)
        assert len(d["vertices"]) == 6   # 2 verts × 3
        assert len(d["edges"])    == 2   # 1 edge × 2


# ── point_cloud ───────────────────────────────────────────────────────────────

class TestPointCloud:
    def test_required_keys(self):
        pts = np.random.rand(10, 3).astype(np.float32)
        d = ser.point_cloud("pts", pts)
        assert d["type"] == "point_cloud"
        assert d["name"] == "pts"
        assert "points" in d and "color" in d and "radius" in d

    def test_flat_layout(self):
        pts = np.ones((5, 3), dtype=np.float32)
        d = ser.point_cloud("pts", pts)
        assert len(d["points"]) == 15


# ── scalar_quantity ───────────────────────────────────────────────────────────

class TestScalarQuantity:
    def test_required_keys(self):
        vals = np.linspace(0, 1, 8)
        d = ser.scalar_quantity("Mesh", "curvature", vals)
        assert d["type"]   == "scalar_quantity"
        assert d["target"] == "Mesh"
        assert d["name"]   == "curvature"
        assert len(d["values"]) == 8

    def test_defined_on(self):
        d = ser.scalar_quantity("M", "f", [0,1], defined_on="faces")
        assert d["defined_on"] == "faces"


# ── vector_quantity ───────────────────────────────────────────────────────────

class TestVectorQuantity:
    def test_required_keys(self):
        vecs = np.random.rand(4, 3).astype(np.float32)
        d = ser.vector_quantity("Mesh", "normals", vecs)
        assert d["type"]   == "vector_quantity"
        assert d["target"] == "Mesh"
        assert d["name"]   == "normals"
        assert len(d["vectors"]) == 12  # 4 × 3 flat

    def test_defined_on_default(self):
        d = ser.vector_quantity("M", "n", np.zeros((2,3)))
        assert d["defined_on"] == "vertices"

    def test_length_default(self):
        d = ser.vector_quantity("M", "n", np.zeros((2,3)))
        assert d["length"] == pytest.approx(0.05)

    def test_radius_defaults_to_ratio_of_length(self):
        d = ser.vector_quantity("M", "n", np.zeros((2,3)), length=0.2)
        assert d["radius"] == pytest.approx(0.2 * 0.04)

    def test_length_and_radius_custom(self):
        d = ser.vector_quantity("M", "n", np.zeros((2,3)), length=0.3, radius=0.01)
        assert d["length"] == pytest.approx(0.3)
        assert d["radius"] == pytest.approx(0.01)


# ── vector_field ─────────────────────────────────────────────────────────────

class TestVectorField:
    def test_required_keys(self):
        origins = np.zeros((3, 3), dtype=np.float32)
        vecs    = np.random.rand(3, 3).astype(np.float32)
        d = ser.vector_field("Field", origins, vecs)
        assert d["type"] == "vector_field"
        assert d["name"] == "Field"
        assert len(d["origins"]) == 9
        assert len(d["vectors"]) == 9

    def test_length_default(self):
        d = ser.vector_field("F", np.zeros((1,3)), np.zeros((1,3)))
        assert d["length"] == pytest.approx(0.05)

    def test_radius_defaults_to_ratio_of_length(self):
        d = ser.vector_field("F", np.zeros((1,3)), np.zeros((1,3)), length=0.2)
        assert d["radius"] == pytest.approx(0.2 * 0.04)

    def test_length_and_radius_custom(self):
        d = ser.vector_field("F", np.zeros((1,3)), np.zeros((1,3)), length=0.3, radius=0.01)
        assert d["length"] == pytest.approx(0.3)
        assert d["radius"] == pytest.approx(0.01)


# ── set_enabled ───────────────────────────────────────────────────────────────

class TestSetEnabled:
    def test_enable(self):
        d = ser.set_enabled("Mesh", True)
        assert d == {"type": "set_enabled", "name": "Mesh", "enabled": True}

    def test_disable(self):
        d = ser.set_enabled("Mesh", False)
        assert d["enabled"] is False
