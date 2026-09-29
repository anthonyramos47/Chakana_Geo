# Call parent class
from hanan.optimization.objective_term import ObjectiveTerm
from hanan.optimization.indexing import interleave_indices_dim
import numpy as np



class Cyclicity(ObjectiveTerm):

    def __init__(self) -> None:
        """ Ciclity: Energy term that minimize the deviation of a face from being cyclic
        The energy function is given by:
        Energy :   sum_F sum_vi in F ||(vi+1 - vi) . (mi - cf)||^2 + || (vi - cf) . nf||^2;
          where F is a face
            mi = (vi + vi+1)/2
            cf is an auxiliary variable representing the circumcenter of the face
        """
        super().__init__()
        self.name = "Circularity" # Name of the constraint
        
        
      
    def initialize_objective(self, X, var_idx, l_faces, var_name, cf_name, nf_name) -> None:
        """ 
        Input:
            X : Variables
            var_idx : dictionary of indices of variables
            l_faces : List of faces of the mesh
            var_name: Name of the variable to be optimized
            cf_name : Name of the variable use as auxiliary circumcenter
            nf_name : Name of the variable use as auxiliary normal
        """ 
        
        # Vertices indices
        v_idx = var_idx[var_name]
        c_idx = var_idx[cf_name]
        n_idx = var_idx[nf_name]
        
        # Filtrate the faces that have 4 vertices
        faces = [f for f in l_faces if len(f) == 4]

        # Init indices
        self.vi  = []
        self.vi1 = []
        self.cf  = []
        self.nf  = []
        
        
        # Column indices
        num_faces = len(faces)

        rows_circ = []
        rows_plan = []
        cols_circ = []
        cols_plan = []
        for i, f in enumerate(faces):

            # Get the indices of the vertices
            v0 = v_idx[interleave_indices_dim(f[0],3)]
            v2 = v_idx[interleave_indices_dim(f[2],3)]
            v3 = v_idx[interleave_indices_dim(f[3],3)]
            v1 = v_idx[interleave_indices_dim(f[1],3)]

            # Get indices of the normals
            cf_idx = c_idx[interleave_indices_dim(i, 3)]  
            nf_idx = n_idx[interleave_indices_dim(i, 3)]  

            vi   = np.array([v0, v1, v2, v3]).reshape(-1, 3)
            
            vip1 = np.array([v1, v2, v3, v0]).reshape(-1, 3)
            cf   = np.array([cf_idx]*4).reshape(-1, 3)
            nf   = np.array([nf_idx]*4).reshape(-1, 3)
                     

            # Add indices to the list each sum has (vi - vi+1) . nf
            self.vi.extend([v0, v1,  v2, v3])
            self.vi1.extend([v1, v2, v3, v0])
            self.cf.extend([cf_idx]*4)
            self.nf.extend([nf_idx]*4)

            # First term goes in the first |F|*4 rows and the second term in the next |F|*4 rows
            # Add rows for First term (vi - vi+1) . (mi - cf)
            # Repeated 9 times for the 3 components of vi, vi+1 and cf
            rows_circ.extend( np.arange(4*i, 4*i + 4).repeat(9).tolist() )
            # Add rows for Second term (vi - cf) . nf
            # Repeated 12 times for the 3 components of vi, vj, cf and nf
            rows_plan.extend( np.arange(num_faces*4 + 4*i, num_faces*4 + 4*i + 4).repeat(12).tolist() )

            # Add column indices
            cols_circ.extend( np.column_stack((vi, vip1, cf)).flatten().tolist())
            cols_plan.extend( np.column_stack((vi, vip1, cf, nf)).flatten().tolist())

            

        self.num_residuals = num_faces * 8

        self._rows = np.array(rows_circ + rows_plan)
        self._cols = np.array(cols_circ + cols_plan)


        # Flatten the indices
        self.vi  = np.array(self.vi).flatten()
        self.vi1 = np.array(self.vi1).flatten()
        self.cf  = np.array(self.cf).flatten()
        self.nf  = np.array(self.nf).flatten()

    def grad(self, X):
        vi  = X[self.vi]
        vi1 = X[self.vi1]
        cf  = X[self.cf]
        nf  = X[self.nf]
        mij = (vi + vi1) * 0.5
        df1_vi  = -vi + cf
        df1_vi1 =  vi1 - cf
        df1_cf  = -vi1 + vi
        df2_vi = df2_vi1 = nf * 0.5
        df2_cf = -nf
        df2_nf =  mij - cf
        values_circ = np.column_stack((df1_vi.reshape(-1, 3), df1_vi1.reshape(-1, 3), df1_cf.reshape(-1, 3))).flatten()
        values_plan = np.column_stack((df2_vi.reshape(-1, 3), df2_vi1.reshape(-1, 3), df2_cf.reshape(-1, 3), df2_nf.reshape(-1, 3))).flatten()
        return np.concatenate((values_circ, values_plan))

    def res(self, X):
        vi  = X[self.vi]
        vi1 = X[self.vi1]
        cf  = X[self.cf]
        nf  = X[self.nf]
        vii    = (vi1 - vi).reshape(-1, 3)
        mij    = ((vi + vi1) / 2).reshape(-1, 3)
        circum = cf.reshape(-1, 3)
        res_circ = np.einsum("ij,ij->i", vii, mij - circum)
        res_plan = np.einsum("ij,ij->i", mij - circum, nf.reshape(-1, 3))
        return np.concatenate((res_circ, res_plan))
