import numpy as np

def iso_sphere_to_sphere(i_sphere):
    """
    Convert an isotropic 4-D point back to (center, radius).

    Args:
        i_sphere: Isotropic 4-D representation (4,).

    Returns:
        center: Sphere center (3,).
        radius: Sphere radius (float).
    """
    r = i_sphere[0] + i_sphere[3]
    c3 = (i_sphere[0] - i_sphere[3])
    c1 = -i_sphere[1]
    c2 = -i_sphere[2] 
    return np.array([c1, c2, c3]), r

def i_inverse_point(point):
    """
    Inversion of a point in isotropic space (divides by the squared xy-norm).

    Args:
        point: Point in isotropic space (3,).

    Returns:
        Inverted point (3,).
    """
    return point/ (point[:2]@ point[:2])

def i_scale_point(point, scale):
    """
    Scale a point in isotropic space by a scalar factor.

    Args:
        point: Point (3,).
        scale: Scaling factor (float).

    Returns:
        Scaled point (3,).
    """
    return point * scale

def i_translate_point(point, translation):
    """
    Translate a point in isotropic space by a given vector.

    Args:
        point: Point (3,).
        translation: Translation vector (3,).

    Returns:
        Translated point (3,).
    """
    return point + translation

def i_csphere_sphere(i_center, i_radius, center, radius):
    """
    Express a Euclidean sphere in the coordinate frame of an isotropic cylindrical sphere.

    Args:
        i_center: 2-D center of the isotropic cylindrical sphere (2,).
        i_radius: Radius of the isotropic cylindrical sphere.
        center: Center of the Euclidean sphere (3,).
        radius: Radius of the Euclidean sphere.

    Returns:
        Isotropic cylindrical sphere representation (4,).
    """
    mx, my = i_center[0], i_center[1]
    ri = i_radius
    c1,c2,c3 = center[0], center[1], center[2]
    r = radius

    vec = [
    (-2*c1*mx - 2*c2*my + c3*(-1 + mx**2 + my**2) + (1 + mx**2 + my**2)*r) / (2 * ri**2),
    -c1 + mx*(c3 + r + c3/ri**2) - (mx * (-2*c1*mx - 2*c2*my + r + (mx**2 + my**2)*(c3 + r))) / (ri**2),
    -c2 + my*(c3 + r) - (my * (-2*c1*mx - 2*c2*my + c3*(-1 + mx**2 + my**2) + (1 + mx**2 + my**2)*r)) / (ri**2),
    c1*mx + c2*my - (mx**2 + my**2)*(c3 + r) + ((mx**2 + my**2) * (-2*c1*mx - 2*c2*my + c3*(-1 + mx**2 + my**2) + (1 + mx**2 + my**2)*r)) / (2 * ri**2) + 0.5*(c3 + r)*ri**2] 

    return np.array(vec)


def i_point_to_or_plane(i_point):
    """
    Convert a point in isotropic space to its oriented-plane representation.

    Args:
        i_point: Point in isotropic space (3,).

    Returns:
        Oriented plane as [nx, ny, nz, h] (4,).
    """
    factor = i_point[:-1]@ i_point[:-1]

    return 1 / (1 + factor) * np.array([
        2*i_point[0],
        2*i_point[1],
        (1 - factor),
        2*i_point[-1],
    ])
    
    

def i_csphere_inverse_point(i_center, i_radius, point):
    """
    Invert a point with respect to an isotropic cylindrical sphere.

    Args:
        i_center: 2-D center of the isotropic cylindrical sphere (2,).
        i_radius: Radius of the isotropic cylindrical sphere.
        point: Point to transform (3,).

    Returns:
        Inverted point (3,).
    """
    # Extended the point to 3D if it is 2D

    return i_translate_point( i_scale_point(i_inverse_point(i_scale_point(i_translate_point(point, - i_center), 1/i_radius)), i_radius), i_center)


def get_ri_cyl_sphere_auto_inverse(v, angle, axis, r, mx, my):
    """
    Function that compute the radius of a i-sphere of cylindrical type with
    center mx, my so that the sphere cx, cy, cz, r is auto_inverse w.r.t the cylindrical sphere.
    cx = v[0] + r/sin(angle) * axis[0]
    cy = v[1] + r/sin(angle) * axis[1]
    cz = v[2] + r/sin(angle) * axis[2]
    return ri**2
    """

    d = mx**2 + my**2
    sa = np.sin(angle)

    vx, vy, vz = v
    ax, ay, az = axis

    ri2 = d - 1 - 2 * (sa * (vx * mx + vy * my) + r * (ax* mx + ay * my)) / (sa * (vz + r) + r * az) 

    return ri2

def compute_auto_inverse_sphere_radius(v, angle, axis, mx, my, ri2):
    """
    Function that compute the radius of the sphere whose isotropic representation is auto_inverse w.r.t the cylindrical sphere of center mx, my and radius ri2 = ri**2 (can be negative).
        cx = v[0] + r/sin(angle) * axis[0]
        cy = v[1] + r/sin(angle) * axis[1]
        cz = v[2] + r/sin(angle) * axis[2]
    return cx, cy, cz, r
    """
    d = mx**2 + my**2
    sa = np.sin(angle)

    vx, vy, vz = v
    ax, ay, az = axis

    r = ( 2 * (vx * mx + vy * my) -  vz * (d -1 - ri2) )/ ( (1/sa) * ( az * (d - 1 - ri2 ) - 2 * ax * mx - 2 * ay * my) + d - 1 - ri2)

    cx = v[0] + r/sa * axis[0]
    cy = v[1] + r/sa * axis[1]
    cz = v[2] + r/sa * axis[2]

    return cx, cy, cz, r