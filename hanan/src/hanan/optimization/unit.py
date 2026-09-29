import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm

class Unit(ObjectiveTerm):
    """
    Unit vector constraint: enforces ||v|| = 1 for vector variables.

    Energy: E = sum_i (||v_i||^2 - 1)^2

    This constraint ensures that vector variables maintain unit length.
    Commonly used for normals, tangents, or direction vectors.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "Unit"
        self.dim = None
        self.v_name = None

    def initialize_objective(self, X, var_indices, var_name, dim) -> None:
        """
        Initialize the unit vector constraint.

        Args:
            X: Variable vector
            var_indices: Dictionary mapping variable names to indices
            var_name: Name of the variable to constrain
            dim: Dimensionality of each vector (e.g., 3 for 3D vectors)
        """
        self.v_name = var_name
        self.dim = dim
        self.idx_var = var_indices[var_name]

        # Number of vectors to constrain
        self.num_residuals = len(self.idx_var) // dim
      
        # Pre-build Jacobian structure
        # For residual r_i = ||v_i||^2 - 1, derivative is: dr_i/dv_i = 2*v_i
        # Each constraint row i has 'dim' non-zero entries (one per vector component)
        self._rows = np.arange(self.num_residuals).repeat(dim)
        self._cols = self.idx_var
    
        

    def grad(self, X):
        return 2.0 * X[self.idx_var]

    def res(self, X):
        xs = X[self.idx_var].reshape(-1, self.dim)
        return np.sum(xs * xs, axis=1) - 1.0
