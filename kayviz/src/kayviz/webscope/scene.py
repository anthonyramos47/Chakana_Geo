"""
Scene builder — a Polyscope-style context manager for collecting geometry objects.

Usage:
    from .scene import Scene

    with Scene() as s:
        s.register_surface_mesh("Base", V, F, color=(0.8, 0.8, 0.8))
        s.register_curve_network("Gauss Map", gv, ge)
        s.add_vector_quantity("Base", "normals", N, defined_on="vertices")

    objects = s.snapshot()  # list[dict] — pass directly to ws.send_json as "objects"

All methods mirror their kayviz.serializers counterpart; the multi-object ones
(visualize_frame, add_cross_field) extend the internal list. Geometry such as
spheres or circles comes in as arrays, e.g. s.register_surface_mesh("S", *glyphs.sphere(c, r)).
"""

from __future__ import annotations
from kayviz import serializers as ser


class Scene:
    """Collects serializer dicts produced during a Python computation block."""

    def __init__(self):
        self._objects: list[dict] = []

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False  # do not suppress exceptions

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> list[dict]:
        """Return collected objects (a shallow copy)."""
        return list(self._objects)

    def clear(self):
        """Reset the collected objects."""
        self._objects.clear()

    # ── Registration — mirrors ps.register_* ─────────────────────────────────

    def register_surface_mesh(self, name: str, vertices, faces,
                              color=(0.8, 0.8, 0.8), face_size=None,
                              opacity: float = 1.0, show_edges: bool = False,
                              edge_color=(0.8, 0.8, 0.8)):
        """Mirrors ps.register_surface_mesh(). Pass show_edges=True to overlay the wireframe."""
        result = ser.surface_mesh(name, vertices, faces,
                                  color=color, face_size=face_size,
                                  opacity=opacity,
                                  show_edges=show_edges, edge_color=edge_color)
        if isinstance(result, list):
            self._objects.extend(result)
        else:
            self._objects.append(result)
        return self

    def register_curve_network(self, name: str, vertices, edges,
                               color=(0.8, 0.2, 0.2)):
        """Mirrors ps.register_curve_network()."""
        self._objects.append(ser.curve_network(name, vertices, edges, color=color))
        return self

    def register_point_cloud(self, name: str, points,
                             color=(0.2, 0.5, 0.8), radius: float = 0.01):
        """Mirrors ps.register_point_cloud()."""
        self._objects.append(ser.point_cloud(name, points, color=color, radius=radius))
        return self

    # ── Quantity methods — mirrors structure.add_*_quantity() ────────────────

    def add_scalar_quantity(self, target_name: str, field_name: str,
                            values, defined_on: str = "vertices"):
        """Mirrors structure.add_scalar_quantity()."""
        self._objects.append(
            ser.scalar_quantity(target_name, field_name, values, defined_on=defined_on)
        )
        return self

    def add_vector_quantity(self, target_name: str, field_name: str,
                            vectors, defined_on: str = "vertices",
                            length: float = 0.05, radius: float = None):
        """Mirrors structure.add_vector_quantity()."""
        self._objects.append(
            ser.vector_quantity(target_name, field_name, vectors, defined_on=defined_on,
                                length=length, radius=radius)
        )
        return self

    def register_vector_field(self, name: str, origins, vectors,
                              length: float = 0.05, radius: float = None,
                              color=(0.2, 0.8, 0.4)):
        """Render an arrow field (cylinder shaft + cone head per vector)."""
        self._objects.append(
            ser.vector_field(name, origins, vectors, length=length, radius=radius, color=color)
        )
        return self

    def set_enabled(self, name: str, enabled: bool):
        """Mirrors structure.set_enabled()."""
        self._objects.append(ser.set_enabled(name, enabled))
        return self

    # ── multi-object helpers ──────────────────────────────────────────────────

    def visualize_frame(self, name, points, e1, e2, n):
        """Returns [point_cloud, vec_qty, vec_qty, vec_qty]."""
        self._objects.extend(ser.visualize_frame(name, points, e1, e2, n))
        return self

    def add_cross_field(self, mesh_name, vec1, vec2, name="", rad=0.002,
                        size=0.04, color=(0.8, 0.2, 0.2)):
        """Returns four vector_quantity dicts."""
        self._objects.extend(
            ser.add_cross_field(mesh_name, vec1, vec2,
                                name=name, rad=rad, size=size, color=color)
        )
        return self

    # ── Extend with a pre-built list ──────────────────────────────────────────

    def extend(self, objects: list[dict]):
        """Append a list of already-serialized dicts (e.g. from ser.lmesh_scene())."""
        self._objects.extend(objects)
        return self
