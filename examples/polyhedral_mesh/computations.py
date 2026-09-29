"""Core computation functions for polyhedral mesh optimization."""

import os
import numpy as np
from hanan.geometry.mesh import Mesh
from hanan.geometry.utils import (
    read_obj,
    normalize_vertices,
    planarity_measure_quad_mesh,
    compute_circumcircles_quad_mesh,
)
from hanan.optimization.optimizer import Optimizer
from hanan.optimization.planarity import Planarity
from hanan.optimization.cyclicity import Cyclicity

from hanan import glyphs
from kayviz import serializers as ser


def load_mesh(mesh_path: str, state) -> None:
    """Load and initialize mesh from OBJ file."""
    vertices, faces = read_obj(mesh_path)
    vertices = normalize_vertices(vertices)
    #vertices += np.random.rand(*vertices.shape) * 0.01

    mesh = Mesh()
    mesh.make_mesh(vertices, faces)

    state.vertices = mesh.vertices
    state.faces = mesh.faces
    state.mesh = mesh
    state.name = os.path.splitext(os.path.basename(mesh_path))[0]


def setup_optimizer(state) -> None:
    """Set up the optimization problem with all energy terms."""
    optimizer = Optimizer()

    optimizer.add_variable("v",   state.vertices.flatten())
    optimizer.add_variable("n_f", state.mesh.face_normals.flatten())
    optimizer.add_variable("cf",  state.mesh.face_barycenters().flatten())

    if state.planarity_w > 0:
        planarity = Planarity()
        planarity.name = "Planarity"
        optimizer.add_objective_term(planarity, args=([state.faces]),
                                     w=state.planarity_w, ce=True)

    if state.cyclicity_w > 0:
        cyclicity = Cyclicity()
        cyclicity.name = "Cyclicity"
        optimizer.add_objective_term(
            cyclicity,
            args=(state.faces, "v", "cf", "n_f"),
            w=state.cyclicity_w,
            ce=True,
        )

    if state.conical_w > 0:
        optimizer.add_variable(
            "aux_n",
            state.mesh.vertex_normals[state.mesh.inner_vertices()].flatten()
        )
        optimizer.unitize_variable("aux_n", 3, w=5)
        conical_term = Planarity()
        conical_term.name = "Conical"
        inner_vf = [
            state.mesh.vertex_face_adjacency_list()[i]
            for i in state.mesh.inner_vertices()
        ]
        optimizer.add_objective_term(
            conical_term,
            args=(inner_vf, "n_f", "aux_n"),
            w=state.conical_w,
            ce=True,
        )

    vertex_adj  = state.mesh.vertex_adjacency_list()
    face_adj    = state.mesh.face_face_adjacency_list()

    if state.fairness_v_w > 0:
        optimizer.set_fairness(
            "v", vertex_adj, dim=3,
            damp_factor=0.8, damp_iteration=state.damp_iteration,
            w=state.fairness_v_w, ce=True,
        )

    if state.fairness_nf_w > 0:
        optimizer.set_fairness(
            "n_f", face_adj, dim=3,
            damp_factor=0.8, damp_iteration=state.damp_iteration,
            w=state.fairness_nf_w, ce=True,
        )

    edges = state.mesh.edge_vertices()
    optimizer.edge_length("v", edges, target_length=None, w=1)
    optimizer.unitize_variable("n_f", 3, w=5)

    optimizer.initialize_optimizer(verbose=True, adaptive_mu=False)
    state.optimizer = optimizer
    state.current_iteration = 0
    state.energy_history = []
    state.energy_change_history = []


def update_weights(state) -> None:
    """Push the current weight fields from state into the live optimizer."""
    weight_map = {
        "Planarity":  state.planarity_w,
        "Cyclicity":  state.cyclicity_w,
        "Conical":    state.conical_w,
        "Fairness_v": state.fairness_v_w,
        "Fairness_n": state.fairness_nf_w,
    }
    w_dict = state.optimizer.get_term_weights_dict()
    for opt_key in w_dict:
        for map_key, val in weight_map.items():
            if map_key.lower() in opt_key.lower() or opt_key.lower() in map_key.lower():
                w_dict[opt_key] = val
    state.optimizer.set_term_weights(w_dict)


def optimization_step(state) -> None:
    """Perform a single optimization step."""
    if state.current_iteration >= state.max_iterations:
        return

    optimizer = state.optimizer
    optimizer.get_gradients()
    optimizer.optimize_step()

    new_vertices = optimizer.unpack("v").reshape(-1, 3)
    state.vertices = new_vertices
    state.mesh.vertices = new_vertices
    state.mesh.update_mesh()

    current_energy = optimizer.energy[-1]
    state.energy_history.append(current_energy)
    if state.last_energy > 0:
        state.energy_change_history.append(state.last_energy - current_energy)
    state.last_energy = current_energy
    state.current_iteration += 1


def scene_snapshot(state) -> dict:
    """Build a scene_update payload from current mesh state."""
    objects = []

    mesh_result = ser.surface_mesh(
        "Optimized mesh", state.vertices, state.faces,
        color=(0.8, 0.8, 0.8), show_edges=True,
    )
    if isinstance(mesh_result, list):
        objects.extend(mesh_result)
    else:
        objects.append(mesh_result)

    planarity_values = planarity_measure_quad_mesh(state.mesh)
    objects.append(ser.scalar_quantity("Optimized mesh", "Planarity",
                                       planarity_values, defined_on="faces"))

    gv, _gf, ge = state.mesh.gauss_image()
    gv = 0.5 * gv + np.array([0.0, 0.0, -2.0])
    objects.append(ser.curve_network("Gauss image", gv, ge, color=(0.8, 0.2, 0.2)))

    if state.cyclicity_w > 0 and state.show_circles:
        centers, normals, radii = compute_circumcircles_quad_mesh(state.vertices, state.faces)
        objects.append(ser.curve_network("Circles_circles", *glyphs.circles(centers, normals, radii),
                                         color=(1.0, 0.0, 0.0)))

    energy = state.last_energy
    return {
        "action":    "scene_update",
        "iteration": state.current_iteration,
        "energy":    float(energy) if energy else None,
        "objects":   objects,
    }


def export_mesh(state, filepath: str) -> None:
    """Export optimized mesh to OBJ file."""
    from hanan.geometry.utils import write_obj
    write_obj(filepath, state.mesh.vertices, state.mesh.faces)


def get_energy_summary(state) -> dict:
    """Get summary of optimization energy."""
    if not state.energy_history:
        return {"current": 0.0, "change": 0.0, "iteration": 0}
    return {
        "current":   state.energy_history[-1],
        "change":    state.energy_change_history[-1] if state.energy_change_history else 0.0,
        "iteration": state.current_iteration,
    }
