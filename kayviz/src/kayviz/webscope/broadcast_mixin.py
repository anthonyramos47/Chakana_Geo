"""
BroadcastMixin — shared buffer + WebSocket broadcast logic.

Used by both ScriptApp and CallbackApp so geometry pushed by the user
(via ws.register_surface_mesh etc.) is buffered and replayed on reload.
"""

from __future__ import annotations

import asyncio
from fastapi import WebSocket


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
            # ws.clear() inside a callback arrives as a marker rather than an
            # HTTP call; drop everything buffered so far so objects from a
            # previous mesh/run don't linger behind the new scene.
            if obj.get("action") == "clear":
                self._buffer.clear()
                continue
            name = obj.get("name")
            if name:
                self._buffer[name] = obj

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

    async def _broadcast(self, msg: dict) -> None:
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead
        if not self._clients:
            self._idle_event.set()

    async def push(self, objects: list[dict]) -> None:
        """Merge objects into buffer and broadcast."""
        self._buffer_objects(objects)
        await self._broadcast({"action": "scene_update", "objects": objects})

    async def do_clear(self) -> None:
        self._buffer.clear()
        await self._broadcast({"action": "clear"})

    async def do_remove(self, name: str) -> None:
        self._buffer.pop(name, None)
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
