"""
kayviz server — FastAPI app factory and the in-process background server.

    create_app()        → FastAPI app serving the viewer + every registered app
    BackgroundServer    → runs create_app() with uvicorn in a daemon thread

Most users never touch this module: ``kayviz.init()`` starts a
BackgroundServer for the current script/notebook. Use ``create_app`` when you
want to run kayviz under your own uvicorn command, e.g. a server hosting
several apps:

    from kayviz.server import create_app
    app = create_app(apps=[MyApp(), OtherApp()])
    # uvicorn mymodule:app
"""

from __future__ import annotations

import asyncio
import atexit
import os
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .security import LocalOnlyMiddleware, is_loopback
from .runtime.registry import register_app, mount_all, get_app, app_names
from .runtime.script_app import ScriptApp

STATIC_DIR = Path(__file__).parent / "static"


class _NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching JS/CSS so edits are reflected immediately."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") and request.url.path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-store"
        return response


# Browsers send small JSON messages; the limit only bounds what a client can make
# the server buffer (uvicorn's own default is 16 MB).
WS_MAX_SIZE = 4 * 1024 * 1024


def create_app(apps=(), shared: bool = False, default_app: str | None = None,
               network: bool = False) -> FastAPI:
    """
    Build the FastAPI app: viewer page, static frontend, and one router per
    registered app (plus any registered later).

    Args:
        apps:        GUIApp instances to register before mounting.
        shared:      mark this server as a standalone viewer that other
                     processes may attach to (see ``kayviz.init``).
        default_app: app opened at ``/`` when the URL has no ``?app=``.
                     Defaults to the most recently registered app.
        network:     served on a network interface (see kayviz.security): the
                     Host check is off; Origin and cross-site checks stay.
    """
    script = get_app("script")
    if script is None:
        register_app(ScriptApp(shared=shared))
    else:
        script.shared = shared
    for app in apps:
        register_app(app)

    @asynccontextmanager
    async def lifespan(_app):
        # Hand the serving loop to the scripting API so kayviz.register_* in
        # this process is delivered directly instead of over HTTP to itself.
        from .runtime import script as _script
        _script._bind_loop(asyncio.get_running_loop())
        yield
        _script._bind_loop(None)
        _script._on_server_stopped()
        from .runtime.registry import unmount
        unmount(_app)

    fastapi_app = FastAPI(title="kayviz", lifespan=lifespan)
    fastapi_app.add_middleware(_NoCacheMiddleware)
    fastapi_app.add_middleware(LocalOnlyMiddleware, network=network)   # outermost
    fastapi_app.state.default_app = default_app
    # Tabs left from an earlier server reconnect to a new one on the same port;
    # a different instance id tells them to reload (fresh panel and scene).
    instance = uuid.uuid4().hex

    @fastapi_app.get("/api/_info")
    def info():
        names = app_names()
        user_apps = [n for n in names if n != "script"]
        default = fastapi_app.state.default_app or (user_apps[-1] if user_apps else "script")
        from .runtime import script as _script
        return {"apps": names, "default": default, "shared": shared, "instance": instance,
                "up": _script._up}

    @fastapi_app.post("/api/_shutdown")
    def shutdown():
        # Used by kayviz.kill_servers(). Whoever runs the uvicorn server sets
        # app.state.shutdown; a server under a foreign uvicorn has none.
        stop = getattr(fastapi_app.state, "shutdown", None)
        if stop is None:
            return {"ok": False, "error": "this server cannot be stopped over HTTP"}
        threading.Timer(0.2, stop).start()      # let this response go out first
        return {"ok": True, "pid": os.getpid()}

    mount_all(fastapi_app)

    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @fastapi_app.get("/")
    def root():
        # the page reads the up axis synchronously, before it builds the camera
        from .runtime import script as _script
        html = (STATIC_DIR / "index.html").read_text().replace("__KAYVIZ_UP__", _script._up)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return fastapi_app


def _listening(host: str, port: int) -> bool:
    """Something accepts connections there (also a server bound to 0.0.0.0, which a
    bind test with SO_REUSEADDR does not see on macOS)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.05)
        return s.connect_ex((host, port)) == 0


def _bind(host: str, port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Like uvicorn: connections of a server that just stopped linger in TIME_WAIT;
    # without this the port looks taken and a re-run moves to the next one, away
    # from the tabs waiting to reconnect.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        s.close()
        raise
    return s


def find_free_port(start: int = 8000, host: str = "127.0.0.1", tries: int = 100) -> int:
    """Return the first port >= start that can be bound on *host* (and where no
    server is listening)."""
    for port in range(start, start + tries):
        if _listening(host, port):
            continue
        try:
            _bind(host, port).close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"no free port in {start}..{start + tries - 1}")


def bind_free_port(start: int, host: str, tries: int = 100) -> socket.socket:
    """Bind the first free port >= start and keep the socket: no other process can
    take it between the check and the server start."""
    for port in range(start, start + tries):
        if _listening(host, port):
            continue
        try:
            return _bind(host, port)
        except OSError:
            continue
    raise RuntimeError(f"no free port in {start}..{start + tries - 1}")


def ws_impl() -> str:
    """uvicorn's sans-I/O websockets protocol when available: the default ("auto")
    still picks the deprecated websockets.legacy, which logs AssertionErrors when a
    tab closes during a large send."""
    try:
        from uvicorn.config import WS_PROTOCOLS
        return "websockets-sansio" if "websockets-sansio" in WS_PROTOCOLS else "auto"
    except ImportError:
        return "auto"


class BackgroundServer:
    """uvicorn running ``create_app()`` in a daemon thread of this process."""

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        import uvicorn

        if not is_loopback(host):
            raise ValueError(f"kayviz: the in-process viewer serves this machine only "
                             f"(host {host!r}); use `python -m kayviz --host {host} "
                             f"--allow-network` to serve a network")
        self.host = host
        if port:
            if _listening(host, port):
                raise RuntimeError(f"kayviz: port {port} is taken")
            self._sock = _bind(host, port)
        else:
            self._sock = bind_free_port(int(os.environ.get("KAYVIZ_PORT", 8000)), host)
        self.port = self._sock.getsockname()[1]
        self.app = create_app()
        config = uvicorn.Config(self.app, host=self.host, port=self.port,
                                log_level="warning", ws=ws_impl(),
                                ws_max_size=WS_MAX_SIZE,
                                timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self.app.state.shutdown = lambda: setattr(self._server, "should_exit", True)
        self._thread = threading.Thread(target=self._server.run,
                                        kwargs={"sockets": [self._sock]},
                                        name="kayviz-server", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
        # A daemon thread still serving while the interpreter finalizes crashed the
        # process at exit (SIGSEGV, about 1 run in 75 of a short script): stop it first.
        atexit.register(self._stop_at_exit)
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError(f"kayviz server failed to start on {self.url}")
            if time.monotonic() > deadline:
                raise RuntimeError(f"kayviz server did not start within {timeout}s")
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def _stop_at_exit(self) -> None:
        if self._thread.is_alive():
            # graceful: force_exit cancelled the app's lifespan and logged an error;
            # open tabs are waited for at most timeout_graceful_shutdown (2 s)
            self._server.should_exit = True
            self._thread.join(timeout=3)

