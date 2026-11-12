"""
CLI entry point for `python -m kayviz.evaluate`.

Flags:
    --suite speed,memory       Suites to run (default: speed,memory; browser on request)
    --scenes small|large|<id>  Scene group or comma-separated scene ids
    --out DIR                  Output directory for JSON and Markdown reports
    --compare FILE             Compare against baseline JSON; exit 1 on regression
    --quick                    1 repetition, small scenes (for CI and tests)
    --no-open                  browser suite: print the URL instead of opening it
    --frames N                 browser suite: frames per mode (default 60)
"""

from __future__ import annotations

import argparse
import sys

from . import compare as _compare
from . import memory as _memory
from . import report as _report
from . import scenes as _scenes
from . import speed as _speed

AVAILABLE_SUITES = ("speed", "memory", "browser")
DEFAULT_SUITES = ("speed", "memory")         # browser needs a tab: on request


def _resolve_suites(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_SUITES)
    out: list[str] = []
    for part in spec.split(","):
        s = part.strip()
        if not s:
            continue
        if s not in AVAILABLE_SUITES:
            raise ValueError(f"unknown suite {s!r} (available: {', '.join(AVAILABLE_SUITES)})")
        if s not in out:
            out.append(s)
    return out


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kayviz.evaluate",
        description="Run kayviz speed and memory evaluation suites.",
    )
    parser.add_argument(
        "--suite",
        default=None,
        help="comma-separated suites: speed, memory, browser (default: speed,memory)",
    )
    parser.add_argument(
        "--scenes",
        default=None,
        help="small (default), large, or comma-separated scene ids",
    )
    parser.add_argument(
        "--out",
        default=".",
        help="directory where evaluate-<date>-<host>.{json,md} are written (default: cwd)",
    )
    parser.add_argument(
        "--compare",
        default=None,
        metavar="FILE",
        help="compare results against baseline JSON and exit 1 on any regression",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="1 repetition, small scenes (for CI and tests)",
    )
    parser.add_argument("--no-open", action="store_true",
                        help="browser suite: print the viewer URL instead of opening it")
    parser.add_argument("--frames", type=int, default=60,
                        help="browser suite: frames timed per mode (default 60)")
    args = parser.parse_args(argv)

    try:
        suites = _resolve_suites(args.suite)
        scene_spec = args.scenes if args.scenes is not None else "small"
        scene_list = _scenes.resolve_scenes(scene_spec)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    reps = 1 if args.quick else 5
    results: list[dict] = []

    for suite in suites:
        if suite == "speed":
            results.extend(_speed.run_suite(scene_list, reps=reps))
        elif suite == "memory":
            results.extend(_memory.run_suite(scene_list))
        elif suite == "browser":
            from . import browser as _browser
            results.extend(_browser.run_suite(scene_list, frames=args.frames,
                                              open_browser=not args.no_open))

    rep = _report.build_report(results)
    json_path, md_path = _report.write_report(rep, out_dir=args.out)
    print(_report.format_markdown(rep))
    print(f"Wrote {json_path} and {md_path}", flush=True)

    if args.compare:
        cmp_res = _compare.compare_files(args.compare, rep)
        print("\n" + cmp_res["table"], flush=True)
        if not cmp_res["ok"]:
            return 1

    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
