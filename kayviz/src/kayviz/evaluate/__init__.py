"""
kayviz.evaluate — speed, memory, browser and robustness evaluation suite.

Run from the command line:

    python -m kayviz.evaluate
    python -m kayviz.evaluate --quick
    python -m kayviz.evaluate --suite speed,memory --scenes small
    python -m kayviz.evaluate --compare baseline.json
"""

from .compare import DEFAULT_TOLERANCES, compare_files, compare_reports
from .report import build_report, format_markdown, write_report
from .scenes import LARGE_SCENES, SCENES, SMALL_SCENES, resolve_scenes

__all__ = [
    "SCENES",
    "SMALL_SCENES",
    "LARGE_SCENES",
    "resolve_scenes",
    "build_report",
    "format_markdown",
    "write_report",
    "DEFAULT_TOLERANCES",
    "compare_reports",
    "compare_files",
]
