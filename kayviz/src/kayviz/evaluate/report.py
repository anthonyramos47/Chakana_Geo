"""
JSON and Markdown report writer for kayviz.evaluate.

Writes `evaluate-<date>-<host>.json` and `evaluate-<date>-<host>.md` with one
table per suite.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import platform
import re

import numpy as np

import kayviz


def machine_info() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "kayviz": kayviz.__version__,
        "numpy": np.__version__,
    }


def _host_slug(host: str | None = None) -> str:
    raw = (host or platform.node() or "localhost").split(".")[0]
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    return slug or "localhost"


def build_report(results: list[dict], date: str | None = None) -> dict:
    """Wrap flat result rows into the version-1 evaluation report schema."""
    stamp = date or datetime.now().strftime("%Y-%m-%d")
    norm_rows: list[dict] = []
    for r in results:
        norm_rows.append({
            "suite": str(r["suite"]),
            "scene": r.get("scene"),
            "metric": str(r["metric"]),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "better": r.get("better", "lower"),
            "note": r.get("note"),
        })
    return {
        "version": 1,
        "date": stamp,
        "machine": machine_info(),
        "results": norm_rows,
    }


def _fmt_value(v, unit: str | None = None) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int) or (unit == "bytes" and isinstance(v, (int, float))):
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _suite_table(rows: list[dict]) -> str:
    has_scenes = any(r.get("scene") not in (None, "", "-") for r in rows)
    if not has_scenes:
        lines = [
            "| metric | value | unit | note |",
            "|---|---:|---|---|",
        ]
        for r in rows:
            val = _fmt_value(r.get("value"), r.get("unit"))
            unit = r.get("unit") or ""
            note = r.get("note") or ""
            lines.append(f"| {r['metric']} | {val} | {unit} | {note} |")
        return "\n".join(lines)

    scenes: list[str] = []
    metrics: list[tuple[str, str | None]] = []
    by_key: dict[tuple[str, str], dict] = {}
    notes: list[str] = []

    for r in rows:
        sc = str(r.get("scene") or "-")
        m = str(r["metric"])
        u = r.get("unit")
        if sc not in scenes:
            scenes.append(sc)
        if not any(k == m for k, _ in metrics):
            metrics.append((m, u))
        by_key[(sc, m)] = r
        if r.get("note") and m == "kayviz_mb":
            notes.append(f"- `{sc}` ({m}): {r['note']}")

    headers = ["scene"] + [f"{m} ({u})" if u else m for m, u in metrics]
    align = ["---"] + ["---:" for _ in metrics]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(align) + " |",
    ]
    for sc in scenes:
        cells = [sc]
        for m, u in metrics:
            cell_row = by_key.get((sc, m))
            cells.append(_fmt_value(cell_row.get("value") if cell_row else None, u))
        lines.append("| " + " | ".join(cells) + " |")

    if notes:
        lines.append("")
        lines.extend(notes)
    return "\n".join(lines)


def format_markdown(report: dict) -> str:
    """Format a report dictionary as Markdown with one table per suite."""
    mach = report.get("machine", {})
    lines = [
        f"# kayviz evaluation ({report.get('date', '')})",
        "",
        f"- **Platform**: `{mach.get('platform', '')}`",
        f"- **Python**: `{mach.get('python', '')}`",
        f"- **kayviz**: `{mach.get('kayviz', '')}`",
        f"- **numpy**: `{mach.get('numpy', '')}`",
        "",
    ]

    suites: list[str] = []
    for r in report.get("results", []):
        s = r.get("suite")
        if s and s not in suites:
            suites.append(s)

    for suite in suites:
        suite_rows = [r for r in report.get("results", []) if r.get("suite") == suite]
        lines.append(f"## {suite}")
        lines.append("")
        lines.append(_suite_table(suite_rows))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: dict,
    out_dir: str | Path = ".",
    host: str | None = None,
) -> tuple[Path, Path]:
    """Write `evaluate-<date>-<host>.json` and `evaluate-<date>-<host>.md` into *out_dir*."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_slug = str(report.get("date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    host_slug = _host_slug(host)
    stem = f"evaluate-{date_slug}-{host_slug}"

    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")
    return json_path, md_path
