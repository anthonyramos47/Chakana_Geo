"""
BroadcastMixin — shared buffer + WebSocket broadcast logic.

Used by both ScriptApp and CallbackApp so geometry pushed by the user
(via ws.register_surface_mesh etc.) is buffered and replayed on reload.
"""

from __future__ import annotations

import asyncio
from fastapi import WebSocket

from .wire import encode_async, send, send_encoded   # send re-exported for the apps


class BroadcastMixin:
    """
    Adds a named-object buffer and WebSocket broadcast to a GUIApp subclass.

    The buffer stores the most recent serializer dict for each named object
    so that newly-connected browsers receive the full current scene.
    """

    def _init_broadcast(self):
        self._buffer: dict[str, dict] = {}
        self._clients: set[WebSocket] = set()
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._seen_client = False     # has any browser connected yet?

    # ── Buffer helpers ────────────────────────────────────────────────────────

    def _buffer_objects(self, objects: list[dict]) -> None:
        for obj in objects:
            # ws.clear() / ws.remove() inside a callback arrive as markers in the
            # object stream, so they stay ordered with the geometry around them.
            action = obj.get("action")
            if action == "clear":
                self._buffer.clear()
                continue
            if action == "remove":
                self._drop(obj.get("name"))
                continue
            name = obj.get("name")
            target = obj.get("target")
            if obj.get("type") == "edge_child" and target:
                self._buffer[f"{target}::edges"] = obj
                continue
            if target and name:
                # A quantity: keyed by its target, so the same field name on two
                # meshes does not collide. show=True also shows the target.
                if obj.get("show") is True and target in self._buffer:
                    self._buffer[target] = {**self._buffer[target], "show": True}
                self._buffer[f"{target}::{name}"] = obj
                continue
            if obj.get("type") == "set_enabled":
                # Keep the object and record its visibility on it; storing the
                # message under the name would replace the object itself.
                if name in self._buffer:
                    self._buffer[name] = {**self._buffer[name], "show": bool(obj["enabled"])}
                continue
            if name:
                # (Re-)registering a structure replaces it, quantities included (as the
                # viewer does, and Polyscope): drop name::*, and append it at the end
                # so its new quantities, pushed after it, also replay after it.
                self._drop(name)
                self._buffer[name] = obj

    def _drop(self, name) -> None:
        """Forget a structure and everything attached to it (name::*)."""
        if not name:
            return
        self._buffer.pop(name, None)
        prefix = f"{name}::"
        for key in [k for k in self._buffer if k.startswith(prefix)]:
            del self._buffer[key]

    def _buffer_snapshot(self) -> list[dict]:
        return list(self._buffer.values())

    # ── Client tracking ───────────────────────────────────────────────────────

    def _add_client(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        self._seen_client = True
        self._idle_event.clear()

    def _remove_client(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        if not self._clients:
            self._idle_event.set()

    # ── Broadcast ─────────────────────────────────────────────────────────────

    # A tab that stops reading (backgrounded, asleep, half-closed socket) makes
    # send_json block forever; drop it after this long instead of stalling pushes.
    SEND_TIMEOUT = 10.0

    async def _broadcast(self, msg: dict) -> None:
        if self._clients:
            await self._broadcast_encoded(await encode_async(msg))   # once for all clients

    async def _broadcast_encoded(self, data) -> None:
        clients = list(self._clients)
        if not clients:
            return

        async def send_one(ws):
            await asyncio.wait_for(send_encoded(ws, data), timeout=self.SEND_TIMEOUT)

        results = await asyncio.gather(*(send_one(ws) for ws in clients),
                                       return_exceptions=True)
        dead = {ws for ws, r in zip(clients, results) if isinstance(r, BaseException)}
        for ws in dead:
            try:
                await asyncio.wait_for(ws.close(), timeout=1.0)
            except Exception:
                pass
        self._clients -= dead
        if not self._clients:
            self._idle_event.set()

    async def push(self, objects: list[dict]) -> None:
        """Merge objects into buffer and broadcast. Raises (and buffers nothing) when
        an object cannot be encoded: buffered, it would break every later snapshot."""
        data = await encode_async({"action": "scene_update", "objects": objects})
        self._buffer_objects(objects)
        await self._broadcast_encoded(data)

    async def do_clear(self) -> None:
        self._buffer.clear()
        await self._broadcast({"action": "clear"})

    async def do_remove(self, name: str) -> None:
        self._drop(name)
        await self._broadcast({"action": "remove", "name": name})

    async def wait_until_idle(self, timeout: float = 300.0,
                              connect_timeout: float = 0.0,
                              grace: float = 0.0) -> bool:
        """
        Wait until no browser is connected.

        connect_timeout: first wait up to this long for a browser to connect,
                         so a tab that is still opening is not taken as closed.
        grace:           after the last client leaves, wait this long for a
                         reconnect (page reload) before reporting idle.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        if connect_timeout and not self._clients:
            end = min(deadline, loop.time() + connect_timeout)
            while not self._clients and loop.time() < end:
                await asyncio.sleep(0.2)
        while loop.time() < deadline:
            try:
                await asyncio.wait_for(self._idle_event.wait(),
                                       timeout=max(0.0, deadline - loop.time()))
            except asyncio.TimeoutError:
                return False
            if grace:
                await asyncio.sleep(grace)
            if not self._clients:
                return True
        return False
