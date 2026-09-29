"""Half-edge Mesh: construction and topological queries on a quad grid."""

import numpy as np
import pytest

from hanan.geometry.mesh import Mesh

N = 6   # N×N vertices → (N-1)×(N-1) quads


def vid(r, c):
    return r * N + c


def fid(r, c):
    return r * (N - 1) + c


@pytest.fixture
def grid():
    xs, ys = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
    V = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(N * N)])
    F = [[vid(r, c), vid(r, c + 1), vid(r + 1, c + 1), vid(r + 1, c)]
         for r in range(N - 1) for c in range(N - 1)]
    mesh = Mesh()
    mesh.make_mesh(V, F)
    return mesh


def test_counts_and_euler_characteristic(grid):
    n_edges = 2 * N * (N - 1)
    assert grid.V == N * N
    assert grid.F == (N - 1) ** 2
    assert len(grid.edge_vertices()[0]) == n_edges
    assert grid.V - n_edges + grid.F == 1          # a disk


def test_boundary_and_inner_vertices(grid):
    boundary = set(grid.boundary_vertices().tolist())
    assert len(boundary) == 4 * (N - 1)
    assert vid(0, 0) in boundary and vid(2, 2) not in boundary
    assert set(grid.inner_vertices().tolist()) == set(range(N * N)) - boundary


def test_vertex_adjacency_is_symmetric_with_grid_degrees(grid):
    adj = grid.vertex_adjacency_list()
    for v, nbrs in enumerate(adj):
        for u in nbrs:
            assert v in adj[u]
    assert sorted(adj[vid(2, 2)]) == sorted([vid(1, 2), vid(3, 2), vid(2, 1), vid(2, 3)])
    assert len(adj[vid(0, 0)]) == 2          # corner
    assert len(adj[vid(0, 2)]) == 3          # boundary edge


def test_face_adjacency(grid):
    adj = grid.face_face_adjacency_list()
    assert sorted(adj[fid(2, 2)]) == sorted([fid(1, 2), fid(3, 2), fid(2, 1), fid(2, 3)])
    assert len(adj[fid(0, 0)]) == 2


@pytest.mark.parametrize("fi, fj", [((2, 2), (2, 3)), ((2, 2), (3, 2))])
def test_shared_edge_vertices(grid, fi, fj):
    vk, vl = grid.shared_edge_vertices(fid(*fi), fid(*fj))
    F = grid.faces
    shared = set(F[fid(*fi)]) & set(F[fid(*fj)])
    assert {vk, vl} == shared


def test_interior_edges_have_two_faces(grid):
    v1, v2, f1, f2 = grid.edge_vertices_faces()
    assert len(v1) == 2 * (N - 1) * (N - 2)
    assert np.all(f1 >= 0) and np.all(f2 >= 0) and np.all(f1 != f2)
