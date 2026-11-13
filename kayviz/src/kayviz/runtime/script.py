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

Layout: this module holds the state (mode, URL, server, loop, push sink, the
structures pushed) and the plumbing (init, _send, _run_on_loop, …); the API is
in register.py, view.py, capture.py and lifecycle.py, re-exported at the end.
Those modules reach everything defined here as ``script.name`` at call time, so
monkeypatching ``script.X`` (tests) and reading ``script._state`` (other
modules) work as when it was one file.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import os
import sys
import threading
from typing import Optional

import requests

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


# A tab whose server stopped retries every <= 2 s (ws.js): after a restart on the
# same port it is back within _TAB_RETURN_WAIT. It then reloads itself for the new
# server (switching to this app if its own is gone), which takes a few seconds more.
_TAB_RETURN_WAIT = 2.5
_TAB_RELOAD_WAIT = 8.0


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


# ── The API, by theme (they use the state above as script._…) ───────────────

from .register import (  # noqa: E402
    register_surface_mesh,
    register_curve_network,
    register_point_cloud,
    add_scalar_quantity,
    add_parameterization_quantity,
    add_vector_quantity,
    register_vector_field,
    push_objects,
    _push_with_seq,
    set_enabled,
    remove,
    clear,
    export,
    set_origin,
)
from .view import (  # noqa: E402
    set_up_dir,
    look_at,
    reset_camera,
    _view,
)
from .capture import (  # noqa: E402
    get_camera,
    _capture,
    screenshot,
    screenshot_views,
    benchmark,
    benchmark_table,
    save_grid,
)
from .lifecycle import (  # noqa: E402
    register_app,
    set_user_callback,
    thread,
    show,
    kill_servers,
    _port_owner,
    _wait_for_tab,
    _wait_until_idle,
)
