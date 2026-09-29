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
        self.register_actions()

    # ── Public API ────────────────────────────────────────────────────────────

    def action(self, name: str, fn: Callable):
        """
        Register an action handler.

        Sync handlers: fn(state, data) → dict | list | None
          - Return a scene snapshot dict to send to the client.
          - Return None to suppress any response.

        Async (streaming) handlers: async fn(state, data, ws) → None
          - Receive ws directly; send as many messages as needed.
          - Must send its own final message or nothing (no auto-send).
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
        try:
            while True:
                raw    = await ws.receive_text()
                data   = json.loads(raw)
                action = data.get("action", "")

                # Built-in: sync state from client (auto-panel debounced push)
                if action == "_set_state":
                    _apply_cs(self.state, data.get("state", {}))
                    continue

                fn = self._actions.get(action)
                if fn is None:
                    await ws.send_json({
                        "action": "error",
                        "message": f"Unknown action: '{action}'"
                    })
                    continue

                try:
                    if asyncio.iscoroutinefunction(fn):
                        # Streaming handler — gets ws to send multiple messages
                        await fn(self.state, data, ws)
                    else:
                        result = fn(self.state, data)
                        if result is not None:
                            await ws.send_json(result)
                except Exception as exc:
                    traceback.print_exc()
                    try:
                        await ws.send_json({"action": "error", "message": str(exc)})
                    except Exception:
                        pass

        except WebSocketDisconnect as exc:
            print(f"[ws:{self.name}] client disconnected (code={exc.code})")
        except Exception as exc:
            print(f"[ws:{self.name}] unhandled exception: {exc}")
            traceback.print_exc()

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
