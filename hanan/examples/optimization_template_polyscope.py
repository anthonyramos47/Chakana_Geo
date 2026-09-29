"""
================================================================================
OPTIMIZATION TEMPLATE — based on quad_optimization_test.py
================================================================================

This file walks through a complete optimization setup using the hanan
framework. It follows the same structure as quad_optimization_test.py
(planarity + cyclicity on a quad mesh) and annotates every step so you can
adapt it to your own problem.

OVERVIEW OF THE FRAMEWORK
--------------------------
The optimizer minimizes a sum of weighted least-squares energy terms:

    E(X) = sum_k  w_k * ||r_k(X)||^2

where X is a single flat vector that concatenates all optimization variables,
and each energy term r_k is an ObjectiveTerm subclass. The solver uses
Levenberg-Marquardt (LM): it builds the sparse Jacobian J and solves

    (J^T J + mu * I) dx = -J^T r

at every iteration to get the update step dx.

TYPICAL SETUP ORDER
-------------------
1.  Load your mesh / data
2.  Create the Optimizer, declare variables and set initial values  (add_variable)
3.  Register energy terms                                           (add_objective_term)
5.  Add built-in regularisers (fairness, edge-length, unit norms …)
6.  Call initialize_optimizer()
7.  Run the iteration loop

================================================================================
"""

# ── Standard library ──────────────────────────────────────────────────────────
import os

# ── Third-party ───────────────────────────────────────────────────────────────
import numpy as np
import polyscope as ps
import polyscope.imgui as psim

# ── hanan geometry helpers ─────────────────────────────────────────────────
from hanan.geometry.mesh import Mesh
from hanan import glyphs                   # mesh data for circles, spheres, …
from hanan.geometry.utils import (
    read_obj,                           # read an OBJ file → (vertices, faces)
    normalize_vertices,                 # scale mesh to fit inside unit sphere
    planarity_measure_quad_mesh,        # scalar planarity per face (for display)
    compute_circumcircles_quad_mesh,    # circumcircle per quad face
)

# ── hanan optimization classes ─────────────────────────────────────────────
from hanan.optimization.optimizer import Optimizer   # the main solver
from hanan.optimization.planarity import Planarity   # quad planarity energy
from hanan.optimization.cyclicity import Cyclicity   # cyclicity (inscribed-circle) energy


# ==============================================================================
# STEP 0 — POINT TO YOUR DATA
# ==============================================================================
# Change data_path to the folder that contains your mesh file and update `name`
# to the filename you want to optimise.

data_path = os.path.join(os.path.dirname(__file__), "data/")
name = "cone_mesh_0.obj"          # replace with your quad-mesh OBJ file


# ==============================================================================
# STEP 1 — LOAD AND PREPARE THE MESH
# ==============================================================================
# read_obj returns plain NumPy arrays: vertices (V×3) and faces (F×4 for quads)
vertices, faces = read_obj(data_path + name)

# Normalising puts the mesh inside the unit sphere and makes the initial energy
# scale-independent, which helps convergence.
vertices = normalize_vertices(vertices)

# A tiny random perturbation breaks exact degeneracies (e.g. perfectly flat
# initial meshes) that would give zero-valued Jacobian rows at iteration 0.
vertices += np.random.rand(*vertices.shape) * 0.001

# Build the topology object.  The Mesh class exposes adjacency queries that are
# needed to construct energy terms (face normals, inner vertices, etc.).
mesh = Mesh()
mesh.make_mesh(vertices, faces)

# Pre-compute topology that we will need for energy initialisation.
face_normals                  = mesh.face_normals                 # F×3
vertex_normals                = mesh.vertex_normals               # V×3
face_barycenters              = mesh.face_barycenters()           # F×3
inner_vertices                = mesh.inner_vertices()             # list of vertex indices
vertex_face_adjacency_list    = mesh.vertex_face_adjacency_list() # V-length list of face-index lists


# ==============================================================================
# STEP 2 — CREATE THE OPTIMIZER AND DECLARE VARIABLES
# ==============================================================================
# The optimizer holds a single flat vector X = [v | n_f | cf | aux_n | ...].
# You declare named blocks; the optimizer assigns contiguous index ranges and
# grows X automatically.
#
# add_variable(name, vals)
#   name : string key used throughout (must be unique)
#   vals : flat numpy array of initial values; its length defines the block size
#          e.g. vertices.flatten() stores one 3-D vector per vertex

optimizer = Optimizer()

# Vertex positions — 3 coordinates per vertex
optimizer.add_variable("v",     vertices.flatten())

# Face normals — 3 components per face (will be kept unit-length by a regulariser)
optimizer.add_variable("n_f",   face_normals.flatten())

# Circumcentre auxiliary variable for the Cyclicity term — one 3-D point per face
optimizer.add_variable("cf",    face_barycenters.flatten())   # good starting guess for circumcentres

# Auxiliary normals at inner vertices (used by the Conical term if activated)
optimizer.add_variable("aux_n", vertex_normals[inner_vertices].flatten())

# NOTE: add as many variables as your problem needs.  Variables that are not
# referenced by any energy term are still carried in X but have no gradient,
# so they remain at their initial value throughout.


# ==============================================================================
# STEP 4 — REGISTER ENERGY TERMS
# ==============================================================================
# add_objective_term(term_instance, args, w, ce)
#
#   term_instance : ObjectiveTerm subclass (see docs/hanan/OPTIMIZATION_API.md, "Writing an objective term")
#   args          : positional arguments forwarded to term.initialize_objective()
#   w             : weight (scales the contribution of this term in J^T J)
#   ce            : if True the per-iteration energy of this term is recorded
#                   and shown in the final report

# ── 4a. PLANARITY ─────────────────────────────────────────────────────────────
# Penalises deviation of each quad face from a common plane.
# The Planarity term needs only the face connectivity array.

planarity = Planarity()
optimizer.add_objective_term(planarity, args=([faces]), w=1, ce=True)

# ── 4b. CYCLICITY ─────────────────────────────────────────────────────────────
# Cyclicity enforces that each quad face has an inscribed circle, which is the
# defining property of a cyclic quad mesh.  The term uses four variable names
# and the face array.
#
# args format: (faces, vertex_var_name, circumcentre_var_name, normal_var_name)

cyclicity_term = Cyclicity()
optimizer.add_objective_term(cyclicity_term, args=(faces, "v", "cf", "n_f"), w=1, ce=True)

# ── 4c. CONICAL TERM (optional — uncomment to activate) ───────────────────────
# A conical mesh has planar vertex stars on the Gauss map, i.e. the face
# normals around each inner vertex are coplanar.  This is the same as the
# Planarity energy but applied to normals instead of positions.
#
# from hanan.optimization.planarity import Planarity
# inner_vertex_face_adjacency_list = [vertex_face_adjacency_list[i] for i in inner_vertices]
# conical_term = Planarity()
# conical_term.name = "Conical"   # rename so it lives under a different key
# optimizer.add_objective_term(conical_term,
#                              args=(inner_vertex_face_adjacency_list, "n_f", "aux_n"),
#                              w=1, ce=True)


# ==============================================================================
# STEP 5 — BUILT-IN REGULARISERS
# ==============================================================================
# These helpers add common soft constraints via the same add_objective_term path
# but with a more convenient interface.

vertex_adjacency_list = mesh.vertex_adjacency_list()

# ── 5a. FAIRNESS / SMOOTHNESS ─────────────────────────────────────────────────
# Penalises the discrete Laplacian of the vertex positions, biasing the mesh
# towards a smooth surface.
#
# set_fairness(var_name, adjacency_list, dim, damp_factor, damp_iteration, w, ce)
#   damp_factor / damp_iteration : the weight is multiplied by damp_factor every
#   damp_iteration iterations, so it decays and lets the primary energies dominate.

optimizer.set_fairness("v", vertex_adjacency_list, dim=3,
                        damp_factor=0.8, damp_iteration=10, w=0.02, ce=True)

# ── 5b. EDGE-LENGTH PRESERVATION ──────────────────────────────────────────────
# Keeps edge lengths close to their initial values, preventing collapse or
# extreme distortion of the mesh.
#
# edge_length(var_name, edges, target_length, w)
#   target_length=None  →  use the initial edge lengths as targets

edges = mesh.edge_vertices()     # E×2 array of vertex-index pairs
optimizer.edge_length("v", edges, target_length=None, w=0.1)

# ── 5c. UNIT-NORM CONSTRAINTS ──────────────────────────────────────────────────
# Forces every 3-D sub-vector of the named variable to have unit length.
# Essential for normal vectors that appear in bilinear energy terms.
#
# unitize_variable(var_name, dim, w)

optimizer.unitize_variable("n_f",   3, w=5)
optimizer.unitize_variable("aux_n", 3, w=5)


# ==============================================================================
# STEP 6 — INITIALISE THE OPTIMIZER
# ==============================================================================
# Must be called AFTER all variables and terms have been registered.
# It resets iteration bookkeeping without touching X.
#
# initialize_optimizer(verbose, adaptive_mu)
#   verbose      : print per-iteration energy to stdout
#   adaptive_mu  : use gain-ratio adaptive damping (recommended; set False for
#                  the classic fixed-damping LM variant)

optimizer.initialize_optimizer(verbose=True, adaptive_mu=False)


# ==============================================================================
# STEP 7 — OPTIMISATION LOOP (interactive, via polyscope)
# ==============================================================================
# The loop function is registered as a polyscope callback.  It is called on
# every UI frame, letting you control the optimisation interactively.
#
# For a headless / script-only run you can replace this section with:
#
#   for i in range(max_iterations):
#       optimizer.get_gradients()
#       optimizer.optimize_step()
#   optimizer.print_report()

def loop(variables):
    """
    Polyscope per-frame callback.

    variables : dict holding shared mutable state between frames
    """
    psim.Text("Running optimization...")

    # Button to (re)start the optimisation
    if psim.Button("Run optimization step"):
        variables["run"] = True

    # Check termination condition
    if variables["it"] > variables["max_iterations"]:
        psim.Text("Optimization complete.")

        # ── Print a text summary of per-term energies ──────────────────────
        optimizer.print_report()

        # ── Retrieve final values from X ───────────────────────────────────
        # unpack(name) returns the variable's slice of X.
        new_vertices = optimizer.unpack("v").reshape(-1, 3)
        faces_now    = variables["mesh"].faces

        # ── Visualise inscribed circles ────────────────────────────────────
        centers, normals_c, radius = compute_circumcircles_quad_mesh(new_vertices, faces_now)
        ps.register_curve_network("Circles_Quad_Mesh", *glyphs.circles(centers, normals_c, radius),
                                  color=(1, 0, 0), radius=0.001)

        variables["run"] = False  # stop further iterations
        variables["it"]  = 0      # reset so the button works again

    # Execute one optimisation step per frame while running
    if variables["run"]:
        variables["it"] += 1

        # get_gradients() assembles the sparse Jacobian J and residual r
        # from all registered energy terms.
        optimizer.get_gradients()

        # optimize_step() solves (J^T J + mu I) dx = -J^T r and updates X.
        optimizer.optimize_step()

        # ── Update the polyscope mesh with the new vertex positions ────────
        new_vertices = optimizer.unpack("v").reshape(-1, 3)
        mesh.vertices = new_vertices           # keep Mesh object in sync
        faces_now     = variables["mesh"].faces

        # ── Colour the mesh by planarity deviation (diagnostic) ────────────
        planarity_values = planarity_measure_quad_mesh(variables["mesh"])
        optimized_mesh   = ps.register_surface_mesh("Optimized mesh", new_vertices, faces_now)
        optimized_mesh.add_scalar_quantity("Planarity", planarity_values,
                                           defined_on="faces")


# Shared state dictionary — avoids global variables in the callback
variables = {
    "optimizer":      optimizer,
    "mesh":           mesh,
    "max_iterations": 40,    # total number of LM steps to run
    "it":             0,
    "run":            False,
}


# ==============================================================================
# STEP 8 — LAUNCH POLYSCOPE VIEWER
# ==============================================================================
ps.init()
ps.remove_all_structures()

# Register the original (un-optimised) mesh for reference
ps.register_surface_mesh("mesh", vertices, faces)

# Attach the callback and open the viewer
ps.set_user_callback(lambda: loop(variables))
ps.show()
