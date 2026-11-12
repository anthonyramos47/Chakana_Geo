"""
Python-side memory suite for kayviz.evaluate.

Runs each scene in a fresh subprocess (`sys.executable -m kayviz.evaluate._probe <scene>`)
so scenes do not pollute each other's memory measurements.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .scenes import SCENES, resolve_scenes

MB = 1024 * 1024


def _parse_size_mb(num_str: str, unit_str: str) -> float:
    val = float(num_str.replace(",", ""))
    u = unit_str.strip().upper()
    if u in ("B", "BYTES"):
        return val / MB
    if u in ("K", "KB", "KIB"):
        return (val * 1024.0) / MB
    if u in ("M", "MB", "MIB"):
        return val
    if u in ("G", "GB", "GIB"):
        return val * 1024.0
    return val


def parse_footprint_output(text: str) -> float | None:
    """Extract physical footprint in MB from macOS `footprint` or `vmmap --summary` output."""
    patterns = (
        r"(?:Physical\s+footprint|Footprint|phys_footprint)\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMG]?i?B|[KMG]|B)\b",
    )
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return _parse_size_mb(m.group(1), m.group(2))
    return None


def parse_proc_status_vmrss(text: str) -> float | None:
    """Extract VmRSS in MB from Linux `/proc/<pid>/status` content."""
    m = re.search(r"^VmRSS:\s*([0-9]+)\s*([a-zA-Z]+)", text, flags=re.MULTILINE)
    if not m:
        return None
    return _parse_size_mb(m.group(1), m.group(2))


def process_footprint_mb(pid: int | None = None) -> float | None:
    """Return the physical memory footprint of process *pid* in MB, or None."""
    target_pid = os.getpid() if pid is None else int(pid)

    if sys.platform.startswith("linux"):
        status_path = Path("/proc/self/status") if target_pid == os.getpid() else Path(f"/proc/{target_pid}/status")
        try:
            return parse_proc_status_vmrss(status_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None

    if sys.platform == "darwin":
        for cmd in (["footprint", str(target_pid)], ["vmmap", "--summary", str(target_pid)]):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                continue
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            val = parse_footprint_output(out)
            if val is not None:
                return val
        return None

    return None


def classify_filename(filename: str) -> tuple[str, str | None]:
    """Classify a tracemalloc frame filename into ('kayviz', 'kayviz/...'), ('numpy', None)
    or ('other', None)."""
    fn = filename.replace("\\", "/")
    if "/kayviz/" in fn or fn.startswith("kayviz/"):
        rel = "kayviz/" + fn.rsplit("/kayviz/", 1)[1] if "/kayviz/" in fn else fn
        if rel.startswith("kayviz/evaluate/"):
            return "other", None
        return "kayviz", rel
    if "/numpy/" in fn or fn.startswith("numpy/"):
        return "numpy", None
    return "other", None


def probe_scene(scene_name: str, timeout: float = 180.0) -> dict:
    """Run `sys.executable -m kayviz.evaluate._probe <scene>` in a fresh subprocess."""
    if scene_name not in SCENES:
        raise ValueError(f"unknown scene {scene_name!r}")

    env = dict(os.environ, KAYVIZ_NO_BROWSER="1")
    env.pop("KAYVIZ_URL", None)
    env.pop("WEBSCOPE_URL", None)

    proc = subprocess.run(
        [sys.executable, "-m", "kayviz.evaluate._probe", scene_name],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"memory probe for {scene_name!r} failed (exit {proc.returncode}):\n{proc.stderr}"
        )

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("PROBE_RESULT:"):
            return json.loads(line[len("PROBE_RESULT:"):])
    raise RuntimeError(f"memory probe for {scene_name!r} produced no result:\n{proc.stdout}")


def run_scene(scene_name: str, timeout: float = 180.0) -> list[dict]:
    """Run the memory probe on *scene_name* and return flat result rows."""
    data = probe_scene(scene_name, timeout=timeout)
    files_mb = data.get("kayviz_files_mb") or {}
    files_note = (
        ", ".join(f"{k}: {v:.2f} MB" for k, v in files_mb.items() if v >= 0.01)
        or None
    )

    return [
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "raw_geometry_mb",
            "value": data["raw_geometry_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "tracemalloc_current_mb",
            "value": data["tracemalloc_current_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "tracemalloc_peak_mb",
            "value": data["tracemalloc_peak_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "kayviz_mb",
            "value": data["kayviz_mb"],
            "unit": "MB",
            "better": "lower",
            "note": files_note,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "numpy_mb",
            "value": data["numpy_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "other_mb",
            "value": data["other_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "kayviz_ratio",
            "value": data["kayviz_ratio"],
            "unit": "x",
            "better": "lower",
            "note": "kayviz_mb / raw_geometry_mb",
        },
        {
            "suite": "memory",
            "scene": scene_name,
            "metric": "footprint_mb",
            "value": data["footprint_mb"],
            "unit": "MB",
            "better": "lower",
            "note": None,
        },
    ]


def run_suite(scenes: list[str] | None = None, timeout: float = 180.0) -> list[dict]:
    """Run the memory suite across *scenes*."""
    scene_list = scenes if scenes is not None else resolve_scenes("small")
    results: list[dict] = []
    for name in scene_list:
        results.extend(run_scene(name, timeout=timeout))
    return results
