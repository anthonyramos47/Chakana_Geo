"""
Algebraic Operations and Vector Utilities

This file contains functions for vector normalization, projection,
barycentric coordinate calculations, and other basic algebraic operations.
"""

import numpy as np

def unit(v):
    """
    Normalize a vector or array of row-vectors to unit length.

    Args:
        v: 1-D vector (3,) or 2-D array (N, 3) of row-vectors.

    Returns:
        Array of same shape as v with each row normalized to unit length.
    """
    if len(v.shape) == 1:
        return v / np.linalg.norm(v)
    return v / np.linalg.norm(v, axis=1)[:, None]

def normalize(M, axis=1):
    """
    Normalize rows (or columns) of a matrix, skipping zero-norm entries.

    Args:
        M: Array of shape (N, D) or (D, N).
        axis: Axis along which norms are computed (default: 1, i.e. row-wise).

    Returns:
        Array of same shape as M with each row (or column) normalized.
    """
    norms = np.linalg.norm(M, axis=axis, keepdims=True)
    # Create a mask for non-zero norms
    mask = norms > 0
    # Initialize output array with zeros
    normalized = np.zeros_like(M)
    # Only normalize non-zero vectors
    normalized[mask.squeeze()] = M[mask.squeeze()] / norms[mask, None]
    return normalized

def proj(v, u):
    """
    Project vector v onto direction u.

    Args:
        v: Vector or (N, 3) array of row-vectors.
        u: Direction vector or (N, 3) array.

    Returns:
        Scalar projection component (or (N,) array for batched input).
    """
    v = np.array(v)
    u = np.array(u)
    vu = vec_dot(v, u)
    uu = vec_dot(u, u)
    if len(v.shape) == 1 and len(u.shape) == 1:
        return (vu / uu) * u
    return (vu / uu)[:, None] * u

def barycenters(v, f):
    """
    Arithmetic mean (centroid) of each face.

    Args:
        v: Vertex positions, shape (V, 3).
        f: Face index lists, shape (F,) of variable-length lists.

    Returns:
        Barycenters array of shape (F, 3).
    """
    bary = np.zeros((len(f), 3))
    for i, face in enumerate(f):
        bary[i] = np.sum(v[face], axis=0) / len(face)
    return bary

def barycentric_coordinates(vi, vj, vk, vl):
    """
    Barycentric coordinates of point vl with respect to triangle (vi, vj, vk).

    Args:
        vi: First triangle vertex (3,).
        vj: Second triangle vertex (3,).
        vk: Third triangle vertex (3,).
        vl: Query point (3,).

    Returns:
        Tuple (u, v, w) of floats summing to 1.
    """
    A = np.vstack([vi, vj, vk])
    return tuple(np.linalg.solve(A, vl))

def orth_proj(v, u):
    """
    Component of v orthogonal to direction u (i.e. v − proj(v, u) * û).

    Args:
        v: Vector or (N, 3) array.
        u: Direction to project out.

    Returns:
        Vector perpendicular to u, same shape as v.
    """
    return v - proj(v, u)

def vec_dot(v1, v2, ax=1):
    """
    Row-wise dot product of two arrays.

    Args:
        v1: Array of shape (N, 3) or (3,).
        v2: Array of shape (N, 3) or (3,).
        ax: Summation axis (default: 1, row-wise).

    Returns:
        Scalar for 1-D inputs, or (N,) array for batched inputs.
    """
    if len(v1.shape) == 1 and len(v2.shape) == 1:
        return v1 @ v2
    if ax == 1:
        return np.einsum('ij,ij->i', v1, v2)
    return np.einsum('ij,ij->j', v1, v2)

def hat(v):
    """
    Skew-symmetric (cross-product) matrix for vector v.

    Args:
        v: 3-D vector (3,).

    Returns:
        (3, 3) skew-symmetric ndarray such that hat(v) @ u == cross(v, u).
    """
    if len(v.shape) == 1:
        return np.array([[0, -v[2], v[1]],
                         [v[2], 0, -v[0]],
                         [-v[1], v[0], 0]])
    
def rotation_matrix(axis, angle):
    """
    Rodrigues rotation matrix around axis by angle radians.

    Args:
        axis: Rotation axis (3,); need not be unit length.
        angle: Rotation angle in radians.

    Returns:
        (3, 3) rotation matrix.
    """
    axis = unit(axis)
    cos_angle = np.cos(angle)
    sin_angle = np.sin(angle)
    

    return np.eye(3) * cos_angle + \
           sin_angle * hat(axis) + \
           (1 - cos_angle) * np.outer(axis, axis)


#======================================== LIE DUPIN CYCLIDES ========================================

def make_param_grid_vec(I1, I2, n, m, *, dtype=float):
    """
    Vectorised parametric grid for an n × m subdivision of I1 × I2.

    Args:
        I1: (a, b) interval tuple for the first parameter.
        I2: (a, b) interval tuple for the second parameter.
        n: Number of subdivisions in the first direction.
        m: Number of subdivisions in the second direction.
        dtype: NumPy dtype for the output arrays (default: float64).

    Returns:
        V: Sample points (t1, t2), shape (n*m, 2).
        F: Quad face indices (CCW), shape ((n-1)*(m-1), 4).
        t1: Parameter values along first axis, shape (n,).
        t2: Parameter values along second axis, shape (m,).
    """
    a1, b1 = I1
    a2, b2 = I2

    # ─── vertices ──────────────────────────────────────────────────────────────
    t1 = np.linspace(a1, b1, n, dtype=dtype)          # (n+1,)
    t2 = np.linspace(a2, b2, m, dtype=dtype)          # (m+1,)
    # meshgrid with indexing='xy' → first axis = t2, second = t1
    V = np.stack(np.meshgrid(t1, t2, indexing='xy'), axis=-1).reshape(-1, 2)

    # ─── connectivity ─────────────────────────────────────────────────────────
    # Lay indices out as a 2-D grid
    idx = np.arange((m) * (n), dtype=np.int64).reshape(m, n)

    # Four corner arrays (broadcasted, then flattened)
    v0 = idx[:-1, :-1].ravel()         # lower-left
    v1 = idx[:-1, 1: ].ravel()         # lower-right
    v2 = idx[1: , 1: ].ravel()         # upper-right
    v3 = idx[1: , :-1].ravel()         # upper-left

    F = np.column_stack((v0, v1, v2, v3))                 # (m*n, 4)

    return V, F, t1, t2

def angle_vectors(vec1, vec2):
    """
    Angle in radians between two vectors.

    Args:
        vec1: First vector (3,).
        vec2: Second vector (3,).

    Returns:
        Angle in radians as a float.
    """
    unit_vec1 = unit(vec1)
    unit_vec2 = unit(vec2)
    dot_product = np.clip(np.dot(unit_vec1, unit_vec2), -1.0, 1.0)
    angle = np.arccos(dot_product)
    return angle

# ─── Array utilities ──────────────────────────────────────────────────────────

def np_pop(arr, index=-1):
    """
    Mimic list.pop() for a 1-D NumPy array (non-destructive).

    Args:
        arr: 1-D NumPy array.
        index: Index of the element to remove (default: -1, last element).

    Returns:
        popped_value: The element at index.
        new_array: Array with that element removed.
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError("Input must be a NumPy array")
    if arr.ndim != 1:
        raise ValueError("np_pop is for one-dimensional arrays")
    if arr.size == 0:
        raise IndexError("pop from empty array")
    if index < 0:
        index += arr.size
    if index < 0 or index >= arr.size:
        raise IndexError("pop index out of range")
    return arr[index], np.delete(arr, index)


# ── Frames ────────────────────────────────────────────────────────────────────
#
# A *frame* is a dict {"pt", "u", "v", "n"} describing an orthonormal pair (u, v)
# tangent to a face with normal n, based at the point pt. Optionally carries "f",
# the face index it belongs to. Used by the Dupin cyclide propagation.


