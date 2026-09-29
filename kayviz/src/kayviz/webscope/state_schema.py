"""
Widget metadata helpers for @gui_state dataclasses.

Usage:
    from .state_schema import gui_state, slider, dropdown, checkbox, text_field

    @gui_state
    @dataclass
    class MyState:
        max_iter: slider(1, 200, 1, "Max Iterations") = 30
        mode:     dropdown(["a", "b"], "Mode")       = "a"
        visible:  checkbox("Show Mesh")               = True
        name:     text_field("Experiment Name")       = "exp0"

    to_json(MyState)  → list[dict] for the frontend AutoPanel
    apply_client_state(instance, payload_dict)  → updates fields with type coercion
"""

from __future__ import annotations
import dataclasses
from typing import Annotated, Any, get_args, get_origin


# ── Widget annotation helpers ─────────────────────────────────────────────────

class _WidgetMeta:
    """Carries lil-gui widget metadata attached to a field via Annotated[...]."""
    __slots__ = ("kind", "label", "min", "max", "step", "options")

    def __init__(self, kind, label, *, min=None, max=None, step=None, options=None):
        self.kind    = kind
        self.label   = label
        self.min     = min
        self.max     = max
        self.step    = step
        self.options = options


def slider(min_val: float, max_val: float, step: float, label: str):
    """Annotated type alias that marks a field as a slider widget."""
    meta = _WidgetMeta("slider", label, min=min_val, max=max_val, step=step)
    return Annotated[float, meta]


def int_slider(min_val: int, max_val: int, step: int, label: str):
    """Annotated type alias that marks a field as an integer slider widget."""
    meta = _WidgetMeta("int_slider", label, min=min_val, max=max_val, step=step)
    return Annotated[int, meta]


def dropdown(options: list, label: str):
    """Annotated type alias that marks a field as a dropdown widget."""
    meta = _WidgetMeta("dropdown", label, options=options)
    return Annotated[Any, meta]


def checkbox(label: str):
    """Annotated type alias that marks a field as a checkbox widget."""
    meta = _WidgetMeta("checkbox", label)
    return Annotated[bool, meta]


def text_field(label: str):
    """Annotated type alias that marks a field as a text input widget."""
    meta = _WidgetMeta("text", label)
    return Annotated[str, meta]


def gui_state(cls):
    """Class decorator that marks a dataclass as a gui_state (no-op, for discoverability)."""
    cls.__gui_state__ = True
    return cls


# ── Schema extraction ─────────────────────────────────────────────────────────

def to_json(cls) -> list[dict]:
    """
    Walk a @gui_state @dataclass and return a JSON-serialisable list of widget
    descriptors for the frontend AutoPanel.

    Fields without widget metadata (plain type annotations, dicts, etc.) are
    skipped — they are internal state not exposed in the panel.
    """
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls} is not a dataclass")

    schema = []
    instance = cls()  # default values

    for f in dataclasses.fields(cls):
        meta = _get_meta(f.type)
        if meta is None:
            continue

        default = getattr(instance, f.name)
        # dict / list defaults are not JSON-serialisable as-is; skip them
        if isinstance(default, (dict, list)):
            continue

        entry: dict = {
            "key":     f.name,
            "kind":    meta.kind,
            "label":   meta.label,
            "default": default,
        }
        if meta.min     is not None: entry["min"]     = meta.min
        if meta.max     is not None: entry["max"]     = meta.max
        if meta.step    is not None: entry["step"]    = meta.step
        if meta.options is not None: entry["options"] = meta.options

        schema.append(entry)

    return schema


def apply_client_state(instance, payload: dict) -> None:
    """
    Write values from a client payload dict into a dataclass instance.
    Performs type coercion using the field's base type annotation.
    Ignores keys not present as dataclass fields.
    """
    if not dataclasses.is_dataclass(instance):
        raise TypeError(f"{instance} is not a dataclass instance")

    field_map = {f.name: f for f in dataclasses.fields(instance)}
    for key, value in payload.items():
        if key not in field_map:
            continue
        f    = field_map[key]
        base = _base_type(f.type)
        try:
            if base in (int,):
                value = int(value)
            elif base in (float,):
                value = float(value)
            elif base in (bool,):
                value = bool(value)
            elif base in (str,):
                value = str(value)
        except (TypeError, ValueError):
            pass
        setattr(instance, key, value)


# ── Internals ─────────────────────────────────────────────────────────────────

def _get_meta(annotation) -> _WidgetMeta | None:
    """Return the _WidgetMeta attached to an Annotated type, or None."""
    if get_origin(annotation) is Annotated:
        for arg in get_args(annotation):
            if isinstance(arg, _WidgetMeta):
                return arg
    return None


def _base_type(annotation):
    """Return the underlying Python type from an Annotated alias, or the annotation itself."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            return args[0]
    return annotation
