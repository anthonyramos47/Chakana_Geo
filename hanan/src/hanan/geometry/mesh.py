"""
Mesh Data Structure
===================

Half-edge based representation of a 3D polygonal mesh.

Half-edge layout (one row per half-edge):

    col 0  Origin   — index of the start vertex
    col 1  Twin     — index of the opposite half-edge (-1 before boundary half-edges are added)
    col 2  Face     — index of the adjacent face (-1 for boundary half-edges)
    col 3  Next     — index of the next half-edge in the face loop
    col 4  Previous — index of the previous half-edge in the face loop
    col 5  Edge     — unique edge index shared by a half-edge and its twin

Boundary half-edges are appended after all interior half-edges.
Their Face column is -1 and their Twin points back to the interior half-edge.

Public API summary
------------------

Construction:
    make_mesh(vertices, faces)      Build from vertex positions and face lists.
    copy_mesh()                     Return a deep copy.

Properties:
    V, F, E                         Vertex / face / edge counts.
    H / halfedges                   (H, 6) half-edge matrix.
    vertices                        (V, 3) vertex positions.
    faces                           List of per-face vertex-index arrays.
    vertex_normals                  (V, 3) per-vertex normals (lazy).
    face_normals                    (F, 3) per-face normals (lazy).
    inner_faces                     Faces not touching the boundary.

Half-edge traversal (accept scalar or array index):
    he_next(he)                     Next half-edge in the face loop.
    he_prev(he)                     Previous half-edge in the face loop.
    he_twin(he)                     Opposite (twin) half-edge.
    he_origin(he)                   Origin vertex of a half-edge.
    he_face(he)                     Face of a half-edge (-1 if boundary).
    he_edge(he)                     Undirected edge index of a half-edge.

Topological queries — single element:
    vertex_star(v)                  Neighbour vertices of v.
    vertex_degree(v)                Valence of v.
    face_ring(f)                    Faces sharing an edge with f.
    face_ring_faces_vertices(f)     Adjacent faces and their shared vertex pairs.
    max_min_edge(f)                 Max/min edge lengths of face f.
    shared_edge_vertices(fi, fj)    Endpoints of the shared edge between two faces.
    halfedge_from_faces(f1, f2)     Half-edge of f1 on the shared edge with f2.
    halfedge_from_vertices(v1, v2)  Half-edge with origin v1 and destination v2.
    faces_from_edge(vi, vj)         f0, f1 of the edge vi→vj (f0 on the vi side).

Topological queries — global lists:
    vertex_adjacency_list()         Per-vertex neighbour vertex lists.
    vertex_face_adjacency_list()    Per-vertex adjacent face lists.
    face_face_adjacency_list()      Per-face adjacent face lists.
    vertex_multiple_ring_vertices(v, depth)
                                    Vertices within *depth* hops of v.

Edge queries:
    edge_vertices()                 Start/end vertices per edge.
    edge_faces()                    Two faces per edge.
    edge_vertices_faces()           Vertices and faces for interior edges.
    edge_opposite_vertices()        Opposite vertices per edge side.
    inner_edges()                   Indices of non-boundary edges.

Boundary queries:
    boundary_vertices()             Vertices on the boundary.
    boundary_faces()                Faces touching the boundary.
    inner_vertices()                Interior (non-boundary) vertices.
    corners(corner_tol)             Boundary vertices with a sharp turn.
    boundary_curves()               Ordered vertex loops per boundary component.
    boundary_split_corners(corner_tol)
                                    Boundary curves split at corners.

Geometry:
    face_barycenters()              (F, 3) face centroids.
    face_areas()                    (F,) face areas.
    vertex_areas()                  (V,) barycentric vertex areas.

Discrete differential geometry:
    laplacian_matrix()              Uniform combinatorial Laplacian (sparse).
    mass_matrix()                   Diagonal mass matrix with vertex areas.
    cotan_matrix()                  Cotangent-weighted Laplacian (triangles).
    quad_gauss_curvature()          Angle-deficit Gaussian curvature (quads).

Dual mesh:
    dual_top()                      Combinatorial dual topology.
    dual_mesh()                     Dual Mesh object.
    gauss_image()                   Gauss map (face normals on S²).

Quad-mesh utilities:
    quad_face_strips(f_idx)         U/V strip through a quad face.
    grid_face_matrix()              Arrange quad faces into a 2-D grid.

I/O:
    read_obj_file(file_name)        Load from a Wavefront OBJ file.

Author: Davide Pellis (original), Anthony Ramos-Cisneros (extensions)

Derived from the MIT-licensed half-edge mesh of Davide Pellis's geometrylab (as distributed
in ArchGeo, https://github.com/WWmore/DOS); see hanan/THIRD_PARTY_NOTICES.md.
"""
__author__ = "Anthony Ramos-Cisneros"

import copy

import numpy as np
import scipy as sp
from scipy.sparse import coo_matrix

from hanan.geometry.algebraic import (
    vec_dot,
    unit,
    np_pop,
    angle_vectors,
)


# =============================================================================
# Mesh class
# =============================================================================

class Mesh:
    """Half-edge mesh for 3-D polygonal surfaces."""

    # -------------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------------

    def __init__(self):
        self._V = 0               # vertex count
        self._F = 0               # face count
        self._E = 0               # edge count
        self.halfedges = None     # (H, 6) int64 half-edge matrix
        self._vertices = None     # (V, 3) float64 vertex positions
        self._boundaryhalfedges = None
        self._vertex_normals = None
        self._face_normals = None

    def make_mesh(self, vertices, faces):
        """Build the half-edge structure from vertex positions and face lists.

        Tries direct construction first; if that fails (inconsistent face
        orientations) it runs ``orient_faces`` and tries again.

        Args:
            vertices (array-like): (V, 3) vertex coordinates.
            faces (list[list[int]]): Face vertex index lists (triangles, quads,
                or general polygons).

        Raises:
            Exception: If the mesh cannot be oriented consistently.
        """
        self._face_grid_cache = None   # invalidated by any topology change
        try:
            self._make_mesh(vertices, faces)
        except Exception:
            try:
                faces = self.orient_faces(vertices, faces)
                self._make_mesh(vertices, faces)
                print("Faces were oriented")
            except Exception:
                raise Exception("Mesh not orientable")
        print(self)

    def _make_mesh(self, vertices, faces):
        """Internal builder — assembles the half-edge matrix from V/F arrays."""
        vertices = np.array(vertices, dtype=np.float64)
        self._vertices = vertices
        self._V = vertices.shape[0]
        self._F = len(faces)

        origin     = []
        twin_i     = []   # twin source vertex  (used to look up the paired half-edge)
        twin_j     = []   # twin target vertex
        face_idxs  = []
        nxt        = []
        prev       = []

        h = 0  # running half-edge counter
        for f in range(self.F):
            n = len(faces[f])

            # First half-edge of the face
            origin.append(faces[f][0])
            face_idxs.append(f)
            nxt.append(h + 1)
            prev.append(h + n - 1)
            twin_i.append(faces[f][1])
            twin_j.append(faces[f][0])
            h += 1

            # Middle half-edges
            for i in range(1, n - 1):
                origin.append(faces[f][i])
                face_idxs.append(f)
                nxt.append(h + 1)
                prev.append(h - 1)
                twin_i.append(faces[f][i + 1])
                twin_j.append(faces[f][i])
                h += 1

            # Last half-edge of the face
            origin.append(faces[f][n - 1])
            face_idxs.append(f)
            nxt.append(h - n + 1)
            prev.append(h - 1)
            twin_i.append(faces[f][0])
            twin_j.append(faces[f][n - 1])
            h += 1

        # Build twin lookup via sparse matrix: twin[i, j] = index+1 of the
        # half-edge whose origin is i and whose next's origin is j.
        twin = coo_matrix(
            (np.arange(h) + 1, (twin_i, twin_j)),
            shape=(self.V, self.V)
        ).tocsc()

        H = np.zeros((h, 6), dtype=np.int64)
        H[:, 0] = origin
        H[:, 2] = face_idxs
        H[:, 3] = nxt
        H[:, 4] = prev
        H[:, 1] = twin[origin, H[H[:, 3], 0]] - 1  # twin column

        # ---- append boundary half-edges for unpaired interior half-edges ----
        b = np.where(H[:, 1] == -1)[0]   # interior half-edges without a twin
        boundary = H[b, :].copy()
        # boundary half-edge: origin is the *destination* of the interior he
        boundary[:, 0] = H[H[b, 3], 0]
        boundary[:, 2] = -1      # no face
        boundary[:, 1] = b       # its twin is the interior he

        B = len(boundary)
        if B > 0:
            Bh    = np.arange(h, h + B)
            zeros = np.zeros(B, dtype=np.int8)

            H[b, 1] = Bh  # complete the twin link from the interior side

            # Build prev for boundary half-edges
            dic = coo_matrix(
                (Bh, (H[b, 0], zeros)), shape=(self.V, 1)
            ).tocsc()
            boundary[:, 4] = dic[boundary[:, 0], zeros]

            # Build next for boundary half-edges
            next_origins = boundary[boundary[:, 4] - h, 0]
            dic = coo_matrix(
                (Bh, (next_origins, zeros)), shape=(self.V, 1)
            ).tocsc()
            boundary[:, 3] = dic[boundary[:, 0], zeros]

            H = np.vstack((H, boundary))

        # ---- assign unique edge indices ------------------------------------
        # Edge index = min(half-edge index, its twin's index)
        aux = H[:, (4, 1)].copy()
        aux[:, 0] = np.arange(H.shape[0])
        m  = np.amin(aux, axis=1)
        u  = np.unique(m)
        imap       = np.arange(np.max(u) + 1, dtype=np.int64)
        imap[u]    = np.arange(u.shape[0], dtype=np.int64)
        H[:, 5]    = imap[m]

        self.halfedges = H
        self._E = int(H.shape[0] / 2)
        self._update_dimensions()

    def orient_faces(self, vertices_list, faces_list):
        """Make face orientations consistent across the mesh.

        Uses a BFS-like propagation: starts from face 0 and flips neighbours
        that are inconsistently oriented.

        Args:
            vertices_list: Vertex positions (unused, kept for API symmetry).
            faces_list (list[list[int]]): Face vertex index lists.

        Returns:
            list[list[int]]: Re-oriented face list.
        """
        F = len(faces_list)
        V = len(vertices_list)

        fmap         = -np.ones((V, V), dtype=np.int32)
        inconsistent = np.zeros((V, V), dtype=bool)
        flipped      = np.zeros(F, dtype=bool)
        oriented     = np.zeros(F, dtype=bool)
        oriented_faces = copy.deepcopy(faces_list)

        for f in range(F):
            face = faces_list[f]
            for j in range(len(face)):
                v0, v1 = face[j - 1], face[j]
                if fmap[v0, v1] == -1:
                    fmap[v0, v1] = f
                else:
                    fmap[v1, v0] = f
                    inconsistent[v0, v1] = True
                    inconsistent[v1, v0] = True

        ring = [0]
        oriented[0] = True
        i = 1

        while ring:
            next_ring = []
            for f in ring:
                face = faces_list[f]
                for j in range(len(face)):
                    v0, v1 = face[j - 1], face[j]
                    if fmap[v0, v1] == f:
                        v2, v3 = v1, v0
                    else:
                        v2, v3 = v0, v1

                    flip = (inconsistent[v2, v3] and not flipped[f]) or \
                           (not inconsistent[v2, v3] and flipped[f])

                    fi = fmap[v2, v3]
                    if fi != -1 and not oriented[fi]:
                        if fi not in next_ring:
                            next_ring.append(fi)
                        if flip:
                            oriented_faces[fi].reverse()
                            flipped[fi] = True
                        i += 1
                        oriented[fi] = True
                        if i == F:
                            return oriented_faces

            ring = next_ring
            if not ring:
                unoriented = np.where(~oriented)[0]
                if unoriented.size:
                    ring = [unoriented[0]]
                else:
                    return oriented_faces

        return oriented_faces

    def copy_mesh(self):
        """Return a deep copy of this mesh."""
        m = Mesh()
        m._vertices  = self._vertices.copy()
        m.halfedges  = self.halfedges.copy()
        m._V = self._V
        m._F = self._F
        m._E = self._E
        return m

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def V(self):
        """Number of vertices."""
        return self._V

    @property
    def F(self):
        """Number of faces."""
        return self._F

    @property
    def E(self):
        """Number of edges."""
        return self._E

    @property
    def H(self):
        """Half-edge matrix (alias for ``halfedges``)."""
        return self.halfedges

    @H.setter
    def H(self, halfedges):
        halfedges = np.asarray(halfedges, dtype=np.int64)
        assert halfedges.ndim == 2 and halfedges.shape[1] == 6
        self.halfedges = halfedges
        self._update_dimensions()

    @property
    def BH(self):
        """Boundary half-edge indices."""
        return self._boundaryhalfedges

    @property
    def vertices(self):
        """(V, 3) vertex position array."""
        return self._vertices

    @vertices.setter
    def vertices(self, v):
        v = np.asarray(v, dtype=np.float64)
        assert v.ndim == 2, "vertices must be (V, 3)"
        self._vertices = v
        self._update_dimensions()

    @property
    def faces(self):
        """List of face vertex-index arrays, one per face."""
        H   = self.halfedges
        idx = np.where(H[:, 2] != -1)[0]
        f   = H[idx, 2]
        vs  = H[idx, 0]

        faces = [[] for _ in range(self.F)]
        for i in range(len(f)):
            faces[f[i]].append(vs[i])

        try:
            faces = np.array(faces, dtype=np.int32)
        except Exception:
            pass
        return faces

    @property
    def vertex_normals(self):
        """(V, 3) per-vertex normals (lazy, computed on first access)."""
        if self._vertex_normals is None:
            self._vertex_normals_compute()
        return self._vertex_normals

    @vertex_normals.setter
    def vertex_normals(self, normals):
        normals = np.asarray(normals, dtype=np.float64)
        assert normals.ndim == 2 and normals.shape[1] == 3
        self._vertex_normals = normals

    def update_mesh(self):
        """Recompute cached properties after vertex positions have changed."""
        self._vertex_normals_compute()
        self._face_normals_compute()

    @property
    def face_normals(self):
        """(F, 3) per-face normals (lazy, computed on first access)."""
        if self._face_normals is None:
            self._face_normals_compute()
        return self._face_normals

    @property
    def inner_faces(self):
        """Indices of faces that do not touch any boundary edge."""
        return np.delete(np.arange(self.F), self.boundary_faces())

    def __str__(self):
        return "Mesh |V|={}, |F|={}, |E|={}".format(self.V, self.F, self.E)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _update_dimensions(self):
        """Recompute V, F, E counts from the half-edge matrix."""
        H = self.halfedges
        self._V = int(np.amax(H[:, 0])) + 1
        self._F = int(np.amax(H[:, 2])) + 1
        self._E = int(np.amax(H[:, 5])) + 1

    # -------------------------------------------------------------------------
    # Normal computation
    # -------------------------------------------------------------------------

    def _vertex_normals_compute(self):
        """Compute per-vertex normals as the average of adjacent face normals."""
        fn  = self.face_normals
        vfa = self.vertex_face_adjacency_list()
        normals = np.zeros((self.V, 3), dtype=np.float64)
        for i in range(self.V):
            n = np.sum(fn[vfa[i]], axis=0)
            n = unit(n)
            if np.linalg.norm(n) == 0:
                n = np.array([0., 0., 1.])
            normals[i] = n
        self._vertex_normals = normals

    def _face_normals_compute(self):
        """Compute per-face normals for triangles, quads, and general n-gons.

        - Triangles : cross product of two edges.
        - Quads     : cross product of the two diagonals.
        - n-gons    : average of cross products of consecutive edge triplets.
        """
        fac_normals = np.zeros((self.F, 3))
        faces = self.faces

        face_sizes  = np.array([len(f) for f in faces])
        tri_idx     = np.where(face_sizes == 3)[0]
        quad_idx    = np.where(face_sizes == 4)[0]
        ngon_idx    = np.where(face_sizes  > 4)[0]

        # `faces` is a ragged container (plain list for mixed-degree meshes), so
        # it cannot be fancy-indexed with an array — gather the rows explicitly.
        def _gather(idx):
            return np.asarray([faces[i] for i in idx], dtype=np.intp)

        if tri_idx.size:
            F3  = _gather(tri_idx)
            v0, v1, v2 = self.vertices[F3[:, 0]], self.vertices[F3[:, 1]], self.vertices[F3[:, 2]]
            fac_normals[tri_idx] = unit(np.cross(v1 - v0, v2 - v0))

        if quad_idx.size:
            F4  = _gather(quad_idx)
            v0  = self.vertices[F4[:, 0]]
            v1  = self.vertices[F4[:, 1]]
            v2  = self.vertices[F4[:, 2]]
            v3  = self.vertices[F4[:, 3]]
            fac_normals[quad_idx] = unit(np.cross(v2 - v0, v1 - v3))

        for f in ngon_idx:
            verts = faces[f]
            n = np.zeros(3)
            for i in range(len(verts)):
                v0 = self.vertices[verts[i]]
                v1 = self.vertices[verts[(i + 1) % len(verts)]]
                v2 = self.vertices[verts[(i + 2) % len(verts)]]
                n += unit(np.cross(v1 - v0, v2 - v0))
            fac_normals[f] = unit(n)

        self._face_normals = fac_normals

    # Public aliases kept for callers that used the old names
    def vertex_normals_compute(self):
        """Recompute and cache per-vertex normals."""
        self._vertex_normals_compute()

    def face_normals_compute(self):
        """Recompute and cache per-face normals."""
        self._face_normals_compute()

    # -------------------------------------------------------------------------
    # Half-edge traversal
    # -------------------------------------------------------------------------

    def he_next(self, he):
        """Next half-edge in the face loop of *he*.

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Next half-edge index/indices.
        """
        return self.halfedges[he, 3]

    def he_prev(self, he):
        """Previous half-edge in the face loop of *he*.

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Previous half-edge index/indices.
        """
        return self.halfedges[he, 4]

    def he_twin(self, he):
        """Twin (opposite) half-edge of *he*.

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Twin half-edge index/indices.
        """
        return self.halfedges[he, 1]

    def he_origin(self, he):
        """Origin vertex of half-edge *he*.

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Vertex index/indices.
        """
        return self.halfedges[he, 0]

    def he_face(self, he):
        """Face of half-edge *he* (-1 for boundary half-edges).

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Face index/indices.
        """
        return self.halfedges[he, 2]

    def he_edge(self, he):
        """Undirected edge index of half-edge *he*.

        Args:
            he (int | array-like): Half-edge index or array of indices.

        Returns:
            int or np.ndarray: Edge index/indices.
        """
        return self.halfedges[he, 5]

    # -------------------------------------------------------------------------
    # Topological queries — single element
    # -------------------------------------------------------------------------

    def vertex_star(self, v):
        """Indices of all vertices directly connected to vertex *v* by an edge.

        Args:
            v (int): Vertex index.

        Returns:
            np.ndarray: Neighbour vertex indices.
        """
        H  = self.halfedges
        hv = np.where(H[:, 0] == v)
        return H[H[hv, 1], 0][0]

    def vertex_degree(self, v):
        """Number of edges incident on vertex *v*.

        Args:
            v (int): Vertex index.

        Returns:
            int: Vertex valence.
        """
        H = self.halfedges
        return int(np.sum(H[:, 0] == v))

    def face_ring(self, f):
        """Indices of faces sharing an edge with face *f*.

        Args:
            f (int): Face index.

        Returns:
            np.ndarray: Adjacent face indices (boundary half-edges excluded).
        """
        H  = self.halfedges
        hf = np.where(H[:, 2] == f)[0]
        fs = H[H[hf, 1], 2]
        return fs[fs != -1]

    def face_ring_faces_vertices(self, f):
        """Adjacent faces and the shared vertex pairs for face *f*.

        For each neighbour face, returns the two vertices that form the
        shared edge (in the winding order of face *f*).

        Args:
            f (int): Face index.

        Returns:
            tuple:
                adjacent_faces (list[int]): Neighbouring face indices.
                f_vi (list[int]):  Origin vertex of the shared half-edge in *f*.
                f_vj (list[int]):  Destination vertex of the shared half-edge.
        """
        H          = self.halfedges
        he_origins = H[H[:, 2] == f, 0]  # origin vertices of half-edges in f

        adjacent_faces = []
        f_vi = []
        f_vj = []
        for he in np.where(H[:, 2] == f)[0]:
            twin = H[he, 1]
            adj  = H[twin, 2]
            if adj != -1:
                adjacent_faces.append(adj)
                f_vi.append(H[he,  0])
                f_vj.append(H[H[he, 3], 0])

        return adjacent_faces, f_vi, f_vj

    def max_min_edge(self, f):
        """Maximum and minimum edge lengths of face *f*.

        Args:
            f (int): Face index.

        Returns:
            tuple: (max_length, min_length)
        """
        H      = self.halfedges
        hf     = np.where(H[:, 2] == f)[0]
        edges  = self.vertices[H[H[hf, 3], 0]] - self.vertices[H[hf, 0]]
        lengths = np.linalg.norm(edges, axis=1)
        return float(np.max(lengths)), float(np.min(lengths))

    def shared_edge_vertices(self, fi, fj):
        """The two endpoints of the shared edge between adjacent faces *fi* and *fj*.

        Returns the vertices in the winding order of face *fi*.

        Args:
            fi (int): First face index.
            fj (int): Second face index.

        Returns:
            tuple: (vi, vj) vertex indices, or (None, None) if faces do not share an edge.
        """
        H     = self.halfedges
        hf_i  = np.where(H[:, 2] == fi)[0]
        match = np.where(H[H[hf_i, 1], 2] == fj)[0]
        if match.size:
            he = hf_i[match[0]]
            return int(H[he, 0]), int(H[H[he, 1], 0])
        return None, None

    def halfedge_from_faces(self, f1, f2):
        """Return the index of the half-edge of face *f1* on the shared edge with *f2*.

        Args:
            f1 (int): Face whose half-edge is requested.
            f2 (int): The adjacent face on the other side of the edge.

        Returns:
            int: Half-edge index, or -1 if the faces do not share an edge.
        """
        H = self.halfedges
        candidates = np.where(H[:, 2] == f1)[0]
        for he in candidates:
            if H[H[he, 1], 2] == f2:
                return int(he)
        return -1

    def halfedge_from_vertices(self, v1, v2):
        """Return the half-edge whose origin is *v1* and whose destination is *v2*.

        Args:
            v1 (int): Origin vertex.
            v2 (int): Destination vertex (i.e. origin of the next half-edge).

        Returns:
            int: Half-edge index, or -1 if no such half-edge exists.
        """
        H = self.halfedges
        candidates = np.where(H[:, 0] == v1)[0]
        for he in candidates:
            if H[H[he, 3], 0] == v2:
                return int(he)
        return -1

    def faces_from_edge(self, vi, vj):
        """Return the two faces sharing the edge between vertices *vi* and *vj*.

        The ordering is determined by the half-edge whose **origin is vi**:
        - ``f0`` is the face of that half-edge (vi → vj side).
        - ``f1`` is the face of its twin (vj → vi side).

        For a boundary edge, the boundary side is returned as -1.

        Args:
            vi (int): Origin vertex that defines which half-edge is the reference.
            vj (int): Destination vertex.

        Returns:
            tuple: (f0, f1) where *f0* is the face on the vi→vj side and *f1*
            is the face on the opposite (vj→vi) side.  Returns (-1, -1) if the
            edge does not exist.
        """
        H  = self.halfedges
        he = self.halfedge_from_vertices(vi, vj)
        if he == -1:
            return -1, -1
        f0 = int(H[he,        2])
        f1 = int(H[H[he, 1],  2])
        return f0, f1

    def edge_vertices_faces(self):
        """Start/end vertices and adjacent faces for every interior edge.

        Like ``edge_vertices`` and ``edge_faces`` combined, but boundary edges
        (where f1 or f2 is -1) are excluded.

        Returns:
            tuple: (v1, v2, f1, f2) each of shape (E_interior,).
        """
        H    = self.halfedges
        idx  = np.argsort(H[:, 5])
        v    = H[idx, 0]
        f    = H[idx, 2]
        v1, v2 = v[0::2], v[1::2]
        f1, f2 = f[0::2], f[1::2]
        interior = (f1 != -1) & (f2 != -1)
        return v1[interior], v2[interior], f1[interior], f2[interior]

    # -------------------------------------------------------------------------
    # Topological queries — global lists
    # -------------------------------------------------------------------------

    def vertex_adjacency_list(self):
        """Per-vertex list of neighbouring vertex indices (in ring order).

        Returns:
            list[list[int]]: ``adjacency[v]`` contains the neighbours of vertex *v*
            ordered by the half-edge ring.
        """
        v, vi = self._vertex_ring_vertices_iterators(order=True)
        adjacency = [[] for _ in range(self.V)]
        for i in range(len(v)):
            adjacency[v[i]].append(vi[i])
        return adjacency

    def vertex_face_adjacency_list(self):
        """Per-vertex list of adjacent face indices (in ring order).

        Returns:
            list[list[int]]: ``adjacency[v]`` contains the faces incident to vertex *v*.
        """
        H       = self.halfedges
        ord_idx = self._vertex_ring_ordered_halfedges()
        vs      = H[ord_idx, 0]
        fs      = H[ord_idx, 2]

        adjacency = [[] for _ in range(self.V)]
        for i in range(len(vs)):
            if fs[i] != -1:
                adjacency[vs[i]].append(fs[i])
        return adjacency

    def face_face_adjacency_list(self):
        """Per-face list of neighbouring face indices (in half-edge order).

        Returns:
            list[list[int]]: ``adjacency[f]`` contains faces sharing an edge with *f*.
        """
        H       = self.halfedges
        ord_idx = self._face_ordered_halfedges()
        fs      = H[ord_idx, 2]
        fs_n    = H[H[ord_idx, 1], 2]

        adjacency = [[] for _ in range(self.F)]
        for i in range(len(fs)):
            if fs_n[i] != -1:
                adjacency[fs[i]].append(fs_n[i])
        return adjacency

    def vertex_multiple_ring_vertices(self, v, depth=1):
        """Vertices reachable from *v* within *depth* edge hops.

        Args:
            v (int):     Source vertex.
            depth (int): Number of edge hops.

        Returns:
            np.ndarray: Sorted unique vertex indices within the *depth*-ring.
        """
        vi, vj = self._vertex_ring_vertices_iterators()
        ring   = np.array([], dtype='i')
        search = np.array([v], dtype='i')

        for _ in range(int(depth)):
            vring = np.array([], dtype='i')
            for s in search:
                vring = np.hstack((vj[vi == s], vring))
            vring  = np.unique(vring)
            vring  = vring[~np.isin(vring, ring)]
            search = vring
            ring   = np.hstack((ring, vring))
            if len(ring) == self.V:
                return ring

        return np.unique(ring)

    # -------------------------------------------------------------------------
    # Edge queries
    # -------------------------------------------------------------------------

    def edge_vertices(self):
        """Start and end vertex index for every edge.

        Returns:
            tuple: (v1, v2) each of shape (E,); edge *k* spans ``v1[k]``–``v2[k]``.
        """
        H  = self.halfedges
        v  = H[np.argsort(H[:, 5]), 0]
        return v[0::2], v[1::2]

    def edge_faces(self):
        """The two face indices on either side of every edge.

        For boundary edges one entry is -1.

        Returns:
            tuple: (f1, f2) each of shape (E,).
        """
        H  = self.halfedges
        f  = H[np.argsort(H[:, 5]), 2]
        return f[0::2], f[1::2]

    def edge_opposite_vertices(self):
        """Vertex opposite to each half-edge's *next* direction, for both sides.

        For edge (vi, vj) this returns the third vertex of the triangle on
        each side (the vertex reached by ``next.next``).

        Returns:
            tuple: (ov1, ov2) opposite vertices for each edge side, shape (E,).
        """
        H   = self.halfedges
        opv = H[H[H[np.argsort(H[:, 5]), 3], 3], 0]
        return opv[0::2], opv[1::2]

    def inner_edges(self):
        """Indices of edges that are not on the boundary.

        Returns:
            np.ndarray: Edge index array.
        """
        H   = self.halfedges
        bnd = H[H[:, 2] == -1, 5]       # edge indices of boundary half-edges
        all_e = np.unique(H[:, 5])
        return np.setdiff1d(all_e, bnd)

    # -------------------------------------------------------------------------
    # Boundary queries
    # -------------------------------------------------------------------------

    def boundary_vertices(self):
        """Indices of vertices on the mesh boundary.

        Returns:
            np.ndarray: Sorted unique boundary vertex indices.
        """
        H  = self.halfedges
        vs = H[H[:, 2] == -1, 0]
        return np.unique(vs)

    def boundary_faces(self):
        """Indices of faces that have at least one boundary edge.

        Returns:
            np.ndarray: Sorted unique boundary-adjacent face indices.
        """
        H      = self.halfedges
        fs     = H[H[:, 2] != -1, :]
        idx    = np.argsort(fs[:, 2])
        fs_n   = H[fs[idx, 1], 2]
        fs_ord = fs[idx, 2]
        return np.unique(fs_ord[fs_n == -1])

    def inner_vertices(self):
        """Indices of vertices not on the boundary.

        Returns:
            np.ndarray: Interior vertex indices.
        """
        return np.delete(np.arange(self.V), self.boundary_vertices())

    def corners(self, corner_tol=0.3):
        """Boundary vertices where the boundary direction changes sharply.

        A corner is detected when the cosine of the turn angle along the
        boundary falls below *corner_tol* (i.e. the turn is more than
        ~72° for the default threshold).

        Args:
            corner_tol (float): cos(angle) threshold.  Lower → sharper corners only.

        Returns:
            np.ndarray: Corner vertex indices.
        """
        H  = self.halfedges
        bh = np.where(H[:, 2] == -1)[0]   # boundary half-edges
        vs   = H[bh, 0]
        nxt  = H[H[bh, 3], 0]
        prv  = H[H[bh, 4], 0]

        vp = unit(self.vertices[vs] - self.vertices[prv])
        vn = unit(self.vertices[nxt] - self.vertices[vs])
        cos_angle = vec_dot(vn, vp)

        return vs[cos_angle < corner_tol]

    def left_right_corners(self, corner_tol=0.3):
        """For each corner vertex, the two adjacent boundary vertices.

        Returns them as (previous, next) in boundary-traversal order.

        Args:
            corner_tol (float): Passed directly to :meth:`corners`.

        Returns:
            tuple: (prev_vertices, next_vertices) each of shape (n_corners,).
        """
        H   = self.halfedges
        bh  = np.where(H[:, 2] == -1)[0]
        cor = self.corners(corner_tol)

        he_corners = np.where(H[bh, 0] == cor[:, None])[1]
        nxt = H[H[bh, 3], 0][he_corners]
        prv = H[H[bh, 4], 0][he_corners]
        return prv, nxt

    def boundary_curves(self):
        """Ordered vertex loops along each connected boundary component.

        Returns:
            list[list[int]]: One list per boundary loop; each list contains
            vertex indices in traversal order.
        """
        H            = self.halfedges
        visited      = set()
        boundaries   = []

        for h_start in range(H.shape[0]):
            if H[h_start, 2] != -1 or h_start in visited:
                continue
            loop = []
            h    = h_start
            while h not in visited:
                visited.add(h)
                loop.append(int(H[h, 0]))
                h = int(H[h, 3])
            boundaries.append(loop)

        return boundaries

    def boundary_split_corners(self, corner_tol=0.3):
        """Boundary curves split at corner vertices.

        Args:
            corner_tol (float): Passed to :meth:`corners`.

        Returns:
            list[np.ndarray]: Sub-curves between consecutive corners.
        """
        bd_curves  = self.boundary_curves()
        corners    = self.corners(corner_tol)
        new_curves = []

        for boundary in bd_curves:
            boundary = np.array(boundary)
            idx = np.where(np.isin(boundary, corners))[0]
            if idx.size:
                for i in range(len(idx) - 1):
                    new_curves.append(boundary[idx[i]:idx[i + 1] + 1])
                new_curves.append(np.r_[boundary[idx[-1]:], boundary[:idx[0] + 1]])

        return new_curves

    def boundary_loops(self):
        """Ordered vertex–pair loops for each boundary component.

        Returns consecutive (vi, vj) pairs along boundary half-edges,
        assembled into closed loops.

        Returns:
            list[list[int]]: Flattened vertex sequences for each boundary loop.

        .. note::
            Prefer :meth:`boundary_curves` for most use cases; this method
            uses a different assembly strategy that may be useful when you
            need raw vertex-pair connectivity.
        """
        H  = self.halfedges
        vi = self.boundary_vertices()
        vj = H[H[vi, 1], 0]
        ls = np.c_[vi, vj]

        loops = []
        while len(ls):
            loop    = []
            val, ls = np_pop(ls, 0)
            loop.extend(val.flatten())
            done    = False
            nxt     = val[1]

            while not done:
                idx = np.where(ls[:, 1] == nxt)[0]
                if not len(idx) or idx[0] == loop[0]:
                    done = True
                elif ls[idx[0], 0] == nxt:
                    val, ls = np_pop(ls, idx[0])
                    loop.extend(val.flatten())
                    nxt = val[1]
                elif ls[idx[0], 1] == nxt:
                    val, ls = np_pop(ls, idx[0])
                    val = np.flip(val)
                    loop.extend(val.flatten())
                    nxt = val[1]

            loops.append(loop)

        return loops

    # -------------------------------------------------------------------------
    # Geometry queries
    # -------------------------------------------------------------------------

    def face_barycenters(self):
        """Centroid of each face.

        Returns:
            np.ndarray: (F, 3) barycenter coordinates.
        """
        H   = self.halfedges
        fs  = H[H[:, 2] != -1, :]
        idx = np.argsort(fs[:, 2])
        vs  = self.vertices[fs[idx, 0]]
        fi  = fs[idx, 2]

        bary = [[] for _ in range(self.F)]
        for i in range(len(vs)):
            bary[fi[i]].append(vs[i])
        return np.array([np.mean(b, axis=0) for b in bary])

    def face_areas(self):
        """Area of each face.

        Uses the cross-product formula for triangles and a barycentric
        subdivision for general polygons.

        Returns:
            np.ndarray: (F,) area per face.
        """
        faces    = self.faces
        vertices = self.vertices

        if all(len(f) == 3 for f in faces):
            vi, vj, vk = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
            return 0.5 * np.linalg.norm(np.cross(vj - vi, vk - vi, axis=1), axis=1)

        A        = np.zeros(len(faces))
        bcenters = [np.mean(vertices[f], axis=0) for f in faces]
        for f in range(len(faces)):
            for i in range(len(faces[f])):
                v0 = vertices[faces[f][i]]
                v1 = vertices[faces[f][(i + 1) % len(faces[f])]]
                A[f] += 0.5 * np.linalg.norm(np.cross(v0 - bcenters[f], v1 - bcenters[f]))
        return A

    def vertex_areas(self):
        """Barycentric area associated with each vertex.

        Each vertex receives ``(1/n) * A_f`` from every adjacent face *f*
        with *n* vertices.

        Returns:
            np.ndarray: (V,) area per vertex.
        """
        H          = self.halfedges
        fa         = self.face_areas()
        mask       = H[:, 2] >= 0
        he_verts   = H[mask, 0]
        he_faces   = H[mask, 2]
        n_per_face = np.bincount(he_faces, minlength=self.F)
        contrib    = fa[he_faces] / n_per_face[he_faces]

        areas = np.zeros(self.V)
        np.add.at(areas, he_verts, contrib)
        return areas

    # -------------------------------------------------------------------------
    # Discrete differential geometry
    # -------------------------------------------------------------------------

    def laplacian_matrix(self):
        """Uniform-weight combinatorial Laplacian matrix (sparse, COO).

        The matrix *L* satisfies: *L[i, i]* = degree(i), *L[i, j]* = -1 for
        each neighbour *j*, and 0 otherwise.

        Returns:
            scipy.sparse.coo_matrix: (V, V) Laplacian.
        """
        adjacency = self.vertex_adjacency_list()
        row, col, data = [], [], []

        for vi, nbrs in enumerate(adjacency):
            for vj in nbrs:
                row.append(vi);  col.append(vj);  data.append(-1)
            row.append(vi);  col.append(vi);  data.append(len(nbrs))

        return coo_matrix((data, (row, col)), shape=(self.V, self.V))

    def mass_matrix(self):
        """Diagonal mass matrix with per-vertex barycentric areas.

        Returns:
            scipy.sparse.dia_matrix: (V, V) diagonal sparse matrix.
        """
        return sp.sparse.diags(self.vertex_areas())

    def cotan_matrix(self):
        """Cotangent-weighted Laplacian (triangle meshes).

        For edge (vi, vj) the weight is ``(cot α + cot β) / 2`` where α and β
        are the angles opposite that edge in the two incident triangles.

        Returns:
            scipy.sparse.csr_matrix: (V, V) cotangent Laplacian.
        """
        H        = self.halfedges
        vertices = self.vertices
        adj_v    = self.vertex_adjacency_list()
        ei, ej   = self.edge_vertices()
        ea, eb   = self.edge_opposite_vertices()

        row, col, data = [], [], []

        for e in range(len(ei)):
            vi = vertices[ei[e]];  vj = vertices[ej[e]]
            va = vertices[ea[e]];  vb = vertices[eb[e]]

            # angles opposite to edge (vi, vj)
            dot_a = np.dot(vi - va, vj - va)
            alpha = np.arccos(np.clip(
                dot_a / (np.linalg.norm(vi - va) * np.linalg.norm(vj - va)),
                -1.0, 1.0))

            dot_b = np.dot(vi - vb, vj - vb)
            beta  = np.arccos(np.clip(
                dot_b / (np.linalg.norm(vi - vb) * np.linalg.norm(vj - vb)),
                -1.0, 1.0))

            w = (1.0 / np.tan(alpha) + 1.0 / np.tan(beta)) / 2.0

            for ri, ci in [(ei[e], ej[e]), (ej[e], ei[e])]:
                row.append(ri);  col.append(ci);  data.append(w)

        C = coo_matrix((data, (row, col)), shape=(self.V, self.V)).tocsr()

        # Diagonal: negative sum of row weights
        for i in range(self.V):
            w_ii = sum(C[i, k] for k in adj_v[i])
            row.append(i);  col.append(i);  data.append(-w_ii)

        C += coo_matrix((data, (row, col)), shape=(self.V, self.V)).tocsr()
        return C

    def quad_gauss_curvature(self):
        """Angle-deficit Gaussian curvature at each vertex of a quad mesh.

        Uses a vectorised angle-sum formula over all half-edges:
        ``K_v = 4 * (2π − Σ θ_v) / area_v``.

        Returns:
            np.ndarray: (V,) Gaussian curvature per vertex.
        """
        H      = self.halfedges
        V      = self.vertices
        areas  = self.vertex_areas()
        origin = H[:, 0]

        next_v = H[H[:, 3], 0]
        prev_v = H[H[:, 4], 0]
        diag_v = H[H[H[:, 3], 3], 0]

        v_orig = V[origin]
        vec_n  = V[next_v] - v_orig
        vec_p  = V[prev_v] - v_orig
        vec_d  = V[diag_v] - v_orig

        def _angles(a, b):
            na  = np.linalg.norm(a, axis=1)
            nb  = np.linalg.norm(b, axis=1)
            cos = np.sum(a * b, axis=1) / (na * nb)
            return np.arccos(np.clip(cos, -1.0, 1.0))

        theta  = _angles(vec_n, vec_p)
        alpha  = _angles(vec_n, vec_d)
        beta   = _angles(vec_d, vec_p)

        deficit = np.zeros(self.V)
        np.add.at(deficit, origin, (theta + alpha + beta) * 0.5)

        return 4.0 * (2.0 * np.pi - deficit) / areas

    # -------------------------------------------------------------------------
    # Dual mesh
    # -------------------------------------------------------------------------

    def dual_top(self):
        """Face rings in vertex order — the combinatorial dual topology.

        For each interior vertex, lists the faces in ring order around it.

        Returns:
            list[list[int]]: ``dual[k]`` is the ordered face ring of the *k*-th
            interior vertex.
        """
        in_v           = self.inner_vertices()
        face_neighbors = self._vertex_ring_faces_list()
        return [face_neighbors[i] for i in in_v]

    def dual_mesh(self):
        """Construct the combinatorial dual mesh.

        Dual vertices are placed at face barycenters; dual faces correspond to
        interior vertices of the primal mesh.

        Returns:
            Mesh: The dual mesh object.
        """
        dm = Mesh()
        dm.make_mesh(self.face_barycenters(), self.dual_top())
        return dm

    def gauss_image(self):
        """Gauss map of the mesh.

        Maps face normals to the unit sphere; the combinatorial structure is
        the same as the dual mesh.

        Returns:
            tuple:
                face_normals (np.ndarray): (F, 3) unit normals on S².
                dual_faces (list[list[int]]): Dual face connectivity.
                edges (np.ndarray): (E_inner, 2) edge pairs (fi, fj) with
                    both faces non-boundary.
        """
        fn         = unit(self.face_normals)
        dual_faces = self.dual_top()
        fi, fj     = self.edge_faces()
        mask       = (fi != -1) & (fj != -1)
        edges      = np.column_stack((fi[mask], fj[mask]))
        return fn, dual_faces, edges

    # -------------------------------------------------------------------------
    # Quad-mesh strip extraction
    # -------------------------------------------------------------------------

    def quad_face_strips(self, f_idx):
        """Extract the two quad strips (u- and v-direction) through face *f_idx*.

        Both strips include *f_idx* itself and run the full width/height of the
        grid, ordered end to end.

        Read straight off the face grid built by :meth:`grid_face_matrix`: the
        row through *f_idx* is one strip, the column through it is the other.
        The grid is cached after the first call, so repeated queries are cheap.

        The previous half-edge walk ("next-next-twin" from each twin of the
        starting face) was wrong on every mesh tested — on `cone_mesh_small.obj`
        it produced empty lists for 26 of 72 faces and duplicated entries for
        42, and matched the true strip for none of them. Its `len(hes) == 2`
        branch mishandled boundary faces and the `len(hes) == 4` branch walked
        both directions from the same half-edge pair, revisiting faces.

        Args:
            f_idx (int): Starting face index.

        Returns:
            tuple: (u_faces, v_faces) — lists of face indices along each strip,
            each containing *f_idx*. Empty lists if the face is not on the grid.

        Raises:
            Exception: If the mesh is not grid-like (see grid_face_matrix).
        """
        if getattr(self, "_face_grid_cache", None) is None:
            self._face_grid_cache = self.grid_face_matrix()
        grid = self._face_grid_cache

        hit = np.argwhere(grid == int(f_idx))
        if len(hit) == 0:
            return [], []

        r, c = (int(x) for x in hit[0])
        return ([int(f) for f in grid[r, :] if f != -1],
                [int(f) for f in grid[:, c] if f != -1])

    def grid_face_matrix(self):
        """Arrange quad-mesh faces into a 2-D grid matrix.

        Traverses from a corner vertex along u then v directions.

        Returns:
            np.ndarray: (rows, cols) integer matrix of face indices.

        Raises:
            Exception: If the mesh is not grid-like (non-quad faces or
                inhomogeneous row lengths).
        """
        faces = self.faces
        if any(len(f) != 4 for f in faces):
            raise Exception("grid_face_matrix: all faces must be quads")

        H   = self.halfedges
        vc  = self.corners(corner_tol=0.3)
        he  = np.where(np.isin(H[:, 0], vc))[0][0]

        mat    = []
        finish = False

        while not finish:
            he_r = int(he)
            row  = [int(H[he_r, 2])]
            finish_row = False

            while not finish_row:
                he_r = int(H[H[H[he_r, 3], 3], 1])   # next → next → twin
                if H[he_r, 2] != -1:
                    row.append(int(H[he_r, 2]))
                else:
                    mat.append(row)
                    finish_row = True
                    next_he = int(H[H[he, 3], 1])     # next → twin along v
                    if H[next_he, 2] == -1:
                        finish = True
                    else:
                        he = int(H[next_he, 3])

        try:
            return np.array(mat, dtype=np.int32)
        except ValueError:
            raise Exception("grid_face_matrix: inhomogeneous row lengths")

    def quad_iso_curves(self):
        """Extract u- and v-direction iso-curves of vertex indices on a quad grid mesh.

        Starts from a corner vertex and walks the vertex grid row by row
        (u-direction), then transposes to get the v-direction columns.

        Each row is walked with ``next → twin → next`` steps (a row edge
        stays inside the mesh until the far column boundary). Advancing to
        the next row uses ``next → next → twin``. The last row is special:
        its row-direction edges only exist as *boundary* half-edges (the
        adjacent face lies above, not below), so it is walked in reverse
        with ``prev → prev → twin`` steps instead, terminating when that
        composition hits a boundary half-edge.

        Returns:
            tuple: (u_curves, v_curves) — each a list of 1-D int arrays of
                vertex indices; ``u_curves[i]`` is the i-th row (constant v,
                varying u), ``v_curves[j]`` is the j-th column (constant u,
                varying v).

        Raises:
            Exception: If the mesh is not a quad mesh (all faces with 4
                vertices) or is not grid-like (inhomogeneous row lengths).
        """
        u_mat = self._quad_vertex_grid()
        u_curves = [row.copy() for row in u_mat]
        v_curves = [col.copy() for col in u_mat.T]
        return u_curves, v_curves

    def quad_vertex_adjacency(self):
        """Per-vertex u- and v-direction neighbor lists on a quad grid mesh.

        Built from the same vertex grid as :meth:`quad_iso_curves`.

        Returns:
            tuple: (u_adj, v_adj) — each a list of length ``self.V`` where
                ``u_adj[i]`` / ``v_adj[i]`` is a list of the 1 (boundary) or
                2 (interior) neighboring vertex indices of vertex *i* along
                that direction.

        Raises:
            Exception: If the mesh is not a quad mesh (all faces with 4
                vertices) or is not grid-like (inhomogeneous row lengths).
        """
        u_mat = self._quad_vertex_grid()
        rows, cols = u_mat.shape

        u_adj = [None] * self.V
        v_adj = [None] * self.V

        for i in range(rows):
            for j in range(cols):
                v = int(u_mat[i, j])
                u_adj[v] = [int(u_mat[i, k]) for k in (j - 1, j + 1) if 0 <= k < cols]
                v_adj[v] = [int(u_mat[k, j]) for k in (i - 1, i + 1) if 0 <= k < rows]

        return u_adj, v_adj

    def _quad_vertex_grid(self):
        """Arrange quad-mesh vertices into a 2-D grid matrix.

        Traverses from a corner vertex along u then v directions, mirroring
        :meth:`grid_face_matrix` one level down (vertices instead of faces).

        Returns:
            np.ndarray: (rows, cols) integer matrix of vertex indices.

        Raises:
            Exception: If the mesh is not a quad mesh (all faces with 4
                vertices) or is not grid-like (inhomogeneous row lengths).
        """
        faces = self.faces
        if any(len(f) != 4 for f in faces):
            raise Exception("quad_vertex_grid: all faces must be quads")

        H = self.halfedges

        def extract_row_forward(he_start):
            he  = int(he_start)
            row = [int(H[he, 0])]
            while True:
                t = int(H[H[he, 3], 1])          # twin(next(he))
                if H[t, 2] == -1:
                    row.append(int(H[H[t, 3], 0]))   # origin of next(t)
                    return row
                he = int(H[t, 3])                # next(t)
                row.append(int(H[he, 0]))

        def extract_row_backward(he_start):
            he  = int(he_start)
            row = [int(H[he, 0])]
            while True:
                pp = int(H[H[he, 4], 4])          # prev(prev(he))
                t  = int(H[pp, 1])                # twin(prev(prev(he)))
                row.append(int(H[H[he, 4], 0]))   # origin of prev(he)
                if H[t, 2] == -1:
                    return row
                he = t

        vc = self.corners(corner_tol=0.3)
        he = int(np.where(np.isin(H[:, 0], vc))[0][0])

        mat = [extract_row_forward(he)]
        while True:
            nrs = int(H[H[H[he, 3], 3], 1])   # next → next → twin
            if H[nrs, 2] == -1:
                interior = int(H[H[nrs, 4], 1])   # twin(prev(nrs))
                mat.append(extract_row_backward(interior))
                break
            mat.append(extract_row_forward(nrs))
            he = nrs

        try:
            return np.array(mat, dtype=np.int32)
        except ValueError:
            raise Exception("quad_vertex_grid: inhomogeneous row lengths")

    # -------------------------------------------------------------------------
    # I/O
    # -------------------------------------------------------------------------

    def read_obj_file(self, file_name):
        """Load the mesh from a Wavefront OBJ file.

        Args:
            file_name (str | Path): Path to the OBJ file.
        """
        file_name = str(file_name)
        self.name = file_name.split('.')[0]
        vertices_list, faces_list, uv_list = [], [], []

        with open(file_name, encoding='utf-8') as obj_file:
            for line in obj_file:
                tokens = line.split()
                if not tokens:
                    continue
                tag = tokens[0]

                if tag == 'v':
                    vertices_list.append([float(tokens[1]), float(tokens[2]), float(tokens[3])])

                elif tag == 'f':
                    v_list = []
                    try:
                        for tok in tokens[1:]:
                            v_list.append(int(tok.split('/')[0]) - 1)
                    except ValueError:
                        v_list = [int(tok) - 1 for tok in tokens[1:]]
                    faces_list.append(v_list)

                elif tag == 'vt':
                    uv_list.append([float(tokens[1]), float(tokens[2])])

        if uv_list:
            self._uv = np.array(uv_list)

        self.make_mesh(vertices_list, faces_list)

    # -------------------------------------------------------------------------
    # Internal traversal helpers (prefixed _ — not part of the public API)
    # -------------------------------------------------------------------------

    def _vertex_ring_ordered_halfedges(self):
        """Half-edge indices sorted so that all half-edges of each vertex appear
        consecutively in one-ring order (twin-previous chain).

        Returns:
            np.ndarray: Ordered half-edge index array.
        """
        H = np.copy(self.halfedges)
        i = np.argsort(H[:, 0])
        v = H[i, 0]

        index = np.arange(H.shape[0])
        _, j  = np.unique(v, True)
        v     = np.delete(v, j)
        index = np.delete(index, j)

        while v.shape[0] > 0:
            _, j = np.unique(v, True)
            # Walk around the vertex ring: go to previous → twin
            i[index[j]] = H[H[i[index[j] - 1], 4], 1]
            v     = np.delete(v, j)
            index = np.delete(index, j)

        return i

    def _face_ordered_halfedges(self):
        """Half-edge indices sorted so that all half-edges of each face appear
        consecutively in face-loop order (next chain).

        Returns:
            np.ndarray: Ordered half-edge index array.
        """
        H = np.copy(self.halfedges)
        i = np.argsort(H[:, 2])
        i = i[H[i, 2] >= 0]    # drop boundary half-edges
        f = H[i, 2]

        index = np.arange(i.shape[0])
        _, j  = np.unique(f, True)
        f     = np.delete(f, j)
        index = np.delete(index, j)

        while f.shape[0] > 0:
            _, j = np.unique(f, True)
            i[index[j]] = H[i[index[j] - 1], 3]   # follow next pointer
            f     = np.delete(f, j)
            index = np.delete(index, j)

        return i

    def _vertex_ring_vertices_iterators(self, sort=False, order=False):
        """Parallel arrays (v, vj) where half-edge h has origin v and its
        twin's origin is vj (i.e. an edge v → vj exists).

        Args:
            order (bool): Use ring-ordered traversal (calls
                ``_vertex_ring_ordered_halfedges``).
            sort (bool): Sort by origin vertex index (cheaper than ``order``).

        Returns:
            tuple: (v, vj) both shape (H,).
        """
        H  = self.halfedges
        v  = H[:, 0]
        vj = H[H[:, 1], 0]
        if order:
            idx = self._vertex_ring_ordered_halfedges()
            v, vj = v[idx], vj[idx]
        elif sort:
            idx = np.argsort(v)
            v, vj = v[idx], vj[idx]
        return v, vj

    def _vertex_ring_faces_iterators(self, sort=False, order=False):
        """Parallel arrays (v, fj) where half-edge h has origin v and
        belongs to face fj (interior half-edges only when order=False).

        Args:
            order (bool): Use ring-ordered traversal.
            sort (bool): Sort by vertex.

        Returns:
            tuple: (v, fj).
        """
        H = self.halfedges
        if order:
            idx = self._vertex_ring_ordered_halfedges()
            v   = H[idx, 0]
            fj  = H[idx, 2]
        else:
            idx = np.where(H[:, 2] >= 0)[0]
            v   = H[idx, 0]
            fj  = H[idx, 2]
            if sort:
                s  = np.argsort(v)
                v, fj = v[s], fj[s]
        return v, fj

    def _vertex_ring_faces_list(self):
        """Per-vertex list of adjacent face indices in ring order.

        Returns:
            list[list[int]]: ``ring[v]`` contains face indices in ring order.
        """
        ring_list = [[] for _ in range(self.V)]
        v, fj = self._vertex_ring_faces_iterators(order=True)
        for i in range(len(v)):
            ring_list[v[i]].append(fj[i])
        return ring_list
