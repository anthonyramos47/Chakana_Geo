"""
kayviz.runtime.imgui — Polyscope-style widget helpers for set_user_callback.

Two execution modes, driven by a thread-local context:

  schema mode (default):
    Each widget call records its descriptor into _ctx.schema and returns
    a neutral value so the callback body does not execute side effects.
      slider_float/int  → (False, current_value)
      checkbox/dropdown → (False, current_value)
      button            → False

  live mode (triggered by a browser event):
    _ctx.trigger  — the widget key or button label that fired
    _ctx.payload  — the full state dict sent by the browser
    Each widget compares its key/label against the trigger and returns
    the real changed flag + new value.

Usage inside a user callback:

    from kayviz.runtime import imgui

    def my_gui():
        changed, val = imgui.slider_float("Alpha", state, "alpha", 0.0, 1.0)
        if imgui.button("Run"):
            do_work()

Called by CallbackApp._run_callback() which sets the thread-local before
invoking the user function.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any

# ── Thread-local context ──────────────────────────────────────────────────────

_local = threading.local()


class _Context:
    """Mutable per-call context stored in thread-local storage."""

    def __init__(self):
        self.mode: str = "schema"          # "schema" | "live"
        self.schema: list[dict] = []       # widget descriptors (both modes)
        self.trigger: str = ""             # widget key / button label (live mode)
        self.button: bool = False          # the event is a button click
        self.payload: dict = {}            # full state dict from browser (live mode)
        self.changed: set = set()          # keys the user edited since the last event
        self.bindings: dict = {}           # key -> (state dict, key): values sent back
        self._section_stack: list[str] = []  # active header labels


def _ctx() -> _Context:
    if not hasattr(_local, "ctx"):
        _local.ctx = _Context()
    return _local.ctx


def _enter_schema_mode() -> _Context:
    """Reset context to schema-collection mode. Returns the context."""
    ctx = _ctx()
    ctx.mode = "schema"
    ctx.schema = []
    ctx.trigger = ""
    ctx.button = False
    ctx.payload = {}
    ctx.changed = set()
    ctx.bindings = {}
    ctx._section_stack = []
    return ctx


def _enter_live_mode(trigger: str, payload: dict, changed=None, button: bool = False) -> _Context:
    """Switch context to live mode for one browser event. *changed* lists the keys
    the user edited since the previous event (all of them are applied, so a quick
    edit of a second widget does not lose the first); without it, the trigger."""
    ctx = _ctx()
    ctx.mode = "live"
    ctx.schema = []
    ctx.trigger = trigger
    ctx.button = button
    ctx.payload = payload
    ctx.changed = set(changed) if changed is not None else {trigger}
    ctx.bindings = {}
    ctx._section_stack = []
    return ctx


def _current_section() -> str | None:
    ctx = _ctx()
    return ctx._section_stack[-1] if ctx._section_stack else None


def _widget(kind: str, label: str, state: dict, key: str, current, cast, **extra):
    """Shared logic of the value widgets: (changed, value)."""
    ctx = _ctx()
    ctx.schema.append({"kind": kind, "key": key, "label": label, **extra,
                       "default": current, "section": _current_section()})
    if ctx.mode == "schema":
        return False, current
    ctx.bindings[key] = (state, key)
    if key in ctx.changed and key in ctx.payload:
        new_val = cast(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


# ── Public widget API ─────────────────────────────────────────────────────────

def slider_float(
    label: str,
    state: dict,
    key: str,
    min_val: float,
    max_val: float,
    step: float = 0.01,
) -> tuple[bool, float]:
    """
    Float slider widget. Returns (changed, new_value).

    In schema mode: registers the widget descriptor, returns (False, current).
    In live mode: returns (True, new_value) when the user changed this slider.
    """
    return _widget("slider", label, state, key, float(state.get(key, 0.0)), float,
                   min=min_val, max=max_val, step=step)


def slider_int(
    label: str,
    state: dict,
    key: str,
    min_val: int,
    max_val: int,
    step: int = 1,
) -> tuple[bool, int]:
    """Integer slider widget. Returns (changed, new_value)."""
    return _widget("int_slider", label, state, key, int(state.get(key, 0)),
                   lambda v: int(round(float(v))), min=min_val, max=max_val, step=step)


def checkbox(label: str, state: dict, key: str) -> tuple[bool, bool]:
    """Checkbox widget. Returns (changed, new_value)."""
    def to_bool(v):
        return v.strip().lower() in ("1", "true", "yes", "on") if isinstance(v, str) else bool(v)
    return _widget("checkbox", label, state, key, bool(state.get(key, False)), to_bool)


def dropdown(
    label: str,
    state: dict,
    key: str,
    options: list,
) -> tuple[bool, object]:
    """Dropdown/select widget. Returns (changed, new_value). The value keeps the type
    of the option (an option 2 comes back as the int 2, not "2")."""
    def to_option(v):
        for o in options:
            if o == v or str(o) == str(v):
                return o
        return v
    current = state.get(key, options[0] if options else "")
    return _widget("dropdown", label, state, key, current, to_option, options=list(options))


def text_input(label: str, state: dict, key: str) -> tuple[bool, str]:
    """Text input widget. Returns (changed, new_value)."""
    return _widget("text", label, state, key, str(state.get(key, "")), str)


def button(label: str) -> bool:
    """
    Action button. Returns True in live mode when this button was clicked.

    In schema mode: records a button entry (kind="button", key=label).
    """
    ctx = _ctx()
    ctx.schema.append({"kind": "button", "key": label, "label": label,
                       "section": _current_section()})
    if ctx.mode == "schema":
        return False
    return ctx.button and ctx.trigger == label


@contextmanager
def header(label: str):
    """
    Collapsible section header — context manager that groups subsequent widgets.

    Usage:
        with imgui.header("Cylinder"):
            imgui.slider_float("Radius", state, "radius", 0.1, 10)
    """
    ctx = _ctx()
    ctx._section_stack.append(label)
    try:
        yield
    finally:
        ctx._section_stack.pop()
