# Mesh API Reference

Half-edge mesh for 3-D polygonal surfaces.  
Source: `hanan/src/hanan/geometry/mesh.py` · `from hanan.geometry import Mesh`

> **Attribution.** The `Mesh` class is a modified version of the half-edge mesh code
> written by **[Davide Pellis](https://scholar.google.com/citations?user=JnocFM4AAAAJ&hl=en)** in *geometrylab*. Anthony Ramos-Cisneros adapted and
> extended it for hanan; the original design and the core half-edge implementation are
> Davide Pellis's work. geometrylab is also the basis of
> [ArchGeo](https://www.huiwang.me/mkdocs-archgeo/2.about/) by Hui Wang
> ([code](https://github.com/WWmore/DOS)), released under the MIT License; that license
> notice is kept in [`hanan/THIRD_PARTY_NOTICES.md`](../../hanan/THIRD_PARTY_NOTICES.md).

---

## Half-edge layout

Every half-edge is one row of the integer matrix `Mesh.halfedges` (shape `H × 6`):

| Column | Name     | Description |
|--------|----------|-------------|
| 0      | Origin   | Index of the start vertex |
| 1      | Twin     | Index of the opposite half-edge |
| 2      | Face     | Index of the adjacent face (`-1` for boundary half-edges) |
| 3      | Next     | Next half-edge in the face loop |
| 4      | Previous | Previous half-edge in the face loop |
| 5      | Edge     | Unique edge index shared by a half-edge and its twin |

Boundary half-edges are appended after all interior half-edges.  
Their `Face` column is `-1` and their `Twin` points back to the interior half-edge.

---

## Construction

### `make_mesh(vertices, faces)`
Build the half-edge structure from a vertex array and a face list.

- `vertices` — `(V, 3)` float array of vertex coordinates.
- `faces` — list of lists of vertex indices (triangles, quads, or general polygons).

Tries direct construction first; if that fails due to inconsistent orientations it runs
`orient_faces` and retries. Raises `Exception` if the mesh cannot be oriented.

### `orient_faces(vertices_list, faces_list)`
BFS-based face orientation.  Propagates a consistent winding order from face 0 to all
reachable faces.  Returns the re-oriented face list.

### `copy_mesh()`
Return a deep copy of the mesh with independent vertex and half-edge arrays.

### `read_obj_file(file_name)`
Load vertices and faces from a Wavefront `.obj` file.  UV coordinates are stored in
`self._uv` if present.

---

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `V` | `int` | Number of vertices |
| `F` | `int` | Number of faces |
| `E` | `int` | Number of edges |
| `H` | `ndarray (H×6)` | Half-edge matrix (alias for `halfedges`) |
| `BH` | `ndarray` | Boundary half-edge indices |
| `vertices` | `ndarray (V×3)` | Vertex positions (settable) |
| `faces` | `list / ndarray` | Per-face vertex-index lists |
| `face_normals` | `ndarray (F×3)` | Per-face normals (lazy) |
| `vertex_normals` | `ndarray (V×3)` | Per-vertex normals (lazy, settable) |
| `inner_faces` | `ndarray` | Face indices not touching any boundary edge |

---

## Half-edge traversal

All six methods accept either a single integer index or an array of indices and return the
corresponding value(s) directly from the half-edge matrix.

### `he_next(he)`
Next half-edge in the face loop.

**Returns** `int` or `ndarray`.

### `he_prev(he)`
Previous half-edge in the face loop.

**Returns** `int` or `ndarray`.

### `he_twin(he)`
Opposite (twin) half-edge.

**Returns** `int` or `ndarray`.

### `he_origin(he)`
Origin vertex of the half-edge.

**Returns** `int` or `ndarray`.

### `he_face(he)`
Face the half-edge belongs to.  Returns `-1` for boundary half-edges.

**Returns** `int` or `ndarray`.

### `he_edge(he)`
Undirected edge index shared by the half-edge and its twin.

**Returns** `int` or `ndarray`.

**Example**
```python
# from two faces
he   = mesh.halfedge_from_faces(f1, f2)
twin = mesh.he_twin(he)                        # same edge seen from f2

# from two vertices
he   = mesh.halfedge_from_vertices(v1, v2)
dest = mesh.he_origin(mesh.he_next(he))        # == v2

# two faces from an oriented edge (vi is the reference origin)
f0, f1 = mesh.faces_from_edge(vi, vj)         # f0 on vi side, f1 on vj side
```

---

## Topological queries — single element

### `vertex_star(v)`
All vertices directly connected to vertex `v` by an edge.

**Returns** `ndarray` of neighbour vertex indices.

### `vertex_degree(v)`
Number of edges incident on vertex `v` (valence).

**Returns** `int`.

### `face_ring(f)`
Indices of faces sharing an edge with face `f`.  Boundary half-edges are excluded.

**Returns** `ndarray`.

### `face_ring_faces_vertices(f)`
Adjacent faces and the shared vertex pairs for face `f`.  Returns vertices in the winding
order of face `f`.

**Returns** `(adjacent_faces, f_vi, f_vj)` — three lists of equal length.

### `max_min_edge(f)`
Maximum and minimum edge length of face `f`.

**Returns** `(max_length, min_length)` as floats.

### `shared_edge_vertices(fi, fj)`
The two endpoints of the shared edge between adjacent faces `fi` and `fj`, in the winding
order of face `fi`.

**Returns** `(vi, vj)` or `(None, None)` if the faces do not share an edge.

### `halfedge_from_faces(f1, f2)`
Return the half-edge of face `f1` that lies on the shared edge with face `f2`.

- `f1` — face whose half-edge is requested.
- `f2` — the adjacent face on the other side of the edge.

**Returns** `int` half-edge index, or `-1` if the faces do not share an edge.

### `halfedge_from_vertices(v1, v2)`
Return the half-edge whose origin is `v1` and whose destination is `v2`
(i.e. `he_origin(he) == v1` and `he_origin(he_next(he)) == v2`).

- `v1` — origin vertex.
- `v2` — destination vertex.

**Returns** `int` half-edge index, or `-1` if no such half-edge exists.

### `faces_from_edge(vi, vj)`
Return the two faces sharing the edge between vertices `vi` and `vj`.

The ordering is determined by the half-edge whose **origin is `vi`**:

- `f0` — face on the `vi → vj` side.
- `f1` — face on the opposite `vj → vi` side (the twin's face).

For a boundary edge the boundary side is returned as `-1`.  
Returns `(-1, -1)` if the edge does not exist.

- `vi` — origin vertex; defines which half-edge is the reference.
- `vj` — destination vertex.

**Returns** `(f0, f1)` as a tuple of `int`.

```python
f0, f1 = mesh.faces_from_edge(vi, vj)
# f0 is the face whose half-edge runs vi → vj
# f1 is the face on the other side of the same edge
```

---

## Topological queries — global lists

### `vertex_adjacency_list()`
Per-vertex ordered list of neighbouring vertex indices.

**Returns** `list[list[int]]` of length `V`.

### `vertex_face_adjacency_list()`
Per-vertex ordered list of adjacent face indices.

**Returns** `list[list[int]]` of length `V`.

### `face_face_adjacency_list()`
Per-face list of neighbouring face indices (sharing an edge).

**Returns** `list[list[int]]` of length `F`.

### `vertex_multiple_ring_vertices(v, depth=1)`
Vertices reachable from vertex `v` within `depth` edge hops.

**Returns** sorted unique `ndarray`.

---

## Edge queries

### `edge_vertices()`
Start and end vertex index for every edge.

**Returns** `(v1, v2)` each of shape `(E,)`.  Edge `k` spans `v1[k]`–`v2[k]`.

### `edge_faces()`
The two face indices on either side of every edge.  Boundary edges have one entry `-1`.

**Returns** `(f1, f2)` each of shape `(E,)`.

### `edge_opposite_vertices()`
For each edge side, the vertex reached by following `next → next` from that half-edge
(the "opposite" vertex in the local triangle).

**Returns** `(ov1, ov2)` each of shape `(E,)`.

### `edge_vertices_faces()`
Start/end vertices and the two adjacent faces for every interior edge (boundary edges
where either face is `-1` are excluded).

**Returns** `(v1, v2, f1, f2)` each of shape `(E_interior,)`.

### `inner_edges()`
Indices of edges not touching any boundary.

**Returns** `ndarray`.

---

## Boundary queries

### `boundary_vertices()`
Sorted unique indices of vertices on the mesh boundary.

**Returns** `ndarray`.

### `boundary_faces()`
Sorted unique indices of faces adjacent to at least one boundary edge.

**Returns** `ndarray`.

### `inner_vertices()`
Indices of vertices not on the boundary.

**Returns** `ndarray`.

### `corners(corner_tol=0.3)`
Boundary vertices where the boundary direction turns sharply.  A corner is detected when
`cos(turn angle) < corner_tol`.  Lower values detect only very sharp corners.

**Returns** `ndarray` of corner vertex indices.

### `left_right_corners(corner_tol=0.3)`
For each corner vertex, its two adjacent boundary vertices in traversal order.

**Returns** `(prev_vertices, next_vertices)`.

### `boundary_curves()`
Ordered vertex loops along each connected boundary component.

**Returns** `list[list[int]]`.  One list per boundary loop.

### `boundary_split_corners(corner_tol=0.3)`
Boundary curves split at corner vertices into sub-curves between consecutive corners.

**Returns** `list[ndarray]`.

### `boundary_loops()`
Vertex-pair loops for each boundary component, built from raw half-edge connectivity.  
Prefer `boundary_curves()` for most use cases.

**Returns** `list[list[int]]`.

---

## Geometry queries

### `face_barycenters()`
Centroid (arithmetic mean of vertex positions) of each face.

**Returns** `ndarray (F, 3)`.

### `face_areas()`
Area of each face.  Uses the cross-product formula for triangles and a barycentric
subdivision for general polygons.

**Returns** `ndarray (F,)`.

### `vertex_areas()`
Barycentric area associated with each vertex: each vertex receives `(1/n) * A_f` from every
adjacent face `f` with `n` vertices.

**Returns** `ndarray (V,)`.

---

## Discrete differential geometry

### `laplacian_matrix()`
Uniform-weight combinatorial Laplacian matrix.

`L[i, i]` = degree(i),  `L[i, j]` = `-1` for each neighbour, `0` otherwise.

**Returns** `scipy.sparse.coo_matrix` of shape `(V, V)`.

### `mass_matrix()`
Diagonal mass matrix with per-vertex barycentric areas.

**Returns** `scipy.sparse.dia_matrix` of shape `(V, V)`.

### `cotan_matrix()`
Cotangent-weighted Laplacian for triangle meshes.  For edge `(vi, vj)` the weight is
`(cot α + cot β) / 2` where `α` and `β` are the angles opposite that edge.

**Returns** `scipy.sparse.csr_matrix` of shape `(V, V)`.

### `quad_gauss_curvature()`
Angle-deficit Gaussian curvature per vertex for quad meshes.  Fully vectorised.

`K_v = 4 * (2π − Σ θ_v) / area_v`

**Returns** `ndarray (V,)`.

---

## Dual mesh

### `dual_top()`
Combinatorial dual topology: for each interior vertex, the ordered ring of adjacent faces.

**Returns** `list[list[int]]`.

### `dual_mesh()`
Construct the combinatorial dual mesh.  Dual vertices are placed at face barycenters;
dual faces correspond to interior vertices of the primal mesh.

**Returns** a new `Mesh` object.

### `gauss_image()`
Gauss map of the mesh — face normals mapped to the unit sphere with the dual connectivity.

**Returns** `(face_normals (F×3), dual_faces, edges (E_inner×2))`.

---

## Quad-mesh strip extraction

### `quad_face_strips(f_idx)`
Extract the u- and v-direction quad strips through face `f_idx`.  Uses the standard
`next → next → twin` traversal.

**Returns** `(u_faces, v_faces)` — lists of face indices.

### `quad_iso_curves()`
Vertex-index iso-curves of a grid-like quad mesh: walks the vertex grid row by row
from a corner (u-direction), then transposes for the v-direction.

**Returns** `(u_curves, v_curves)` — lists of 1-D int arrays of vertex indices (rows / columns).  
**Raises** `Exception` for non-quad or non-grid meshes.

### `quad_vertex_adjacency()`
Per-vertex neighbours along each grid direction, built from the same vertex grid as
`quad_iso_curves`.

**Returns** `(u_adj, v_adj)` — lists of length `V`; entry `i` holds the 1 (boundary) or
2 (interior) neighbours of vertex `i` in that direction.  
**Raises** `Exception` for non-quad or non-grid meshes.

### `grid_face_matrix()`
Arrange quad-mesh faces into a 2-D grid matrix, starting from a corner vertex.

**Returns** `ndarray (rows, cols)` of face indices.  
**Raises** `Exception` for non-quad or inhomogeneous meshes.

---

## Normal recomputation

### `update_mesh()`
Recompute cached quantities (normals, …) after `vertices` changed — call it after
writing optimizer output back into the mesh.

### `vertex_normals_compute()`
Force recomputation of per-vertex normals (averaged from adjacent face normals).

### `face_normals_compute()`
Force recomputation of per-face normals.  Handles triangles (cross product),
quads (diagonal cross product), and n-gons (averaged edge-triplet cross products).

---

## Internal helpers (prefixed `_`)

These are not part of the public API and may change without notice.

| Method | Description |
|--------|-------------|
| `_make_mesh(vertices, faces)` | Core half-edge builder |
| `_update_dimensions()` | Recompute V, F, E from halfedges |
| `_vertex_normals_compute()` | Internal vertex-normal computation |
| `_face_normals_compute()` | Internal face-normal computation |
| `_vertex_ring_ordered_halfedges()` | Half-edges sorted in per-vertex ring order |
| `_face_ordered_halfedges()` | Half-edges sorted in per-face loop order |
| `_vertex_ring_vertices_iterators()` | Parallel (v, vj) arrays for all half-edges |
| `_vertex_ring_faces_iterators()` | Parallel (v, fj) arrays for interior half-edges |
| `_vertex_ring_faces_list()` | Per-vertex face ring lists |
| `_quad_vertex_grid()` | Corner-anchored vertex grid shared by `quad_iso_curves` / `quad_vertex_adjacency` |

---

## Renamed methods (from previous version)

| Old name | New name | Reason |
|----------|----------|--------|
| `LaplacianMatrix` | `laplacian_matrix` | snake\_case consistency |
| `GaussImage` | `gauss_image` | snake\_case consistency |
| `boundaries` | `boundary_loops` | disambiguate from `boundary_vertices` / `boundary_curves` |
| `edge_oposite_vertices` | `edge_opposite_vertices` | typo fix |
| `vertex_ring_ordered_halfedges` | `_vertex_ring_ordered_halfedges` | internal helper |
| `face_ordered_halfedges` | `_face_ordered_halfedges` | internal helper |
| `vertex_ring_vertices_iterators` | `_vertex_ring_vertices_iterators` | internal helper |
| `vertex_ring_faces_iterators` | `_vertex_ring_faces_iterators` | internal helper |
| `vertex_ring_faces_list` | `_vertex_ring_faces_list` | internal helper |

## Removed

| Method | Reason |
|--------|--------|
| `quad_normals_compute` | Fully superseded by `face_normals_compute` |
| `topology_update` | Thin wrapper around `_update_dimensions`; no callers |
| Jet-fitting block (`localCoord`, `jet_fit`, `compute_curvature_from_jet_fit`, `curvatures`) | Commented out in original; use `igl.principal_curvature` instead |
