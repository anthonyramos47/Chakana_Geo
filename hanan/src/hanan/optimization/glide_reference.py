import numpy as np
import igl
from hanan.optimization.objective_term import ObjectiveTerm


class GlideReference(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Gliding constraint against a reference surface.

        E_glide = \sum_var  <v - v_proj, n_proj>^2

        where v_proj is the closest point of v on the reference mesh and
        n_proj is the unit normal of the reference FACE containing v_proj.
        This is the tangent-plane distance: moving tangentially along the
        reference surface is free, moving off it is penalised — which is what
        "gliding" means, and matches E_prox in
        "Approximation by Meshes with Spherical Faces", Sec. 5.2.

        Previously n_proj was taken as the normalised offset (v - v_proj)/|.|.
        That has two problems:

          * it is undefined exactly when the constraint is satisfied. A vertex
            sitting ON the reference surface gives an offset of ~0 whose
            direction is floating-point noise (the + 1e-8 guard stops the
            division exploding but cannot invent a direction, and at
            |offset| ~ 1e-7 it also distorts the magnitude by ~10%);
          * with that choice <v - v_proj, n> reduces to |v - v_proj|, i.e. the
            plain point distance, duplicating ProximityReference rather than
            gliding.

        The face normal is well defined everywhere, including on the surface.
        """
        super().__init__()
        self.name = "glideReference" # Name of the constraint

        self.V_ref = None # Reference positions
        self.F_ref = None # Reference faces
        self.FN_ref = None # Unit normal per reference face
        self.N_ref = None # Normal at each projection point (frozen per step)
        self.v_proj = None # Closest point per variable (frozen per step)

        # Cont for weight decrease
        self.cont = 0


    def initialize_objective(self, X, var_idx, var_name, V_ref, F_ref) -> None:
        """
        Input:
            X : Variables
            var_idx     : dictionary of indices of variables
            var_name    : Name of the variable
            V_ref       : Reference positions
            F_ref       : Reference faces
        """

        # Store reference values
        self.V_ref = np.asarray(V_ref, dtype=float)
        self.F_ref = np.asarray(F_ref, dtype=np.int32)

        # Unit normal per reference face, computed once (the reference mesh is
        # constant). Degenerate triangles fall back to +Z rather than nan.
        fn = np.cross(self.V_ref[self.F_ref[:, 1]] - self.V_ref[self.F_ref[:, 0]],
                      self.V_ref[self.F_ref[:, 2]] - self.V_ref[self.F_ref[:, 0]])
        nrm = np.linalg.norm(fn, axis=1, keepdims=True)
        self.FN_ref = np.where(nrm > 1e-12, fn / np.maximum(nrm, 1e-12),
                               np.array([0.0, 0.0, 1.0]))

        # Set residuals
        self.num_residuals = len(var_idx[var_name].reshape(-1, 3))

        # Set idx variables
        self.var_idx = var_idx[var_name]

        # Project once so res/grad have a consistent reference to start from
        self._project(X)

        # Store rows and cols of the Jacobian structure for position term
        self._rows  = np.arange(self.num_residuals).repeat(3)
        self._cols  = self.var_idx


    def _project(self, X):
        """Refresh the closest points and their face normals."""
        pts = X[self.var_idx].reshape(-1, 3)
        _, face_idx, v_proj = igl.point_mesh_squared_distance(
            pts, self.V_ref, self.F_ref)
        self.v_proj = np.asarray(v_proj, dtype=float)
        self.N_ref = self.FN_ref[np.asarray(face_idx, dtype=np.int32)]

    def accept_step(self, X) -> None:
        # The projection is the linearisation point: it is refreshed once the
        # optimizer has taken a step, never inside res() or grad(), so the two
        # always describe the same function at a given X.
        self._project(X)

    def grad(self, X):
        # d/dv <v - v_proj, n> = n, with v_proj and n held fixed for this step.
        return self.N_ref.flatten()

    def res(self, X):
        pts = X[self.var_idx].reshape(-1, 3)
        return np.einsum('ij,ij->i', (pts - self.v_proj), self.N_ref)
