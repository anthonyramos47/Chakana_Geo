"""
CallbackApp — GUIApp that drives a user-supplied Python callback.

The user registers a callback with kv.set_user_callback(fn):

    def gui():
        with imgui.header("Controls"):
            imgui.slider_float("Radius", state, "radius", 0.1, 10)
        if imgui.button("Run"):
            push_result()

    kv.set_user_callback(gui)

CallbackApp:
  1. Runs fn once in schema mode to capture the widget layout.
  2. Sends the schema to the browser so AutoCallbackPanel can render it.
  3. On every "_callback" action from the browser, re-runs fn in live mode
     so the right widget returns True / (True, new_val) and the callback
     body executes its side effects (kv.register_surface_mesh etc.).

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
from .wire import send, encode_async
from . import registry as _registry
from .state_schema import gui_state
from kayviz.runtime import imgui as _imgui


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
            # gui() runs once here only to list its widgets: anything it pushes on
            # the way (registrations outside a button branch) is dropped, not sent.
            with _CallbackPushCapture(self, []):
                self._callback_fn()
        except Exception:
            # Must not crash the server, but widgets after the error are missing.
            print(f"[kayviz] {self.name}: the GUI callback raised while its widgets "
                  "were being collected; widgets after the error will be missing:",
                  flush=True)
            traceback.print_exc()
        self._widget_schema = list(ctx.schema)
        self._buttons = {w["key"] for w in self._widget_schema if w["kind"] == "button"}
        keys = [w["key"] for w in self._widget_schema]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            print(f"[kayviz] {self.name}: several widgets share the key/label "
                  f"{', '.join(map(repr, dup))}; they will react to each other's events",
                  flush=True)

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
        self._open.add(ws)
        await self._connect_client(ws)        # the current scene is its first message

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
                    await self._reply(ws, {"action": "error",
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
            self._open.discard(ws)
            self._remove_client(ws)

    def _enqueue(self, queue: list[dict], data: dict) -> None:
        """Queue a widget event; a slider/checkbox/dropdown event replaces a queued
        event of the same widget (its payload already holds the newest value).
        Button clicks are never merged."""
        trig = data.get("trigger", "")
        if data.get("action") == "_callback" and trig not in self._buttons:
            for i, q in enumerate(queue):
                if q.get("action") == "_callback" and q.get("trigger") == trig:
                    # the newer payload holds every newest value; keep the keys the
                    # replaced event changed too, or that edit would be lost
                    if "changed" in data or "changed" in q:
                        data = {**data, "changed": sorted(
                            set(q.get("changed", [trig])) | set(data.get("changed", [trig])))}
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
        async with self._lock():
            # The thread cannot be cancelled: if this tab goes away meanwhile, keep
            # the lock until the callback returns (else the next event would run a
            # second callback on the same state) and still publish its result.
            run = asyncio.ensure_future(asyncio.to_thread(self._call_user, data))
            try:
                pushed, error, gui = await asyncio.shield(run)
            except asyncio.CancelledError:
                pushed, error, gui = await run
                if pushed and not error:
                    await self._publish_pushed(pushed)
                raise
        if gui is not None:
            # Widget values after the callback (Python may have changed them) and,
            # when widgets appeared or went, the new layout: to every tab of the app.
            await self._broadcast(gui)
        if error:
            await self._reply(ws, {"action": "error", "message": error})
            return
        if pushed:
            try:
                await self._publish_pushed(pushed)
            except Exception as exc:          # nothing buffered: it would break reloads
                traceback.print_exc()
                await self._reply(ws, {"action": "error",
                                       "message": f"could not send the scene: {exc}"})

    async def _publish_pushed(self, pushed: list[dict]) -> None:
        """Buffer what a callback pushed and send it to every tab of this app (not
        only the one that clicked). Encoded first: an object that cannot be encoded
        raises here and nothing is buffered."""
        data = await encode_async({"action": "scene_update", "objects": pushed})
        await self._publish(pushed, data)
        # clear/remove inside the callback also cleared objects pushed from the main
        # thread live (one viewer shows both); keep the script buffer in step so a
        # reload shows the same scene.
        markers = [o for o in pushed if o.get("action") in ("clear", "remove")]
        script = _registry.get_app("script")
        if markers and script is not None and script is not self:
            script._buffer_objects(markers)

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
        trigger = data.get("trigger", "")
        # older pages send no "button" flag: a trigger naming a button is a click
        button = data.get("button", trigger in self._buttons)
        with _CallbackPushCapture(self, pushed):
            ctx = _imgui._enter_live_mode(trigger, data.get("state", {}),
                                          changed=data.get("changed"), button=button)
            try:
                self._callback_fn()
                return pushed, None, self._gui_state(ctx)
            except Exception as exc:
                traceback.print_exc()
                return [], str(exc), None
            finally:
                _imgui._enter_schema_mode()   # this pool thread may run other code next

    def _gui_state(self, ctx) -> dict:
        """Current widget values, and the widget list if it changed (a widget shown
        only under some condition): sent to the panel after each callback."""
        values = {k: s[key] for k, (s, key) in ctx.bindings.items() if key in s}
        msg = {"action": "gui_state", "values": values}
        layout = lambda schema: [{k: v for k, v in w.items() if k != "default"} for w in schema]
        if layout(ctx.schema) != layout(self._widget_schema):
            self._widget_schema = list(ctx.schema)        # new tabs get the new layout
            self._buttons = {w["key"] for w in ctx.schema if w["kind"] == "button"}
            msg["schema"] = self._widget_schema
        return msg

    def _handle_callback(self, state, data: dict):
        """Run the callback synchronously and return the scene_update (or None).
        Kept for direct callers; the WebSocket path uses _run_callback."""
        pushed, error, _ = self._call_user(data)
        if error:
            return {"action": "error", "message": error}
        if pushed:
            self._buffer_objects(pushed)
            return {"action": "scene_update", "objects": pushed}
        return None


# ── Push capture context manager ──────────────────────────────────────────────

class _CallbackPushCapture:
    """
    Temporarily redirects kv.register_surface_mesh / push_objects calls made
    inside the callback to a local list so CallbackApp can buffer + broadcast
    them rather than sending to the ScriptApp channel.
    """

    def __init__(self, app: CallbackApp, sink: list):
        self._app  = app
        self._sink = sink
        self._orig_push = None

    def __enter__(self):
        from kayviz.runtime import script as _script
        self._orig_push = _script._push_sink()
        _script._set_push_sink(self._sink.extend)
        return self

    def __exit__(self, *_):
        from kayviz.runtime import script as _script
        _script._set_push_sink(self._orig_push)
