"""
Python-side speed suite for kayviz.evaluate.

Measures per scene without a server:
- serializer execution time (median of N runs, ms)
- wire.encode execution time (median of N runs, ms)
- encoded wire size (bytes)
- combined serialization + encoding throughput (MB/s)
"""

from __future__ import annotations

import statistics
import time

from kayviz import serializers as ser
from kayviz.runtime import wire
from .scenes import SCENES, resolve_scenes

MB = 1024 * 1024


def run_scene(scene_name: str, reps: int = 5) -> list[dict]:
    """Run the Python-side speed benchmark on one scene."""
    if scene_name not in SCENES:
        raise ValueError(f"unknown scene {scene_name!r}")

    calls = SCENES[scene_name]()
    n_reps = max(1, int(reps))

    ser_times: list[float] = []
    objects: list[dict] = []
    for _ in range(n_reps):
        t0 = time.perf_counter()
        objects = [getattr(ser, kind)(**kw) for kind, kw in calls]
        ser_times.append(time.perf_counter() - t0)
    serialize_s = statistics.median(ser_times)
    serialize_ms = serialize_s * 1000.0

    msg = {"action": "scene_update", "objects": objects}
    enc_times: list[float] = []
    encoded: str | bytes = ""
    for _ in range(n_reps):
        t0 = time.perf_counter()
        encoded = wire.encode(msg)
        enc_times.append(time.perf_counter() - t0)
    encode_s = statistics.median(enc_times)
    encode_ms = encode_s * 1000.0

    encoded_bytes = len(encoded.encode("utf-8") if isinstance(encoded, str) else encoded)
    total_s = serialize_s + encode_s
    throughput_mb_s = (encoded_bytes / MB) / total_s if (calls and total_s > 0) else 0.0

    return [
        {
            "suite": "speed",
            "scene": scene_name,
            "metric": "serialize_ms",
            "value": round(serialize_ms, 4),
            "unit": "ms",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "speed",
            "scene": scene_name,
            "metric": "encode_ms",
            "value": round(encode_ms, 4),
            "unit": "ms",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "speed",
            "scene": scene_name,
            "metric": "encoded_bytes",
            "value": int(encoded_bytes),
            "unit": "bytes",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "speed",
            "scene": scene_name,
            "metric": "throughput_mb_s",
            "value": round(throughput_mb_s, 3),
            "unit": "MB/s",
            "better": "higher",
            "note": None,
        },
    ]


def run_suite(scenes: list[str] | None = None, reps: int = 5) -> list[dict]:
    """Run the Python-side speed suite across *scenes*."""
    scene_list = scenes if scenes is not None else resolve_scenes("small")
    results: list[dict] = []
    for name in scene_list:
        results.extend(run_scene(name, reps=reps))
    return results
