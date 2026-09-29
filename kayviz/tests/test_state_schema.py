"""
Unit tests for server/webscope/state_schema.py.

Tests widget annotation helpers, schema extraction (to_json),
and client-state application (apply_client_state).

Run:
    pytest tests/test_state_schema.py
"""

import pytest
from dataclasses import dataclass, field

from kayviz.webscope.state_schema import (
    gui_state, slider, int_slider, dropdown, checkbox, text_field,
    to_json, apply_client_state,
)


# ── Sample state classes ──────────────────────────────────────────────────────

@gui_state
@dataclass
class FullState:
    alpha:    slider(0.0, 1.0, 0.01, "Alpha")        = 0.5
    count:    int_slider(1, 100, 1, "Count")          = 10
    mode:     dropdown(["a", "b", "c"], "Mode")       = "a"
    visible:  checkbox("Visible")                     = True
    name:     text_field("Name")                      = "exp0"
    # internal — not exposed as a widget
    mesh:     object                                  = None
    data:     dict = field(default_factory=dict)


@gui_state
@dataclass
class EmptyState:
    pass


@gui_state
@dataclass
class MixedState:
    alpha:  slider(0.0, 1.0, 0.01, "Alpha") = 0.5
    _internal: object = None


# ── gui_state decorator ───────────────────────────────────────────────────────

class TestGuiState:
    def test_marks_class(self):
        assert hasattr(FullState, "__gui_state__")
        assert FullState.__gui_state__ is True

    def test_still_a_dataclass(self):
        import dataclasses
        assert dataclasses.is_dataclass(FullState)

    def test_instantiates_with_defaults(self):
        s = FullState()
        assert s.alpha   == pytest.approx(0.5)
        assert s.count   == 10
        assert s.mode    == "a"
        assert s.visible is True
        assert s.name    == "exp0"
        assert s.mesh    is None


# ── to_json ───────────────────────────────────────────────────────────────────

class TestToJson:
    def test_only_widget_fields_exported(self):
        schema = to_json(FullState)
        keys = [w["key"] for w in schema]
        assert "alpha"   in keys
        assert "count"   in keys
        assert "mode"    in keys
        assert "visible" in keys
        assert "name"    in keys
        assert "mesh"    not in keys   # internal object field
        assert "data"    not in keys   # internal dict field

    def test_slider_shape(self):
        schema = to_json(FullState)
        w = next(w for w in schema if w["key"] == "alpha")
        assert w["kind"]    == "slider"
        assert w["label"]   == "Alpha"
        assert w["min"]     == pytest.approx(0.0)
        assert w["max"]     == pytest.approx(1.0)
        assert w["step"]    == pytest.approx(0.01)
        assert w["default"] == pytest.approx(0.5)

    def test_int_slider_shape(self):
        schema = to_json(FullState)
        w = next(w for w in schema if w["key"] == "count")
        assert w["kind"]    == "int_slider"
        assert w["min"]     == 1
        assert w["max"]     == 100
        assert w["default"] == 10

    def test_dropdown_shape(self):
        schema = to_json(FullState)
        w = next(w for w in schema if w["key"] == "mode")
        assert w["kind"]    == "dropdown"
        assert w["options"] == ["a", "b", "c"]
        assert w["default"] == "a"

    def test_checkbox_shape(self):
        schema = to_json(FullState)
        w = next(w for w in schema if w["key"] == "visible")
        assert w["kind"]    == "checkbox"
        assert w["default"] is True

    def test_text_field_shape(self):
        schema = to_json(FullState)
        w = next(w for w in schema if w["key"] == "name")
        assert w["kind"]    == "text"
        assert w["default"] == "exp0"

    def test_empty_state_returns_empty_list(self):
        assert to_json(EmptyState) == []

    def test_non_dataclass_raises(self):
        with pytest.raises(TypeError):
            to_json(object)

    def test_only_widget_in_mixed(self):
        schema = to_json(MixedState)
        assert len(schema) == 1
        assert schema[0]["key"] == "alpha"


# ── apply_client_state ────────────────────────────────────────────────────────

class TestApplyClientState:
    def test_updates_float(self):
        s = FullState()
        apply_client_state(s, {"alpha": 0.9})
        assert s.alpha == pytest.approx(0.9)

    def test_updates_int(self):
        s = FullState()
        apply_client_state(s, {"count": "42"})   # string from JSON
        assert s.count == 42
        assert isinstance(s.count, int)

    def test_updates_bool(self):
        s = FullState()
        apply_client_state(s, {"visible": False})
        assert s.visible is False

    def test_updates_str(self):
        s = FullState()
        apply_client_state(s, {"name": "run_7"})
        assert s.name == "run_7"

    def test_updates_dropdown(self):
        s = FullState()
        apply_client_state(s, {"mode": "c"})
        assert s.mode == "c"

    def test_unknown_keys_ignored(self):
        s = FullState()
        apply_client_state(s, {"nonexistent": 99})  # must not raise

    def test_partial_update_leaves_rest_unchanged(self):
        s = FullState()
        apply_client_state(s, {"alpha": 0.1})
        assert s.count == 10   # untouched
        assert s.mode  == "a"  # untouched

    def test_non_dataclass_raises(self):
        with pytest.raises(TypeError):
            apply_client_state({"not": "a dataclass"}, {})
