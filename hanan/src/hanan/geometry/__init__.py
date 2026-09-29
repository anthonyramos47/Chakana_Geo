"""
hanan.geometry — half-edge mesh, geometric primitives, constructions and measures.

Submodules: mesh, algebraic, primitives, construction, measures, conical, lie,
isotropic_geometry, io. `hanan.geometry.utils` re-exports all of them for
convenience (`from hanan.geometry.utils import ...`).
"""

# ── Core mesh class ───────────────────────────────────────────────────────────
from .mesh import Mesh

# ── Vector algebra ─────────────────────────────────────────────────────────
from .algebraic import (
    unit,
    normalize,
    proj,
    barycenters,
    barycentric_coordinates,
    orth_proj,
    vec_dot,
    hat,
    rotation_matrix,
    make_param_grid_vec,
    angle_vectors,
    np_pop,
)

# ── Points, lines, planes, circles, spheres ────────────────────────────────
from .primitives import (
    distance_point_plane,
    circle_3pts,
    plane_plane_intersection,
    clip_line_to_convex_face,
    reflect_point_line,
    reflect_point_plane,
    plane_normal,
    dist_point_plane,
    project_point_plane,
    clst_point_lines,
    foot_point_line,
    dist_point_line,
    line_plane_inter,
    reflect_plane,
    reflect_point,
    circle_3d,
    circular_arc,
    plane_patch,
    project_to_sphere,
    sphere_inversion,
)

# ── Mesh and curve construction ────────────────────────────────────────────
from .construction import (
    normalize_vertices,
    cylinder,
    loft_curves,
    catmull_clark_subdivision,
    dodecahedron,
    polysphere,
    get_barycentric_coords,
    interpolate_triangle_mesh,
    merge_meshes,
    merge_curves,
    offset_curve,
)

# ── Per-face measures ──────────────────────────────────────────────────────
from .measures import (
    compute_face_normals,
    face_planarity,
    compute_planarity,
    planarity_measure_quad_mesh,
    compute_circumcircles_quad_mesh,
)

# ── Cones and conical meshes ───────────────────────────────────────────────
from .conical import (
    oriented_cone,
    cone_strip,
    cone_strip_mesh,
    rotational_cone_radius,
    half_angle_rotational_cone,
    cone_axis_from_planes,
    compute_cone_axes,
    sphere_center_on_cone_axis,
    mesh_axes_intersections,
    conical_mesh_smallest_curvature_sphere,
    mesh_cone_axis_smallest_sphere,
)

# ── Lie sphere geometry ────────────────────────────────────────────────────
from .lie import (
    lie_inner_prod,
    base_vector,
    set_lie_coordinates,
    normalize_lie_sphere,
    map_lie_s_to_sphere,
    boundary_lie_sphere_cyclide,
    lie_midpoint,
    get_tangent_vector,
    cyclidic_family_lie,
    eval_cyclidic_family_lie,
    envelope_point,
)

# ── Isotropic geometry ─────────────────────────────────────────────────────
from .isotropic_geometry import (
    iso_sphere_to_sphere,
    i_inverse_point,
    i_scale_point,
    i_translate_point,
    i_csphere_sphere,
    i_point_to_or_plane,
    i_csphere_inverse_point,
    get_ri_cyl_sphere_auto_inverse,
    compute_auto_inverse_sphere_radius,
)

# ── I/O ─────────────────────────────────────────────────────────────────────
# (mesh data for drawing lives in hanan.glyphs)
from .io import (
    get_color,
    hex_to_norm_rgb,
    read_obj,
    write_obj,
    read_off,
    triangulate_quads,
    mathematica_v,
)
