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
                              edge_color=(0.1, 0.1, 0.1), show: bool = True,
                              material=None, shading: str = "auto", edge_radius: float = 0.0,
                              back_color=None, show_wireframe: bool = False,
                              wireframe_width: float = 1.0):
        """Mirrors ps.register_surface_mesh(). Pass show_edges=True to overlay the wireframe,
        show=False to register it hidden, material="glass" to pin this mesh's shader."""
        result = ser.surface_mesh(name, vertices, faces,
                                  color=color, face_size=face_size,
                                  opacity=opacity,
                                  show_edges=show_edges, edge_color=edge_color, show=show,
                                  material=material, shading=shading, edge_radius=edge_radius,
                                  back_color=back_color, show_wireframe=show_wireframe,
                                  wireframe_width=wireframe_width)
        self._objects.append(result)
        return self

    def register_curve_network(self, name: str, vertices, edges,
                               color=(0.8, 0.2, 0.2), radius: float = None, show: bool = True):
        """Mirrors ps.register_curve_network(). show=False registers it hidden."""
        self._objects.append(ser.curve_network(name, vertices, edges, color=color, radius=radius,
                                               show=show))
        return self

    def register_point_cloud(self, name: str, points,
                             color=(0.2, 0.5, 0.8), radius: float = None, show: bool = True,
                             point_render: str = "sprite"):
        """Mirrors ps.register_point_cloud(). show=False registers it hidden.
        point_render: "sprite" (default) or "sphere", as kv.register_point_cloud."""
        self._objects.append(ser.point_cloud(name, points, color=color, radius=radius, show=show,
                                             point_render=point_render))
        return self

    # ── Quantity methods — mirrors structure.add_*_quantity() ────────────────

    def add_scalar_quantity(self, target_name: str, field_name: str,
                            values, defined_on: str = "vertices", show: bool = None,
                            cmap: str = "viridis", vminmax=None, isolines: bool = False,
                            iso_spacing: float = None, iso_width: float = 1.0):
        """Mirrors structure.add_scalar_quantity(). show, isolines: see
        kayviz.add_scalar_quantity."""
        self._objects.append(
            ser.scalar_quantity(target_name, field_name, values, defined_on=defined_on,
                                show=show, cmap=cmap, vminmax=vminmax, isolines=isolines,
                                iso_spacing=iso_spacing, iso_width=iso_width)
        )
        return self

    def add_parameterization_quantity(self, target_name: str, field_name: str, uv,
                                      style: str = "checker", scale: float = 1.0):
        """Mirrors kayviz.add_parameterization_quantity."""
        self._objects.append(ser.parameterization_quantity(target_name, field_name, uv,
                                                           style=style, scale=scale))
        return self

    def add_vector_quantity(self, target_name: str, field_name: str,
                            vectors, defined_on: str = "vertices",
                            length: float = None, radius: float = None,
                            show: bool = None, color=None, vectortype: str = "standard"):
        """Mirrors structure.add_vector_quantity(). show, color: see kayviz.add_vector_quantity."""
        self._objects.append(
            ser.vector_quantity(target_name, field_name, vectors, defined_on=defined_on,
                                length=length, radius=radius, show=show, color=color,
                                vectortype=vectortype)
        )
        return self

    def register_vector_field(self, name: str, origins, vectors,
                              length: float = None, radius: float = None,
                              color=(0.2, 0.8, 0.4), show: bool = True,
                              vectortype: str = "standard"):
        """Render an arrow field (cylinder shaft + cone head per vector). show=False: hidden."""
        self._objects.append(
            ser.vector_field(name, origins, vectors, length=length, radius=radius, color=color,
                             show=show, vectortype=vectortype)
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
