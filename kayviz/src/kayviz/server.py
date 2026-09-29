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
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .webscope.registry import register_app, mount_all, get_app, app_names
from .webscope.script_app import ScriptApp

STATIC_DIR = Path(__file__).parent / "static"


class _NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching JS/CSS so edits are reflected immediately."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") and request.url.path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(apps=(), shared: bool = False, default_app: str | None = None) -> FastAPI:
    """
    Build the FastAPI app: viewer page, static frontend, and one router per
    registered app (plus any registered later).

    Args:
        apps:        GUIApp instances to register before mounting.
        shared:      mark this server as a standalone viewer that other
                     processes may attach to (see ``kayviz.init``).
        default_app: app opened at ``/`` when the URL has no ``?app=``.
                     Defaults to the most recently registered app.
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
        from .webscope import script as _script
        _script._bind_loop(asyncio.get_running_loop())
        yield
        _script._bind_loop(None)

    fastapi_app = FastAPI(title="kayviz", lifespan=lifespan)
    fastapi_app.add_middleware(_NoCacheMiddleware)
    fastapi_app.state.default_app = default_app

    @fastapi_app.get("/api/_info")
    def info():
        names = app_names()
        user_apps = [n for n in names if n != "script"]
        default = fastapi_app.state.default_app or (user_apps[-1] if user_apps else "script")
        return {"apps": names, "default": default, "shared": shared}

    mount_all(fastapi_app)

    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @fastapi_app.get("/")
    def root():
        return FileResponse(STATIC_DIR / "index.html")

    return fastapi_app


def find_free_port(start: int = 8000, host: str = "127.0.0.1", tries: int = 100) -> int:
    """Return the first port >= start that can be bound on *host*."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {start}..{start + tries - 1}")


class BackgroundServer:
    """uvicorn running ``create_app()`` in a daemon thread of this process."""

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        import uvicorn

        self.host = host
        self.port = port or find_free_port(
            int(os.environ.get("KAYVIZ_PORT", 8000)), host)
        self.app = create_app()
        config = uvicorn.Config(self.app, host=self.host, port=self.port,
                                log_level="warning", ws_max_size=256 * 1024 * 1024)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run,
                                        name="kayviz-server", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
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

