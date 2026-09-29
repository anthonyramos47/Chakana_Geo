"""
Lie sphere geometry: oriented spheres as points of the Lie quadric, pencils,
midpoints, and cyclidic families / envelopes.
"""

import numpy as np
from hanan.geometry.algebraic import unit


def lie_inner_prod(lp1, lp2):
    """
    Inner product for the Lie quadric with signature (+ + + + - -).

    Args:
        lp1: Point in Lie projective space (6,).
        lp2: Point in Lie projective space (6,).

    Returns:
        Scalar <lp1, lp2>_L.
    """

    v1 = lp1[:-2]
    v2 = lp2[:-2]

    n1 = lp1[-2:]
    n2 = lp2[-2:]

    return v1@v2 - n1@n2


def base_vector(n, i):
    """
    Canonical basis vector e_i in R^n.

    Args:
        n: Dimension of the space.
        i: Index of the axis (0 to n-1).

    Returns:
        (n,) ndarray with 1 at position i and 0 elsewhere.
    """
    if i < 0 or i >= n:
        raise ValueError("Index out of bounds for base vector")
    vec = np.zeros(n)
    vec[i] = 1.0
    return vec


def set_lie_coordinates(val_n, val_0, val_einf, val_r):
    """
    Assemble a Lie sphere from its positional and basis components.

    Args:
        val_n: Positional coordinates (3,).
        val_0: Coefficient for basis e0.
        val_einf: Coefficient for basis e_inf.
        val_r: Radius coefficient.

    Returns:
        Lie point as a (6,) ndarray.
    """
    n = len(val_n) + 3  # Size of vector

    en1 = base_vector(n, n-3)
    en2 = base_vector(n, n-2)
    en3 = base_vector(n, n-1)

    e0 = 0.5 * (en2 - en1)
    einf = 0.5 * (en2 + en1)

    v_n = np.sum([val_n[i] * base_vector(n, i) for i in range(3)], axis=0)

    return val_0 * e0 + val_einf * einf + v_n + val_r * en3


def normalize_lie_sphere(lie_sphere):
    """
    Normalize a Lie sphere with respect to the e0 coefficient.

    Args:
        lie_sphere: Lie sphere point (6,).

    Returns:
        Normalized Lie sphere (6,) with e0 coefficient equal to 1.
    """
    n = len(lie_sphere) - 3  # Size of vector

    factor = lie_sphere[-2] - lie_sphere[-3]
    if factor == 0:
        return lie_sphere  # Avoid division by zero
    else:
        return lie_sphere/factor


def map_lie_s_to_sphere(lieS):
    """
    Convert a Lie sphere back to (center, radius).

    Args:
        lieS: Lie sphere point (6,).

    Returns:
        center: Sphere center (3,).
        radius: Sphere radius (float).
    """
    n = len(lieS) - 3  # Size of vector
    

    
    factor = lieS[-2] - lieS[-3]
    center = lieS[:n]/factor
    radius = lieS[-1]/factor

    # check for nan
    if np.isnan(radius) or np.isnan(center).any():
        print(f"factror = {factor}, lieS = {lieS}")

    return center, radius


def boundary_lie_sphere_cyclide(x, xi, n):
    """
    Boundary sphere of a Dupin cyclide (Bobenko & Huhnen-Venedey).

    Args:
        x: Point x on the surface (3,).
        xi: Adjacent point xi (3,).
        n: Surface normal at x (3,).

    Returns:
        Lie sphere (6,) representing the boundary sphere of the cyclide.
    """
    #print(f"Boundary cyclide: x = {x}, xi = {xi}, n = {n}")
    delta_x  = xi - x
    dot_dx_n = delta_x @ n

    if np.isclose(dot_dx_n,0):
        value_n   = n
        value_inf = 2 * x @ n 

        return set_lie_coordinates(value_n, 0, value_inf, 1.0)
    
    else:
        dot_x_n = x @ n
        norm_dx = np.linalg.norm(delta_x)
        norm_x  = np.linalg.norm(x)

        value_n   = x + (norm_dx**2)/(2 * dot_dx_n) * n
        value_inf = (norm_x**2 * dot_dx_n + norm_dx**2 * dot_x_n )/(dot_dx_n)
        value_r   = norm_dx**2/(2*(dot_dx_n))

        return set_lie_coordinates(value_n, 1.0, value_inf, value_r)


def lie_midpoint(x, xi, ti):
    """
    Midpoint sphere in Lie representation between two surface points.

    Args:
        x: Point x (3,).
        xi: Point xi (3,).
        ti: Tangent direction at x toward xi (3,).

    Returns:
        Lie sphere (6,) at the midpoint between x and xi.
    """
    # Delta
    dx = xi - x
    # Norm
    norm_dx = np.linalg.norm(dx)

    v = norm_dx * ti  + dx 
    rho = norm_dx**2 / (2 * (dx @ v))
    
    y_vec = x + rho * v
    return set_lie_coordinates(y_vec, 1, y_vec@y_vec, 0)


def get_tangent_vector(x, xi, u, v):
    """
    Select the tangent direction at x toward xi from a local frame {u, v}.

    Args:
        x: Current surface point (3,).
        xi: Target surface point (3,).
        u: First tangent vector of the local frame (3,).
        v: Second tangent vector of the local frame (3,).

    Returns:
        The frame vector (u or v) most aligned with the direction x → xi.
    """

    delta_x = unit(xi - x)
    dot_dx_u = delta_x @ u
    dot_dx_v = delta_x @ v

    if np.isclose(dot_dx_u, 0) and np.isclose(dot_dx_v, 0):
        return u  # Default to u if both are zero

    if np.isclose(dot_dx_u, 0):
        return v  # If u is zero, return v
    if np.isclose(dot_dx_v, 0):
        return u  # If v is zero, return u

    # Choose the vector with the larger dot product
    if dot_dx_u > dot_dx_v:
        return u
    else:
        return v


def cyclidic_family_lie(lie_sphere_1,  lie_sphere_2,  lie_sphere_3 ):
    """
    Define a one-parameter cyclidic family from three Lie spheres.

    Args:
        lie_sphere_1: First boundary Lie sphere (6,).
        lie_sphere_2: Midpoint Lie sphere (6,).
        lie_sphere_3: Second boundary Lie sphere (6,).

    Returns:
        sphere_matrix: (6, 3) matrix of the three Lie spheres as columns.
        coefficients: (3,) array of inner-product coefficients for evaluation.
    """
    # Define the sphere coordinates as columns of a matrix
    sph_math = np.array([lie_sphere_1, lie_sphere_2, lie_sphere_3]).T

    # Compute the coefficients of the cyclidic family
    a12 = lie_inner_prod(lie_sphere_1, lie_sphere_2)
    a13 = lie_inner_prod(lie_sphere_1, lie_sphere_3)
    a23 = lie_inner_prod(lie_sphere_2, lie_sphere_3)

    #print(f"Coefficients: a12 = {a12}, a13 = {a13}, a23 = {a23}")

    return sph_math, np.array([a23, a13, a12])


def eval_cyclidic_family_lie(sphere_matrix, coefficients, t):
    """
    Evaluate a cyclidic family at parameter t ∈ [0, 1].

    Args:
        sphere_matrix: (6, 3) matrix from cyclidic_family_lie.
        coefficients: (3,) coefficient array from cyclidic_family_lie.
        t: Evaluation parameter in [0, 1].

    Returns:
        Lie sphere (6,) at parameter t.
    """
    

    t_vector = np.array([2 * t**2 - 3 * t + 1, t - t**2, 2 * t**2 - t])  # Quadratic polynomial for evaluation
    # Compute the linear combination of the spheres
    lie_sphere = np.sum([coefficients[i] * sphere_matrix[:, i] * t_vector[i] for i in range(len(coefficients))], axis=0)

    

    # Normalize the result with respect to e0
    return lie_sphere


def envelope_point(cyclidic_f1, cyclidic_f2, t1, t2):
    """
    Envelope point of two cyclidic families at parameter pair (t1, t2).

    Args:
        cyclidic_f1: First cyclidic family as (sphere_matrix, coefficients).
        cyclidic_f2: Second cyclidic family as (sphere_matrix, coefficients).
        t1: Parameter in [0, 1] for the first family.
        t2: Parameter in [0, 1] for the second family.

    Returns:
        Lie sphere (6,) — a point-sphere on the envelope.
    """
    # Evaluate the cyclidic families at parameter t
    sphere1 = eval_cyclidic_family_lie(cyclidic_f1[0], cyclidic_f1[1], t1)
    sphere2 = eval_cyclidic_family_lie(cyclidic_f2[0], cyclidic_f2[1], t2)


    r1 = sphere1[-1]  # Radius of the first sphere
    r2 = sphere2[-1]  # Radius of the second sphere

    # Envelope point calculation
    point = ( r2 * sphere1 - r1 * sphere2 )

    if np.linalg.norm(point) == 0:
        print("Warning Envelop ons phere near 0")
        print("sphere1: ", sphere1)
        print("sphere2: ", sphere2)

    # Check is a point
    #print(f"Point radius = {point[-1]}")

    # Combine the results to form the Dupin envelope
    return point
