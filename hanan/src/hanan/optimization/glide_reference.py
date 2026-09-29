import numpy as np
import igl
from hanan.optimization.objective_term import ObjectiveTerm


class GlideReference(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Template constraint
        Energy to approximate a reference surface. 
        E_{proximity} = \sum_{var} ((vi - v_prox) . n_prox)^2 
        Reference surface is a dense triangular mesh.
        """
        super().__init__()
        self.name = "glideReference" # Name of the constraint
        
        self.V_ref = None # Reference positions
        self.F_ref = None # Reference faces
        self.N_ref = None # Reference normals
    
        # Cont for weight decrease
        self.cont = 0

      
    def initialize_objective(self, X, var_idx, var_name, V_ref, F_ref) -> None:
        """ 
        We assume knots are normalized
        Input:
            X : Variables
            var_idx     : dictionary of indices of variables
            var_name    : Name of the variable
            V_ref       : Reference positions
            F_ref       : Reference faces
        """
        
        # Store reference values
        self.V_ref = V_ref
        self.F_ref = np.array(F_ref)
        # self.N_ref = np.cross( V_ref[self.F_ref[:,1]] - V_ref[self.F_ref[:,0]], 
        #                        V_ref[self.F_ref[:,2]] - V_ref[self.F_ref[:,0]] )
        # self.N_ref = self.N_ref / np.linalg.norm(self.N_ref, axis=1)[:,np.newaxis]  
    

        # Set residuals
        self.num_residuals = len(var_idx[var_name].reshape(-1, 3)) 

        # Set idx variables
        self.var_idx = var_idx[var_name]   

        # Initialize normals at projection points
        pts = X[self.var_idx].reshape(-1,3)
        _, _, v_proj = igl.point_mesh_squared_distance(pts, self.V_ref, self.F_ref)
        self.N_ref = pts - v_proj
        self.N_ref = self.N_ref / (np.linalg.norm(self.N_ref, axis=1)[:,np.newaxis] + 1e-8)



        # Store rows and cols of the Jacobian structure for position term
        self._rows  = np.arange(self.num_residuals).repeat(3)
        self._cols  = self.var_idx
    
        
    def grad(self, X):
        pts = X[self.var_idx].reshape(-1, 3)
        _, _, v_proj = igl.point_mesh_squared_distance(pts, self.V_ref, self.F_ref)
        values = self.N_ref.flatten()
        # Update normals for next iteration
        self.N_ref = pts - v_proj
        self.N_ref = self.N_ref / (np.linalg.norm(self.N_ref, axis=1)[:, np.newaxis] + 1e-8)
        return values

    def res(self, X):
        pts = X[self.var_idx].reshape(-1, 3)
        _, _, v_proj = igl.point_mesh_squared_distance(pts, self.V_ref, self.F_ref)
        return np.einsum('ij,ij->i', (pts - v_proj), self.N_ref)



        
        