"""
Test: shared_edge_vertices on a 6x6 quad grid.

Picks two edge-adjacent face pairs and colours the two vertices they share
so the result of shared_edge_vertices(fi, fj) is easy to inspect. The pair is
returned in the winding order of face fi.

  fi barycenter → blue sphere
  fj barycenter → yellow sphere
  shared verts  → red spheres
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

def face_idx(row, col):
    """Face index in the (N-1)x(N-1) quad grid."""
    return row * (N - 1) + col

# ── query shared_edge_vertices ───────────────────────────────────────────────
# horizontally adjacent pair (side by side) → shared vertical edge
fi_h = face_idx(2, 2)
fj_h = face_idx(2, 3)
vk_h, vl_h = mesh.shared_edge_vertices(fi_h, fj_h)

# vertically adjacent pair (stacked)        → shared horizontal edge
fi_v = face_idx(2, 2)
fj_v = face_idx(3, 2)
vk_v, vl_v = mesh.shared_edge_vertices(fi_v, fj_v)

print(f"Horizontal pair {fi_h},{fj_h}: shared edge vertices = ({vk_h}, {vl_h})")
print(f"Vertical   pair {fi_v},{fj_v}: shared edge vertices = ({vk_v}, {vl_v})")

assert None not in (vk_h, vl_h), "horizontally adjacent faces should share an edge"
assert None not in (vk_v, vl_v), "vertically adjacent faces should share an edge"

# face barycenters
def face_centroid(fid):
    return vertices[faces[fid]].mean(axis=0)

# ── polyscope visualisation ───────────────────────────────────────────────────
ps.init()

ps_mesh = ps.register_surface_mesh("grid", vertices, faces,
                                   color=(0.85, 0.85, 0.85), edge_width=1.0)

# small z-lift so spheres sit above the mesh
lift = np.array([0, 0, 0.03])

def sphere(name, pts, radius, color):
    pts = np.atleast_2d(pts) + lift
    cloud = ps.register_point_cloud(name, pts, radius=radius)
    cloud.set_color(color)

# horizontal pair
sphere("fi horiz (blue)",   face_centroid(fi_h), 0.030, (0.15, 0.35, 1.0))
sphere("fj horiz (yellow)", face_centroid(fj_h), 0.030, (1.0, 0.85, 0.0))
sphere("vertex right" , vertices[vk_h], 0.025, (1.0, 0.0, 0.15))
sphere("vertex left", vertices[vl_h], 0.025, (0.0, 0.5, 0.1))

# vertical pair
sphere("fi vert (cyan)",   face_centroid(fi_v), 0.030, (0.1, 0.8, 0.8))
sphere("fj vert (purple)", face_centroid(fj_v), 0.030, (0.6, 0.1, 0.8))
sphere("vertex_v right" , vertices[vk_v], 0.025, (0.0, 0., 0.))
sphere("vertex_v left", vertices[vl_v], 0.025, (1.0, 0.15, 0.15))

ps.show()
