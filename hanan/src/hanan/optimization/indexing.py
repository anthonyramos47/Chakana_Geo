"""
Index helpers for packing per-element variables into the optimizer's flat vector.
"""

import numpy as np


def interleave_indices_dim(arr, n=3):
    """
    Interleaved flattened per-coordinate indices for stacked arrays.

    Args:
        arr: 1-D index array of length K.
        n: Number of coordinates per element (default: 3).

    Returns:
        Flattened index array of length K*n with interleaved coordinates.
    """
    multiplied = arr * n
    for i in range(1, n):
        multiplied = np.vstack([multiplied, arr * n + i])
    return multiplied.flatten('F')
