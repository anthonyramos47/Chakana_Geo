import numpy as np
import igl
from hanan.optimization.objective_term import ObjectiveTerm


class ProximityReference(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Template constraint
        Energy to approximate a reference surface. 
        E_{proximity} = \sum_{var} ||vi - v_prox||^2 
        Reference surface is a dense triangular mesh.
        """
        super().__init__()
        self.name = "proximity_reference" # Name of the constraint
        
        self.V_ref = None # Reference positions
        self.F_ref = None # Reference faces
    
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

        # Set residuals
        self.num_residuals = len(var_idx[var_name]) 

        # Set idx variables
        self.var_idx = var_idx[var_name]   

        # Store rows and cols of the Jacobian structure for position term
        self._rows_const   = np.arange(len(self.var_idx))
        self._cols_const   = self.var_idx
        self._values_const = np.ones(len(self._cols_const))

        
    def grad(self, X):
        return None

    def res(self, X):
        var = X[self.var_idx]
        _, _, v_proj = igl.point_mesh_squared_distance(var.reshape(-1, 3), self.V_ref, self.F_ref)
        return var - v_proj.reshape(-1)



        
        