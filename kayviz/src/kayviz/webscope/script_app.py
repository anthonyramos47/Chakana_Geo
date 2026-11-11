"""
ScriptApp — server-side broadcast app for the scripting/notebook API.

Always registered alongside GUIApp subclasses. Scripts and notebooks push
geometry over HTTP (POST /api/script/push); connected browser clients receive
it immediately via WebSocket broadcast. Reloading the browser replays the
current buffer so the scene is never lost.

Extra HTTP routes (beyond the standard /schema, /load, /ws):
    GET  /api/script/ping           — liveness check for ws.init()
    POST /api/script/push           — push objects or clear
    GET  /api/script/wait?timeout=N — long-poll until all WS clients disconnect
    POST /api/script/remove         — remove one named object

Screenshot handshake (the pixels only exist in the browser, so Python asks the
browser to render and hand them back):
    POST /api/script/screenshot/request — Python queues a capture job
    GET  /api/script/screenshot/pending — browser claims the next job
    POST /api/script/screenshot/result  — browser returns the PNG data URLs
    GET  /api/script/screenshot/collect — Python long-polls for the result
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .app import GUIApp
from .state_schema import gui_state
from .broadcast_mixin import BroadcastMixin
from .wire import send


@gui_state
@dataclass
class ScriptState:
    pass  # no user-facing widgets — scripting API has no control panel state


SHOT_MAX_PIXELS = 12_000_000        # as the viewer's save-picture cap


class ScriptApp(BroadcastMixin, GUIApp):
    name      = "script"
    state_cls = ScriptState
    out_dir   = ""

    def __init__(self, shared: bool = False):
        # shared=True marks a standalone viewer (`python -m kayviz`) that other
        # processes may attach to; a project's in-process server is private.
        self.shared = shared
        super().__init__()
        self._init_broadcast()
        # Screenshot handshake state: jobs waiting to be claimed by a browser,
        # and finished results waiting to be collected by Python.
        self._shot_queue: list[dict] = []           # unused (old pages poll /pending)
        self._shot_pending: set[str] = set()        # sent to a tab, not collected yet
        self._shot_done: dict[str, dict] = {}

    # ── GUIApp overrides ──────────────────────────────────────────────────────

    def register_actions(self):
        pass  # no action-button panel; all interaction is via HTTP push

    def initial_scene(self, mesh_name: str = "") -> dict:
        return {"objects": self._buffer_snapshot()}

    # ── WebSocket — replay buffer then stream pushes ──────────────────────────

    async def handle_websocket(self, ws: WebSocket):
        await ws.accept()
        await self._connect_client(ws)        # the current scene is its first message

        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            self._remove_client(ws)

    # ── Extra routes registered via extra_routes() hook ──────────────────────

    def extra_routes(self, router: APIRouter) -> None:
        app = self

        @router.get("/ping")
        def ping():
            return {"ok": True, "kayviz": True, "shared": app.shared,
                    "objects": len(app._buffer)}

        @router.post("/push")
        async def push(payload: dict):
            if payload.get("action") == "clear":
                await app.do_clear()
                return {"ok": True, "action": "clear"}
            objects = payload.get("objects", [])
            await app.push(objects)
            return {"ok": True, "pushed": len(objects)}

        @router.post("/view")
        async def view(payload: dict):
            from . import script as _script
            if payload.get("up") in ("y", "z"):
                _script._up = payload["up"]
            await app._broadcast({"action": "view", **payload})
            return {"ok": True}

        @router.post("/remove")
        async def remove(payload: dict):
            name = payload.get("name", "")
            if not name:
                return {"ok": False, "error": "name required"}
            await app.do_remove(name)
            return {"ok": True, "removed": name}

        @router.get("/wait")
        async def wait(timeout: float = 300.0, connect_timeout: float = 0.0,
                       grace: float = 0.0):
            idle = await app.wait_until_idle(timeout=timeout,
                                             connect_timeout=connect_timeout,
                                             grace=grace)
            return {"idle": idle, "seen": app._seen_client}

        # ── Screenshot handshake ────────────────────────────────────────────

        @router.post("/screenshot/request")
        async def screenshot_request(payload: dict):
            if not app._clients:
                return {"ok": False, "error": "no browser connected"}
            w, h = int(payload.get("width", 900)), int(payload.get("height", 700))
            if w <= 0 or h <= 0 or w * h > SHOT_MAX_PIXELS:
                # the browser allocates this canvas (plus studio buffers) on the GPU
                return {"ok": False, "error": f"{w}x{h} exceeds the "
                        f"{SHOT_MAX_PIXELS / 1e6:.0f} Mpx screenshot limit"}
            job = {
                "id":        uuid.uuid4().hex,
                "views":     payload.get("views", []),
                "width":     w,
                "height":    h,
                "hide_grid": payload.get("hide_grid", True),
                "background": payload.get("background", "white"),
            }
            # One tab renders it: the most recently connected one (the tab the user
            # just opened or reloaded), through its own queue.
            tab = next(reversed(app._queues), None)
            if tab is None:
                return {"ok": False, "error": "no browser connected"}
            app._shot_pending.add(job["id"])
            await app._reply(tab, {"action": "screenshot", **job})
            return {"ok": True, "id": job["id"]}

        @router.get("/screenshot/pending")
        async def screenshot_pending():
            return {}           # jobs now travel over the WebSocket

        @router.post("/screenshot/result")
        async def screenshot_result(payload: dict):
            jid = payload.get("id", "")
            if jid in app._shot_pending:        # late results of a timed-out job: dropped
                app._shot_pending.discard(jid)
                app._shot_done[jid] = {
                    "images": payload.get("images", []),
                    "error":  payload.get("error"),
                    "camera": payload.get("camera"),
                }
            return {"ok": True}

        @router.get("/screenshot/collect")
        async def screenshot_collect(id: str, timeout: float = 30.0):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if id in app._shot_done:
                    return app._shot_done.pop(id)
                await asyncio.sleep(0.1)
            app._shot_pending.discard(id)       # a result arriving now is dropped
            return {"images": [], "error": "timeout waiting for browser"}
