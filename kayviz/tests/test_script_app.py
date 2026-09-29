"""
Unit tests for server/webscope/script_app.py.

Tests the ScriptApp scene buffer, broadcast logic, and extra routes
without starting a real HTTP server (uses FastAPI's TestClient and
the ASGI WebSocket test utilities).

Run:
    pytest tests/test_script_app.py
"""

import asyncio
import pytest
import numpy as np

from kayviz.webscope.script_app import ScriptApp
from kayviz import serializers as ser


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_app() -> ScriptApp:
    return ScriptApp()


def mesh_obj(name="Mesh"):
    V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
    F = np.array([[0,1,2]], dtype=np.int32)
    return ser.surface_mesh(name, V, F)


# ── Buffer management ─────────────────────────────────────────────────────────

class TestBuffer:
    def test_push_adds_to_buffer(self):
        app = make_app()
        obj = mesh_obj("A")
        asyncio.run(app.push([obj]))
        assert "A" in app._buffer

    def test_push_updates_existing(self):
        app = make_app()
        obj1 = mesh_obj("A")
        obj2 = {**mesh_obj("A"), "color": [1.0, 0.0, 0.0]}
        asyncio.run(app.push([obj1]))
        asyncio.run(app.push([obj2]))
        assert app._buffer["A"]["color"] == [1.0, 0.0, 0.0]
        assert len(app._buffer) == 1  # no duplicate

    def test_push_multiple_objects(self):
        app = make_app()
        asyncio.run(app.push([mesh_obj("A"), mesh_obj("B"), mesh_obj("C")]))
        assert set(app._buffer.keys()) == {"A", "B", "C"}

    def test_clear_empties_buffer(self):
        app = make_app()
        asyncio.run(app.push([mesh_obj("A"), mesh_obj("B")]))
        asyncio.run(app.do_clear())
        assert app._buffer == {}

    def test_remove_deletes_one(self):
        app = make_app()
        asyncio.run(app.push([mesh_obj("A"), mesh_obj("B")]))
        asyncio.run(app.do_remove("A"))
        assert "A" not in app._buffer
        assert "B" in app._buffer

    def test_remove_nonexistent_is_noop(self):
        app = make_app()
        asyncio.run(app.do_remove("ghost"))  # must not raise

    def test_objects_without_name_skipped(self):
        app = make_app()
        no_name = {"type": "surface_mesh", "vertices": [], "faces": []}
        asyncio.run(app.push([no_name]))
        assert len(app._buffer) == 0


# ── initial_scene ─────────────────────────────────────────────────────────────

class TestInitialScene:
    def test_empty_on_fresh_app(self):
        app = make_app()
        result = app.initial_scene()
        assert result == {"objects": []}

    def test_returns_buffer_contents(self):
        app = make_app()
        obj = mesh_obj("X")
        asyncio.run(app.push([obj]))
        result = app.initial_scene()
        assert len(result["objects"]) == 1
        assert result["objects"][0]["name"] == "X"

    def test_initial_scene_after_clear(self):
        app = make_app()
        asyncio.run(app.push([mesh_obj("X")]))
        asyncio.run(app.do_clear())
        assert app.initial_scene() == {"objects": []}


# ── Idle event ────────────────────────────────────────────────────────────────

class TestIdleEvent:
    def test_idle_when_no_clients(self):
        app = make_app()
        # Should resolve immediately — no clients connected
        result = asyncio.run(app.wait_until_idle(timeout=1.0))
        assert result is True

    def test_idle_timeout(self):
        app = make_app()
        # Manually mark as non-idle (pretend a client is connected)
        app._idle_event.clear()
        result = asyncio.run(app.wait_until_idle(timeout=0.1))
        assert result is False  # timed out


# ── state_schema ──────────────────────────────────────────────────────────────

class TestStateSchema:
    def test_empty_schema(self):
        app = make_app()
        schema = app.state_schema()
        assert schema == []  # ScriptState has no widget fields


# ── extra_routes wiring ───────────────────────────────────────────────────────

class TestExtraRoutes:
    """Smoke-test that extra_routes() registers the expected paths."""
    def test_routes_registered(self):
        from fastapi import APIRouter
        app  = make_app()
        router = APIRouter(prefix="/api/script")
        app.extra_routes(router)
        paths = {r.path for r in router.routes}
        assert "/api/script/ping"   in paths
        assert "/api/script/push"   in paths
        assert "/api/script/wait"   in paths
        assert "/api/script/remove" in paths
