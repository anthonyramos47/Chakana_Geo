"""
kayviz.webscope.imgui — Polyscope-style widget helpers for set_user_callback.

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

    from kayviz.webscope import imgui

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
        self.schema: list[dict] = []       # populated in schema mode
        self.trigger: str = ""             # widget key / button label (live mode)
        self.payload: dict = {}            # full state dict from browser (live mode)
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
    ctx.payload = {}
    ctx._section_stack = []
    return ctx


def _enter_live_mode(trigger: str, payload: dict) -> _Context:
    """Switch context to live mode for a specific trigger event."""
    ctx = _ctx()
    ctx.mode = "live"
    ctx.schema = []
    ctx.trigger = trigger
    ctx.payload = payload
    ctx._section_stack = []
    return ctx


def _current_section() -> str | None:
    ctx = _ctx()
    return ctx._section_stack[-1] if ctx._section_stack else None


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
    In live mode: returns (True, new_value) when this slider fired.
    """
    ctx = _ctx()
    current = float(state.get(key, 0.0))

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":    "slider",
            "key":     key,
            "label":   label,
            "min":     min_val,
            "max":     max_val,
            "step":    step,
            "default": current,
            "section": _current_section(),
        })
        return False, current

    # live mode
    if ctx.trigger == key and key in ctx.payload:
        new_val = float(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


def slider_int(
    label: str,
    state: dict,
    key: str,
    min_val: int,
    max_val: int,
    step: int = 1,
) -> tuple[bool, int]:
    """Integer slider widget. Returns (changed, new_value)."""
    ctx = _ctx()
    current = int(state.get(key, 0))

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":    "int_slider",
            "key":     key,
            "label":   label,
            "min":     min_val,
            "max":     max_val,
            "step":    step,
            "default": current,
            "section": _current_section(),
        })
        return False, current

    if ctx.trigger == key and key in ctx.payload:
        new_val = int(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


def checkbox(label: str, state: dict, key: str) -> tuple[bool, bool]:
    """Checkbox widget. Returns (changed, new_value)."""
    ctx = _ctx()
    current = bool(state.get(key, False))

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":    "checkbox",
            "key":     key,
            "label":   label,
            "default": current,
            "section": _current_section(),
        })
        return False, current

    if ctx.trigger == key and key in ctx.payload:
        new_val = bool(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


def dropdown(
    label: str,
    state: dict,
    key: str,
    options: list[str],
) -> tuple[bool, str]:
    """Dropdown/select widget. Returns (changed, new_value)."""
    ctx = _ctx()
    current = str(state.get(key, options[0] if options else ""))

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":    "dropdown",
            "key":     key,
            "label":   label,
            "options": options,
            "default": current,
            "section": _current_section(),
        })
        return False, current

    if ctx.trigger == key and key in ctx.payload:
        new_val = str(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


def text_input(label: str, state: dict, key: str) -> tuple[bool, str]:
    """Text input widget. Returns (changed, new_value)."""
    ctx = _ctx()
    current = str(state.get(key, ""))

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":    "text",
            "key":     key,
            "label":   label,
            "default": current,
            "section": _current_section(),
        })
        return False, current

    if ctx.trigger == key and key in ctx.payload:
        new_val = str(ctx.payload[key])
        state[key] = new_val
        return True, new_val
    return False, current


def button(label: str) -> bool:
    """
    Action button. Returns True in live mode when this button was clicked.

    In schema mode: records a button entry (kind="button", key=label).
    """
    ctx = _ctx()

    if ctx.mode == "schema":
        ctx.schema.append({
            "kind":  "button",
            "key":   label,
            "label": label,
            "section": _current_section(),
        })
        return False

    return ctx.trigger == label


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
