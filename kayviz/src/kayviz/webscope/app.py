"""
GUIApp base class — replaces bespoke FastAPI WebSocket routers.

Subclass GUIApp, set `name` and `state_cls`, implement `register_actions`
and `initial_scene`, then register with the registry:

    from .registry import register_app
    register_app(MyApp())

The framework auto-creates /api/<name>/ws, /api/<name>/schema,
and /api/<name>/load routes.
"""

from __future__ import annotations
import asyncio
import json
import traceback
from typing import Callable
from fastapi import WebSocket, WebSocketDisconnect
from .state_schema import to_json, apply_client_state as _apply_cs
from .wire import send, Socket, track_scene


class GUIApp:
    """
    Base class for all GUI applications.

    Subclasses must define:
        name:       str         — URL segment, e.g. "lmesh"
        state_cls:  type        — @gui_state @dataclass class
        out_dir:    str         — root output directory, e.g. "out"

    Optional:
        panel_js:   str | None  — path to a custom panel ES module. The browser
                                  loads it from /api/<name>/panel.js; without
                                  it the panel is generated from the schema.
                                  Import kayviz base classes in it with
                                  `import { Panel } from 'kayviz/gui/panel.js'`.

    Subclasses should override:
        register_actions()      — calls self.action(...) for each WS action
        initial_scene()         — returns the initial HTTP load payload dict
    """

    name: str = ""
    state_cls: type = None
    out_dir: str = ""
    panel_js: str | None = None

    def __init__(self):
        if self.state_cls is None:
            raise TypeError(f"{self.__class__.__name__} must define state_cls")
        self.state = self.state_cls()
        self._actions: dict[str, Callable] = {}
        self._handler_lock = None    # (loop, asyncio.Lock), see _lock()
        self._streaming: set[str] = set()   # streaming actions running now
        self._open: set = set()             # open sockets (to reload them on replacement)
        self.register_actions()

    # ── Public API ────────────────────────────────────────────────────────────

    def action(self, name: str, fn: Callable):
        """
        Register an action handler.

        Sync handlers: fn(state, data) → dict | list | None
          - Return a scene snapshot dict to send to the client.
          - Return None to suppress any response.
          - Run in a worker thread, one at a time per app, so a slow handler
            does not freeze the server (other tabs, pings, screenshots).

        Async (streaming) handlers: async fn(state, data, ws) → None
          - Receive ws directly; send as many messages as needed.
          - Must send its own final message or nothing (no auto-send).
          - Run as a background task, so the connection keeps reading: a
            "stop" action sent during a "run" is handled while it runs. Heavy
            synchronous work inside should go through ``asyncio.to_thread``.
        """
        self._actions[name] = fn

    def register_actions(self):
        """Override to register action handlers via self.action(name, fn)."""

    def initial_scene(self) -> dict:
        """
        Return the initial scene payload for POST /api/<name>/load.

        The dict must contain at least {"objects": [...]}.
        Override in subclasses to load mesh and return base geometry.
        """
        return {"objects": []}

    def state_schema(self) -> list[dict]:
        """Return the JSON schema list for this app's state."""
        return to_json(self.state_cls)

    def extra_routes(self, router) -> None:
        """Override to register additional routes beyond /schema, /load, /ws."""

    # ── WebSocket dispatch loop ────────────────────────────────────────────────

    async def handle_websocket(self, ws: WebSocket):
        """Main WebSocket handler — called by the framework router."""
        await ws.accept()
        self._open.add(ws)
        tasks: set[asyncio.Task] = set()     # running streaming handlers
        try:
            while True:
                raw    = await ws.receive_text()
                data   = json.loads(raw)
                action = data.get("action", "")

                # Built-in: sync state from client (auto-panel debounced push).
                # Under the handler lock: another tab must not change the state while
                # a handler of this app is using it in its thread.
                if action == "_set_state":
                    async with self._lock():
                        _apply_cs(self.state, data.get("state", {}))
                    continue

                fn = self._actions.get(action)
                if fn is None:
                    await self._reply(ws, {"action": "error",
                                           "message": f"Unknown action: '{action}'"})
                    continue

                if asyncio.iscoroutinefunction(fn):
                    if action in self._streaming:
                        await self._reply(ws, {"action": "error", "message":
                                               f"'{action}' is already running"})
                        continue
                    self._streaming.add(action)        # now: the next message may be a 2nd run
                    task = asyncio.create_task(self._run_streaming(action, fn, data, ws))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                else:
                    await self._run_sync(fn, data, ws)

        except WebSocketDisconnect as exc:
            print(f"[ws:{self.name}] client disconnected (code={exc.code})")
        except Exception as exc:
            print(f"[ws:{self.name}] unhandled exception: {exc}")
            traceback.print_exc()
        finally:
            self._open.discard(ws)
            for t in tasks:
                t.cancel()

    def _lock(self) -> asyncio.Lock:
        """Handler lock of the loop serving this app (recreated for a new loop: an
        asyncio.Lock used on one loop fails on another, e.g. after a server restart)."""
        loop = asyncio.get_running_loop()
        if self._handler_lock is None or self._handler_lock[0] is not loop:
            self._handler_lock = (loop, asyncio.Lock())
        return self._handler_lock[1]

    async def _reply(self, ws: WebSocket, msg: dict) -> None:
        """Send a message to one tab (BroadcastMixin queues it behind earlier ones)."""
        await send(ws, msg)

    async def _run_sync(self, fn, data: dict, ws: WebSocket) -> None:
        """A sync handler in a worker thread (one at a time per app); reply to ws."""
        try:
            async with self._lock():
                result = await asyncio.to_thread(fn, self.state, data)
            if result is not None:
                track_scene(result)
                await self._reply(ws, result)
        except Exception as exc:
            traceback.print_exc()
            await self._send_error(ws, exc)

    async def _run_streaming(self, action: str, fn, data: dict, ws: WebSocket) -> None:
        """A streaming handler as a task: the connection keeps reading meanwhile (a
        "stop" action reaches it). One run per action at a time (handle_websocket
        marks the action running; this clears it)."""
        try:
            await fn(self.state, data, Socket(ws))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            traceback.print_exc()
            await self._send_error(ws, exc)
        finally:
            self._streaming.discard(action)

    async def _send_error(self, ws: WebSocket, exc: Exception) -> None:
        try:
            await self._reply(ws, {"action": "error", "message": str(exc)})
        except Exception:
            pass

    # ── Helpers for subclasses ────────────────────────────────────────────────

    def _apply_client_state(self, payload: dict):
        """Write client-supplied fields into self.state (type-coerced)."""
        _apply_cs(self.state, payload)

    def _make_scene_update(self, objects: list[dict], **extra) -> dict:
        """Wrap a list of serializer dicts as a scene_update message."""
        return {"action": "scene_update", "objects": objects, **extra}

    def _done(self, action_name: str, **extra) -> dict:
        """Return a lifecycle completion message."""
        return {"action": action_name, **extra}
