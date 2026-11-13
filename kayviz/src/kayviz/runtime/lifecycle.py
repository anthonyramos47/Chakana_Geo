"""
lifecycle.py — Apps, showing the viewer, waiting for tabs, stopping servers.

Part of the scripting API (kayviz.runtime.script re-exports every name).
Shared state and helpers live in script.py and are reached as `_s.name`,
looked up at call time, so tests that monkeypatch script.X still apply.
"""

from __future__ import annotations

import contextvars
import os
import sys
import threading
import time
import webbrowser
import requests
from . import registry as _registry

from . import script as _s


def register_app(app, panel_js: str = None) -> None:
    """
    Serve a GUIApp from this process's viewer; ``show()`` then opens it.

    Args:
        app:      a GUIApp instance (state class + action handlers).
        panel_js: optional custom panel module for the browser. Relative
                  paths are resolved against the calling file's directory.
    """
    _s._refuse_if_attached("register_app")
    if panel_js:
        app.panel_js = _s._resolve_caller_path(panel_js)
    _registry.register_app(app)
    _s._default_app = app.name


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
    _s._refuse_if_attached("set_user_callback")
    _s.register_app(CallbackApp(fn, app_name=app_name, on_load=on_load))


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
    _s._ensure_init()
    if _s._mode == "hosted":
        return      # running inside a server process — nothing to open

    if block == "auto":
        block = "IPython" not in sys.modules

    name = app or _s._default_app or "script"
    if _s._mode == "local" and _registry.get_app(name) is None:
        raise ValueError(f"show: no app named {name!r} "
                         f"(apps: {', '.join(_registry.app_names())})")
    viewer_url = f"{_s._url}/?app={name}"
    if name in _s._opened:
        print(f"[kayviz] Viewer already open — {viewer_url}", flush=True)
    elif (_s._mode == "local" and os.environ.get("KAYVIZ_NO_BROWSER", "0") != "1"
          and _s._wait_for_tab(name)):
        # A tab from an earlier run reconnected (it reloads itself for this server).
        print(f"[kayviz] Reusing the open viewer tab — {viewer_url}", flush=True)
        _s._opened.add(name)
    elif os.environ.get("KAYVIZ_NO_BROWSER", "0") == "1":
        print(f"[kayviz] Viewer at {viewer_url} (KAYVIZ_NO_BROWSER: open it yourself)",
              flush=True)
        _s._opened.add(name)
    else:
        print(f"[kayviz] Opening {viewer_url}", flush=True)
        webbrowser.open(viewer_url)
        _s._opened.add(name)

    if block:
        print("[kayviz] Close the browser tab or press Ctrl+C to exit.", flush=True)
        try:
            _s._wait_until_idle()
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
    import socket

    if ports is None:                       # the range kv.init() picks from
        ports = range(_s._DEFAULT_PORT, _s._DEFAULT_PORT + 100)

    stopped, found = [], 0
    if _s._server is not None:                     # this process's own server
        own = _s._server.url
        _s._server.stop()
        stopped.append(own)
        print(f"[kayviz] Stopped {own} (this process)", flush=True)
    _s._on_server_stopped()
    _s._url, _s._mode = None, None

    for port in ports:
        base = f"http://{host}:{port}"
        if base in stopped:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            if s.connect_ex((host, port)) != 0:
                continue
        if _s._ping_info(base) is None:            # something else, not kayviz
            continue
        found += 1

        try:
            r = requests.post(f"{base}/api/_shutdown", timeout=2)
            ok = r.status_code == 200 and r.json().get("ok", False)
        except (requests.RequestException, ValueError):
            ok = False

        proc = _s._port_owner(port)
        who  = f" (pid {proc.pid})" if proc else ""
        if ok:
            # Wait for the port to actually go quiet before reporting it.
            deadline = time.monotonic() + 5
            while _s._ping_info(base) is not None and time.monotonic() < deadline:
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


def _wait_for_tab(name: str) -> bool:
    """True if an open browser tab comes back and shows app *name*."""
    app = _registry.get_app(name)
    script = _registry.get_app("script")
    clients = getattr(app, "_clients", None)
    if clients is None or script is None:    # app without client tracking
        return False
    deadline = time.monotonic() + _s._TAB_RETURN_WAIT
    while not script._clients:               # every page connects to "script"
        if clients:
            return True
        if time.monotonic() > deadline:
            return False                     # no tab came back: open one
        time.sleep(0.1)
    deadline = time.monotonic() + _s._TAB_RELOAD_WAIT
    while time.monotonic() < deadline:
        if clients:
            return True
        time.sleep(0.1)
    return False


def _wait_until_idle(poll_interval: float = 1.0, timeout: float = 24 * 3600.0) -> None:
    """Block until every viewer tab is closed (reloads are tolerated)."""
    deadline = time.monotonic() + timeout
    hinted = False
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{_s._url}/api/script/wait",
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
                print(f"[kayviz] No viewer tab connected yet — open {_s._url} in a browser "
                      f"(Ctrl+C to stop).", flush=True)
            if r.status_code != 200:
                time.sleep(poll_interval)        # never spin on a failing server
        except (requests.RequestException, ValueError):
            time.sleep(poll_interval)
