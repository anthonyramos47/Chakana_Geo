import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm


class BoundaryGlide(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Boundary interpolation (Tang et al. 2014, Sec. 3.3, w_bdry).

        E_bdry = \sum_{v in boundary} || P_v (v - p_v) ||^2

        p_v is the closest point of v on the reference boundary polyline C and
        P_v = I - t t^T removes the component along the tangent t of C at p_v:
        the constraint v in C is replaced by v in T*, the tangent line of C at
        the closest point (2 linear constraints). Corner vertices use P_v = I,
        so they stay at their reference position.

        p_v and t are the linearisation point: refreshed in accept_step after
        each step, never in res()/grad(), so both describe the same function.
        """
        super().__init__()
        self.name = "BoundaryGlide"

    def initialize_objective(self, X, var_idx, var_name, loops, corners, V_ref) -> None:
        """
        Input:
            X        : Variables
            var_idx  : dictionary of indices of variables
            var_name : Name of the vertex variable
            loops    : Ordered closed boundary loops (lists of vertex indices)
            corners  : Vertex indices pinned to their reference position
            V_ref    : (V, 3) reference vertex positions defining the curves
        """
        V_ref   = np.asarray(V_ref, dtype=float)
        corners = set(int(c) for c in corners)
        v_idx   = var_idx[var_name].reshape(-1, 3)

        # Reference polyline per loop and its vertex tangents (central differences)
        self.curves   = [V_ref[np.asarray(l)] for l in loops]
        self.tangents = [_unit(np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0))
                         for P in self.curves]

        self.verts     = np.array([v for l in loops for v in l], dtype=np.int64)
        self.loop_of   = np.array([i for i, l in enumerate(loops) for _ in l])
        self.is_corner = np.array([v in corners for v in self.verts])

        self.x_idx = v_idx[self.verts].flatten()
        n = len(self.verts)
        self.num_residuals = 3 * n

        # Row 3i+a depends on the 3 coordinates of vertex i: value P_i[a, b]
        self._rows = np.arange(3 * n).repeat(3)
        self._cols = v_idx[self.verts].repeat(3, axis=0).flatten()

        self._project(X)

    def _project(self, X):
        """Closest points on the reference curves and their tangent projectors."""
        x = X[self.x_idx].reshape(-1, 3)
        n = len(x)
        self.p = np.empty((n, 3))
        self.Pm = np.tile(np.eye(3), (n, 1, 1))

        for li, (C, T) in enumerate(zip(self.curves, self.tangents)):
            sel = np.where(self.loop_of == li)[0]
            A, B = C, np.roll(C, -1, axis=0)
            AB = B - A
            # Parameter of the closest point on every segment, for every vertex
            t = np.einsum('vsk,sk->vs', x[sel, None, :] - A[None], AB)
            t = np.clip(t / np.maximum(np.einsum('sk,sk->s', AB, AB), 1e-30), 0.0, 1.0)
            Q = A[None] + t[..., None] * AB[None]
            s = np.argmin(np.linalg.norm(Q - x[sel, None, :], axis=2), axis=1)
            ts = t[np.arange(len(sel)), s]
            self.p[sel] = Q[np.arange(len(sel)), s]
            # Tangent interpolated between the segment's vertex tangents
            tan = _unit((1 - ts)[:, None] * T[s] + ts[:, None] * np.roll(T, -1, axis=0)[s])
            self.Pm[sel] = np.eye(3) - tan[:, :, None] * tan[:, None, :]

        c = self.is_corner
        if c.any():
            ref = np.concatenate(self.curves)          # same order as self.verts
            self.p[c] = ref[c]
            self.Pm[c] = np.eye(3)

    def accept_step(self, X) -> None:
        self._project(X)

    def grad(self, X):
        return self.Pm.reshape(-1)

    def res(self, X):
        x = X[self.x_idx].reshape(-1, 3)
        return np.einsum('vab,vb->va', self.Pm, x - self.p).reshape(-1)


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-30)
