"""
capture.py — Screenshots, the camera they report, the render benchmark, contact sheets.

Part of the scripting API (kayviz.runtime.script re-exports every name).
Shared state and helpers live in script.py and are reached as `_s.name`,
looked up at call time, so tests that monkeypatch script.X still apply.
"""

from __future__ import annotations

import os
import requests
from kayviz import serializers as ser

from . import script as _s


def get_camera():
    """Camera of the open viewer, as recorded by the most recent capture.

    Returns a dict with ``position``, ``target``, ``up``, ``fov`` and
    ``distance``, or None if no capture has run yet.  Take a screenshot first
    (even a tiny one) to populate it:

        kv.screenshot_views(width=16, height=16)
        print(ws.get_camera())

    Positions are in your coordinates (the scene origin added back).
    """
    o = ser.get_origin()
    if _s._last_camera is None or o is None:
        return _s._last_camera
    shift = lambda p: [float(a + b) for a, b in zip(p, o)]
    return {**_s._last_camera, "position": shift(_s._last_camera["position"]),
            "target": shift(_s._last_camera["target"])}


def _capture(views, width, height, hide_grid, timeout, background="white"):
    """Ask the browser to render `views` and return a list of PNG bytes."""
    import base64

    _s._ensure_init()
    norm = []
    for v in views:
        if v.get("live"):
            item = {"live": True, "zoom": float(v.get("zoom", 1.0))}
            if v.get("orbit"):
                item["orbit"] = float(v["orbit"])
        else:
            if "dir" not in v:
                raise ValueError(f"screenshot view needs 'dir' (or 'live': True), got {v}")
            item = {"dir":  list(v["dir"]), "zoom": float(v.get("zoom", 1.0))}
            if "up" in v:
                item["up"] = list(v["up"])
        norm.append(item)
    views = norm
    try:
        r = requests.post(f"{_s._url}/api/script/screenshot/request",
                          json={"views": views, "width": width,
                                "height": height, "hide_grid": hide_grid,
                                "background": background},
                          timeout=10)
        req = r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"screenshot request failed: {e}") from e

    if not req.get("ok"):
        raise RuntimeError(
            f"screenshot failed: {req.get('error', 'unknown')}. "
            f"Open {_s._url} in a browser (kayviz.show()) and keep the tab open; "
            "a tab left from an earlier kernel points at a different server."
        )

    try:
        r = requests.get(f"{_s._url}/api/script/screenshot/collect",
                         params={"id": req["id"], "timeout": timeout},
                         timeout=timeout + 10)
        res = r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"screenshot collect failed: {e}") from e

    if res.get("error"):
        raise RuntimeError(f"screenshot failed in browser: {res['error']}")

    out = []
    for url in res.get("images", []):
        out.append(base64.b64decode(url.split(",", 1)[1]))
    if not out:
        raise RuntimeError("screenshot returned no images")
    _s._last_camera = res.get("camera")
    return out


def screenshot(path, views=None, width: int = 900, height: int = 700,
               hide_grid: bool = True, timeout: float = 30.0,
               background: str = "white"):
    """
    Capture the current scene from two (or more) views.

    Args:
        path:      output path. With a single view this is the file written.
                   With several views a ``_v0``, ``_v1`` … suffix is inserted
                   before the extension, and the list of paths is returned.
        views:     iterable of ``{"dir": (x,y,z), "up": (x,y,z), "zoom": f}`` or
                   ``{"live": True}``; default: the current view of the open tab,
                   written to *path* (pass DEFAULT_VIEWS for the two-view pair).
        width:     pixel width of each view.
        height:    pixel height of each view.
        hide_grid: hide the reference grid during capture.
        timeout:   seconds to wait for the browser to respond.
        background: "white" (default), any CSS colour, "transparent" for an
                   empty (alpha) background, or "viewer" to keep the viewer's.

    Returns:
        str | list[str]: the path(s) written.

    Requires an open viewer tab — the pixels are produced by the browser.
    """
    views = list(views) if views is not None else [{"live": True}]
    blobs = _s._capture(views, width, height, hide_grid, timeout, background)

    path = str(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

    if len(blobs) == 1:
        with open(path, "wb") as fh:
            fh.write(blobs[0])
        return path

    stem, ext = os.path.splitext(path)
    ext = ext or ".png"
    paths = []
    for i, b in enumerate(blobs):
        q = f"{stem}_v{i}{ext}"
        with open(q, "wb") as fh:
            fh.write(b)
        paths.append(q)
    return paths


def screenshot_views(views=None, width: int = 900, height: int = 700,
                     hide_grid: bool = True, timeout: float = 30.0,
                     background: str = "white"):
    """Capture the scene and return the raw PNG bytes per view (no file written).

    Useful for assembling a contact sheet across several scenes — see
    ``save_grid``.  ``background`` is as in ``screenshot``.
    """
    views = list(views) if views is not None else list(_s.DEFAULT_VIEWS)
    return _s._capture(views, width, height, hide_grid, timeout, background)


def benchmark(frames: int = 60, timeout: float = 60.0, show: bool = True,
              toggles: bool = False, tab_memory: bool = False) -> dict:
    """Measure the open viewer tab drawing the current scene, in plain and in studio
    mode: frame times (each frame timed until the GPU finished it), triangles, draw
    calls, and memory (geometry exactly; screen, studio and shadow buffers estimated
    from their formats; the browser's JavaScript heap). Prints a table when *show*.

    toggles: also time studio on/off, the largest mesh's edge overlay and flat
    shading (key "toggles"). tab_memory: also the tab's whole memory
    (memory_mb["tab"]); only a cross-origin isolated page can measure it
    (KAYVIZ_ISOLATED=1 before the server starts), else None.

    Returns the measurements as a dict (keys "modes", "scene", "memory_mb")."""
    _s._ensure_init()
    try:
        r = requests.post(f"{_s._url}/api/script/benchmark/request",
                          json={"frames": frames, "toggles": toggles, "tab_memory": tab_memory},
                          timeout=10).json()
        if not r.get("ok"):
            raise RuntimeError(f"benchmark: {r.get('error')} — open {_s._url} in a browser")
        res = requests.get(f"{_s._url}/api/script/screenshot/collect",
                           params={"id": r["id"], "timeout": timeout}, timeout=timeout + 10).json()
    except requests.RequestException as e:
        raise RuntimeError(f"benchmark failed: {e}") from e
    if res.get("error") or not res.get("result"):
        raise RuntimeError(f"benchmark failed in browser: {res.get('error')}")
    result = res["result"]
    if show:
        print(_s.benchmark_table(result))
    return result


def benchmark_table(r: dict) -> str:
    """A kv.benchmark() result as a plain-text table."""
    p, s = r["modes"]["plain"], r["modes"]["studio"]
    m = r["memory_mb"]
    f = lambda x, d=1: "—" if x is None else f"{x:.{d}f}"
    rows = [
        ("frame, median (ms)", f(p["median_ms"]), f(s["median_ms"])),
        ("frame, 95% (ms)",    f(p["p95_ms"]),    f(s["p95_ms"])),
        ("frames / s",         f(p["fps"], 0),    f(s["fps"], 0)),
        ("triangles",          f"{p['triangles']:,}", f"{s['triangles']:,}"),
        ("draw calls",         str(p["draw_calls"]), str(s["draw_calls"])),
        ("GPU memory (MB)",    f(p["gpu_mb"]),    f(s["gpu_mb"])),
        ("  geometry",         f(m["geometry"]),  f(m["geometry"])),
        ("  screen buffers",   f(p["buffers_mb"]["screen"]), f(s["buffers_mb"]["screen"])),
        ("  studio buffers",   "—",               f(s["buffers_mb"]["studio"])),
        ("  shadow maps",      "—",               f(s["buffers_mb"]["shadow"])),
        ("JS heap (MB)",       f(m["js_heap"]),   ""),
    ]
    w = max(len(a) for a, _, _ in rows)
    lines = [f"{'':<{w}}  {'plain':>10}  {'studio':>10}"]
    lines += [f"{a:<{w}}  {b:>10}  {c:>10}" for a, b, c in rows]
    sc = r["scene"]
    lines.append(f"{sc['objects']} objects, {sc['vertices']:,} vertices, canvas {sc['canvas']} "
                 f"(pixel ratio {r['pixel_ratio']}), {r['frames']} frames per mode; buffer "
                 f"sizes estimated, geometry exact.")
    return "\n".join(lines)


def save_grid(path, rows, labels=None, pad: int = 8, bg=(255, 255, 255),
              label_height: int = 28):
    """
    Assemble captured views into one contact-sheet image.

    Args:
        path:   output image path (``.png`` or ``.jpg``).
        rows:   list of rows; each row is a list of PNG byte strings, as
                returned by ``screenshot_views``. One row per mesh.
        labels: optional per-row text drawn in the left margin.
        pad:    padding in pixels between tiles.
        bg:     background colour.
        label_height: height of the caption strip under each row (0 to disable).

    Returns:
        str: the path written.

    Requires Pillow.
    """
    from io import BytesIO

    try:
        from PIL import Image, ImageDraw
    except ImportError as e:  # pragma: no cover - depends on environment
        raise RuntimeError("save_grid needs Pillow (pip install pillow)") from e

    def _tile(b):
        # Composite over bg so transparent captures don't turn black.
        im = Image.open(BytesIO(b)).convert("RGBA")
        base = Image.new("RGBA", im.size, tuple(bg) + (255,))
        return Image.alpha_composite(base, im).convert("RGB")

    grid = [[_tile(b) for b in row] for row in rows]
    if not grid or not grid[0]:
        raise ValueError("save_grid: no images")

    ncol = max(len(r) for r in grid)
    tw   = max(im.width for r in grid for im in r)
    th   = max(im.height for r in grid for im in r)
    cell_h = th + (label_height if labels else 0)

    W = ncol * tw + (ncol + 1) * pad
    H = len(grid) * cell_h + (len(grid) + 1) * pad

    sheet = Image.new("RGB", (W, H), tuple(bg))
    draw  = ImageDraw.Draw(sheet)

    for r, row in enumerate(grid):
        y = pad + r * (cell_h + pad)
        for c, im in enumerate(row):
            x = pad + c * (tw + pad)
            sheet.paste(im, (x, y))
        if labels and r < len(labels) and labels[r]:
            draw.text((pad + 4, y + th + 6), str(labels[r]), fill=(20, 20, 20))

    d = os.path.dirname(str(path))
    if d:
        os.makedirs(d, exist_ok=True)
    sheet.save(str(path))
    return str(path)
