"""
CallbackApp — GUIApp that drives a user-supplied Python callback.

The user registers a callback with ws.set_user_callback(fn):

    def gui():
        with imgui.header("Controls"):
            imgui.slider_float("Radius", state, "radius", 0.1, 10)
        if imgui.button("Run"):
            push_result()

    ws.set_user_callback(gui)

CallbackApp:
  1. Runs fn once in schema mode to capture the widget layout.
  2. Sends the schema to the browser so AutoCallbackPanel can render it.
  3. On every "_callback" action from the browser, re-runs fn in live mode
     so the right widget returns True / (True, new_val) and the callback
     body executes its side effects (ws.register_surface_mesh etc.).

Geometry pushed inside the callback is routed through the broadcast buffer
(BroadcastMixin) so the scene survives browser reloads.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, make_dataclass
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

from .app import GUIApp
from .broadcast_mixin import BroadcastMixin
from .state_schema import gui_state
from kayviz.webscope import imgui as _imgui


def _make_empty_state_cls(name: str):
    """Dynamically create a minimal @gui_state dataclass (no widget fields)."""
    cls = make_dataclass(f"{name}State", [])
    cls.__gui_state__ = True
    return cls


class CallbackApp(BroadcastMixin, GUIApp):
    """
    Generic GUI app whose entire panel is described by a Python callback.

    Parameters
    ----------
    callback_fn:  the user-supplied gui() function
    app_name:     URL segment, e.g. "darboux"
    """

    out_dir = ""

    def __init__(self, callback_fn: Callable, app_name: str = "callback",
                 on_load: Callable | None = None):
        self.name      = app_name
        self.state_cls = _make_empty_state_cls(app_name)

        # Capture schema by running the callback in schema mode
        self._callback_fn = callback_fn
        self._on_load_fn  = on_load
        self._widget_schema: list[dict] = []
        self._capture_schema()

        super().__init__()          # GUIApp.__init__ → register_actions()
        self._init_broadcast()      # BroadcastMixin

        # If an on_load was provided, run it now to seed the buffer
        if self._on_load_fn is not None:
            pushed: list[dict] = []
            with _CallbackPushCapture(self, pushed):
                try:
                    self._on_load_fn()
                except Exception:
                    traceback.print_exc()
            if pushed:
                self._buffer_objects(pushed)

    # ── Schema capture ────────────────────────────────────────────────────────

    def _capture_schema(self) -> None:
        ctx = _imgui._enter_schema_mode()
        try:
            self._callback_fn()
        except Exception:
            pass  # schema capture must never crash the server
        self._widget_schema = list(ctx.schema)

    # ── GUIApp overrides ──────────────────────────────────────────────────────

    def register_actions(self):
        self.action("_callback", self._handle_callback)

    def state_schema(self) -> list[dict]:
        """
        Return the widget schema captured from the callback.
        The browser AutoCallbackPanel reads this to render the panel.
        """
        return self._widget_schema

    def initial_scene(self, mesh_name: str = "") -> dict:
        return {"objects": self._buffer_snapshot()}

    # ── WebSocket loop ────────────────────────────────────────────────────────

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
            import json
            from .state_schema import apply_client_state as _apply_cs

            while True:
                raw  = await ws.receive_text()
                data = json.loads(raw)
                action = data.get("action", "")

                if action == "_set_state":
                    # AutoPanel sends this on every slider drag — ignore for
                    # CallbackApp (state lives in the user's dict, not self.state)
                    continue

                fn = self._actions.get(action)
                if fn is None:
                    await ws.send_json({
                        "action":  "error",
                        "message": f"Unknown action: '{action}'",
                    })
                    continue

                try:
                    if asyncio.iscoroutinefunction(fn):
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
        finally:
            self._remove_client(ws)

    # ── _callback action handler ──────────────────────────────────────────────

    def _handle_callback(self, state, data: dict):
        """
        Re-run the user callback in live mode.

        data expected:
            { "action": "_callback",
              "trigger": "<key or button label>",
              "state": { key: value, ... }   # current slider/dropdown values
            }
        """
        trigger = data.get("trigger", "")
        payload = data.get("state", {})

        # Collect any objects the callback pushes synchronously
        pushed: list[dict] = []

        with _CallbackPushCapture(self, pushed):
            ctx = _imgui._enter_live_mode(trigger, payload)
            try:
                self._callback_fn()
            except Exception as exc:
                traceback.print_exc()
                return {"action": "error", "message": str(exc)}

        if pushed:
            # Buffer the objects so reloading clients get the scene back.
            self._buffer_objects(pushed)
            # Return a scene_update — GUIApp.handle_websocket sends it for us.
            return {"action": "scene_update", "objects": pushed}

        return None


# ── Push capture context manager ──────────────────────────────────────────────

class _CallbackPushCapture:
    """
    Temporarily redirects ws.register_surface_mesh / push_objects calls made
    inside the callback to a local list so CallbackApp can buffer + broadcast
    them rather than sending to the ScriptApp channel.
    """

    def __init__(self, app: CallbackApp, sink: list):
        self._app  = app
        self._sink = sink
        self._orig_push = None

    def __enter__(self):
        from kayviz.webscope import script as _script
        self._orig_push = _script._push_to_sink

        def capture(objects: list[dict]):
            self._sink.extend(objects)

        _script._push_to_sink = capture
        return self

    def __exit__(self, *_):
        from kayviz.webscope import script as _script
        _script._push_to_sink = self._orig_push
