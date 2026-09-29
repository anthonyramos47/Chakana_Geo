"""
Test: face_face_adjacency_list on a 6x6 quad grid.

Visualize one face (f_idx) and its adjacent faces and vertices in order,
coloured with a fixed palette: blue, red, green, yellow (cycling if needed).

  picked face     → white sphere at centroid (large)
  adj_face[k]     → palette[k] sphere at centroid
  face vertices   → palette[k] sphere at vertex position
    (vertices of the picked face share the same colour order as adj faces)

The polyscope GUI panel lets you change f_idx interactively.
"""

import sys
import numpy as np
import polyscope as ps
import polyscope.imgui as psim


from hanan.geometry.mesh import Mesh

# ── grid ──────────────────────────────────────────────────────────────────────
N = 6   # N×N vertices → (N-1)×(N-1) quads

xs, ys = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
vertices = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(N * N)])

def vi_idx(row, col):
    return row * N + col

faces = []
for r in range(N - 1):
    for c in range(N - 1):
        faces.append([vi_idx(r, c), vi_idx(r, c + 1),
                      vi_idx(r + 1, c + 1), vi_idx(r + 1, c)])
faces = np.array(faces, dtype=np.int32)
n_faces = len(faces)

mesh = Mesh()
mesh.make_mesh(vertices, faces)

face_face_adj  = mesh.face_face_adjacency_list()   # per-face list of neighbour faces
mesh_faces_vts = mesh.faces                       # per-face vertex lists

# ── palette: blue, red, green, yellow (then cycle) ────────────────────────────
PALETTE = [
    (0.20, 0.47, 1.00),   # blue
    (0.90, 0.18, 0.18),   # red
    (0.18, 0.75, 0.28),   # green
    (0.95, 0.85, 0.10),   # yellow
    (0.75, 0.25, 0.90),   # purple  (fallback if face has >4 neighbours)
    (0.10, 0.85, 0.85),   # cyan
    (1.00, 0.40, 0.70),   # pink
    (1.00, 0.55, 0.10),   # orange
]

def color_for(k):
    return PALETTE[k % len(PALETTE)]

def face_centroid(fid):
    return vertices[faces[fid]].mean(axis=0)

# ── state ─────────────────────────────────────────────────────────────────────
state = {"f_idx": 12}   # default face

LIFT = np.array([0, 0, 0.04])

# ── polyscope helpers ─────────────────────────────────────────────────────────
def sphere(name, pt, radius, color):
    cloud = ps.register_point_cloud(name, np.atleast_2d(pt + LIFT), radius=radius)
    cloud.set_color(color)

def remove_point_clouds_by_prefix(prefix):
    """Remove all previously registered point clouds that start with prefix."""
    # polyscope doesn't expose a list API, so we just re-register (overwrite) them
    # during rebuild; stale ones from a larger previous set are handled by
    # registering an empty/hidden cloud or by using a fixed max budget.
    pass  # handled by always re-registering with the same names

def rebuild(f_idx):
    """Rebuild all overlay point clouds for the chosen face."""

    adj_faces = face_face_adj[f_idx]
    face_verts = list(mesh_faces_vts[f_idx])   # ordered vertices of picked face

    # picked face centroid — white
    sphere("picked_face", face_centroid(f_idx), 0.038, (1.0, 1.0, 1.0))

    # adjacent faces + face vertices share the same colour order
    max_items = max(len(adj_faces), len(face_verts))

    for k in range(max_items):
        col = color_for(k)

        if k < len(adj_faces):
            sphere(f"adj_f[{k}]", face_centroid(adj_faces[k]), 0.026, col)
        else:
            # hide slot if fewer adj faces than vertices
            ps.register_point_cloud(f"adj_f[{k}]",
                                    np.empty((0, 3)), radius=0.001)

        if k < len(face_verts):
            sphere(f"face_v[{k}]", vertices[face_verts[k]], 0.022, col)
        else:
            ps.register_point_cloud(f"face_v[{k}]",
                                    np.empty((0, 3)), radius=0.001)

    # hide any leftover slots from a previous face that had more neighbours
    for k in range(max_items, 8):
        ps.register_point_cloud(f"adj_f[{k}]", np.empty((0, 3)), radius=0.001)
        ps.register_point_cloud(f"face_v[{k}]", np.empty((0, 3)), radius=0.001)

    print(f"\nFace {f_idx}:")
    print(f"  vertices (ordered): {face_verts}")
    print(f"  adj faces:          {adj_faces}")

# ── GUI callback ──────────────────────────────────────────────────────────────
def gui_callback():
    psim.SetNextWindowPos((10, 10), cond=psim.ImGuiCond_FirstUseEver)
    psim.SetNextWindowSize((300, 120), cond=psim.ImGuiCond_FirstUseEver)

    

    changed, new_idx = psim.InputInt("Face index", state["f_idx"])
    if changed:
        new_idx = int(np.clip(new_idx, 0, n_faces - 1))
        if new_idx != state["f_idx"]:
            state["f_idx"] = new_idx
            rebuild(new_idx)

    psim.TextWrapped(f"Total faces: {n_faces}  (0 – {n_faces - 1})")
    psim.TextWrapped(f"Adj faces: {face_face_adj[state['f_idx']]}")

    psim.End()

# ── polyscope init ────────────────────────────────────────────────────────────
ps.init()
ps.register_surface_mesh("grid", vertices, faces,
                          color=(0.3, 0.3, 0.3), edge_color=(1, 1, 1), edge_width=1.5)

rebuild(state["f_idx"])
ps.set_user_callback(gui_callback)
ps.show()
