"""
register.py — Registering structures and quantities, removing them, export.

Part of the scripting API (kayviz.runtime.script re-exports every name).
Shared state and helpers live in script.py and are reached as `_s.name`,
looked up at call time, so tests that monkeypatch script.X still apply.
"""

from __future__ import annotations

from kayviz import serializers as ser
from . import registry as _registry

from . import script as _s


def register_surface_mesh(name: str, vertices, faces,
                          color=(0.8, 0.8, 0.8), opacity: float = 1.0,
                          show_edges: bool = False,
                          edge_color=(0.1, 0.1, 0.1),
                          edge_radius: float = 0.0, show: bool = True,
                          material=None, shading: str = "auto", face_size=None,
                          back_color=None, show_wireframe: bool = False,
                          wireframe_width: float = 1.0) -> None:
    """Mirrors ps.register_surface_mesh(). Pass show_edges=True to overlay the wireframe,
    show=False to register it hidden (tick it in the scene panel to show it).

    Edges are always drawn as thin tubes (so other objects occlude them); edge_radius=0
    picks 3% of the median edge length. The shader is global (scene panel "Shader") unless
    material names one for this mesh, e.g. material="glass". shading: "flat", "smooth" or
    "auto" (flat for polygon meshes, smooth for triangle meshes). back_color: colour of
    the faces seen from behind (orientation checks), None for the front colour.
    show_wireframe: the polygon edges as lines wireframe_width pixels wide, in
    edge_color (much lighter than show_edges' tubes for big meshes)."""
    if material is not None and material not in _s.KNOWN_MATERIALS:
        import warnings
        warnings.warn(f"{name}: unknown material {material!r} (built-in: "
                      f"{', '.join(_s.KNOWN_MATERIALS)}); unless a custom shader of that name "
                      f"is registered in the browser, the global shader is used", stacklevel=2)
    result = ser.surface_mesh(name, vertices, faces,
                              color=color, opacity=opacity,
                              show_edges=show_edges, edge_color=edge_color,
                              edge_radius=edge_radius, show=show, material=material,
                              shading=shading, face_size=face_size, back_color=back_color,
                              show_wireframe=show_wireframe, wireframe_width=wireframe_width)
    _s._push(result)


def register_curve_network(name: str, vertices, edges,
                           color=(0.8, 0.2, 0.2), radius: float = None,
                           show: bool = True) -> None:
    """Mirrors ps.register_curve_network(). show=False registers it hidden.
    radius: tube radius; None picks 0.15% of the curve's size, 0 draws thin lines."""
    _s._push(ser.curve_network(name, vertices, edges, color=color, radius=radius, show=show))


def register_point_cloud(name: str, points,
                         color=(0.2, 0.5, 0.8), radius: float = None,
                         show: bool = True, point_render: str = "sprite") -> None:
    """Mirrors ps.register_point_cloud(). show=False registers it hidden.
    radius: sphere radius; None picks 0.5% of the cloud's size.
    point_render: "sprite" (default: 2 triangles per point, drawn as a sphere; no
    studio shadow or AO) or "sphere" (~170 triangles per point)."""
    _s._push(ser.point_cloud(name, points, color=color, radius=radius, show=show,
                          point_render=point_render))


def add_scalar_quantity(target: str, field_name: str, values,
                        defined_on: str = "vertices", show: bool = None,
                        cmap: str = "viridis", vminmax=None, isolines: bool = False,
                        iso_spacing: float = None, iso_width: float = 1.0) -> None:
    """Mirrors structure.add_scalar_quantity().

    Targets: surface meshes (defined_on "vertices" or "faces"), point clouds
    ("vertices": one value per point) and curve networks ("vertices", or "edges": one
    value per edge; on tubes a vertex scalar colours each edge with the mean of its ends).

    show: None (default) follows the target; True colours the target with it and shows the
    target if it was hidden; False adds it without colouring the mesh.
    cmap: viridis, plasma, inferno, magma, cividis, coolwarm, rdbu, piyg (diverging: signed
    data), twilight (cyclic: angles), turbo, gray, blues.
    vminmax: (vmin, vmax) colour range; default the range of the finite values.
    isolines: on a surface mesh's vertex scalar, dark lines where the value crosses a
    multiple of iso_spacing (default a tenth of the colour range), iso_width pixels wide.
    """
    d = ser.scalar_quantity(target, field_name, values, defined_on=defined_on, show=show,
                            cmap=cmap, vminmax=vminmax, isolines=isolines,
                            iso_spacing=iso_spacing, iso_width=iso_width)
    _s._check_quantity("add_scalar_quantity", target, len(d["values"]), defined_on,
                    ("surface_mesh", "point_cloud", "curve_network"))
    _s._push(d)


def add_parameterization_quantity(target: str, field_name: str, uv,
                                  style: str = "checker", scale: float = 1.0,
                                  defined_on: str = "vertices") -> None:
    """Show a parameterization of the surface mesh *target*: uv, one (u, v) per
    vertex, or with defined_on="corners" one per face corner in face order (for
    seams), as a checkerboard ("checker") or grid lines ("grid"), *scale* cells per
    unit of uv. Stretching, flips and seams show as distorted or broken cells.
    Corners work on triangle and quad meshes (faces kayviz did not triangulate)."""
    d = ser.parameterization_quantity(target, field_name, uv, style=style, scale=scale,
                                      defined_on=defined_on)
    _s._check_quantity("add_parameterization_quantity", target, len(d["uv"]) // 2, defined_on,
                    ("surface_mesh",))
    _s._push(d)


def add_vector_quantity(target: str, field_name: str, vectors,
                        defined_on: str = "vertices",
                        length: float = None, radius: float = None,
                        show: bool = None, color=None, vectortype: str = "standard") -> None:
    """Mirrors structure.add_vector_quantity().

    Args:
        target:     Name of the surface mesh (or point cloud) the vectors are attached to.
        field_name: Scene label for the vector quantity.
        vectors:    (N, 3) vectors.
        defined_on: "vertices" (arrows start at the vertices) or "faces" (at the face
                    barycenters; N must be the number of faces).
        length:     Arrow length in scene units (of the longest arrow for "standard");
                    None picks 4% of the target's size. Adjust with the scene-panel slider.
        radius:     Arrow shaft/cone radius in scene units; defaults to length * 0.04.
        show:       None (default) follows the target: hidden while the target is hidden.
                    True shows the arrows and the target; False adds them hidden.
                    Several vector quantities of one target can be shown at once.
        color:      [r, g, b] in 0-1. None (default): the next colour of the viewer's
                    palette not used by the target's other vector quantities.
        vectortype: "standard" (default): arrow length × |v| / max|v|, magnitudes
                    compare; "ambient": |v| in scene units; "unit": all `length`.
    """
    d = ser.vector_quantity(target, field_name, vectors, defined_on=defined_on,
                            length=length, radius=radius, show=show, color=color,
                            vectortype=vectortype)
    _s._check_quantity("add_vector_quantity", target, len(d["vectors"]) // 3, defined_on,
                    ("surface_mesh",) if defined_on == "faces" else ("surface_mesh", "point_cloud"))
    _s._push(d)


def register_vector_field(name: str, origins, vectors,
                          length: float = None,
                          radius: float = None,
                          color=(0.2, 0.8, 0.4), show: bool = True,
                          vectortype: str = "standard") -> None:
    """Render an arrow field (cylinder shaft + cone head per vector).

    Args:
        name:    Scene label.
        origins: (N, 3) base points for each arrow.
        vectors: (N, 3) vectors.
        length:  Arrow length in scene units (of the longest arrow for "standard");
                 adjust with the scene-panel slider.
        radius:  Arrow shaft/cone radius in scene units; defaults to length * 0.04.
        color:   [r, g, b] in 0-1.
        show:    False registers it hidden (tick it in the scene panel to show it).
        vectortype: "standard", "ambient" or "unit", as in add_vector_quantity.
    """
    _s._push(ser.vector_field(name, origins, vectors, length=length, radius=radius, color=color,
                           show=show, vectortype=vectortype))


def push_objects(objects: list) -> None:
    """Push a list of pre-built serializer dicts (from Scene or ser.lmesh_scene etc.)."""
    if not objects:
        return
    _s._track(objects)
    sink = _s._push_sink()
    if sink is not None:
        sink(objects)
        return
    _s._send("push", objects=objects)


def _push_with_seq(objects: list, seq: int) -> None:
    """push_objects, asking the tabs to report when they drew it: they answer
    {action: "applied", seq}, read at /api/script/applied (kayviz.evaluate).
    Needs this process's own server (local or hosted mode)."""
    _s._ensure_init()
    if _s._mode not in ("local", "hosted"):
        raise RuntimeError("kayviz: timed pushes need this process's own server")
    _s._track(objects)
    _s._run_on_loop(_registry.get_app("script").push(objects, seq=seq))


def set_enabled(name: str, enabled: bool) -> None:
    """Mirrors structure.set_enabled()."""
    _s._push(ser.set_enabled(name, enabled))


def remove(name: str) -> None:
    """Remove one named object (and its quantities) from the scene."""
    marker = [{"action": "remove", "name": name}]
    _s._track(marker)
    sink = _s._push_sink()
    if sink is not None:            # inside a user callback: its app's buffer too
        sink(marker)
        return
    _s._send("remove", name=name)


def clear() -> None:
    """Remove all objects from the scene. Mirrors ps.remove_all_structures()."""
    # Inside a user callback (CallbackApp), geometry is captured into a local
    # sink rather than sent to the script channel — route the clear through
    # the same hook so it clears that app's buffer.
    _s._track([{"action": "clear"}])
    ser._new_scene()
    sink = _s._push_sink()
    if sink is not None:
        sink([{"action": "clear"}])
        return
    _s._send("clear")


def export(name: str, path, format: str | None = None):
    """Write the registered object *name* (surface mesh, curve network or point cloud)
    to *path*: ``.obj`` or ``.ply`` (or *format*). Polygon meshes keep their
    polygons; PLY also carries the object's vertex and face scalar quantities.
    Coordinates are yours (the scene origin added back). Needs no browser.

    Returns the path written."""
    from .. import exporter as _export
    from .broadcast_mixin import BroadcastMixin
    if _s._mode == "attached":
        raise RuntimeError("kv.export: the scene lives in the shared server's process; "
                           "export from there, or call kayviz.exporter.write(path, obj)")
    for app_name in ["script"] + [n for n in _registry.app_names() if n != "script"]:
        app = _registry.get_app(app_name)
        buf = getattr(app, "_buffer", None) if isinstance(app, BroadcastMixin) else None
        if buf and name in buf:
            quantities = [o for k, o in buf.items() if k.startswith(name + "::")]
            return _export.write(path, buf[name], quantities, fmt=format)
    raise ValueError(f"kv.export: no object named {name!r} (registered from this process)")


def set_origin(origin) -> None:
    """Send positions relative to *origin* (a 3D point), or None to let kayviz choose.

    float32, the GPU's precision, keeps ~7 digits: coordinates around 1e6 lose
    everything below ~0.1. kayviz subtracts the origin in float64 first. By
    default the first positions of a scene decide: their centre (rounded) when it
    is farther than max(1000 x their size, 1e4) from zero, else none is used; all
    later objects share that choice, and kv.clear() starts a new one. Set it
    before registering: objects already sent keep the frame they were sent in."""
    ser.set_origin(origin)
