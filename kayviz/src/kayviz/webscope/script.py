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
import inspect
import os
import sys
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

# _push_to_sink is a hook used by CallbackApp._CallbackPushCapture to redirect
# geometry pushes that happen inside a user callback away from the script
# channel and into the CallbackApp broadcast buffer instead.
# None means: use the normal push path.
_push_to_sink: Optional[callable] = None

# App opened by show(): the last app registered from this process.
_default_app: Optional[str] = None


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
                          edge_color=(0.8, 0.8, 0.8),
                          edge_radius: float = 0.0, show: bool = True) -> None:
    """Mirrors ps.register_surface_mesh(). Pass show_edges=True to overlay the wireframe,
    show=False to register it hidden (tick it in the scene panel to show it)."""
    result = ser.surface_mesh(name, vertices, faces,
                              color=color, opacity=opacity,
                              show_edges=show_edges, edge_color=edge_color,
                              edge_radius=edge_radius, show=show)
    if isinstance(result, list):
        push_objects(result)
    else:
        _push(result)


def register_curve_network(name: str, vertices, edges,
                           color=(0.8, 0.2, 0.2), radius: float = 0.002,
                           show: bool = True) -> None:
    """Mirrors ps.register_curve_network(). show=False registers it hidden."""
    _push(ser.curve_network(name, vertices, edges, color=color, radius=radius, show=show))


def register_point_cloud(name: str, points,
                         color=(0.2, 0.5, 0.8), radius: float = 0.0005,
                         show: bool = True) -> None:
    """Mirrors ps.register_point_cloud(). show=False registers it hidden."""
    _push(ser.point_cloud(name, points, color=color, radius=radius, show=show))


def add_scalar_quantity(target: str, field_name: str, values,
                        defined_on: str = "vertices", show: bool = None) -> None:
    """Mirrors structure.add_scalar_quantity().

    show: None (default) follows the target; True colours the target with it and shows the
    target if it was hidden; False adds it without colouring the mesh.
    """
    _push(ser.scalar_quantity(target, field_name, values, defined_on=defined_on, show=show))


def add_vector_quantity(target: str, field_name: str, vectors,
                        defined_on: str = "vertices",
                        length: float = 0.05, radius: float = None,
                        show: bool = None, color=None) -> None:
    """Mirrors structure.add_vector_quantity().

    Args:
        target:     Name of the surface mesh (or point cloud) the vectors are attached to.
        field_name: Scene label for the vector quantity.
        vectors:    (N, 3) direction vectors (unit-normalized in the viewer).
        defined_on: "vertices" (arrows start at the vertices) or "faces" (at the face
                    barycenters; N must be the number of faces).
        length:     Total arrow length in scene units; adjust with the scene-panel slider.
        radius:     Arrow shaft/cone radius in scene units; defaults to length * 0.04.
        show:       None (default) follows the target: hidden while the target is hidden.
                    True shows the arrows and the target; False adds them hidden.
                    Several vector quantities of one target can be shown at once.
        color:      [r, g, b] in 0-1. None (default): the next colour of the viewer's
                    palette not used by the target's other vector quantities.
    """
    _push(ser.vector_quantity(target, field_name, vectors, defined_on=defined_on,
                              length=length, radius=radius, show=show, color=color))


def register_vector_field(name: str, origins, vectors,
                          length: float = 0.05,
                          radius: float = None,
                          color=(0.2, 0.8, 0.4), show: bool = True) -> None:
    """Render an arrow field (cylinder shaft + cone head per vector).

    Args:
        name:    Scene label.
        origins: (N, 3) base points for each arrow.
        vectors: (N, 3) direction vectors (unit-normalized in the viewer).
        length:  Total arrow length in scene units; adjust with the scene-panel slider.
        radius:  Arrow shaft/cone radius in scene units; defaults to length * 0.04.
        color:   [r, g, b] in 0-1.
        show:    False registers it hidden (tick it in the scene panel to show it).
    """
    _push(ser.vector_field(name, origins, vectors, length=length, radius=radius, color=color,
                           show=show))


def push_objects(objects: list) -> None:
    """Push a list of pre-built serializer dicts (from Scene or ser.lmesh_scene etc.)."""
    if not objects:
        return
    if _push_to_sink is not None:
        _push_to_sink(objects)
        return
    _send("push", objects=objects)


def set_enabled(name: str, enabled: bool) -> None:
    """Mirrors structure.set_enabled()."""
    _push(ser.set_enabled(name, enabled))


def remove(name: str) -> None:
    """Remove one named object from the scene."""
    _send("remove", name=name)


def clear() -> None:
    """Remove all objects from the scene. Mirrors ps.remove_all_structures()."""
    # Inside a user callback (CallbackApp), geometry is captured into a local
    # sink rather than sent to the script channel — route the clear through
    # the same hook so it clears that app's buffer.
    if _push_to_sink is not None:
        _push_to_sink([{"action": "clear"}])
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
FITTED_VIEWS = (
    {"dir": (1.0, 0.7, 1.0),   "up": (0.0, 1.0, 0.0), "zoom": 1.05},
    {"dir": (-1.0, 0.5, -0.8), "up": (0.0, 1.0, 0.0), "zoom": 1.05},
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
    {"dir": (1.0, 0.7, 1.0),   "up": (0.0, 1.0, 0.0), "zoom": TIGHT_ZOOM},
    {"dir": (-1.0, 0.5, -0.8), "up": (0.0, 1.0, 0.0), "zoom": TIGHT_ZOOM},
)

# Populated by the last capture; surfaced through get_camera().
_last_camera = None


def get_camera():
    """Camera of the open viewer, as recorded by the most recent capture.

    Returns a dict with ``position``, ``target``, ``up``, ``fov`` and
    ``distance``, or None if no capture has run yet.  Take a screenshot first
    (even a tiny one) to populate it:

        ws.screenshot_views(width=16, height=16)
        print(ws.get_camera())
    """
    return _last_camera


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
            item = {"dir":  list(v["dir"]),
                    "up":   list(v.get("up", (0.0, 1.0, 0.0))),
                    "zoom": float(v.get("zoom", 1.0))}
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
        views:     iterable of ``{"dir": (x,y,z), "up": (x,y,z), "zoom": f}``;
                   defaults to two three-quarter views.
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
    views = list(views) if views is not None else list(DEFAULT_VIEWS)
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
    viewer_url = f"{_url}/?app={name}"
    if name in _opened:
        print(f"[kayviz] Viewer already open — {viewer_url}", flush=True)
    else:
        print(f"[kayviz] Opening {viewer_url}", flush=True)
        if os.environ.get("KAYVIZ_NO_BROWSER", "0") != "1":
            webbrowser.open(viewer_url)
        _opened.add(name)

    if block:
        print("[kayviz] Close the browser tab or press Ctrl+C to exit.", flush=True)
        try:
            _wait_until_idle()
        except KeyboardInterrupt:
            print("\n[kayviz] Interrupted.")


def kill_servers(ports=range(8000, 8100), host: str = "127.0.0.1",
                 force: bool = False) -> list:
    """
    Stop every kayviz viewer server on this machine and reset this process's
    viewer, so the next kayviz call starts a fresh server with an empty scene.

    Each kernel/script that used kayviz runs its own server on the first free
    port from 8000; they keep running until their process exits. This stops
    them all — the processes themselves (e.g. Jupyter kernels) keep running.

    Args:
        ports: ports to scan.
        host:  interface the servers listen on.
        force: also terminate a standalone ``python -m kayviz`` process that
               does not answer the shutdown request (never a Jupyter kernel).

    Returns:
        list[str]: URLs of the servers that were stopped.
    """
    global _url, _mode
    import socket

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
    script = _registry.get_app("script")
    if script is not None:                      # start the next one empty
        script._buffer.clear()
        script._shot_queue.clear()
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


def _run_on_loop(coro) -> None:
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        # Inside a handler on the server loop — blocking would deadlock.
        _loop.create_task(coro)
    else:
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
    path, payload = {"push":   ("push",   {"objects": objects}),
                     "remove": ("remove", {"name": name}),
                     "clear":  ("push",   {"action": "clear"})}[op]
    try:
        requests.post(f"{_url}/api/script/{path}", json=payload, timeout=10)
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


def _ping() -> bool:
    """Return True if the server is reachable."""
    return _url is not None and _ping_info(_url) is not None


def _wait_until_idle(poll_interval: float = 1.0, timeout: float = 24 * 3600.0) -> None:
    """Block until every viewer tab is closed (reloads are tolerated)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{_url}/api/script/wait",
                             params={"timeout": 30.0, "connect_timeout": 30.0,
                                     "grace": 3.0},
                             timeout=100.0)
            res = r.json() if r.status_code == 200 else {}
            if res.get("idle") and res.get("seen"):
                return
        except (requests.RequestException, ValueError):
            time.sleep(poll_interval)
