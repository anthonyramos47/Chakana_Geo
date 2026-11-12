"""Tests for kayviz.evaluate (P0-A)."""

from __future__ import annotations

from kayviz import serializers as ser
from kayviz.evaluate.scenes import (
    LARGE_SCENES,
    SCENES,
    SMALL_SCENES,
    raw_geometry_bytes,
    resolve_scenes,
    serialize_scene,
)


def test_scene_ids_and_groups():
    expected = (
        "empty",
        "objects-1k",
        "mesh-100k",
        "mesh-2M",
        "merged-12M",
        "ngon-200k",
        "points-1M",
        "curves-200k",
        "quantities",
    )
    assert tuple(SCENES) == expected
    assert resolve_scenes("small") == list(SMALL_SCENES)
    assert resolve_scenes("large") == list(LARGE_SCENES)
    assert "merged-12M" not in resolve_scenes("small")
    assert "merged-12M" in resolve_scenes("large")
    assert resolve_scenes("empty,mesh-100k") == ["empty", "mesh-100k"]


def test_small_scenes_serialize_cleanly():
    for name in SMALL_SCENES:
        calls = SCENES[name]()
        objs = [getattr(ser, kind)(**kw) for kind, kw in calls]
        assert len(objs) == len(calls)
        if name == "empty":
            assert objs == []
            assert raw_geometry_bytes(calls) == 0
        elif name == "objects-1k":
            assert len(objs) == 1000
            assert len(objs[0]["faces"]) == 1280 * 3
            assert raw_geometry_bytes(calls) > 0
        elif name == "mesh-100k":
            assert len(objs) == 1
            assert len(objs[0]["faces"]) == 100_000 * 3
        elif name == "ngon-200k":
            assert len(objs) == 1
            assert objs[0]["tris_per_face"] is not None
            assert len(objs[0]["faces"]) == 200_000 * 3
        elif name == "curves-200k":
            assert len(objs) == 1
            assert len(objs[0]["edges"]) == 200_000 * 2
        assert len(serialize_scene(calls)) == len(calls)
