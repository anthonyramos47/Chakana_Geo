"""
App registry + router factory.

Usage:
    from kayviz.webscope import register_app, mount_all

    register_app(MyApp())
    mount_all(fastapi_app)

Each registered app gets these routes under /api/<name>:
    GET  /schema    → state widget schema + registered action names
    POST /load      → app.initial_scene() — initial HTTP scene load
    WS   /ws        → app.handle_websocket() — optimization/interaction loop
    GET  /panel.js  → the app's custom panel module (only if app.panel_js is set)

Apps may be registered after mount_all() — e.g. from a script that already
started its in-process server. They are mounted on every live FastAPI
instance immediately. Routes look the app up by name on each request, so
re-registering a name (re-running a notebook cell) swaps the implementation.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse

from .app import GUIApp

_apps: dict[str, GUIApp] = {}
_mounted: list[FastAPI] = []          # FastAPI instances that mount_all() ran on
_routed: dict[int, set[str]] = {}     # id(FastAPI) → app names already routed


def register_app(app: GUIApp) -> None:
    """Register a GUIApp instance (before or after mount_all())."""
    if not app.name:
        raise ValueError(f"{app.__class__.__name__}.name must be set")
    _apps[app.name] = app
    for fastapi_app in _mounted:
        _include(fastapi_app, app.name)


def get_app(name: str) -> GUIApp | None:
    return _apps.get(name)


def app_names() -> list[str]:
    return list(_apps.keys())


def mount_all(fastapi_app: FastAPI) -> None:
    """Route every registered app on *fastapi_app*, and any registered later."""
    if fastapi_app not in _mounted:
        _mounted.append(fastapi_app)
    for name in list(_apps):
        _include(fastapi_app, name)


def _include(fastapi_app: FastAPI, name: str) -> None:
    done = _routed.setdefault(id(fastapi_app), set())
    if name in done:
        return
    fastapi_app.include_router(_make_router(name))
    done.add(name)


# ── Router factory ────────────────────────────────────────────────────────────

def _lookup(name: str) -> GUIApp:
    app = _apps.get(name)
    if app is None:
        raise HTTPException(status_code=404, detail=f"app '{name}' is not registered")
    return app


def _make_router(name: str) -> APIRouter:
    router = APIRouter(prefix=f"/api/{name}")

    @router.get("/schema")
    def get_schema():
        app = _lookup(name)
        return {
            "app":     name,
            "state":   app.state_schema(),
            "actions": list(app._actions.keys()),
            "panel":   bool(app.panel_js),
        }

    @router.post("/load")
    def load(mesh_name: str = ""):
        app = _lookup(name)
        return app.initial_scene(mesh_name) if mesh_name else app.initial_scene()

    @router.get("/panel.js")
    def panel_js():
        app = _lookup(name)
        if not app.panel_js or not os.path.isfile(app.panel_js):
            raise HTTPException(status_code=404, detail="no custom panel")
        return FileResponse(app.panel_js, media_type="text/javascript",
                            headers={"Cache-Control": "no-store"})

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await _lookup(name).handle_websocket(ws)

    # Extra routes are bound to the instance registered first under this name.
    _apps[name].extra_routes(router)

    return router
