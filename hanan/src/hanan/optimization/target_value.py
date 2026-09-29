import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm


class TargetValue(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Template constraint
        Energy to set a target value to a variable.
        E_{Target Value} = \sum_{var} ( var - target )^2 
        """
        super().__init__()
        self.name = "Target Value" # Name of the constraint
        
        self.targetValue = None # Reference length of the edges
        
        # Cont for weight decrease
        self.cont = 0


      
    def initialize_objective(self, X, var_idx, var_name, targetValue) -> None:
        """ 
        We assume knots are normalized
        Input:
            X : Variables
            var_idx     : dictionary of indices of variables
            var_name    : Name of the variable
            vv_e        : Edges indices
        """
        
        # Store target value
        if len(targetValue) == 1:
            self.targetValue = targetValue[0] * np.ones(len(var_idx[var_name]))
        elif len(targetValue) == len(var_idx[var_name]):
            self.targetValue = targetValue 
        else:
            raise ValueError("TargetValue: targetValue length does not match variable length")

        # Set residuals
        self.num_residuals = len(var_idx[var_name])

        # Set idx variables
        self.var_idx = var_idx[var_name]

        # Store rows and cols of the Jacobian structure for constant term
        self._rows_const   = np.arange(len(var_idx[var_name]))
        self._cols_const   = var_idx[var_name]
        self._values_const = np.ones(len(var_idx[var_name]))
        
    def grad(self, X):
        return None

    def res(self, X):
        return X[self.var_idx] - self.targetValue



        
        