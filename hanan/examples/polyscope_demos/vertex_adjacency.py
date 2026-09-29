"""
Test: vertex_adjacency_list and vertex_face_adjacency_list on a 6x6 quad grid.

Pick one vertex with VERTEX_PICK and the script colours its neighbours and
adjacent faces using the same palette so index 0 is blue, index 1 is orange, …

  picked vertex → white sphere (large)
  adj_vertex[k] → colour[k] sphere
  adj_face[k]   → colour[k] sphere at face centroid  (same colour as adj_vertex[k])
"""

import sys
import numpy as np
import polyscope as ps


from hanan.geometry.mesh import Mesh

# ── grid resolution ───────────────────────────────────────────────────────────
N = 6   # N×N vertices → (N-1)×(N-1) quads

VERTEX_PICK = 14  # change this to inspect a different vertex

# ── build mesh ────────────────────────────────────────────────────────────────
xs, ys = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
vertices = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(N * N)])

def vi_idx(row, col):
    return row * N + col

faces = []
for r in range(N - 1):
    for c in range(N - 1):
        faces.append([vi_idx(r, c), vi_idx(r, c + 1),
                      vi_idx(r + 1, c + 1), vi_idx(r + 1, c)])

mesh = Mesh()
mesh.make_mesh(vertices, faces)

# ── query adjacency lists ─────────────────────────────────────────────────────
adj_verts = mesh.vertex_adjacency_list()
adj_faces = mesh.vertex_face_adjacency_list()

nbr_verts = adj_verts[VERTEX_PICK]
nbr_faces = adj_faces[VERTEX_PICK]

print(f"Vertex {VERTEX_PICK}:")
print(f"  adj vertices ({len(nbr_verts)}): {nbr_verts}")
print(f"  adj faces    ({len(nbr_faces)}): {nbr_faces}")

# ── colour palette (one colour per ring index) ────────────────────────────────
# Generates up to 8 distinct hues; extend if needed.
PALETTE = [
    (0.20, 0.47, 1.00),   # 0 blue
    (1.00, 0.55, 0.10),   # 1 orange
    (0.18, 0.75, 0.28),   # 2 green
    (0.90, 0.18, 0.18),   # 3 red
    (0.75, 0.25, 0.90),   # 4 purple
    (0.95, 0.85, 0.10),   # 5 yellow
    (0.10, 0.85, 0.85),   # 6 cyan
    (1.00, 0.40, 0.70),   # 7 pink
]

def color_for(k):
    return PALETTE[k % len(PALETTE)]

def face_centroid(fid):
    return np.array(vertices[faces[fid]]).mean(axis=0)

# ── polyscope setup ───────────────────────────────────────────────────────────
ps.init()

ps_mesh = ps.register_surface_mesh("grid", vertices, faces,
                                   color=(0.85, 0.85, 0.85), transparency=0.4)

lift = np.array([0, 0, 0.04])

def sphere(name, pt, radius, color):
    cloud = ps.register_point_cloud(name, np.atleast_2d(pt + lift), radius=radius)
    cloud.set_color(color)

# picked vertex — white, larger
sphere(f"picked v{VERTEX_PICK}", vertices[VERTEX_PICK], 0.035, (1.0, 1.0, 1.0))

# adjacent vertices
for k, v in enumerate(nbr_verts):
    col = color_for(k)
    sphere(f"adj_v[{k}] = v{v}", vertices[v], 0.022, col)
    print(f"  adj_v[{k}] = vertex {v}  colour {col}")

# adjacent faces (same colour index as the corresponding vertex)
for k, f in enumerate(nbr_faces):
    col = color_for(k)
    sphere(f"adj_f[{k}] = f{f}", face_centroid(f), 0.028, col)
    print(f"  adj_f[{k}] = face   {f}  colour {col}")

# edges from picked vertex to each neighbour
edge_pts  = np.array([vertices[VERTEX_PICK] + lift] +
                     [vertices[v] + lift for v in nbr_verts])
edge_ends = np.array([[0, i + 1] for i in range(len(nbr_verts))])
spokes = ps.register_curve_network("spokes", edge_pts, edge_ends,
                                   color=(0.7, 0.7, 0.7))
spokes.set_radius(0.005)

ps.show()
