"""
Deprecated name of :mod:`kayviz.runtime` (renamed in kayviz 0.3).

``import kayviz.webscope`` and ``from kayviz.webscope.<module> import ...`` keep
working: every submodule is the same module object as in ``kayviz.runtime``.
"""

import importlib
import sys
import warnings

from kayviz.runtime import *          # noqa: F401,F403
from kayviz.runtime import __all__    # noqa: F401

warnings.warn("kayviz.webscope was renamed kayviz.runtime", DeprecationWarning, stacklevel=2)

for _name in ("app", "broadcast_mixin", "callback_app", "imgui", "registry", "scene",
              "script", "script_app", "state_schema", "wire"):
    _module = importlib.import_module(f"kayviz.runtime.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module
