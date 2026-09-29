import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm

class StepControl(ObjectiveTerm):
    """
    Position anchoring constraint: penalizes deviation from previous values.

    Energy: E = sum_i ||v_i - v_i^prev||^2

    NAMING: This should probably be renamed to 'Variable_Anchor' or 'Position_Anchor'
    because "Step_Control" is misleading - this doesn't control optimization step size,
    it anchors variables to previous values.

    Used to prevent variables from changing too much between iterations.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "Step_Control"  # TODO: Consider renaming to "Variable_Anchor"
        self.v_name = None
        self.prev = None

    def initialize_objective(self, X, var_indices, var_name) -> None:
        """
        Initialize the anchoring constraint.

        Args:
            X: Variable vector
            var_indices: Dictionary mapping variable names to indices
            var_name: Name of the variable to anchor
        """
        self.v_name = var_name
        self.var_idx = var_indices[var_name]

        # Store initial values
        self.prev = X[self.var_idx].copy()

        # Add constraint
        self.num_residuals = len(self.var_idx)
        
        # Pre-build Jacobian structure
        # For residual r_i = v_i - v_i^prev, derivative is: dr_i/dv_i = 1
        self._rows_const = np.arange(self.num_residuals)
        self._cols_const = self.var_idx
        
        # Store Values of Jacobian (constant = 1)
        self._values_const = np.ones(len(self._rows_const), dtype=np.float64)

        
    def grad(self, X):
        return None

    def res(self, X):
        return X[self.var_idx] - self.prev

    def accept_step(self, X):
        # Proximal anchor: the next step is measured from the iterate just reached.
        self.prev = X[self.var_idx].copy()
