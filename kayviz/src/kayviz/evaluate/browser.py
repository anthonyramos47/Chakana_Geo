"""
Browser suite for kayviz.evaluate: what a real tab does with each scene.

Starts this process's own viewer (cross-origin isolated, so the tab can measure
its whole memory), opens it in the default browser or waits for you to open the
printed URL, then per scene:

- delivery_ms: from building the scene in Python until the tab has drawn it (the
  tab answers a push carrying `seq` after that frame, see static/ws.js)
- frame times, triangles, draw calls and memory estimates: kv.benchmark()
- toggle times: studio on/off, the largest mesh's edge overlay, flat shading
- tab_mb: the tab's whole memory (Chrome, isolated page only; else not reported)

Frame times are GPU times of *this* machine and browser: compare runs made on the
same machine. Keep the tab visible: hidden tabs draw nothing and time out.
"""

from __future__ import annotations

import os
import time
import webbrowser

import requests

from .scenes import SCENES, serialize_scene


def _row(scene: str, metric: str, value, unit: str, better: str = "lower",
         note: str | None = None) -> dict:
    return {"suite": "browser", "scene": scene, "metric": metric,
            "value": None if value is None else round(float(value), 3),
            "unit": unit, "better": better, "note": note}


def _start_viewer():
    # Must be set before the server is built (create_app reads it).
    os.environ.setdefault("KAYVIZ_ISOLATED", "1")
    import kayviz as kv
    from kayviz.runtime import script
    kv.init()
    if script._mode != "local":
        raise RuntimeError("the browser suite needs its own viewer; a shared kayviz "
                           "server is running (KAYVIZ_URL or `python -m kayviz`)")
    return kv, script


def _wait_for_tab(timeout: float) -> bool:
    from kayviz.runtime import registry
    app = registry.get_app("script")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app._queues:
            return True
        time.sleep(0.2)
    return False


def run_scene(kv, script, name: str, seq: int, frames: int) -> list[dict]:
    url = kv.url()
    kv.clear()
    time.sleep(0.3)
    calls = SCENES[name]()
    t0 = time.monotonic()
    objects = serialize_scene(calls)
    t_python = time.monotonic() - t0
    script._push_with_seq(objects, seq)
    r = requests.get(f"{url}/api/script/applied", params={"seq": seq, "timeout": 180},
                     timeout=190).json()
    if not r.get("ok"):
        return [_row(name, "delivery_ms", None, "ms", note=r.get("error"))]
    rows = [_row(name, "python_ms", t_python * 1000, "ms"),
            _row(name, "delivery_ms", (r["t"] - t0) * 1000, "ms")]

    b = kv.benchmark(frames=frames, timeout=240, show=False, toggles=True, tab_memory=True)
    p, s, m = b["modes"]["plain"], b["modes"]["studio"], b["memory_mb"]
    rows += [
        _row(name, "plain_median_ms", p["median_ms"], "ms"),
        _row(name, "plain_p95_ms", p["p95_ms"], "ms"),
        _row(name, "studio_median_ms", s["median_ms"], "ms"),
        _row(name, "triangles", p["triangles"], "count"),
        _row(name, "draw_calls", p["draw_calls"], "count"),
        _row(name, "gpu_est_mb", p["gpu_mb"], "MB"),
        _row(name, "studio_gpu_est_mb", s["gpu_mb"], "MB"),
        _row(name, "js_heap_mb", m.get("js_heap"), "MB"),
    ]
    if m.get("tab") is not None:
        rows.append(_row(name, "tab_mb", m["tab"], "MB"))
    for key, ms in (b.get("toggles") or {}).items():
        rows.append(_row(name, key, ms, "ms"))
    return rows


def run_suite(scenes: list[str], frames: int = 60, open_browser: bool = True,
              tab_timeout: float = 120.0) -> list[dict]:
    kv, script = _start_viewer()
    url = kv.url()
    print(f"[evaluate] browser suite: open {url} in Chrome and keep the tab visible",
          flush=True)
    if open_browser and os.environ.get("KAYVIZ_NO_BROWSER") != "1":
        webbrowser.open(url)
    if not _wait_for_tab(tab_timeout):
        raise RuntimeError(f"no tab opened {url} within {tab_timeout:.0f} s")
    time.sleep(1.0)                          # let the page finish loading
    results: list[dict] = []
    for seq, name in enumerate(scenes, start=1):
        print(f"[evaluate] browser: {name}", flush=True)
        results.extend(run_scene(kv, script, name, seq, frames))
    kv.clear()
    return results
