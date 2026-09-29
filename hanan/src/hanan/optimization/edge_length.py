import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm
from hanan.optimization.indexing import interleave_indices_dim


class EdgeLength(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Template constraint
        Energy to constraint the length of edges, to be greater than a reference length.
        E_{Edge_Lenght} = \sum_{e} ( ||vj - vi||^2 - l0^2 - Abs(||vj - vi||^2 - l0^2) )^2 
        """
        super().__init__()
        self.name = "Edge_Lenght" # Name of the constraint
        self.aux_idx = None # Auxiliar variable index
        self.l = None # Reference length of the edges
        
        # Cont for weight decrease
        self.cont = 0


      
    def initialize_objective(self, X, var_idx, var_name, vv_e, length_target=None) -> None:
        """ 
        We assume knots are normalized
        Input:
            X : Variables
            var_idx     : dictionary of indices of variables
            var_name    : Name of the variable
            vv_e        : Edges indices
        """
        
        # Get the nodes
        v = X[var_idx[var_name]]
        v = v.reshape(-1, 3)

        vi = vv_e[0]
        vj = vv_e[1]

    
        # Get the indices of the vertices
        self.vi_idx = var_idx[var_name][interleave_indices_dim(vi, 3)]
        self.vj_idx = var_idx[var_name][interleave_indices_dim(vj, 3)]

        # Number of residuals equals number of edges
        self.num_residuals = len(vi)

        # Store rows and cols of the Jacobian structure
        self._rows = np.arange(self.num_residuals).repeat(6) # 6 derivatives per edge (3 for vi, 3 for vj)
        self._cols = np.column_stack([self.vi_idx, self.vj_idx]).flatten()
        
        if length_target is None:
            # Use current edge lengths as target lengths
            self.l = np.linalg.norm( v[vj] - v[vi], axis=1 )**2
        elif len(length_target)==1:
            # Use single provided target length
            self.l = length_target[0]**2 * np.ones(len(vv_e[0]))
        elif len(length_target)==len(vi):
            # Use provided target lengths per edge
            self.l = length_target**2
        else:
            print("No valid target length provided")

        # Store previous value of the difference 
        #self.prev_diff = np.abs(np.linalg.norm(v[vj] - v[vi], axis=1)**2 - self.l)
        
    def grad(self, X):
        vi  = X[self.vi_idx]
        vj  = X[self.vj_idx]
        vvi = (vj - vi).reshape(-1, 3)
        d_vi = -2 * vvi
        d_vj =  2 * vvi
        return np.column_stack([d_vi.flatten(), d_vj.flatten()]).flatten()

    def res(self, X):
        vi  = X[self.vi_idx]
        vj  = X[self.vj_idx]
        vvi = (vj - vi).reshape(-1, 3)
        return np.einsum('ij,ij->i', vvi, vvi) - self.l



        
        