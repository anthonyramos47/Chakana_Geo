"""
kayviz.evaluate — speed, memory, browser and robustness evaluation suite.

Run from the command line:

    python -m kayviz.evaluate
    python -m kayviz.evaluate --quick
    python -m kayviz.evaluate --suite speed,memory --scenes small
    python -m kayviz.evaluate --compare baseline.json
"""

from .scenes import SCENES, SMALL_SCENES, LARGE_SCENES, resolve_scenes

__all__ = [
    "SCENES",
    "SMALL_SCENES",
    "LARGE_SCENES",
    "resolve_scenes",
]
