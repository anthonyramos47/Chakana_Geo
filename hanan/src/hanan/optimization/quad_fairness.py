import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm

class QuadFairness(ObjectiveTerm):

    def __init__(self) -> None:
        """
        Template constraint for minimizing the deviation of the mesh from a fair surface.
        The energy function is given by:
            E_{fair} = ∑_{vi,vj,vk in Mesh} || 2 vi - vj - vk ||^2
        This energy penalizes irregularities by comparing differences between vertex positions.

        Implementation based on the following paper:
        Form-finding with polyhedral meshes made simple
        Authors: Chengcheng Tang, Xiang Sun, Alexandra Gomes, Johannes Wallner, Helmut Pottmann
        ACM Transactions on Graphics (TOG), Volume 33, Issue 4
        """
        super().__init__()
        self.name = "QuadFairness"  # Base name of the constraint
        
        # Counter for tracking iterations (used for weight decrease updates)
        self.count = 0

    def initialize_objective(self, X, var_idx, var_name, vertex_idx, adj_v, dim, damp_factor, damp_iteration) -> None:
        """
        Initialize the fairness constraint using mesh connectivity information.
        
        
        Inputs:
            X       : Global variable array containing the mesh vertex positions.
            var_idx : Dictionary mapping variable names to their corresponding indices in X.
            var_name: Name of the variable (for example, vertex positions).
            vertex_idx : Indices of the vertices corresponding to the variable.
            adj_v   : List of lists where each sublist contains the indices of adjacent vertices for a given vertex.
            dim     : Dimensionality of the vertex positions (e.g., 2 or 3).
            damp_factor : After certain number of iterations, the weight of the constraint is decreased by multiplying it with this factor.
            damp_iteration : The number of iteration when the weight decrease is set to 0.
        """
        # Update the constraint name with the specific variable name.
        self.name = "QuadFairness_" + var_name
        self.dim = dim



        
        # Check that all vertices have valence 4
        assert all(len(neighbors) == 4 for neighbors in adj_v), "All vertices must have valence 4 for QuadFairness."

        indicesVertices = var_idx[var_name].reshape(-1, dim)
        # Set the decrease factor and step.
        self.damp_factor = damp_factor
        self.damp_iteration = damp_iteration
        # Two residuals per quad vertex (u and v directions)
        self.num_residuals = len(vertex_idx) * dim * 2 
        # Two residuals per quad vertex (u and v directions)
        self._rows_const = []
        self._cols_const = []
        self._values_const = []

        # Two residuals per quad vertex (u and v directions)
        self.v1_idx = []
        self.v2_idx = []
        self.v3_idx = []
        self.v4_idx = []
        self.vi_idx = indicesVertices[vertex_idx].flatten()  # Indices for the central vertex vi


        for i, neigh in enumerate(adj_v):
            
            v1, v2, v3, v4 = neigh  # Four neighbors for vertex i
    
            self.v1_idx.extend( indicesVertices[v1].tolist()  )
            self.v2_idx.extend( indicesVertices[v2].tolist()  )
            self.v3_idx.extend( indicesVertices[v3].tolist()  )
            self.v4_idx.extend( indicesVertices[v4].tolist()  )

            indices_rows = np.arange(i*2*dim, (i+1)*2*dim).repeat(3)  # Two residuals per vertex, each with dim components, repeated for vi, vj, vk

            # First term = 2 * vi - v1 - v3
            columns_first_residual = np.vstack((indicesVertices[vertex_idx[i]], indicesVertices[v1], indicesVertices[v3])).transpose().flatten()  # Flatten to get a 1D array of column indices

            # Second term = 2 * vi - v2 - v4
            columns_second_residual = np.vstack((indicesVertices[vertex_idx[i]], indicesVertices[v2], indicesVertices[v4])).transpose().flatten()   
        
            # Values 
            values = [2.0, -1.0, -1.0] * dim # Coefficients for the first residual


            # First residual: du = 2*vi - vj - vk  (for neighbors v1 and v3)
            self._rows_const.extend( indices_rows )
            self._cols_const.extend( columns_first_residual.tolist() )
            self._values_const.extend( values )

            # Second residual: dv = 2*vi - vj - vk  (for neighbors v2 and v4)
            self._cols_const.extend( columns_second_residual.tolist() )                                
            self._values_const.extend( values )

        
    def grad(self, X):
        if self.count <= self.damp_iteration:
            self.w *= self.damp_factor
        else:
            self.w = 0
        self.count += 1
        return None

    def res(self, X):
        X_vi = X[self.vi_idx]
        X_v1 = X[self.v1_idx]
        X_v2 = X[self.v2_idx]
        X_v3 = X[self.v3_idx]
        X_v4 = X[self.v4_idx]
        res1 = 2 * X_vi - X_v1 - X_v3
        res2 = 2 * X_vi - X_v2 - X_v4
        return np.column_stack((res1.reshape(-1, self.dim), res2.reshape(-1, self.dim))).flatten()
