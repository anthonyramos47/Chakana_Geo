"""
Polyscope-style scripting API — the functions behind ``import kayviz as kv``.

A script or notebook owns its viewer:

    import kayviz as kv

    kv.init()                                   # start this project's server
    kv.register_surface_mesh("Base", V, F, color=(0.5, 0.5, 0.5))
    kv.add_vector_quantity("Base", "normals", N, defined_on="vertices")

    def gui():                                  # optional control panel
        if kv.imgui.button("Step"):
            kv.register_surface_mesh("Base", step(V), F)
    kv.set_user_callback(gui)

    kv.show()                                   # open the browser tab

``init()`` starts a server in a background thread of this process, on the
first free port from 8000. Apps registered with ``set_user_callback`` or
``register_app`` live in that server, so no separate server file is needed.

If a *shared* viewer is already running (``python -m kayviz``), ``init()``
attaches to it instead and geometry is pushed there over HTTP — handy for
several notebooks feeding one window. GUI apps need the in-process server.

Environment variables:
    KAYVIZ_URL         Attach to the kayviz server at this URL (WEBSCOPE_URL
                       is accepted as a legacy alias).
    KAYVIZ_PORT        First port tried for the in-process server (default 8000).
    KAYVIZ_NO_BROWSER  Set to "1" to never open a browser tab (CI, remote).
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import os
import sys
import threading
import time
import webbrowser
from typing import Optional

import requests

from kayviz import serializers as ser
from . import imgui  # re-exported so users can write kv.imgui.*
from . import registry as _registry

# ── Module state ──────────────────────────────────────────────────────────────

_DEFAULT_PORT = int(os.environ.get("KAYVIZ_PORT", 8000))
_url: Optional[str] = None
_server = None                      # kayviz.server.BackgroundServer when local
_mode: Optional[str] = None         # None | "local" | "hosted" | "attached"
_loop: Optional[asyncio.AbstractEventLoop] = None   # loop of a server in this process
_opened: set = set()                # app names a browser tab was opened for

# Push sink: CallbackApp._CallbackPushCapture redirects geometry pushed inside a
# user callback away from the script channel and into the app's buffer. A
# ContextVar is copied by asyncio.to_thread and by kv.thread(), while pushes from
# the main thread or a plain threading.Thread keep the default None (script channel).
_push_sink_var: contextvars.ContextVar[Optional[callable]] = contextvars.ContextVar(
    "kayviz_push_sink", default=None
)


def _push_sink() -> Optional[callable]:
    return _push_sink_var.get()


def _set_push_sink(sink: Optional[callable]) -> contextvars.Token:
    return _push_sink_var.set(sink)


def _reset_push_sink(token: contextvars.Token) -> None:
    _push_sink_var.reset(token)

# App opened by show(): the last app registered from this process.
_default_app: Optional[str] = None

# Structures pushed from this process: name -> {"type", "n_vertices", "n_faces"}.
# Lets add_*_quantity reject a missing target or a wrong length in Python instead
# of the browser dropping the quantity (or colouring the mesh with garbage).
_structures: dict = {}
_structures_lock = threading.Lock()
_STRUCTURE_TYPES = ("surface_mesh", "point_cloud", "curve_network", "vector_field")

# Up axis of the viewer (the page reads it at start: /api/_info).
_up: str = "z"

# Built-in materials of static/lib/MaterialLibrary.js (custom ones registered in the
# browser also work; an unknown name only warns).
KNOWN_MATERIALS = ("physical", "lambert", "phong", "blinn_phong", "toon", "flat",
                   "normal", "depth", "wireframe", "glass")


def _track(objects) -> None:
    """Record structures (and their removal) as they are pushed."""
    with _structures_lock:
        for o in objects:
            action, kind, name = o.get("action"), o.get("type"), o.get("name")
            if action == "clear":
                _structures.clear()
            elif action == "remove":
                _structures.pop(name, None)
            elif kind in _STRUCTURE_TYPES and name:
                info = {"type": kind}
                if kind == "surface_mesh":
                    info["n_vertices"] = len(o["vertices"]) // 3
                    tpf = o.get("tris_per_face")
                    info["n_faces"] = (len(tpf) if tpf is not None
                                       else len(o["faces"]) // max(1, o.get("face_size", 3)))
                    # corners are known (in face order) when the faces went as given
                    info["n_corners"] = None if tpf is not None else len(o["faces"])
                elif kind == "point_cloud":
                    info["n_vertices"] = len(o["points"]) // 3
                elif kind == "curve_network":
                    info["n_vertices"] = len(o["vertices"]) // 3
                    info["n_edges"] = len(o["edges"]) // 2
                _structures[name] = info


def _check_quantity(func: str, target: str, n_values: int, defined_on: str,
                    allowed: tuple) -> None:
    """Raise if *target* is unknown, of the wrong type, or *n_values* does not match."""
    if _mode == "attached":
        return              # the target may come from another process
    with _structures_lock:
        info = _structures.get(target)
        known = sorted(_structures)
    if info is None:
        raise ValueError(f"{func}: no structure named {target!r} "
                         f"(registered: {', '.join(known) or 'none'})")
    if info["type"] not in allowed:
        raise ValueError(f"{func}: {target!r} is a {info['type']}; this quantity needs a "
                         f"{' or '.join(allowed)}")
    need = {"faces": "surface_mesh", "edges": "curve_network",
            "corners": "surface_mesh"}.get(defined_on)
    if need and info["type"] != need:
        raise ValueError(f"{func}: defined_on={defined_on!r} needs a {need}; "
                         f"{target!r} is a {info['type']}")
    if defined_on == "corners" and info.get("n_corners", 0) is None:
        raise ValueError(f"{func}: {target!r} has polygons kayviz triangulated (more than 4 "
                         f"sides, or bent / non-convex quads); per-corner values need "
                         f"triangles or quads, use defined_on='vertices'")
    expected = info.get({"faces": "n_faces", "edges": "n_edges",
                         "corners": "n_corners"}.get(defined_on, "n_vertices"))
    if expected is not None and n_values != expected:
        raise ValueError(f"{func}: {target!r} has {expected} {defined_on}, "
                         f"got {n_values} values")


# ── Public API ────────────────────────────────────────────────────────────────

def init(url: str = None, port: int = None, autostart: bool = None) -> None:
    """
    Start (or attach to) the viewer server. Calling it again is a no-op.

    Args:
        url:       Attach to an already-running kayviz server at this URL.
        port:      Port for the in-process server (default: first free from 8000).
        autostart: Ignored; kept for backward compatibility.
    """
    global _url, _server, _mode

    if _mode is not None:
        return

    url = url or os.environ.get("KAYVIZ_URL") or os.environ.get("WEBSCOPE_URL")
    if url:
        url = url.rstrip("/")
        if _ping_info(url) is None:
            raise RuntimeError(f"[kayviz] No kayviz server reachable at {url}.")
        _url, _mode = url, "attached"
        print(f"[kayviz] Attached to {_url}", flush=True)
        return

    # A process that registered its own GUI apps serves them itself; only
    # plain geometry scripts/notebooks attach to a shared viewer.
    owns_apps = any(n != "script" for n in _registry.app_names())
    if port is None and not owns_apps:
        default_url = f"http://127.0.0.1:{_DEFAULT_PORT}"
        info = _ping_info(default_url)
        if info and info.get("shared"):
            _url, _mode = default_url, "attached"
            print(f"[kayviz] Attached to shared viewer at {_url}", flush=True)
            return

    from kayviz.server import BackgroundServer
    _server = BackgroundServer(port=port)
    _server.start()
    _url, _mode = _server.url, "local"
    print(f"[kayviz] Viewer running at {_url}", flush=True)


def url() -> str:
    """URL of the viewer server (starts it if needed)."""
    _ensure_init()
    return _url


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
    if material is not None and material not in KNOWN_MATERIALS:
        import warnings
        warnings.warn(f"{name}: unknown material {material!r} (built-in: "
                      f"{', '.join(KNOWN_MATERIALS)}); unless a custom shader of that name "
                      f"is registered in the browser, the global shader is used", stacklevel=2)
    result = ser.surface_mesh(name, vertices, faces,
                              color=color, opacity=opacity,
                              show_edges=show_edges, edge_color=edge_color,
                              edge_radius=edge_radius, show=show, material=material,
                              shading=shading, face_size=face_size, back_color=back_color,
                              show_wireframe=show_wireframe, wireframe_width=wireframe_width)
    _push(result)


def register_curve_network(name: str, vertices, edges,
                           color=(0.8, 0.2, 0.2), radius: float = None,
                           show: bool = True) -> None:
    """Mirrors ps.register_curve_network(). show=False registers it hidden.
    radius: tube radius; None picks 0.15% of the curve's size, 0 draws thin lines."""
    _push(ser.curve_network(name, vertices, edges, color=color, radius=radius, show=show))


def register_point_cloud(name: str, points,
                         color=(0.2, 0.5, 0.8), radius: float = None,
                         show: bool = True, point_render: str = "sprite") -> None:
    """Mirrors ps.register_point_cloud(). show=False registers it hidden.
    radius: sphere radius; None picks 0.5% of the cloud's size.
    point_render: "sprite" (default: 2 triangles per point, drawn as a sphere; no
    studio shadow or AO) or "sphere" (~170 triangles per point)."""
    _push(ser.point_cloud(name, points, color=color, radius=radius, show=show,
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
    _check_quantity("add_scalar_quantity", target, len(d["values"]), defined_on,
                    ("surface_mesh", "point_cloud", "curve_network"))
    _push(d)


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
    _check_quantity("add_parameterization_quantity", target, len(d["uv"]) // 2, defined_on,
                    ("surface_mesh",))
    _push(d)


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
    _check_quantity("add_vector_quantity", target, len(d["vectors"]) // 3, defined_on,
                    ("surface_mesh",) if defined_on == "faces" else ("surface_mesh", "point_cloud"))
    _push(d)


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
    _push(ser.vector_field(name, origins, vectors, length=length, radius=radius, color=color,
                           show=show, vectortype=vectortype))


def set_up_dir(axis: str) -> None:
    """Up axis of the viewer: "z" (default) or "y". Open tabs reload to apply it."""
    global _up
    if axis not in ("y", "z"):
        raise ValueError(f"set_up_dir: axis must be 'y' or 'z', got {axis!r}")
    _up = axis
    _view({"up": axis})


def look_at(position, target=(0.0, 0.0, 0.0)) -> None:
    """Place the camera of the open viewer tabs at *position*, looking at *target*."""
    pos = [float(x) for x in position]
    tgt = [float(x) for x in target]
    if len(pos) != 3 or len(tgt) != 3:
        raise ValueError("look_at: position and target are 3D points")
    o = ser.get_origin()                  # the viewer works relative to it
    if o is not None:
        pos = [p - c for p, c in zip(pos, o)]
        tgt = [t - c for t, c in zip(tgt, o)]
    _view({"camera": {"position": pos, "target": tgt}})


def export(name: str, path, format: str | None = None):
    """Write the registered object *name* (surface mesh, curve network or point cloud)
    to *path*: ``.obj`` or ``.ply`` (or *format*). Polygon meshes keep their
    polygons; PLY also carries the object's vertex and face scalar quantities.
    Coordinates are yours (the scene origin added back). Needs no browser.

    Returns the path written."""
    from .. import exporter as _export
    from .broadcast_mixin import BroadcastMixin
    if _mode == "attached":
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


def reset_camera() -> None:
    """Frame the whole scene in the open viewer tabs (as the R key does)."""
    _view({"fit": True})


def _view(msg: dict) -> None:
    """View settings go to every tab (all apps subscribe to the script channel)."""
    _ensure_init()
    if _mode in ("local", "hosted"):
        script = _registry.get_app("script")
        _run_on_loop(script._broadcast({"action": "view", **msg}))
        return
    try:
        requests.post(f"{_url}/api/script/view", json=msg, timeout=10)
    except requests.RequestException as e:
        print(f"[kayviz] view failed: {e}", file=sys.stderr)


def push_objects(objects: list) -> None:
    """Push a list of pre-built serializer dicts (from Scene or ser.lmesh_scene etc.)."""
    if not objects:
        return
    _track(objects)
    sink = _push_sink()
    if sink is not None:
        sink(objects)
        return
    _send("push", objects=objects)


def _push_with_seq(objects: list, seq: int) -> None:
    """push_objects, asking the tabs to report when they drew it: they answer
    {action: "applied", seq}, read at /api/script/applied (kayviz.evaluate).
    Needs this process's own server (local or hosted mode)."""
    _ensure_init()
    if _mode not in ("local", "hosted"):
        raise RuntimeError("kayviz: timed pushes need this process's own server")
    _track(objects)
    _run_on_loop(_registry.get_app("script").push(objects, seq=seq))


def set_enabled(name: str, enabled: bool) -> None:
    """Mirrors structure.set_enabled()."""
    _push(ser.set_enabled(name, enabled))


def remove(name: str) -> None:
    """Remove one named object (and its quantities) from the scene."""
    marker = [{"action": "remove", "name": name}]
    _track(marker)
    sink = _push_sink()
    if sink is not None:            # inside a user callback: its app's buffer too
        sink(marker)
        return
    _send("remove", name=name)


def clear() -> None:
    """Remove all objects from the scene. Mirrors ps.remove_all_structures()."""
    # Inside a user callback (CallbackApp), geometry is captured into a local
    # sink rather than sent to the script channel — route the clear through
    # the same hook so it clears that app's buffer.
    _track([{"action": "clear"}])
    ser._new_scene()
    sink = _push_sink()
    if sink is not None:
        sink([{"action": "clear"}])
        return
    _send("clear")


# ── Screenshots ───────────────────────────────────────────────────────────────

# Default: reuse the camera exactly as it is in the open viewer tab, so captures
# match the framing and zoom the user set up by orbiting.  The second view spins
# that same camera 90 degrees around the orbit target, keeping the zoom level.
DEFAULT_VIEWS = (
    {"live": True},
    {"live": True, "orbit": 90.0},
)

# Framing computed from the scene bounds instead of the live camera.  Use when
# you want every mesh framed identically regardless of where the camera sits.
# "dir" is written y-up (x right, y up, z towards the viewer); with a z-up viewer it is
# turned so the views look the same. Give "up" to use dir and up literally.
FITTED_VIEWS = (
    {"dir": (1.0, 0.7, 1.0),   "zoom": 1.05},
    {"dir": (-1.0, 0.5, -0.8), "zoom": 1.05},
)

# Same fixed angles as FITTED_VIEWS but closer in, so less empty background.
# `zoom` scales the auto-fit distance: 1.0 exactly fits the bounding sphere,
# below 1.0 moves the camera nearer and crops the margin, above 1.0 pulls back.
#
#   ZOOM   framing
#   1.05   default fit, generous margin  (FITTED_VIEWS)
#   0.85   moderately tight
#   0.75   tight  <- current
#   0.65   very tight; a long/curved mesh may start to clip at the edges
#
# Tune TIGHT_ZOOM to taste; both views stay in step because they share it.
TIGHT_ZOOM = 0.75

TIGHT_VIEWS = (
    {"dir": (1.0, 0.7, 1.0),   "zoom": TIGHT_ZOOM},
    {"dir": (-1.0, 0.5, -0.8), "zoom": TIGHT_ZOOM},
)

# Populated by the last capture; surfaced through get_camera().
_last_camera = None


def get_camera():
    """Camera of the open viewer, as recorded by the most recent capture.

    Returns a dict with ``position``, ``target``, ``up``, ``fov`` and
    ``distance``, or None if no capture has run yet.  Take a screenshot first
    (even a tiny one) to populate it:

        kv.screenshot_views(width=16, height=16)
        print(ws.get_camera())

    Positions are in your coordinates (the scene origin added back).
    """
    o = ser.get_origin()
    if _last_camera is None or o is None:
        return _last_camera
    shift = lambda p: [float(a + b) for a, b in zip(p, o)]
    return {**_last_camera, "position": shift(_last_camera["position"]),
            "target": shift(_last_camera["target"])}


def _capture(views, width, height, hide_grid, timeout, background="white"):
    """Ask the browser to render `views` and return a list of PNG bytes."""
    import base64

    _ensure_init()
    norm = []
    for v in views:
        if v.get("live"):
            item = {"live": True, "zoom": float(v.get("zoom", 1.0))}
            if v.get("orbit"):
                item["orbit"] = float(v["orbit"])
        else:
            if "dir" not in v:
                raise ValueError(f"screenshot view needs 'dir' (or 'live': True), got {v}")
            item = {"dir":  list(v["dir"]), "zoom": float(v.get("zoom", 1.0))}
            if "up" in v:
                item["up"] = list(v["up"])
        norm.append(item)
    views = norm
    try:
        r = requests.post(f"{_url}/api/script/screenshot/request",
                          json={"views": views, "width": width,
                                "height": height, "hide_grid": hide_grid,
                                "background": background},
                          timeout=10)
        req = r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"screenshot request failed: {e}") from e

    if not req.get("ok"):
        raise RuntimeError(
            f"screenshot failed: {req.get('error', 'unknown')}. "
            f"Open {_url} in a browser (kayviz.show()) and keep the tab open; "
            "a tab left from an earlier kernel points at a different server."
        )

    try:
        r = requests.get(f"{_url}/api/script/screenshot/collect",
                         params={"id": req["id"], "timeout": timeout},
                         timeout=timeout + 10)
        res = r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"screenshot collect failed: {e}") from e

    if res.get("error"):
        raise RuntimeError(f"screenshot failed in browser: {res['error']}")

    out = []
    for url in res.get("images", []):
        out.append(base64.b64decode(url.split(",", 1)[1]))
    if not out:
        raise RuntimeError("screenshot returned no images")
    global _last_camera
    _last_camera = res.get("camera")
    return out


def screenshot(path, views=None, width: int = 900, height: int = 700,
               hide_grid: bool = True, timeout: float = 30.0,
               background: str = "white"):
    """
    Capture the current scene from two (or more) views.

    Args:
        path:      output path. With a single view this is the file written.
                   With several views a ``_v0``, ``_v1`` … suffix is inserted
                   before the extension, and the list of paths is returned.
        views:     iterable of ``{"dir": (x,y,z), "up": (x,y,z), "zoom": f}`` or
                   ``{"live": True}``; default: the current view of the open tab,
                   written to *path* (pass DEFAULT_VIEWS for the two-view pair).
        width:     pixel width of each view.
        height:    pixel height of each view.
        hide_grid: hide the reference grid during capture.
        timeout:   seconds to wait for the browser to respond.
        background: "white" (default), any CSS colour, "transparent" for an
                   empty (alpha) background, or "viewer" to keep the viewer's.

    Returns:
        str | list[str]: the path(s) written.

    Requires an open viewer tab — the pixels are produced by the browser.
    """
    views = list(views) if views is not None else [{"live": True}]
    blobs = _capture(views, width, height, hide_grid, timeout, background)

    path = str(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

    if len(blobs) == 1:
        with open(path, "wb") as fh:
            fh.write(blobs[0])
        return path

    stem, ext = os.path.splitext(path)
    ext = ext or ".png"
    paths = []
    for i, b in enumerate(blobs):
        q = f"{stem}_v{i}{ext}"
        with open(q, "wb") as fh:
            fh.write(b)
        paths.append(q)
    return paths


def screenshot_views(views=None, width: int = 900, height: int = 700,
                     hide_grid: bool = True, timeout: float = 30.0,
                     background: str = "white"):
    """Capture the scene and return the raw PNG bytes per view (no file written).

    Useful for assembling a contact sheet across several scenes — see
    ``save_grid``.  ``background`` is as in ``screenshot``.
    """
    views = list(views) if views is not None else list(DEFAULT_VIEWS)
    return _capture(views, width, height, hide_grid, timeout, background)


def benchmark(frames: int = 60, timeout: float = 60.0, show: bool = True,
              toggles: bool = False, tab_memory: bool = False) -> dict:
    """Measure the open viewer tab drawing the current scene, in plain and in studio
    mode: frame times (each frame timed until the GPU finished it), triangles, draw
    calls, and memory (geometry exactly; screen, studio and shadow buffers estimated
    from their formats; the browser's JavaScript heap). Prints a table when *show*.

    toggles: also time studio on/off, the largest mesh's edge overlay and flat
    shading (key "toggles"). tab_memory: also the tab's whole memory
    (memory_mb["tab"]); only a cross-origin isolated page can measure it
    (KAYVIZ_ISOLATED=1 before the server starts), else None.

    Returns the measurements as a dict (keys "modes", "scene", "memory_mb")."""
    _ensure_init()
    try:
        r = requests.post(f"{_url}/api/script/benchmark/request",
                          json={"frames": frames, "toggles": toggles, "tab_memory": tab_memory},
                          timeout=10).json()
        if not r.get("ok"):
            raise RuntimeError(f"benchmark: {r.get('error')} — open {_url} in a browser")
        res = requests.get(f"{_url}/api/script/screenshot/collect",
                           params={"id": r["id"], "timeout": timeout}, timeout=timeout + 10).json()
    except requests.RequestException as e:
        raise RuntimeError(f"benchmark failed: {e}") from e
    if res.get("error") or not res.get("result"):
        raise RuntimeError(f"benchmark failed in browser: {res.get('error')}")
    result = res["result"]
    if show:
        print(benchmark_table(result))
    return result


def benchmark_table(r: dict) -> str:
    """A kv.benchmark() result as a plain-text table."""
    p, s = r["modes"]["plain"], r["modes"]["studio"]
    m = r["memory_mb"]
    f = lambda x, d=1: "—" if x is None else f"{x:.{d}f}"
    rows = [
        ("frame, median (ms)", f(p["median_ms"]), f(s["median_ms"])),
        ("frame, 95% (ms)",    f(p["p95_ms"]),    f(s["p95_ms"])),
        ("frames / s",         f(p["fps"], 0),    f(s["fps"], 0)),
        ("triangles",          f"{p['triangles']:,}", f"{s['triangles']:,}"),
        ("draw calls",         str(p["draw_calls"]), str(s["draw_calls"])),
        ("GPU memory (MB)",    f(p["gpu_mb"]),    f(s["gpu_mb"])),
        ("  geometry",         f(m["geometry"]),  f(m["geometry"])),
        ("  screen buffers",   f(p["buffers_mb"]["screen"]), f(s["buffers_mb"]["screen"])),
        ("  studio buffers",   "—",               f(s["buffers_mb"]["studio"])),
        ("  shadow maps",      "—",               f(s["buffers_mb"]["shadow"])),
        ("JS heap (MB)",       f(m["js_heap"]),   ""),
    ]
    w = max(len(a) for a, _, _ in rows)
    lines = [f"{'':<{w}}  {'plain':>10}  {'studio':>10}"]
    lines += [f"{a:<{w}}  {b:>10}  {c:>10}" for a, b, c in rows]
    sc = r["scene"]
    lines.append(f"{sc['objects']} objects, {sc['vertices']:,} vertices, canvas {sc['canvas']} "
                 f"(pixel ratio {r['pixel_ratio']}), {r['frames']} frames per mode; buffer "
                 f"sizes estimated, geometry exact.")
    return "\n".join(lines)


def save_grid(path, rows, labels=None, pad: int = 8, bg=(255, 255, 255),
              label_height: int = 28):
    """
    Assemble captured views into one contact-sheet image.

    Args:
        path:   output image path (``.png`` or ``.jpg``).
        rows:   list of rows; each row is a list of PNG byte strings, as
                returned by ``screenshot_views``. One row per mesh.
        labels: optional per-row text drawn in the left margin.
        pad:    padding in pixels between tiles.
        bg:     background colour.
        label_height: height of the caption strip under each row (0 to disable).

    Returns:
        str: the path written.

    Requires Pillow.
    """
    from io import BytesIO

    try:
        from PIL import Image, ImageDraw
    except ImportError as e:  # pragma: no cover - depends on environment
        raise RuntimeError("save_grid needs Pillow (pip install pillow)") from e

    def _tile(b):
        # Composite over bg so transparent captures don't turn black.
        im = Image.open(BytesIO(b)).convert("RGBA")
        base = Image.new("RGBA", im.size, tuple(bg) + (255,))
        return Image.alpha_composite(base, im).convert("RGB")

    grid = [[_tile(b) for b in row] for row in rows]
    if not grid or not grid[0]:
        raise ValueError("save_grid: no images")

    ncol = max(len(r) for r in grid)
    tw   = max(im.width for r in grid for im in r)
    th   = max(im.height for r in grid for im in r)
    cell_h = th + (label_height if labels else 0)

    W = ncol * tw + (ncol + 1) * pad
    H = len(grid) * cell_h + (len(grid) + 1) * pad

    sheet = Image.new("RGB", (W, H), tuple(bg))
    draw  = ImageDraw.Draw(sheet)

    for r, row in enumerate(grid):
        y = pad + r * (cell_h + pad)
        for c, im in enumerate(row):
            x = pad + c * (tw + pad)
            sheet.paste(im, (x, y))
        if labels and r < len(labels) and labels[r]:
            draw.text((pad + 4, y + th + 6), str(labels[r]), fill=(20, 20, 20))

    d = os.path.dirname(str(path))
    if d:
        os.makedirs(d, exist_ok=True)
    sheet.save(str(path))
    return str(path)


def register_app(app, panel_js: str = None) -> None:
    """
    Serve a GUIApp from this process's viewer; ``show()`` then opens it.

    Args:
        app:      a GUIApp instance (state class + action handlers).
        panel_js: optional custom panel module for the browser. Relative
                  paths are resolved against the calling file's directory.
    """
    global _default_app
    _refuse_if_attached("register_app")
    if panel_js:
        app.panel_js = _resolve_caller_path(panel_js)
    _registry.register_app(app)
    _default_app = app.name


def set_user_callback(fn: callable, app_name: str = "callback",
                      on_load: callable = None) -> None:
    """
    Register a GUI-building callback function, à la ps.set_user_callback().

    Runs `fn` once in schema mode to capture widget descriptors, then serves
    it as a CallbackApp from this process's viewer.

    The callback is invoked again on every browser widget event (slider drag,
    button click). Inside it, use kv.imgui.* to declare widgets and trigger
    side effects:

        state = {"radius": 4.0}

        def gui():
            kv.imgui.slider_float("Radius", state, "radius", 0.1, 10)
            if kv.imgui.button("Run"):
                push_results()

        kv.set_user_callback(gui, on_load=push_initial_scene)
        kv.show()

    Args:
        fn:       Zero-argument callable that describes the GUI.
        app_name: URL segment for the app (default: "callback").
        on_load:  Optional zero-argument callable called once to push the
                  app's initial scene.
    """
    from .callback_app import CallbackApp
    _refuse_if_attached("set_user_callback")
    register_app(CallbackApp(fn, app_name=app_name, on_load=on_load))


def thread(fn: callable, *args, **kwargs) -> threading.Thread:
    """
    Start a daemon thread that runs ``fn(*args, **kwargs)`` in a copy of the
    current ``contextvars`` context, so geometry pushed from it goes where the
    caller's pushes go (e.g. the callback's buffer when started inside
    ``set_user_callback``).
    """
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(fn, *args), kwargs=kwargs, daemon=True)
    t.start()
    return t


def show(block: "str | bool" = "auto", app: str = None) -> None:
    """
    Open the viewer in the browser and optionally wait until it is closed.

    Args:
        block: True  — block until the browser tab is closed (script-style).
               False — open the tab and return immediately (notebook-style).
               "auto" — block in plain scripts; return immediately in IPython.
        app:   app to open (default: the last one registered, else the
               plain script viewer).
    """
    _ensure_init()
    if _mode == "hosted":
        return      # running inside a server process — nothing to open

    if block == "auto":
        block = "IPython" not in sys.modules

    name = app or _default_app or "script"
    if _mode == "local" and _registry.get_app(name) is None:
        raise ValueError(f"show: no app named {name!r} "
                         f"(apps: {', '.join(_registry.app_names())})")
    viewer_url = f"{_url}/?app={name}"
    if name in _opened:
        print(f"[kayviz] Viewer already open — {viewer_url}", flush=True)
    elif (_mode == "local" and os.environ.get("KAYVIZ_NO_BROWSER", "0") != "1"
          and _wait_for_tab(name)):
        # A tab from an earlier run reconnected (it reloads itself for this server).
        print(f"[kayviz] Reusing the open viewer tab — {viewer_url}", flush=True)
        _opened.add(name)
    elif os.environ.get("KAYVIZ_NO_BROWSER", "0") == "1":
        print(f"[kayviz] Viewer at {viewer_url} (KAYVIZ_NO_BROWSER: open it yourself)",
              flush=True)
        _opened.add(name)
    else:
        print(f"[kayviz] Opening {viewer_url}", flush=True)
        webbrowser.open(viewer_url)
        _opened.add(name)

    if block:
        print("[kayviz] Close the browser tab or press Ctrl+C to exit.", flush=True)
        try:
            _wait_until_idle()
        except KeyboardInterrupt:
            print("\n[kayviz] Interrupted.")


def kill_servers(ports=None, host: str = "127.0.0.1",
                 force: bool = False) -> list:
    """
    Stop every kayviz viewer server on this machine and reset this process's
    viewer, so the next kayviz call starts a fresh server with an empty scene.

    Each kernel/script that used kayviz runs its own server on the first free
    port from 8000; they keep running until their process exits. This stops
    them all — the processes themselves (e.g. Jupyter kernels) keep running.

    Args:
        ports: ports to scan; default the 100 ports from KAYVIZ_PORT (8000).
        host:  interface the servers listen on.
        force: also terminate a standalone ``python -m kayviz`` process that
               does not answer the shutdown request (never a Jupyter kernel).

    Returns:
        list[str]: URLs of the servers that were stopped.
    """
    global _url, _mode
    import socket

    if ports is None:                       # the range kv.init() picks from
        ports = range(_DEFAULT_PORT, _DEFAULT_PORT + 100)

    stopped, found = [], 0
    if _server is not None:                     # this process's own server
        own = _server.url
        _server.stop()
        stopped.append(own)
        print(f"[kayviz] Stopped {own} (this process)", flush=True)
    _on_server_stopped()
    _url, _mode = None, None

    for port in ports:
        base = f"http://{host}:{port}"
        if base in stopped:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            if s.connect_ex((host, port)) != 0:
                continue
        if _ping_info(base) is None:            # something else, not kayviz
            continue
        found += 1

        try:
            r = requests.post(f"{base}/api/_shutdown", timeout=2)
            ok = r.status_code == 200 and r.json().get("ok", False)
        except (requests.RequestException, ValueError):
            ok = False

        proc = _port_owner(port)
        who  = f" (pid {proc.pid})" if proc else ""
        if ok:
            # Wait for the port to actually go quiet before reporting it.
            deadline = time.monotonic() + 5
            while _ping_info(base) is not None and time.monotonic() < deadline:
                time.sleep(0.1)
            stopped.append(base)
            print(f"[kayviz] Stopped {base}{who}", flush=True)
            continue

        cmd = " ".join(proc.cmdline()) if proc else ""
        if force and proc and "kayviz" in cmd and "ipykernel" not in cmd:
            proc.terminate()
            stopped.append(base)
            print(f"[kayviz] Terminated standalone viewer {base}{who}", flush=True)
        elif "ipykernel" in cmd:
            print(f"[kayviz] {base}{who} did not stop: it belongs to a Jupyter "
                  "kernel running older kayviz code — restart that kernel.",
                  flush=True)
        else:
            print(f"[kayviz] {base}{who} did not stop "
                  "(pass force=True to terminate a standalone viewer).", flush=True)

    if not stopped and not found:
        print("[kayviz] No kayviz servers running.", flush=True)
    return stopped


# ── Internals ─────────────────────────────────────────────────────────────────

def _on_server_stopped() -> None:
    """Forget this process's server once it has shut down, so the next
    kayviz call starts a new one instead of pushing to a dead loop."""
    global _url, _server, _mode
    if _mode == "local":
        _url, _server, _mode = None, None, None
    _opened.clear()
    with _structures_lock:
        _structures.clear()
    for name in _registry.app_names():          # tabs belong to the old server
        app = _registry.get_app(name)
        if hasattr(app, "_reset_clients"):
            app._reset_clients()
    script = _registry.get_app("script")
    if script is not None:                      # start the next one empty
        script._buffer.clear()
        script._shot_queue.clear()
        script._shot_pending.clear()
        script._shot_done.clear()


def _port_owner(port: int):
    """psutil.Process listening on *port*, or None (no psutil / not ours)."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        for c in psutil.net_connections(kind="tcp"):
            if (c.status == psutil.CONN_LISTEN and c.laddr
                    and c.laddr.port == port and c.pid):
                return psutil.Process(c.pid)
    except psutil.Error:
        pass
    return None


# A tab whose server stopped retries every <= 2 s (ws.js): after a restart on the
# same port it is back within _TAB_RETURN_WAIT. It then reloads itself for the new
# server (switching to this app if its own is gone), which takes a few seconds more.
_TAB_RETURN_WAIT = 2.5
_TAB_RELOAD_WAIT = 8.0


def _wait_for_tab(name: str) -> bool:
    """True if an open browser tab comes back and shows app *name*."""
    app = _registry.get_app(name)
    script = _registry.get_app("script")
    clients = getattr(app, "_clients", None)
    if clients is None or script is None:    # app without client tracking
        return False
    deadline = time.monotonic() + _TAB_RETURN_WAIT
    while not script._clients:               # every page connects to "script"
        if clients:
            return True
        if time.monotonic() > deadline:
            return False                     # no tab came back: open one
        time.sleep(0.1)
    deadline = time.monotonic() + _TAB_RELOAD_WAIT
    while time.monotonic() < deadline:
        if clients:
            return True
        time.sleep(0.1)
    return False


def _ensure_init() -> None:
    if _mode is None:
        init()


def _refuse_if_attached(what: str) -> None:
    if _mode == "attached":
        raise RuntimeError(
            f"[kayviz] {what}() needs this process's own viewer, but kayviz is "
            f"attached to the server at {_url}. Call {what}() before "
            "kayviz.init(), and stop that server (or unset KAYVIZ_URL)."
        )


def _bind_loop(loop) -> None:
    """Called by kayviz.server when a server starts/stops in this process."""
    global _loop, _mode
    _loop = loop
    if loop is not None and _mode is None:
        _mode = "hosted"        # e.g. uvicorn serving create_app() directly
    elif loop is None and _mode == "hosted":
        _mode = None


_loop_tasks: set = set()     # pushes scheduled from the loop itself (kept referenced)


def _report_task(task) -> None:
    _loop_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        print(f"[kayviz] push failed: {task.exception()!r}", file=sys.stderr, flush=True)


def _run_on_loop(coro) -> None:
    if _loop is None:
        coro.close()
        raise RuntimeError("[kayviz] the viewer server is not running")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        # Inside a handler on the server loop — blocking would deadlock. The push
        # takes the app's order lock, so pushes still go out in the order made.
        task = _loop.create_task(coro)
        _loop_tasks.add(task)
        task.add_done_callback(_report_task)
    else:
        # Returns once the message is buffered and queued for the tabs.
        asyncio.run_coroutine_threadsafe(coro, _loop).result(30)


def _resolve_caller_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    here = os.path.dirname(os.path.abspath(__file__))
    for frame in inspect.stack()[1:]:
        fdir = os.path.dirname(os.path.abspath(frame.filename))
        if fdir != here:
            candidate = os.path.join(fdir, path)
            if os.path.exists(candidate):
                return candidate
            break
    return os.path.abspath(path)


def _push(obj: dict) -> None:
    push_objects([obj])


def _send(op: str, objects: list = None, name: str = None) -> None:
    """Deliver a push/remove/clear to the script channel (in-process or HTTP)."""
    _ensure_init()
    if _mode in ("local", "hosted"):
        script = _registry.get_app("script")
        coro = {"push":   lambda: script.push(objects),
                "remove": lambda: script.do_remove(name),
                "clear":  lambda: script.do_clear()}[op]()
        _run_on_loop(coro)
        return
    from .wire import FRAME_TYPE, encode
    path, payload = {"push":   ("push",   {"objects": objects}),
                     "remove": ("remove", {"name": name}),
                     "clear":  ("push",   {"action": "clear"})}[op]
    data = encode(payload)
    # arrays travel as a binary frame (4x smaller than JSON lists, no parsing)
    kw = ({"data": data, "headers": {"Content-Type": "application/json"}}
          if isinstance(data, str) else
          {"data": bytes(data), "headers": {"Content-Type": FRAME_TYPE}})
    try:
        requests.post(f"{_url}/api/script/{path}", timeout=60, **kw)
    except requests.RequestException as e:
        print(f"[kayviz] {op} failed: {e}", file=sys.stderr)


def _ping_info(base_url: str) -> Optional[dict]:
    """Return the /ping payload if a kayviz server answers at base_url."""
    try:
        r = requests.get(f"{base_url}/api/script/ping", timeout=1)
        if r.status_code == 200:
            return r.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def _wait_until_idle(poll_interval: float = 1.0, timeout: float = 24 * 3600.0) -> None:
    """Block until every viewer tab is closed (reloads are tolerated)."""
    deadline = time.monotonic() + timeout
    hinted = False
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{_url}/api/script/wait",
                             params={"timeout": 30.0, "connect_timeout": 30.0,
                                     "grace": 3.0},
                             timeout=100.0)
            res = r.json() if r.status_code == 200 else {}
            if res.get("idle") and res.get("seen"):
                return
            if not res.get("seen") and not hinted:
                # no tab within connect_timeout (KAYVIZ_NO_BROWSER, remote machine,
                # browser that did not open): say where to look instead of hanging
                hinted = True
                print(f"[kayviz] No viewer tab connected yet — open {_url} in a browser "
                      f"(Ctrl+C to stop).", flush=True)
            if r.status_code != 200:
                time.sleep(poll_interval)        # never spin on a failing server
        except (requests.RequestException, ValueError):
            time.sleep(poll_interval)
