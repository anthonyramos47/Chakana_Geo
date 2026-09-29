# objective_term.py (formerly constraint.py)
# This module defines an ObjectiveTerm class for Levenberg-Marquardt optimization.
# Each ObjectiveTerm represents a component of the objective function to minimize.
#
# In LM optimization, we minimize: ||F(x)||² = Σ f_i(x)²
# Each ObjectiveTerm provides:
#   - Residual evaluation f(x)
#   - Jacobian J(x)
#   - Contribution to Gauss-Newton system (H = J^T*J, b = J^T*r)
#
# The code supports sparse Jacobian representations for efficiency.

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix  # For constructing sparse Jacobian matrices

# JAX imports for automatic differentiation
try:
    import jax
    import jax.numpy as jnp
    from jax import jacfwd, jacrev, jit
    JAX_AVAILABLE = True
except ImportError:
    JAX_AVAILABLE = False
    jax = None
    jnp = None

# Numba imports for JIT compilation of finite differences
try:
    from numba import jit as numba_jit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    numba_jit = None

class ObjectiveTerm():
    def __init__(self) -> None:
        """
        Initialize the ObjectiveTerm instance with default values.

        This class represents a single objective term in Levenberg-Marquardt optimization.
        It encapsulates:
        - Residual function f(x)
        - Jacobian computation J(x)
        - Energy/cost evaluation ||f(x)||²
        - Gauss-Newton system contributions (H = J^T*J, b = J^T*r)

        Attributes:
            name (str): Name of the objective term (e.g., "planarity", "fairness").
            w (float): Weight factor for this term's contribution to total objective.

            # Jacobian structure (sparse COO format)
            _rows (np.ndarray): Row indices for non-zero Jacobian entries.
            _cols (np.ndarray): Column indices for non-zero Jacobian entries.
            _values (np.ndarray): Values of non-zero Jacobian entries.

            # Residuals
            _r (np.ndarray): Residual vector f(x).

            # Problem dimensions
            num_residuals (int): Number of residual equations (Jacobian rows).
            num_vars (int): Number of optimization variables (Jacobian columns).

            # Optimization flags
            first_compt (bool): Whether structure has been built (first computation done).
            consider_energy (bool): Whether to include this term in global energy.
            jacobianMethod (str): "analytical", "jax", or "finite_difference".

            # Legacy attributes (deprecated, kept for backward compatibility)
            const (int): Legacy name for num_residuals.
            var (int): Legacy name for num_vars.
            const_idx (dict): Legacy named residual indices.
        """
        self.name = None  # Name of the objective term
        self.w = 1.0  # Weight factor for this term's contribution

        # Jacobian structure (COO format: row indices, column indices, values)
        self._rows = None  # Row indices (numpy array, built in initialize_constraint)
        self._cols = None  # Column indices (numpy array, built in initialize_constraint)

        # Jacobian structure Constant values 
        self._rows_const = None
        self._cols_const = None
        self._values_const = None
        self.slice_non_const = None # Slice for non-constant Jacobian values

        # Problem dimensions (set in initialize_constraint)
        self.num_residuals = 0  # Number of residual equations (rows in Jacobian)
        self.num_vars = None  # Number of variables (columns in Jacobian)

        # Optimization flags
        self.first_compt = False  # Flag for first computation (structure built)
        self.consider_energy = False  # Whether to include in global energy
        self.jacobianMethod = "analytical"  # Jacobian computation method

        # Legacy support (deprecated, kept for backward compatibility)
        self.J_constant = False
        self._cols_csr = None
        self._values = []
        self.const = 0
        self.var = None
        self.const_idx = {}
        self.sparse = True
        self._value_idx = 0

    def initialize_objective(self, X, var_indices, *args) -> None:
        """
        Initialize the objective term with variables and their indices.

        This is a template method that should be implemented in a subclass.

        In this method, subclasses should:
        1. Extract relevant variable indices from var_indices
        2. Compute and store Jacobian structure (_rows, _cols)
        3. Pre-allocate _values and _r arrays
        4. Set num_residuals and num_vars

        Args:
            X (array-like): Array of all optimization variables.
            var_indices (array-like): Mapping from logical variables to X indices.
            *args: Additional arguments specific to the objective term.
        """
        pass

    def _initialize_objective(self, X, var_indices, *args) -> None:
        """
        Internal method to initialize all initial data for the objective term.

        Calls the user-defined 'initialize_objective' method and sets up the variable count.

        Args:
            X (array-like): Array of variables.
            var_indices (array-like): Indices of the variables involved.
            *args: Additional arguments specific to the objective term.
        """
        # Call the subclass's initialization method
        self.initialize_objective(X, var_indices, *args)

        # Check if num_residuals is not None
        if self.num_residuals is None or self.num_residuals == 0:
            raise ValueError("num_residuals must be set in initialize_objective")

        # Check if there are constant Jacobian values to store
        if self.jacobianMethod == "analytical":
            if self._rows_const is not None and self._cols_const is not None and self._values_const is not None:

                num_rows_const = len(self._rows_const)

                # Assert lengths match
                assert (len(self._rows_const) == len(self._cols_const) == len(self._values_const)), f"Constant Jacobian structure lengths do not match:\n rows: {len(self._rows_const)}\n cols : {len(self._cols_const)}\n values: {len(self._values_const)}"

                # Check if there are non-constant Jacobian values
                if self._rows is None or self._cols is None or self._values is None:
                    # Only constant part exists
                    self._rows = self._rows_const
                    self._cols = self._cols_const
                    
                
                else:
                    assert (len(self._rows) == len(self._cols)), f"Non-constant Jacobian structure lengths do not match:\n rows: {len(self._rows)}\n cols : {len(self._cols)}" 

                    num_rows_variable = len(self._rows)

                    # Add at the beginning of the Jacobian structure
                    self._rows = np.concatenate([self._rows_const, self._rows])
                    self._cols = np.concatenate([self._cols_const, self._cols])
                    
                    # init slice for non-constant part
                    self._slice_non_const = slice(num_rows_const, num_rows_const + num_rows_variable    )
            elif self.jacobianMethod == "analytical":
                # No constant part, use existing structure
                self._rows = self._rows
                self._cols = self._cols

            # Transform to numpy arrays if not already
            if not isinstance(self._rows, np.ndarray):
                self._rows = np.array(self._rows, dtype=np.int32)
            if not isinstance(self._cols, np.ndarray):
                self._cols = np.array(self._cols, dtype=np.int32)

            # Build cached CSR and precompute the COO→CSR permutation.
            #
            # COO→CSR reorders entries into row-major order (sorted by row, then
            # column). If we fill the COO data with marker indices [0,1,2,...],
            # the CSR .data array tells us exactly which original COO index landed
            # at each CSR position: _csr_to_coo[csr_pos] = coo_index.
            #
            # On every subsequent call to _computeGrad we simply do:
            #   J_csr.data[:] = values[_csr_to_coo]
            # instead of rebuilding the whole COO→CSR pipeline.
            if self._rows is not None and self._cols is not None:
                nnz = len(self._rows)
                markers = np.arange(nnz, dtype=np.float64)
                self._J_csr = coo_matrix(
                    (markers, (self._rows, self._cols)),
                    shape=(self.num_residuals, len(X))
                ).tocsr()
                assert len(self._J_csr.data) == nnz, (
                    f"{self.name}: duplicate (row,col) entries in Jacobian — "
                    "CSR caching requires unique index pairs."
                )
                # Integer array: _csr_to_coo[i] = which COO entry occupies CSR slot i
                self._csr_to_coo = self._J_csr.data.astype(np.intp)
            else:
                self._J_csr = None
                self._csr_to_coo = None

        else:
            self._J_csr = None
            self._csr_to_coo = None

        # Set the number of variables from the length of X
        self.num_vars = len(X)

        
        
    def _res_dispatch(self, X) -> np.ndarray:
        """Route to res() or fall back to legacy func() for un-migrated terms."""
        if type(self).res is not ObjectiveTerm.res:
            return self.res(X)
        return self.func(X)

    def grad(self, X) -> np.ndarray:
        """
        Return Jacobian non-zero values only (matching the _rows/_cols structure
        set up in initialize_objective).  Return None when the Jacobian is
        constant or zero (base class handles it).

        Subclasses should override this instead of compute().
        """
        pass

    def res(self, X) -> np.ndarray:
        """
        Return the residual vector only.

        Subclasses should override this instead of func().

        Must not modify the term's state: the optimizer also evaluates it at
        trial points it may reject. State that follows the iterates belongs in
        accept_step().
        """
        pass

    def accept_step(self, X) -> None:
        """
        Called by the optimizer after each step it actually takes, with the new X.

        Override to update state that tracks the current iterate (e.g. a
        reference point for a proximal term). Default: nothing.
        """
        pass

    def _compute(self, X):
        """
        Internal dispatcher called by _computeGrad.

        Migration shim: if a subclass still overrides the old compute() method,
        delegate to it so un-migrated terms keep working.  Once all terms
        override grad()/res() the shim branch becomes dead code.
        """
        if type(self).compute is not ObjectiveTerm.compute:
            return self.compute(X)
        return self.grad(X), self.res(X)

    def compute_energy(self, X) -> float:
        """
        Compute the energy contribution of the constraint.

        Uses res() when available, falls back to the legacy func() for
        un-migrated subclasses.

        Args:
            X (array-like): Array of variables.
        """
        if type(self).res is not ObjectiveTerm.res:
            r = self.res(X)
        else:
            r = self.func(X)
        return self.w * np.sum(r**2)

    # ------------------------------------------------------------------
    # Legacy interface — kept for backward compatibility
    # ------------------------------------------------------------------

    def func(self, X) -> np.ndarray:
        """DEPRECATED: override res() instead."""
        pass

    def compute(self, X):
        """DEPRECATED: override grad() and res() instead."""
        pass

    def compute_grad_fd(self, X):
        """
        Compute the Jacobian of the constraint using finite differences.

        This is the standard central difference method with sparsity detection.
        For better performance use jacobianMethod="jax" (automatic
        differentiation) or an analytical Jacobian.
        """

        n = len(X)
        X_pert = X.copy()
        f0 = self._res_dispatch(X)
        m = len(f0)

        
        h = 1e-5 * np.maximum(1.0, np.abs(X))


        # Pre-allocate with maximum possible size
        max_nnz = m * n
        rows = np.zeros(max_nnz, dtype=np.int32)
        cols = np.zeros(max_nnz, dtype=np.int32)
        data = np.zeros(max_nnz, dtype=np.float64)

        nnz = 0  # Counter for actual non-zeros

        for i in range(n):
            original_value = X_pert[i]

            X_pert[i] = original_value + h[i]
            f_forward = self._res_dispatch(X_pert)

            X_pert[i] = original_value - h[i]
            f_backward = self._res_dispatch(X_pert)

            X_pert[i] = original_value

            col_i = (f_forward - f_backward) / (2 * h[i])

            # Find nonzeros
            nz_indices = np.flatnonzero(np.abs(col_i) > 1e-12)
            nz_count = len(nz_indices)

            if nz_count > 0:
                rows[nnz:nnz+nz_count] = nz_indices
                cols[nnz:nnz+nz_count] = i
                data[nnz:nnz+nz_count] = col_i[nz_indices]
                nnz += nz_count

        # Trim to actual size
        J = coo_matrix((data[:nnz], (rows[:nnz], cols[:nnz])), shape=(m, n))

        return J, f0

    def compute_grad_jax(self, X):
        """
        Compute the Jacobian using JAX automatic differentiation.

        NOTE: JAX computes a dense (m×n) Jacobian internally. For large meshes
        (e.g. 10k vertices, 50k residuals) this allocates a very large matrix.
        Only use this method for small problems or when analytical derivatives
        are unavailable. For large problems, implement compute() analytically.

        Args:
            X (array-like): Array of all optimization variables.

        Returns:
            J (coo_matrix): Sparse Jacobian matrix (m x n).
            f0 (np.ndarray): Residual vector at X (length m).

        Raises:
            ImportError: If JAX is not installed.
        """
        if not JAX_AVAILABLE:
            raise ImportError(
                "JAX is not installed. Please install it with: pip install jax jaxlib\n"
                "Or use jacobianMethod='FD' instead."
            )

        X_jax = jnp.array(X)

        def func_jax(x):
            return jnp.asarray(self._res_dispatch(x))

        # Build and cache JIT-compiled jacobian + function on first call.
        # Use num_residuals (already set during initialize_objective) to avoid
        # an extra func(X) evaluation just to determine m.
        if not hasattr(self, '_jax_jac_func'):
            m = self.num_residuals
            n = len(X)
            # jacfwd is faster when n <= m (one forward pass per input variable).
            # jacrev is faster when m < n (one reverse pass per output residual).
            if n <= m:
                self._jax_jac_func = jit(jacfwd(func_jax))
            else:
                self._jax_jac_func = jit(jacrev(func_jax))
            self._jax_func_jit = jit(func_jax)
            self._jax_dims = (m, n)

        J_dense = np.array(self._jax_jac_func(X_jax))
        f0 = np.array(self._jax_func_jit(X_jax))

        mask = np.abs(J_dense) > 1e-12
        rows, cols = np.where(mask)
        J = coo_matrix((J_dense[rows, cols], (rows, cols)), shape=self._jax_dims)

        return J, f0

    def _computeGrad(self, X):
        """
        Internal method to compute the residual and the Jacobian for the constraint.

        This method clears previous Jacobian values, calls the user-defined compute method,
        and then constructs the sparse Jacobian matrix along with computing the energy terms.

        Optimizations:
        - Reuses CSR Jacobian structure (only updates values after first iteration)
        - Pre-allocates numpy array for values (avoids list operations)
        - Caches CSR matrix to avoid repeated COO->CSR conversion

        Supported jacobianMethod values:
        - "analytical": Use user-defined compute() method (fastest, requires manual derivatives)
        - "jax": Use JAX automatic differentiation (fast, accurate, automatic)
        - "FD": Use finite differences (sequential, works for any function)

        Args:
            X (array-like): Array of variables.
            var_idx (array-like): Indices of the variables relevant for computing the constraint.
        """

        if self.jacobianMethod == "analytical":
            # Call the internal dispatcher (routes to grad/res or legacy compute)
            values, r = self._compute(X)

            if values is None and self._values_const is None:
                raise ValueError("Jacobian values cannot be None when using analytical method.")
            elif values is None:  # only constant part
                values = self._values_const
            elif self._values_const is not None:  # constant + variable parts
                values = np.concatenate([self._values_const, values])
            # else: only variable part — values already set

            # Reuse the cached CSR structure: map COO values to CSR positions
            # via the precomputed permutation (avoids full COO→CSR rebuild).
            values = np.asarray(values, dtype=np.float64)
            self._J_csr.data[:] = values[self._csr_to_coo]
            J = self._J_csr

        elif self.jacobianMethod == "jax":
            J, r = self.compute_grad_jax(X)

            # Use CSR format for efficient transpose-multiply operations
            if not isinstance(J, csr_matrix):
                J = J.tocsr()

        else:
            # Finite difference (default fallback for "FD" and unknown methods)
            J, r = self.compute_grad_fd(X)

            # Use CSR format for efficient transpose-multiply operations
            if not isinstance(J, csr_matrix):
                J = J.tocsr()


        H   = self.w * J.T.dot(J)
        b   = self.w * J.T.dot(r)
        res = self.w * np.sum(r**2)
        meanRes = res / len(r)


        return H, b, res, meanRes

    def debug_dimensions(self, values=None, residuals=None, min_slice=0, max_slice=48):
        """
        Debugging method to check dimensions of prior the construction of the Jacobian and residuals.

        This method prints lengths and shapes of rows, cols, values, and residuals to help identify dimension mismatches before constructing the Jacobian.
        """
        
        print(f"Debugging dimensions for {self.name}:")
        print(f"  Number of residuals (const): {self.num_residuals}")
        print(f"  Length of rows: {len(self._rows) if self._rows is not None else 'None'}")
        print(f"  Length of cols: {len(self._cols) if self._cols is not None else 'None'}")
        if values is not None:
            print(f"  Length of values: {len(values) if values is not None else 'None'}")
        if residuals is not None:
            print(f"  Length of residuals: {len(residuals) if residuals is not None else 'None'}")

        # Print pairs of (row, col) for the first few entries to check alignment
        if self._rows is not None and self._cols is not None:
            print("  First 24 (row, col) pairs:")
            for i in range(min_slice, min(max_slice, len(self._rows))):
                if values is not None:
                    print(f"    ({self._rows[i]}, {self._cols[i]}) \t-> value: {values[i]:.3e}")
                else:
                     print(f"    ({self._rows[i]}, {self._cols[i]})")

        
        print("  End of debug.\n")

    def set_weigth(self, w):
        """
        Set the weight factor for the constraint.
        
        Args:
            w (float): Weight factor.
        """
        self.w = w

# ============================================================================
# BACKWARD COMPATIBILITY ALIAS
# ============================================================================
# For existing code that uses "Constraint" class name
Constraint = ObjectiveTerm

# Module-level documentation for deprecation
__all__ = ['ObjectiveTerm', 'Constraint']  # Export both names
