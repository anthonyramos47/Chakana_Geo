import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm


class FixValueVariable(ObjectiveTerm):

    def __init__(self) -> None:
        r""" Template constraint
        Energy to set a target value to a variable.
        E_{Target Value} = \sum_{var} ( var - target )^2 
        """
        super().__init__()
        self.name = "Fix Value Variable" # Name of the constraint
        
        self.targetValue = None # Reference length of the edges
        
        # Cont for weight decrease
        self.cont = 0

      
    def initialize_objective(self, X, var_idx, var_name, indices, targetValues) -> None:
        """ 
        We assume knots are normalized
        Input:
            X : Variables
            var_idx     : dictionary of indices of variables
            var_name    : Name of the variable
            indices     : Indices of the variables to fix
            targetValues: Target values to fix the variables to
        """
        
        # Store target value
        if len(targetValues) == 1:
            self.targetValue = targetValues[0] * np.ones(len(var_idx[var_name][indices]))
        elif len(targetValues) == len(var_idx[var_name][indices]):
            self.targetValue = targetValues 
        else:
            raise ValueError("TargetValue: targetValue length does not match variable length")

        # Set residuals
        self.num_residuals = len(indices)

        # Set idx variables
        self.var_idx = var_idx[var_name][indices]   

        # Store rows and cols of the Jacobian structure for constant term
        self._rows_const   = np.arange(len(var_idx[var_name][indices]))
        self._cols_const   = var_idx[var_name][indices]
        self._values_const = np.ones(len(var_idx[var_name][indices]))
        
    def grad(self, X):
        return None

    def res(self, X):
        return X[self.var_idx] - self.targetValue



        
        