"""Tests for kayviz.evaluate (P0-A)."""

from __future__ import annotations

import copy
import json

from kayviz import serializers as ser
from kayviz.evaluate.__main__ import run as run_cli
from kayviz.evaluate.compare import compare_files, compare_reports
from kayviz.evaluate.memory import (
    classify_filename,
    parse_footprint_output,
    parse_proc_status_vmrss,
    run_scene as run_memory_scene,
)
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


def test_quick_speed_writes_valid_schema(tmp_path):
    rc = run_cli(["--quick", "--suite", "speed", "--out", str(tmp_path)])
    assert rc == 0

    json_files = list(tmp_path.glob("evaluate-*.json"))
    md_files = list(tmp_path.glob("evaluate-*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1

    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert isinstance(data["date"], str) and len(data["date"]) >= 10
    mach = data["machine"]
    assert {"platform", "python", "kayviz", "numpy"} <= set(mach.keys())

    results = data["results"]
    assert isinstance(results, list) and len(results) == len(SMALL_SCENES) * 4
    required_keys = {"suite", "scene", "metric", "value", "unit", "better", "note"}
    for row in results:
        assert set(row.keys()) == required_keys
        assert row["suite"] == "speed"
        assert row["scene"] in SMALL_SCENES
        assert row["better"] in ("lower", "higher")

    md_text = md_files[0].read_text(encoding="utf-8")
    assert "## speed" in md_text
    assert "mesh-100k" in md_text


def test_compare_passes_identical_and_flags_regression(tmp_path):
    rc = run_cli(["--quick", "--suite", "speed", "--scenes", "mesh-100k", "--out", str(tmp_path)])
    assert rc == 0
    base_file = next(tmp_path.glob("evaluate-*.json"))
    baseline = json.loads(base_file.read_text(encoding="utf-8"))

    # Identical report passes.
    same = compare_files(base_file, base_file)
    assert same["ok"] is True
    assert same["regressions"] == []

    # Synthetic time regression (+40% > +25% tolerance).
    reg_time = copy.deepcopy(baseline)
    for row in reg_time["results"]:
        if row["metric"] == "encode_ms":
            row["value"] = round(float(row["value"]) * 1.4 + 1.0, 4)
    res_time = compare_reports(baseline, reg_time)
    assert res_time["ok"] is False
    assert any(r["metric"] == "encode_ms" for r in res_time["regressions"])

    # Synthetic bytes regression (+10% > +5% tolerance).
    reg_bytes = copy.deepcopy(baseline)
    for row in reg_bytes["results"]:
        if row["metric"] == "encoded_bytes":
            row["value"] = int(row["value"] * 1.10)
    res_bytes = compare_reports(baseline, reg_bytes)
    assert res_bytes["ok"] is False
    assert any(r["metric"] == "encoded_bytes" for r in res_bytes["regressions"])

    # CLI --compare exits with 1 when baseline has much smaller encode_ms.
    strict_base = copy.deepcopy(baseline)
    for row in strict_base["results"]:
        if row["metric"] == "encoded_bytes":
            row["value"] = max(1, int(row["value"] * 0.5))
    strict_path = tmp_path / "baseline_strict.json"
    strict_path.write_text(json.dumps(strict_base), encoding="utf-8")
    out2 = tmp_path / "run2"
    rc_fail = run_cli([
        "--quick", "--suite", "speed", "--scenes", "mesh-100k",
        "--out", str(out2), "--compare", str(strict_path),
    ])
    assert rc_fail == 1


def test_memory_probe_and_parsers():
    assert abs(parse_footprint_output("Footprint: 128.5 MB") - 128.5) < 1e-6
    assert abs(parse_footprint_output("Physical footprint:         64.0M") - 64.0) < 1e-6
    assert abs(parse_proc_status_vmrss("Name:\tpython\nVmRSS:\t  204800 kB\n") - 200.0) < 1e-6

    assert classify_filename("/path/to/kayviz/src/kayviz/serializers.py") == (
        "kayviz", "kayviz/serializers.py",
    )
    assert classify_filename("/path/to/kayviz/src/kayviz/evaluate/scenes.py") == (
        "other", None,
    )
    assert classify_filename("/env/lib/python3.11/site-packages/numpy/_core/fromnumeric.py") == (
        "numpy", None,
    )

    rows = run_memory_scene("mesh-100k")
    by_metric = {r["metric"]: r for r in rows}
    assert by_metric["raw_geometry_mb"]["value"] > 1.5
    assert by_metric["tracemalloc_current_mb"]["value"] >= by_metric["kayviz_mb"]["value"]
    assert by_metric["tracemalloc_peak_mb"]["value"] >= by_metric["tracemalloc_current_mb"]["value"]
    assert by_metric["kayviz_mb"]["value"] > 0.0
    assert by_metric["kayviz_ratio"]["value"] > 0.5
