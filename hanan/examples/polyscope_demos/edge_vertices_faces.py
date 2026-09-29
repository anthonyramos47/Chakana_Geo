"""
Test: edge_vertices_faces on a 6x6 quad grid.

Visualises one interior edge and colours vi, vj (vertices) and
fi, fj (face barycenters) so the ordering is easy to inspect.

  vi  → red sphere
  vj  → green sphere
  fi  → blue sphere (face i barycenter)
  fj  → yellow sphere (face j barycenter)
"""

import sys
import numpy as np
import polyscope as ps


from hanan.geometry.mesh import Mesh

# ── build a 6×6 quad grid in the XY plane ────────────────────────────────────
N = 6   # grid resolution (N×N vertices → (N-1)×(N-1) quads)

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

# ── query edge_vertices_faces ─────────────────────────────────────────────────
v1, v2, f1, f2 = mesh.edge_vertices_faces()

# pick a central interior edge to inspect (edge index 12 is well inside the grid)
edge_pick = 24
vi_i = int(v1[edge_pick])
vj_i = int(v2[edge_pick])
fi_i = int(f1[edge_pick])
fj_i = int(f2[edge_pick])

print(f"Edge {edge_pick}:  vi={vi_i}  vj={vj_i}  fi={fi_i}  fj={fj_i}")

# face barycenters
def face_centroid(fid):
    return vertices[faces[fid]].mean(axis=0)

# ── polyscope visualisation ───────────────────────────────────────────────────
ps.init()

# mesh
ps_mesh = ps.register_surface_mesh("grid", vertices, faces,
                                   color=(0.85, 0.85, 0.85), transparency=0.4)

# small z-lift so spheres sit above the mesh
lift = np.array([0, 0, 0.03])

def sphere(name, pt, radius, color):
    c = np.atleast_2d(pt + lift)
    cloud = ps.register_point_cloud(name, c, radius=radius)
    cloud.set_color(color)

sphere("vi (red)",   vertices[vi_i], 0.025, (1.0, 0.15, 0.15))
sphere("vj (green)", vertices[vj_i], 0.025, (0.15, 0.85, 0.15))
sphere("fi (blue)",  face_centroid(fi_i), 0.030, (0.15, 0.35, 1.0))
sphere("fj (yellow)",face_centroid(fj_i), 0.030, (1.0, 0.85, 0.0))

# edge line
edge_pts = np.array([vertices[vi_i] + lift, vertices[vj_i] + lift])
curve = ps.register_curve_network("edge", edge_pts,
                                  np.array([[0, 1]]), color=(1.0, 1.0, 1.0))
curve.set_radius(0.008)

ps.show()
