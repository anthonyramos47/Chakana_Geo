import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm
from scipy.sparse import csr_matrix


class LaplacianFairness(ObjectiveTerm):

    def __init__(self) -> None:
        """
        Template constraint for minimizing to smooth a surface using Laplacian Fairness
        The energy function is given by:
            E_{fair} = ∑_{vi in Mesh} || vi - (sum_vk vk )/|Adj(vk)| ||^2
        This energy penalizes irregularities by comparing differences between vertex positions.

        Implementation based on the following paper:
        Form-finding with polyhedral meshes made simple
        Authors: Chengcheng Tang, Xiang Sun, Alexandra Gomes, Johannes Wallner, Helmut Pottmann
        ACM Transactions on Graphics (TOG), Volume 33, Issue 4
        """
        super().__init__()
        self.name = "Fairness"  # Base name of the constraint
        
        # For vertices with valence not equal to 4 (non-quads)
        self.M_avg = None  # Averaging matrix for neighbors
        self.cont = 0  # Counter for weight decrease

        # # Decrease factor and step to progressively reduce the constraint weight.
        # self.dec_factor = None  # Factor by which to decrease the weight
        # self.dec_step = None    # Number of iterations between weight decreases

        # Counter for tracking iterations (used for weight decrease updates)
        self.cont = 0

    def initialize_objective(self, X, var_idx, var_name, vertex_idx, adj_v, dim, damp_factor, damp_iteration) -> None:
        """
        Initialize the fairness constraint using mesh connectivity information.
        
        
        Inputs:
            X       : Global variable array containing the mesh vertex positions.
            var_idx : Dictionary mapping variable names to their corresponding indices in X.
            var_name: Name of the variable (for example, "vertex").
            vertex_idx: Indices of the vertices corresponding to the variable.
            adj_v   : List of lists where each sublist contains the indices of adjacent vertices for a given vertex.
            dim     : Dimensionality of the vertex positions (e.g., 2 or 3).
            damp_factor : Decrease factor for constraint weight.
            damp_iteration: Number of iterations after which the weight is set 0.
        """
        # Update the constraint name with the specific variable name.
        self.name = "Lap_Fairness_" + var_name
        self.dim = dim

        self.damp_factor = damp_factor
        self.damp_iteration = damp_iteration

        self.vertex_idx = vertex_idx
        self.adj_v = adj_v

        self.vi_idx = var_idx[var_name].reshape(-1, dim)

        # number of vertices
        self.num_vertices = len(self.vi_idx)

        # Total number of residuals
        self.num_residuals = len(vertex_idx) * dim

        self._rows_const = []
        self._cols_const = []
        self._values_const = []

        # All global X indices for every vertex, shaped (total_vertices, dim)
        all_xi = var_idx[var_name].reshape(-1, dim)

        # A_avg: shape (num_vertices*dim, len(X))
        # A_avg @ X  gives the neighbor average for each local vertex (all dims)
        avg_row, avg_col, avg_data = [], [], []

        # Loop over vi vertices
        for i, neigh in enumerate(adj_v):

            if neigh:
                # Get number of neighbors
                Nv = len(neigh)

                # Row indices is dim*i to dim*(i+1) repeated for each neighbor + 1
                self._rows_const.extend( np.tile( np.arange(self.dim * i, self.dim * (i + 1)), Nv + 1 ).tolist() )


                # Cols indices for vi (global X indices)
                col_vi = all_xi[vertex_idx[i]]

                self._cols_const.extend(col_vi.tolist())
                self._values_const.extend(np.ones(dim).tolist())

                w = - 1.0 / float(Nv)

                # Loop over neighbors of vi
                for j_global in neigh:
                    vals = [w] * dim
                    # Global X indices for neighbor vj
                    col_vj = all_xi[j_global]
                    self._cols_const.extend(col_vj.tolist())
                    self._values_const.extend(vals)

                    # A_avg: neighbor averaging using full X (global indices)
                    for d in range(dim):
                        avg_row.append(vertex_idx[i] * dim + d)
                        avg_col.append(j_global * dim + d)
                        avg_data.append(1.0 / float(Nv))

        self.A_avg = csr_matrix((avg_data, (avg_row, avg_col)),
                                shape=(self.num_vertices * dim, self.num_vertices * dim))
        

        set_total_vertices = set(np.arange(len(all_xi)))
        set_vertex_idx = set(vertex_idx)

        # Take the difference 
        missing_vertices = set_total_vertices - set_vertex_idx

        # for mv in missing_vertices:
        #     print(f" Sum A[{mv}] = {self.A_avg[dim*mv:dim*(mv)].sum()} (vertex {mv} not in vertex_idx so sum should be 0)")

        self.all_xi = all_xi




    def grad(self, X):
        if self.cont <= self.damp_iteration:
            self.w *= self.damp_factor
        else:
            self.w = 0
        self.cont += 1
        return None

    def res(self, X):
        vi = X[self.vi_idx].reshape(-1)
        res = vi - self.A_avg @ vi
        return res.reshape(-1, self.dim)[self.vertex_idx].reshape(-1)