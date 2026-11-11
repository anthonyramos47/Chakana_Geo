"""
BroadcastMixin — shared buffer + WebSocket broadcast logic.

Used by both ScriptApp and CallbackApp so geometry pushed by the user
(via kv.register_surface_mesh etc.) is buffered and replayed on reload.

Outbound messages: every tab has its own queue and one sender task, so
  - messages reach a tab in the order they were produced (pushes are published
    under one lock, the snapshot of a new tab included);
  - a slow or asleep tab never stalls the producer (kv.register_* returns once the
    message is queued); a tab that falls MAX_PENDING messages behind is dropped and
    gets a fresh snapshot when it reconnects;
  - one task writes to a socket (replies to a tab go through its queue as well).
The asyncio primitives belong to the loop that serves them: they are recreated when
the app is served by a new loop (a server restarted in the same process).
"""

from __future__ import annotations

import asyncio
import traceback
from fastapi import WebSocket

from .wire import encode_async, send, send_encoded   # send re-exported for the apps


class BroadcastMixin:
    """
    Adds a named-object buffer and WebSocket broadcast to a GUIApp subclass.

    The buffer stores the most recent serializer dict for each named object
    so that newly-connected browsers receive the full current scene.
    """

    # A tab that stops reading (backgrounded, asleep, half-closed socket) would block
    # its sender forever; drop it after this long.
    SEND_TIMEOUT = 10.0
    # Messages queued for one tab before it is dropped (it reloads the snapshot).
    MAX_PENDING = 16

    def _init_broadcast(self):
        self._buffer: dict[str, dict] = {}
        self._reset_clients()

    def _reset_clients(self) -> None:
        """Forget every tab (also called when the server stops)."""
        self._clients: set[WebSocket] = set()
        self._queues: dict[WebSocket, asyncio.Queue] = {}
        self._senders: dict[WebSocket, asyncio.Task] = {}
        self._seen_client = False     # has any browser connected yet?
        self._loop_prims = None       # (loop, order lock, idle event)

    # ── Per-loop primitives ───────────────────────────────────────────────────

    def _prims(self):
        loop = asyncio.get_running_loop()
        if self._loop_prims is None or self._loop_prims[0] is not loop:
            idle = asyncio.Event()
            if not self._clients:
                idle.set()
            self._loop_prims = (loop, asyncio.Lock(), idle)
        return self._loop_prims

    @property
    def _order_lock(self) -> asyncio.Lock:
        return self._prims()[1]

    @property
    def _idle(self) -> asyncio.Event:
        return self._prims()[2]

    # ── Buffer helpers ────────────────────────────────────────────────────────

    def _buffer_objects(self, objects: list[dict]) -> None:
        for obj in objects:
            # kv.clear() / kv.remove() inside a callback arrive as markers in the
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

    async def _connect_client(self, ws: WebSocket) -> None:
        """Register an accepted socket; the current scene is its first message.
        Under the order lock, so no push can slip in between snapshot and register."""
        async with self._order_lock:
            queue: asyncio.Queue = asyncio.Queue()
            if self._buffer:
                try:
                    queue.put_nowait(await encode_async(
                        {"action": "scene_update", "objects": self._buffer_snapshot()}))
                except Exception:
                    traceback.print_exc()     # the tab starts empty; say why
            self._queues[ws] = queue
            self._senders[ws] = asyncio.create_task(self._sender(ws, queue))
            self._add_client(ws)

    def _add_client(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        self._seen_client = True
        self._idle.clear()

    def _remove_client(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        self._queues.pop(ws, None)
        task = self._senders.pop(ws, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        if not self._clients:
            self._idle.set()

    async def _sender(self, ws: WebSocket, queue: asyncio.Queue) -> None:
        try:
            while True:
                data = await queue.get()
                await asyncio.wait_for(send_encoded(ws, data), timeout=self.SEND_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._drop_client(ws)

    async def _drop_client(self, ws: WebSocket) -> None:
        self._remove_client(ws)
        try:
            await asyncio.wait_for(ws.close(), timeout=1.0)
        except Exception:
            pass

    async def _reply(self, ws: WebSocket, msg: dict) -> None:
        """A message for one tab, behind what is already queued for it."""
        queue = self._queues.get(ws)
        if queue is None:
            await send(ws, msg)
            return
        self._queue_message(ws, queue, await encode_async(msg))

    def _queue_message(self, ws, queue: asyncio.Queue, data) -> None:
        if queue.qsize() >= self.MAX_PENDING:
            asyncio.ensure_future(self._drop_client(ws))   # it reloads the snapshot
        else:
            queue.put_nowait(data)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast(self, msg: dict) -> None:
        if self._clients:
            await self._broadcast_encoded(await encode_async(msg))   # once for all clients

    async def _broadcast_encoded(self, data) -> None:
        """Queue an encoded message for every tab (returns without waiting for them)."""
        for ws, queue in list(self._queues.items()):
            self._queue_message(ws, queue, data)

    async def _publish(self, objects: list[dict], data) -> None:
        """Buffer *objects* and queue their encoded message, in publication order."""
        async with self._order_lock:
            self._buffer_objects(objects)
            await self._broadcast_encoded(data)

    async def push(self, objects: list[dict]) -> None:
        """Merge objects into buffer and broadcast. Raises (and buffers nothing) when
        an object cannot be encoded: buffered, it would break every later snapshot."""
        async with self._order_lock:
            data = await encode_async({"action": "scene_update", "objects": objects})
            self._buffer_objects(objects)
            await self._broadcast_encoded(data)

    async def do_clear(self) -> None:
        async with self._order_lock:
            self._buffer.clear()
            await self._broadcast({"action": "clear"})

    async def do_remove(self, name: str) -> None:
        async with self._order_lock:
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
                await asyncio.wait_for(self._idle.wait(),
                                       timeout=max(0.0, deadline - loop.time()))
            except asyncio.TimeoutError:
                return False
            if grace:
                await asyncio.sleep(grace)
            if not self._clients:
                return True
        return False
