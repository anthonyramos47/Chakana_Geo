"""Application state for Polyhedral Mesh Optimization GUI."""

from dataclasses import dataclass, field
import numpy as np
from hanan.optimization.optimizer import Optimizer
from kayviz import gui_state, slider, int_slider, checkbox, text_field


@gui_state
@dataclass
class AppState:
    """Centralized application state for polyhedral mesh optimization."""

    # ── Exposed to the frontend AutoPanel ────────────────────────────────────

    experiment_name: text_field("Experiment Name") = "experiment0"

    # Optimization weights
    planarity_w:   slider(0.0, 10.0, 0.1,    "Planarity Weight")    = 1.0
    cyclicity_w:   slider(0.0, 10.0, 0.1,    "Cyclicity Weight")    = 1.0
    conical_w:     slider(0.0, 10.0, 0.1,    "Conical Weight")      = 0.0
    fairness_v_w:  slider(0.0, 0.5,  0.001,  "Fairness V")          = 0.001
    fairness_nf_w: slider(0.0, 0.5,  0.001,  "Fairness N")          = 0.001

    damp_iteration: int_slider(1, 100, 1, "Fairness Damp Iter") = 10
    max_iterations: int_slider(1, 500, 1, "Max Iterations")     = 50

    show_circles: checkbox("Show Circumcircles") = True

    # ── Internal state (not exposed to the panel) ─────────────────────────────

    mesh: object          = None
    vertices: np.ndarray  = None
    faces: np.ndarray     = None

    name: str          = ""
    mesh_path: str     = ""
    output_path: str   = ""
    save_path: str     = ""
    current_dir: str   = ""

    optimizer: Optimizer = field(default_factory=Optimizer)

    current_iteration: int  = 0
    is_running: bool        = False
    last_energy: float      = 0.0
    energy_history: list    = field(default_factory=list)
    energy_change_history: list = field(default_factory=list)
