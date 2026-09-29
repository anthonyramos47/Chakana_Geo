import numpy as np
from hanan.optimization.objective_term import ObjectiveTerm
from hanan.optimization.indexing import interleave_indices_dim

class Corner(ObjectiveTerm):

    def __init__(self) -> None:
        r"""
        Template constraint for minimizing the corner energy of a mesh.
        The energy function is given by:
            E_{fair} = ∑_{c in V} || (vl - c)\|vl - c| .(vr - c)\|vr - c| - cosA - |previous values| ||^2
        The energy is computed for each vertex c, where vl and vr are the left and right neighbors of c.
    
        """

        super().__init__()
        self.name = "Corner"  # Base name of the constraint

        self.vl = None  # Left neighbor vertex indices
        self.vr = None  # Right neighbor vertex indices
        self.c  = None  # Corner vertex indices
        

    def initialize_objective(self, X, var_idx, var_name, corners, cornerAdjList, targetAngle) -> None:
        """
        Initialize the fairness constraint using mesh connectivity information.
        
        
        Inputs:
            X       : Global variable array containing the mesh vertex positions.
            var_idx : Dictionary mapping variable names to their corresponding indices in X.
            var_name : Name of the variable (e.g., "vertices").
            corners  : List of corner vertex indices.
            cornerAdjList : List of lists where each sublist contains the indices of the left and right neighbors for a given corner vertex.
            targetAngle : Desired angle at the corner (in degrees) or list of angles for each corner. If None or empty, it will be set to the initial angle at each corner.
        """

        # Check adjacency list length
        assert len(cornerAdjList) == len(corners), "Length of adjacency list must match number of corners."

        # Check has only two neighbors
        assert all(len(neighbors) == 2 for neighbors in cornerAdjList), "All corners must have exactly two neighbors."

        cornerAdjList = np.array(cornerAdjList)

        lv = cornerAdjList[:,0]
        rv = cornerAdjList[:,1]

        
        self.c  = var_idx[var_name][interleave_indices_dim(corners, 3)]
        self.vl = var_idx[var_name][interleave_indices_dim(lv, 3)]
        self.vr = var_idx[var_name][interleave_indices_dim(rv, 3)]

        self.num_residuals = len(corners)

        # Check if targetAngle is one value or a list of values
        if targetAngle is None or targetAngle == []:
            print("Target angle set to initial ")
            self.cosA = np.einsum( 'ij,ij->i', X[self.vl].reshape(-1,3) - X[self.c].reshape(-1,3), X[self.vr].reshape(-1,3) - X[self.c].reshape(-1,3))/np.linalg.norm( X[self.vl].reshape(-1,3) - X[self.c].reshape(-1,3), axis=1 )/np.linalg.norm( X[self.vr].reshape(-1,3) - X[self.c].reshape(-1,3), axis=1 )
        elif isinstance(targetAngle, (int, float)):
            self.cosA = np.cos(np.full(self.num_residuals, targetAngle * np.pi / 180))
        elif len(targetAngle) == self.num_residuals:
            self.cosA = np.cos(np.array(targetAngle) * np.pi / 180)
        else:
            print("Target angle set to 90 degrees by default.")
            self.cosA = np.cos(np.full(self.num_residuals, 90 * np.pi / 180))

        # Compute previous lengths for normalization
        lengthsVL = np.linalg.norm( X[self.vl].reshape(-1,3) - X[self.c].reshape(-1,3), axis=1 )
        lengthsVR = np.linalg.norm( X[self.vr].reshape(-1,3) - X[self.c].reshape(-1,3), axis=1 )

        self.divFactor = lengthsVL * lengthsVR

        self.previous_values = np.abs( np.einsum('ij,ij->i',
                                          (X[self.vl].reshape(-1,3) - X[self.c].reshape(-1,3)) ,
                                          (X[self.vr].reshape(-1,3) - X[self.c].reshape(-1,3)) 
                                        )/self.divFactor - self.cosA)
        

         # Prepare sparse matrix indices
        self._rows = np.arange(self.num_residuals).repeat(3*3)
        self._cols = np.column_stack( (self.c.reshape(-1,3), self.vl.reshape(-1,3), self.vr.reshape(-1,3)) ).flatten()
   

    def grad(self, X):
        c  = X[self.c]
        vl = X[self.vl]
        vr = X[self.vr]
        vrc = (vr - c).reshape(-1, 3)
        vlc = (vl - c).reshape(-1, 3)
        dvl = vrc / self.divFactor[:, np.newaxis]
        dvr = vlc / self.divFactor[:, np.newaxis]
        dc  = -(dvl + dvr)
        diff = np.einsum('ij,ij->i', vrc, vlc) / self.divFactor - self.cosA
        self.previous_values = np.abs(diff)
        self.divFactor = (np.linalg.norm(vlc, axis=1) * np.linalg.norm(vrc, axis=1))
        return np.column_stack((dc, dvl, dvr)).flatten()

    def res(self, X):
        c  = X[self.c]
        vl = X[self.vl]
        vr = X[self.vr]
        vrc = (vr - c).reshape(-1, 3)
        vlc = (vl - c).reshape(-1, 3)
        return np.einsum('ij,ij->i', vrc, vlc) / self.divFactor - self.cosA