"""
view.py — The camera and the up axis of the open tabs.

Part of the scripting API (kayviz.runtime.script re-exports every name).
Shared state and helpers live in script.py and are reached as `_s.name`,
looked up at call time, so tests that monkeypatch script.X still apply.
"""

from __future__ import annotations

import sys
import requests
from kayviz import serializers as ser
from . import registry as _registry

from . import script as _s


def set_up_dir(axis: str) -> None:
    """Up axis of the viewer: "z" (default) or "y". Open tabs reload to apply it."""
    if axis not in ("y", "z"):
        raise ValueError(f"set_up_dir: axis must be 'y' or 'z', got {axis!r}")
    _s._up = axis
    _s._view({"up": axis})


def look_at(position, target=(0.0, 0.0, 0.0)) -> None:
    """Place the camera of the open viewer tabs at *position*, looking at *target*."""
    pos = [float(x) for x in position]
    tgt = [float(x) for x in target]
    if len(pos) != 3 or len(tgt) != 3:
        raise ValueError("look_at: position and target are 3D points")
    o = ser.get_origin()                  # the viewer works relative to it
    if o is not None:
        pos = [p - c for p, c in zip(pos, o)]
        tgt = [t - c for t, c in zip(tgt, o)]
    _s._view({"camera": {"position": pos, "target": tgt}})


def reset_camera() -> None:
    """Frame the whole scene in the open viewer tabs (as the R key does)."""
    _s._view({"fit": True})


def _view(msg: dict) -> None:
    """View settings go to every tab (all apps subscribe to the script channel)."""
    _s._ensure_init()
    if _s._mode in ("local", "hosted"):
        script = _registry.get_app("script")
        _s._run_on_loop(script._broadcast({"action": "view", **msg}))
        return
    try:
        requests.post(f"{_s._url}/api/script/view", json=msg, timeout=10)
    except requests.RequestException as e:
        print(f"[kayviz] view failed: {e}", file=sys.stderr)
