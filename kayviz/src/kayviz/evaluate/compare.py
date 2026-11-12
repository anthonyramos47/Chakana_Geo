"""
Baseline comparison for kayviz.evaluate (`--compare baseline.json`).

Computes per-metric relative change and flags regressions when a metric gets
worse by more than its tolerance (defaults: time +25 %, memory +15 %, bytes +5 %).
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_TOLERANCES: dict[str, float] = {
    "time": 0.25,
    "memory": 0.15,
    "bytes": 0.05,
}


def metric_tolerance(row: dict, tolerances: dict[str, float] | None = None) -> float:
    """Return the relative tolerance (e.g. 0.25 for +25 %) for *row*."""
    tols = {**DEFAULT_TOLERANCES, **(tolerances or {})}
    metric = str(row.get("metric") or "")
    if metric in tols:
        return float(tols[metric])

    unit = str(row.get("unit") or "").lower()
    suite = str(row.get("suite") or "").lower()

    if unit in ("bytes", "b") or "bytes" in metric:
        return float(tols["bytes"])
    if unit == "mb" or suite == "memory":
        return float(tols["memory"])
    if unit in ("ms", "s", "mb/s") or suite in ("speed", "browser"):
        return float(tols["time"])
    if suite == "robustness":
        return 0.0
    return float(tols["time"])


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("suite") or ""),
        str(row.get("scene") or ""),
        str(row.get("metric") or ""),
    )


def compare_reports(
    baseline: dict,
    current: dict,
    tolerances: dict[str, float] | None = None,
) -> dict:
    """Compare *current* report against *baseline* report."""
    base_map = {_row_key(r): r for r in baseline.get("results", [])}
    rows: list[dict] = []
    regressions: list[dict] = []

    for cur in current.get("results", []):
        key = _row_key(cur)
        base = base_map.get(key)
        if base is None:
            continue

        b_val = base.get("value")
        c_val = cur.get("value")
        better = cur.get("better") or base.get("better") or "lower"
        tol = metric_tolerance(cur, tolerances)

        rel_change: float | None
        regressed = False

        if b_val is None or c_val is None:
            rel_change = None
        elif float(b_val) == 0.0:
            if float(c_val) == 0.0:
                rel_change = 0.0
            else:
                rel_change = None
                regressed = (float(c_val) > 0.0) if better == "lower" else (float(c_val) < 0.0)
        else:
            rel_change = (float(c_val) - float(b_val)) / abs(float(b_val))
            if better == "lower":
                regressed = rel_change > tol
            else:
                regressed = (-rel_change) > tol

        entry = {
            "suite": cur.get("suite"),
            "scene": cur.get("scene"),
            "metric": cur.get("metric"),
            "unit": cur.get("unit"),
            "better": better,
            "baseline": b_val,
            "current": c_val,
            "rel_change": rel_change,
            "tolerance": tol,
            "regressed": regressed,
        }
        rows.append(entry)
        if regressed:
            regressions.append(entry)

    table = format_comparison_table(rows)
    return {
        "ok": len(regressions) == 0,
        "regressions": regressions,
        "rows": rows,
        "table": table,
    }


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def format_comparison_table(rows: list[dict]) -> str:
    headers = ("suite", "scene", "metric", "baseline", "current", "change", "tol", "status")
    body: list[tuple[str, ...]] = []
    for r in rows:
        rc = r.get("rel_change")
        chg = "—" if rc is None else f"{rc * 100.0:+.1f}%"
        tol = f"{r['tolerance'] * 100.0:.0f}%"
        status = "REGRESSION" if r["regressed"] else "OK"
        body.append((
            str(r.get("suite") or ""),
            str(r.get("scene") or "-"),
            str(r.get("metric") or ""),
            _fmt_num(r.get("baseline")),
            _fmt_num(r.get("current")),
            chg,
            tol,
            status,
        ))

    widths = [
        max([len(headers[i])] + [len(row[i]) for row in body])
        for i in range(len(headers))
    ]
    fmt = lambda row: "  ".join(
        row[i].ljust(widths[i]) if i < 3 or i == 7 else row[i].rjust(widths[i])
        for i in range(len(headers))
    )
    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in body)
    return "\n".join(lines)


def _load_report(src: dict | str | Path) -> dict:
    if isinstance(src, dict):
        return src
    return json.loads(Path(src).read_text(encoding="utf-8"))


def compare_files(
    baseline: dict | str | Path,
    current: dict | str | Path,
    tolerances: dict[str, float] | None = None,
) -> dict:
    """Load baseline and current reports (paths or dicts) and compare them."""
    return compare_reports(_load_report(baseline), _load_report(current), tolerances=tolerances)
