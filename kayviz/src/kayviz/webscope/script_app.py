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


@gui_state
@dataclass
class ScriptState:
    pass  # no user-facing widgets — scripting API has no control panel state


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
        self._shot_queue: list[dict] = []
        self._shot_done: dict[str, dict] = {}

    # ── GUIApp overrides ──────────────────────────────────────────────────────

    def register_actions(self):
        pass  # no action-button panel; all interaction is via HTTP push

    def initial_scene(self, mesh_name: str = "") -> dict:
        return {"objects": self._buffer_snapshot()}

    # ── WebSocket — replay buffer then stream pushes ──────────────────────────

    async def handle_websocket(self, ws: WebSocket):
        await ws.accept()
        self._add_client(ws)

        if self._buffer:
            try:
                await ws.send_json({
                    "action":  "scene_update",
                    "objects": self._buffer_snapshot(),
                })
            except Exception:
                pass

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
            job = {
                "id":        uuid.uuid4().hex,
                "views":     payload.get("views", []),
                "width":     payload.get("width", 900),
                "height":    payload.get("height", 700),
                "hide_grid": payload.get("hide_grid", True),
            }
            app._shot_queue.append(job)
            return {"ok": True, "id": job["id"]}

        @router.get("/screenshot/pending")
        async def screenshot_pending():
            if app._shot_queue:
                return app._shot_queue.pop(0)
            return {}

        @router.post("/screenshot/result")
        async def screenshot_result(payload: dict):
            jid = payload.get("id", "")
            if jid:
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
            return {"images": [], "error": "timeout waiting for browser"}
