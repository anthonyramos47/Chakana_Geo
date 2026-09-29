"""
Integration tests for server/webscope/script.py (the client API).

These tests spin up a real FastAPI TestClient so they exercise the full
HTTP stack without needing a running uvicorn process.

Run:
    pytest tests/test_script_client.py
"""

import numpy as np
import pytest

from fastapi.testclient import TestClient

# ── Build a minimal FastAPI app with ScriptApp registered ────────────────────

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from kayviz.webscope import register_app, mount_all
from kayviz.webscope.script_app import ScriptApp

_script_app = ScriptApp()

def _make_test_fastapi():
    app = FastAPI()
    # Re-use the same ScriptApp instance so tests can inspect its buffer
    from kayviz.webscope import registry as reg
    reg._apps.clear()
    reg._apps["script"] = _script_app
    mount_all(app)
    return app

_fastapi = _make_test_fastapi()
client   = TestClient(_fastapi, raise_server_exceptions=True)

# Reset buffer before each test
@pytest.fixture(autouse=True)
def reset_buffer():
    import asyncio
    asyncio.run(_script_app.do_clear())
    yield


# ── /api/script/ping ─────────────────────────────────────────────────────────

class TestPing:
    def test_returns_ok(self):
        r = client.get("/api/script/ping")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_object_count_reflects_buffer(self):
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        from kayviz import serializers as ser
        obj = ser.surface_mesh("A", V, F)
        client.post("/api/script/push", json={"objects": [obj]})
        r = client.get("/api/script/ping")
        assert r.json()["objects"] == 1


# ── /api/script/push ─────────────────────────────────────────────────────────

class TestPush:
    def test_push_surface_mesh(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        obj = ser.surface_mesh("Mesh", V, F)
        r = client.post("/api/script/push", json={"objects": [obj]})
        assert r.status_code == 200
        assert r.json()["pushed"] == 1
        assert "Mesh" in _script_app._buffer

    def test_push_multiple(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        objs = [
            ser.surface_mesh("A", V, F),
            ser.curve_network("B", V, np.array([[0,1],[1,2]])),
        ]
        r = client.post("/api/script/push", json={"objects": objs})
        assert r.json()["pushed"] == 2
        assert "A" in _script_app._buffer
        assert "B" in _script_app._buffer

    def test_push_updates_existing(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        obj1 = ser.surface_mesh("M", V, F, color=(0.5, 0.5, 0.5))
        obj2 = ser.surface_mesh("M", V, F, color=(1.0, 0.0, 0.0))
        client.post("/api/script/push", json={"objects": [obj1]})
        client.post("/api/script/push", json={"objects": [obj2]})
        assert _script_app._buffer["M"]["color"] == pytest.approx([1.0, 0.0, 0.0])
        assert len(_script_app._buffer) == 1

    def test_clear_action(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        client.post("/api/script/push",
                    json={"objects": [ser.surface_mesh("X", V, F)]})
        r = client.post("/api/script/push", json={"action": "clear"})
        assert r.status_code == 200
        assert r.json()["action"] == "clear"
        assert _script_app._buffer == {}


# ── /api/script/remove ───────────────────────────────────────────────────────

class TestRemove:
    def test_remove_existing(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        client.post("/api/script/push",
                    json={"objects": [ser.surface_mesh("A", V, F),
                                      ser.surface_mesh("B", V, F)]})
        r = client.post("/api/script/remove", json={"name": "A"})
        assert r.status_code == 200
        assert r.json()["removed"] == "A"
        assert "A" not in _script_app._buffer
        assert "B" in _script_app._buffer

    def test_remove_missing_name_returns_error(self):
        r = client.post("/api/script/remove", json={})
        assert r.json()["ok"] is False


# ── /api/script/schema ────────────────────────────────────────────────────────

class TestSchema:
    def test_empty_state_schema(self):
        r = client.get("/api/script/schema")
        assert r.status_code == 200
        body = r.json()
        assert body["app"] == "script"
        assert body["state"] == []

    def test_actions_empty(self):
        r = client.get("/api/script/schema")
        assert r.json()["actions"] == []


# ── /api/script/load ─────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_objects_when_buffer_empty(self):
        r = client.post("/api/script/load")
        assert r.status_code == 200
        assert r.json()["objects"] == []

    def test_returns_buffer_contents(self):
        from kayviz import serializers as ser
        V = np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        F = [[0,1,2]]
        client.post("/api/script/push",
                    json={"objects": [ser.surface_mesh("M", V, F)]})
        r = client.post("/api/script/load")
        objs = r.json()["objects"]
        assert len(objs) == 1
        assert objs[0]["name"] == "M"
