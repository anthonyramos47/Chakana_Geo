"""
PolyhedralMeshApp — planarity/cyclicity optimization of a quad mesh.

A GUIApp: widget state lives in state.py (sliders render automatically),
numerical work in computations.py (hanan), and the action buttons in
polyhedral_panel.js. run.py serves it with kayviz.
"""

from __future__ import annotations
import os

from fastapi import WebSocket

import kayviz as kv
from kayviz import serializers as ser

from state import AppState
import computations as comp

HERE = os.path.dirname(os.path.abspath(__file__))


class PolyhedralMeshApp(kv.GUIApp):
    name      = "polyhedral"
    state_cls = AppState

    def __init__(self, mesh_path: str, out_dir: str = os.path.join(HERE, "out")):
        self.mesh_path = mesh_path
        self.out_dir   = out_dir
        super().__init__()

    # ── Initial scene ─────────────────────────────────────────────────────────

    def initial_scene(self, mesh_name: str = "") -> dict:
        comp.load_mesh(self.mesh_path, self.state)
        self.state.output_path = os.path.join(self.out_dir, self.state.name)

        V = self.state.vertices
        F = self.state.faces

        return {
            "mesh_name":       self.state.name,
            "n_vertices":      len(V),
            "n_faces":         len(F),
            "experiment_name": self.state.experiment_name,
            "objects":         ser.surface_mesh("Base mesh", V, F,
                                                color=(0.8, 0.8, 0.8),
                                                show_edges=True),
        }

    # ── Action registration ───────────────────────────────────────────────────

    def register_actions(self):
        self.action("setup_optimizer", self._setup)
        self.action("step",            self._step)
        self.action("run",             self._run)
        self.action("stop",            self._stop)
        self.action("reset",           self._reset)
        self.action("update_weights",  self._update_weights)
        self.action("export_obj",      self._export)

    # ── Sync handlers ─────────────────────────────────────────────────────────

    def _setup(self, state: AppState, data: dict) -> dict:
        comp.setup_optimizer(state)
        return comp.scene_snapshot(state)

    def _step(self, state: AppState, data: dict) -> dict:
        comp.optimization_step(state)
        return comp.scene_snapshot(state)

    def _stop(self, state: AppState, data: dict) -> dict:
        state.is_running = False
        return self._done("stopped")

    def _reset(self, state: AppState, data: dict) -> dict:
        comp.setup_optimizer(state)
        return comp.scene_snapshot(state)

    def _update_weights(self, state: AppState, data: dict) -> dict:
        comp.update_weights(state)
        return self._done("weights_updated")

    def _export(self, state: AppState, data: dict) -> dict:
        export_dir = os.path.join(
            self.out_dir, state.name, state.experiment_name
        )
        os.makedirs(export_dir, exist_ok=True)
        filepath = os.path.join(export_dir, f"{state.name}_optimized.obj")
        comp.export_mesh(state, filepath)
        return self._done("export_done")

    # ── Async streaming handler ───────────────────────────────────────────────

    async def _run(self, state: AppState, data: dict, ws: WebSocket) -> None:
        state.is_running = True
        while state.is_running and state.current_iteration < state.max_iterations:
            comp.optimization_step(state)
            await ws.send_json(comp.scene_snapshot(state))
        state.is_running = False
        await ws.send_json(self._done("optimization_complete"))
