# Call parent class
from hanan.optimization.objective_term import ObjectiveTerm
import numpy as np



class Planarity(ObjectiveTerm):

    def __init__(self) -> None:
        """ Template constraint
        Planarity: Energy that minimize deviation from a face from planarity
        Energy :   sum_F sum_vi in F ||(vi - vi+1) . n_f||^2; where F is a face
        """
        super().__init__()
        self.name = "Planarity" # Name of the constraint
  
        
        
      
    def initialize_objective(self, X, var_idx,  faces, vertices_name="v", face_normals_name="n_f" ) -> None:
        """ 
        Input:
            X : Variables
            var_idx : dictionary of indices of variables
            l_faces : List of faces to planarize
            var_name: Name of the variable to be optimized
            nf_name : Name of the variable use as auxiliary normal
        """ 
        
        # Vertices indices
        v_idx = var_idx[vertices_name].reshape(-1, 3)      # Variable to move
        n_idx = var_idx[face_normals_name].reshape(-1, 3)  # Auxiliary normals

        # Init indices
        self.vi_indices   = []
        self.vip1_indices = []
        self.nf_indices    = []
        
    
        number_rows = 0
        self._cols = []
        self._rows = []
        
        # Column indices
        for i, f in enumerate(faces):
            
            vi   = v_idx[f[:-1]]     # vi
            vip1 = v_idx[f[1:]]      # vi+1
            n_f  = n_idx[i]          # nf

            columns = np.column_stack((vi, vip1, np.tile(n_f, (len(f)-1, 1)))).flatten() # Columns for vi, vi+1 and nf
            self._cols.extend(columns) # Columns vi vi+1 and nf  
            self._rows.extend(np.arange(number_rows, (number_rows + (len(f) - 1) ) ).repeat(9)) # Rows for the current face
            number_rows +=  (len(f) - 1) 

            self.vi_indices.extend(vi.flatten())
            self.vip1_indices.extend(vip1.flatten())
            self.nf_indices.extend(np.tile(n_f, (len(f)-1, 1)).flatten())
        
        self.num_residuals = number_rows

    def _vars(self, X):
        vi  = X[self.vi_indices]
        vi1 = X[self.vip1_indices]
        nf  = X[self.nf_indices]
        vii = (vi1 - vi).reshape(-1, 3)
        return vi, vi1, nf, vii

    def grad(self, X):
        vi, vi1, nf, vii = self._vars(X)
        d_vi   = -nf.reshape(-1, 3)
        d_vip1 =  nf.reshape(-1, 3)
        d_nf   =  vii
        return np.column_stack((d_vi, d_vip1, d_nf)).flatten()

    def res(self, X):
        vi, vi1, nf, vii = self._vars(X)
        return np.einsum("ij,ij->i", vii, nf.reshape(-1, 3))

        
