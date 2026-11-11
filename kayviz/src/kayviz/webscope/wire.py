"""
wire — how messages travel to the browser.

Serializer dicts carry their geometry as numpy arrays (float32 / int32). A message
without arrays goes out as a JSON text frame. A message with arrays goes out as
one binary frame, so no array is ever written as text:

    uint32 (little endian)  header length H
    H bytes                 JSON header; every array replaced by
                            {"__b": offset, "t": "f32" | "i32" | "u32", "n": length}
    padding to 8 bytes
    the arrays' bytes       at base + offset, each padded to 8 bytes

`static/ws.js` decodes it back into Float32Array / Int32Array / Uint32Array.
For a typical scene this is ~4x smaller than JSON and needs no parsing.

HTTP routes and attach mode (requests.post(json=...)) use `jsonable`, which turns
arrays into lists.
"""

from __future__ import annotations

import asyncio
import json
import struct

import numpy as np

_TYPES = {np.dtype(np.float32): "f32", np.dtype(np.int32): "i32", np.dtype(np.uint32): "u32"}


def _wire_array(a: np.ndarray) -> np.ndarray:
    """Flat, contiguous, 4-byte dtype the browser understands."""
    a = np.asarray(a)
    if a.dtype not in _TYPES:
        if np.issubdtype(a.dtype, np.floating):
            a = a.astype(np.float32)
        elif np.issubdtype(a.dtype, np.unsignedinteger):
            a = a.astype(np.uint32)
        elif np.issubdtype(a.dtype, np.integer) or a.dtype == np.bool_:
            a = a.astype(np.int32)
        else:
            raise TypeError(f"kayviz cannot send arrays of dtype {a.dtype}")
    return np.ascontiguousarray(a.ravel())


def _pad8(n: int) -> int:
    return (n + 7) & ~7


def encode(msg) -> str | bytes:
    """Encode a message: JSON text, or a binary frame if it contains arrays."""
    chunks: list[bytes] = []
    offset = 0

    def walk(o):
        nonlocal offset
        if isinstance(o, np.ndarray):
            a = _wire_array(o)
            b = a.tobytes()
            ref = {"__b": offset, "t": _TYPES[a.dtype], "n": int(a.size)}
            chunks.append(b + b"\0" * (_pad8(len(b)) - len(b)))
            offset += _pad8(len(b))
            return ref
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            # lists of numbers (colours, or big lists in attach mode) stay as they are
            if o and not isinstance(o[0], (dict, list, tuple, np.ndarray)):
                return o
            return [walk(v) for v in o]
        if isinstance(o, np.generic):
            return o.item()
        return o

    header = json.dumps(walk(msg), separators=(",", ":"))
    if not chunks:
        return header
    hb = header.encode()
    head = struct.pack("<I", len(hb)) + hb
    head += b"\0" * (_pad8(len(head)) - len(head))
    return head + b"".join(chunks)


def jsonable(o):
    """Copy of *o* with numpy arrays and scalars turned into lists / numbers."""
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        if o and not isinstance(o[0], (dict, list, tuple, np.ndarray, np.generic)):
            return list(o)
        return [jsonable(v) for v in o]
    return o


async def encode_async(msg) -> str | bytes:
    """`encode` in a worker thread: a big scene would otherwise stall the event loop."""
    return await asyncio.to_thread(encode, msg)


async def send_encoded(ws, data: str | bytes) -> None:
    if isinstance(data, bytes):
        await ws.send_bytes(data)
    else:
        await ws.send_text(data)


async def send(ws, msg) -> None:
    """Send one message to one socket, encoded off the event loop."""
    await send_encoded(ws, await encode_async(msg))


class Socket:
    """The WebSocket handed to streaming action handlers. Their ``send_json``
    goes through `send`, so serializer dicts with numpy arrays work there too.
    Everything else is the underlying WebSocket."""

    def __init__(self, ws):
        self._ws = ws

    async def send_json(self, data, mode: str = "text") -> None:
        await send(self._ws, data)

    def __getattr__(self, name):
        return getattr(self._ws, name)


_DTYPES = {"f32": np.float32, "i32": np.int32, "u32": np.uint32}


def decode(data: str | bytes):
    """Inverse of `encode` (for Python clients and tests): arrays come back as numpy."""
    if isinstance(data, str):
        return json.loads(data)
    (n,) = struct.unpack_from("<I", data, 0)
    header = json.loads(data[4:4 + n].decode())
    base = _pad8(4 + n)

    def revive(o):
        if isinstance(o, dict):
            if "__b" in o:
                start = base + o["__b"]
                return np.frombuffer(data, _DTYPES[o["t"]], o["n"], start).copy()
            return {k: revive(v) for k, v in o.items()}
        if isinstance(o, list):
            return [revive(v) for v in o]
        return o

    return revive(header)
