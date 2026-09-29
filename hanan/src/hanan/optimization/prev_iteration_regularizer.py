import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm


class PrevIterationRegularizer(ObjectiveTerm):
    r"""
    Keeps the iterates close to earlier ones: E = Σ_i ‖X_i − X_i^ref‖².

    Two choices of the reference X^ref (constructor argument ``lagged``):

    lagged=False (default) — proximal term.
        X^ref is the current iterate X_k, so each step solves
        min E(X) + w‖X − X_k‖²; the residual is 0 at the linearisation point and the
        term only damps the step size.

    lagged=True — the behaviour of hanan before 2026-09 (``prev_iteration_regularizer``
    used by the original L-conjugacy app, commit 9624f23).
        X^ref is the iterate *before* the current one, X_{k−1}, so the residual at X_k is
        X_k − X_{k−1} and each step is pulled back towards X_{k−1}. The old code produced
        this by overwriting the reference inside res(); it matches that behaviour exactly
        with fixed damping (adaptive_mu=False), where res() ran once per iteration.
        Use it to reproduce results computed with the old code.
    """

    def __init__(self, lagged: bool = False) -> None:
        super().__init__()
        self.name = "prevRegularizer"
        self.lagged = lagged
        self.v_name = None
        self.prev = None
        self._current = None

    def initialize_objective(self, X, var_indices) -> None:
        """
        Args:
            X: Variable vector (the starting point is the first reference).
            var_indices: Dictionary mapping variable names to indices (unused: the
                term covers every variable).
        """
        self.prev = X.copy()
        self._current = X.copy()

        self.num_residuals = len(X)

        # r = X − X^ref  ⇒  dr/dX = I (constant)
        self._rows_const = np.arange(self.num_residuals)
        self._cols_const = np.arange(self.num_residuals)
        self._values_const = np.ones(len(self._rows_const), dtype=np.float64)

    def grad(self, X):
        return None

    def res(self, X):
        return X - self.prev

    def accept_step(self, X):
        if self.lagged:
            # reference = the iterate we just left
            self.prev = self._current
            self._current = X.copy()
        else:
            # reference = the iterate just reached
            self.prev = X.copy()
