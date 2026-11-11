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
import json
import traceback
from dataclasses import dataclass, make_dataclass
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

from .app import GUIApp
from .broadcast_mixin import BroadcastMixin
from .wire import send
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
            # Must not crash the server, but widgets after the error are missing.
            print(f"[kayviz] {self.name}: the GUI callback raised while its widgets "
                  "were being collected; widgets after the error will be missing:",
                  flush=True)
            traceback.print_exc()
        self._widget_schema = list(ctx.schema)
        self._buttons = {w["key"] for w in self._widget_schema if w["kind"] == "button"}

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
                await send(ws, {"action": "scene_update",
                                "objects": self._buffer_snapshot()})
            except Exception:
                pass

        # Widget events are queued per connection and run one after another by
        # _drain while this loop keeps reading, so a newer value of a slider
        # replaces its queued older one instead of piling up behind a slow callback.
        queue: list[dict] = []
        wake = asyncio.Event()
        worker = asyncio.create_task(self._drain(queue, wake, ws))
        try:
            while True:
                data = json.loads(await ws.receive_text())
                action = data.get("action", "")
                if action == "_set_state":
                    # AutoPanel sends this on every slider drag — ignore for
                    # CallbackApp (state lives in the user's dict, not self.state)
                    continue
                if action not in self._actions:
                    await send(ws, {"action": "error",
                                    "message": f"Unknown action: '{action}'"})
                    continue
                self._enqueue(queue, data)
                wake.set()
        except WebSocketDisconnect as exc:
            print(f"[ws:{self.name}] client disconnected (code={exc.code})")
        except Exception as exc:
            print(f"[ws:{self.name}] unhandled exception: {exc}")
            traceback.print_exc()
        finally:
            worker.cancel()
            self._remove_client(ws)

    def _enqueue(self, queue: list[dict], data: dict) -> None:
        """Queue a widget event; a slider/checkbox/dropdown event replaces a queued
        event of the same widget (its payload already holds the newest value).
        Button clicks are never merged."""
        trig = data.get("trigger", "")
        if data.get("action") == "_callback" and trig not in self._buttons:
            for i, q in enumerate(queue):
                if q.get("action") == "_callback" and q.get("trigger") == trig:
                    queue[i] = data
                    return
        queue.append(data)

    async def _drain(self, queue: list[dict], wake: asyncio.Event, ws: WebSocket):
        while True:
            await wake.wait()
            wake.clear()
            while queue:
                data = queue.pop(0)
                try:
                    if data.get("action") == "_callback":
                        await self._run_callback(data, ws)
                    else:
                        await self._run_sync(self._actions[data["action"]], data, ws)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    traceback.print_exc()     # keep serving the next events

    # ── _callback ─────────────────────────────────────────────────────────────

    async def _run_callback(self, data: dict, ws: WebSocket) -> None:
        """Run the user callback in a worker thread (one at a time per app: the
        user's state dict is shared), then buffer and broadcast what it pushed."""
        self._handler_lock = self._handler_lock or asyncio.Lock()
        async with self._handler_lock:
            pushed, error = await asyncio.to_thread(self._call_user, data)
        if error:
            try:
                await send(ws, {"action": "error", "message": error})
            except Exception:
                pass
            return
        if pushed:
            # Buffered on the loop (the snapshot for new tabs is read there too),
            # and sent to every tab of this app, not only the one that clicked.
            self._buffer_objects(pushed)
            await self._broadcast({"action": "scene_update", "objects": pushed})

    def _call_user(self, data: dict) -> tuple[list[dict], str | None]:
        """
        Re-run the user callback in live mode (in a worker thread).

        data expected:
            { "action": "_callback",
              "trigger": "<key or button label>",
              "state": { key: value, ... }   # current slider/dropdown values
            }
        """
        pushed: list[dict] = []
        with _CallbackPushCapture(self, pushed):
            _imgui._enter_live_mode(data.get("trigger", ""), data.get("state", {}))
            try:
                self._callback_fn()
            except Exception as exc:
                traceback.print_exc()
                return [], str(exc)
        return pushed, None

    def _handle_callback(self, state, data: dict):
        """Run the callback synchronously and return the scene_update (or None).
        Kept for direct callers; the WebSocket path uses _run_callback."""
        pushed, error = self._call_user(data)
        if error:
            return {"action": "error", "message": error}
        if pushed:
            self._buffer_objects(pushed)
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
        self._orig_push = _script._push_sink()
        _script._set_push_sink(self._sink.extend)
        return self

    def __exit__(self, *_):
        from kayviz.webscope import script as _script
        _script._set_push_sink(self._orig_push)
