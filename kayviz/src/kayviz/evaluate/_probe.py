"""
Subprocess memory probe for kayviz.evaluate.

Invoked as:
    python -m kayviz.evaluate._probe <scene>

Measures tracemalloc current/peak and per-module breakdown plus OS physical
footprint after registering <scene> into a local server.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import tracemalloc

from .memory import MB, classify_filename, process_footprint_mb
from .scenes import SCENES, raw_geometry_bytes, register_scene


def probe(scene_name: str) -> dict:
    if scene_name not in SCENES:
        raise ValueError(f"unknown scene {scene_name!r}")

    port_base = max(18700, int(os.environ.get("KAYVIZ_TEST_PORT_BASE", "18700")) + 100)
    os.environ["KAYVIZ_NO_BROWSER"] = "1"
    os.environ["KAYVIZ_PORT"] = str(port_base)
    os.environ.pop("KAYVIZ_URL", None)
    os.environ.pop("WEBSCOPE_URL", None)

    import kayviz as kv
    from kayviz.server import find_free_port

    # Build the raw input arrays before starting tracemalloc so the generator's
    # own buffers do not pollute kayviz's traced allocations.
    calls = SCENES[scene_name]()
    raw_bytes = raw_geometry_bytes(calls)

    kv.init(port=find_free_port(port_base))
    gc.collect()

    tracemalloc.start()
    register_scene(calls)
    del calls
    gc.collect()

    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    snap = tracemalloc.take_snapshot()
    tracemalloc.stop()

    kayviz_bytes = 0
    numpy_bytes = 0
    other_bytes = 0
    kayviz_files: dict[str, int] = {}

    for stat in snap.statistics("filename"):
        fn = stat.traceback[0].filename if stat.traceback else ""
        group, rel = classify_filename(fn)
        if group == "kayviz" and rel is not None:
            kayviz_bytes += stat.size
            kayviz_files[rel] = kayviz_files.get(rel, 0) + stat.size
        elif group == "numpy":
            numpy_bytes += stat.size
        else:
            other_bytes += stat.size

    footprint_mb = process_footprint_mb(os.getpid())

    if kv.script._server is not None:
        kv.script._server.stop()

    raw_mb = raw_bytes / MB
    kayviz_mb = kayviz_bytes / MB
    files_mb = {
        k: round(v / MB, 4)
        for k, v in sorted(kayviz_files.items(), key=lambda item: -item[1])
    }

    return {
        "scene": scene_name,
        "raw_geometry_mb": round(raw_mb, 4),
        "tracemalloc_current_mb": round(current_bytes / MB, 4),
        "tracemalloc_peak_mb": round(peak_bytes / MB, 4),
        "kayviz_mb": round(kayviz_mb, 4),
        "numpy_mb": round(numpy_bytes / MB, 4),
        "other_mb": round(other_bytes / MB, 4),
        "kayviz_ratio": round(kayviz_mb / raw_mb, 4) if raw_mb > 0 else None,
        "footprint_mb": round(footprint_mb, 3) if footprint_mb is not None else None,
        "kayviz_files_mb": files_mb,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m kayviz.evaluate._probe <scene>", file=sys.stderr)
        return 2
    res = probe(args[0])
    print("PROBE_RESULT:" + json.dumps(res), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
