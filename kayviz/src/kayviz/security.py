"""
Who may talk to a kayviz server.

A viewer listens on localhost, so only programs on this machine reach it. But the
browser on this machine also runs other people's pages, and without checks any
web page could open the viewer's WebSocket (read the scene, run callbacks), POST
/api/_shutdown, or reach every route through DNS rebinding. LocalOnlyMiddleware
refuses, for HTTP requests and WebSocket handshakes alike:

  1. a Host header that is not this machine (127.0.0.1, localhost, ::1, plus the
     names in KAYVIZ_ALLOWED_HOSTS): DNS rebinding;
  2. an Origin header that is not the viewer itself (http://<the Host>): another
     page opening the WebSocket or POSTing;
  3. Sec-Fetch-Site "cross-site" / "same-site" on anything but a top-level
     navigation: another page's no-cors requests (e.g. claiming screenshot jobs).

Python clients (kv.* in scripts and notebooks, requests, kill_servers) send no
Origin and no Sec-Fetch headers and keep working. A link to the viewer from
another page (Jupyter) is a navigation and opens it.

Served on the network (--host 0.0.0.0 with --allow-network) the Host check is off:
other machines use their own name for this one. Checks 2 and 3 stay.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def allowed_hosts() -> set[str]:
    extra = os.environ.get("KAYVIZ_ALLOWED_HOSTS", "")
    return LOCAL_HOSTS | {h.strip().lower() for h in extra.split(",") if h.strip()}


def _hostname(host: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1'; '[::1]:8000' -> '::1'."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class LocalOnlyMiddleware:
    """ASGI middleware (covers WebSocket handshakes, unlike BaseHTTPMiddleware)."""

    def __init__(self, app, network: bool = False):
        self.app = app
        self.network = network
        self.hosts = allowed_hosts()

    def reason(self, scope) -> str | None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if not self.network and _hostname(host) not in self.hosts:
            return (f"host {host!r} is not this machine (add it to KAYVIZ_ALLOWED_HOSTS "
                    f"if you reach the viewer through a proxy)")
        origin = headers.get("origin")
        if origin is not None:
            parts = urlsplit(origin)
            if origin == "null" or parts.netloc.lower() != host.lower():
                return f"requests from {origin} are not allowed"
        site = headers.get("sec-fetch-site")
        if site in ("cross-site", "same-site") and headers.get("sec-fetch-mode") != "navigate":
            return "cross-site requests are not allowed"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        why = self.reason(scope)
        if why is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()                                  # websocket.connect
            await send({"type": "websocket.close", "code": 1008, "reason": why[:120]})
            return
        body = f"kayviz: {why}\n".encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def is_loopback(host: str) -> bool:
    return _hostname(host) in LOCAL_HOSTS
