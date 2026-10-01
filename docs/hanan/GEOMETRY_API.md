# Geometry API Reference

`hanan.geometry` — generated from the source docstrings (signatures are exact).
Import from a submodule, or use the convenience namespace that re-exports all of them:

```python
from hanan.geometry.primitives import circle_3d        # specific module
from hanan.geometry.utils import circle_3d, read_obj    # everything in one namespace
```

| Module | Contents |
|---|---|
| [`algebraic`](#algebraic) | Algebraic Operations and Vector Utilities (12) |
| [`primitives`](#primitives) | Points, lines, planes, circles and spheres: distances, projections, reflections, intersections, circle fits, sphere inversion. (20) |
| [`construction`](#construction) | Building meshes and curves: normalization, primitive solids, subdivision, lofting, offsets, barycentric interpolation, and merging pieces into one mesh. (11) |
| [`measures`](#measures) | Per-face quality measures: normals, planarity, circularity, circumcircles. (5) |
| [`conical`](#conical) | Cones of revolution and conical meshes: cones tangent to sphere pairs, cone strips, vertex cone axes and curvature spheres of conical meshes. (11) |
| [`lie`](#lie) | Lie sphere geometry: oriented spheres as points of the Lie quadric, pencils, midpoints, and cyclidic families / envelopes. (11) |
| [`isotropic_geometry`](#isotropic_geometry) | Isotropic geometry (9) |
| [`io`](#io) | Colormaps and mesh file I/O (OBJ, OFF). (7) |
| [`hanan.glyphs`](#glyphs) | Glyphs — mesh data for drawing geometric objects. (13) |
| [`mesh`](MESH_API.md) | `Mesh` — half-edge data structure (separate reference) |

Dependency order (no cycles): `algebraic` → `primitives` → `construction`, `measures`, `conical`;
`lie` → `algebraic`. `hanan.optimization.indexing` holds `interleave_indices_dim`.

## Conventions

**Planes.** Every plane in hanan is a pair `(n, h)` describing `n · x + h = 0`
(`n` unit normal, so `n · p + h` is the signed distance of `p`). The plane through a
point `c` with normal `n` is `(n, -n·c)`. `plane_plane_intersection` also accepts a
point on each plane in place of the scalar offset.

**Lie sphere coordinates.** Six components `(x, y, z, e₁, e₂, e₃)` with signature
`(+ + + + − −)`; `e0 = (e₂ − e₁)/2`, `e∞ = (e₂ + e₁)/2`. A sphere with center `c` and
signed radius `r` is `set_lie_coordinates(c, 1, c·c − r², r)`; point spheres have `r = 0`.

**Batching.** Most point functions accept a single `(3,)` point or an `(N, 3)` array.

---

## algebraic

Algebraic Operations and Vector Utilities

#### `unit(v)`
Normalize a vector or array of row-vectors to unit length.

**Args**
- v: 1-D vector (3,) or 2-D array (N, 3) of row-vectors.

**Returns**
- Array of same shape as v with each row normalized to unit length.

#### `normalize(M, axis=1)`
Normalize rows (or columns) of a matrix, skipping zero-norm entries.

**Args**
- M: Array of shape (N, D) or (D, N).
- axis: Axis along which norms are computed (default: 1, i.e. row-wise).

**Returns**
- Array of same shape as M with each row (or column) normalized.

#### `proj(v, u)`
Project vector v onto direction u.

**Args**
- v: Vector or (N, 3) array of row-vectors.
- u: Direction vector or (N, 3) array.

**Returns**
- Scalar projection component (or (N,) array for batched input).

#### `barycenters(v, f)`
Arithmetic mean (centroid) of each face.

**Args**
- v: Vertex positions, shape (V, 3).
- f: Face index lists, shape (F,) of variable-length lists.

**Returns**
- Barycenters array of shape (F, 3).

#### `barycentric_coordinates(vi, vj, vk, vl)`
Barycentric coordinates of point vl with respect to triangle (vi, vj, vk).

**Args**
- vi: First triangle vertex (3,).
- vj: Second triangle vertex (3,).
- vk: Third triangle vertex (3,).
- vl: Query point (3,).

**Returns**
- Tuple (u, v, w) of floats summing to 1.

#### `orth_proj(v, u)`
Component of v orthogonal to direction u (i.e. v − proj(v, u) * û).

**Args**
- v: Vector or (N, 3) array.
- u: Direction to project out.

**Returns**
- Vector perpendicular to u, same shape as v.

#### `vec_dot(v1, v2, ax=1)`
Row-wise dot product of two arrays.

**Args**
- v1: Array of shape (N, 3) or (3,).
- v2: Array of shape (N, 3) or (3,).
- ax: Summation axis (default: 1, row-wise).

**Returns**
- Scalar for 1-D inputs, or (N,) array for batched inputs.

#### `hat(v)`
Skew-symmetric (cross-product) matrix for vector v.

**Args**
- v: 3-D vector (3,).

**Returns**
- (3, 3) skew-symmetric ndarray such that hat(v) @ u == cross(v, u).

#### `rotation_matrix(axis, angle)`
Rodrigues rotation matrix around axis by angle radians.

**Args**
- axis: Rotation axis (3,); need not be unit length.
- angle: Rotation angle in radians.

**Returns**
- (3, 3) rotation matrix.

#### `make_param_grid_vec(I1, I2, n, m, *, dtype=float)`
Vectorised parametric grid for an n × m subdivision of I1 × I2.

**Args**
- I1: (a, b) interval tuple for the first parameter.
- I2: (a, b) interval tuple for the second parameter.
- n: Number of subdivisions in the first direction.
- m: Number of subdivisions in the second direction.
- dtype: NumPy dtype for the output arrays (default: float64).

**Returns**
- V: Sample points (t1, t2), shape (n*m, 2).
- F: Quad face indices (CCW), shape ((n-1)*(m-1), 4).
- t1: Parameter values along first axis, shape (n,).
- t2: Parameter values along second axis, shape (m,).

#### `angle_vectors(vec1, vec2)`
Angle in radians between two vectors.

**Args**
- vec1: First vector (3,).
- vec2: Second vector (3,).

**Returns**
- Angle in radians as a float.

#### `np_pop(arr, index=-1)`
Mimic list.pop() for a 1-D NumPy array (non-destructive).

**Args**
- arr: 1-D NumPy array.
- index: Index of the element to remove (default: -1, last element).

**Returns**
- popped_value: The element at index.
- new_array: Array with that element removed.


## primitives

Points, lines, planes, circles and spheres: distances, projections, reflections, intersections, circle fits, sphere inversion.

#### `distance_point_plane(point, normal, plane_distance)`
Signed distance from a point to the plane normal · x + h = 0.

Same as dist_point_plane (kept for existing callers).

**Args**
- point: Query point (3,).
- normal: Plane normal (3,).
- plane_distance: Plane offset h in n · x + h = 0.

**Returns**
- Signed distance as a float.

#### `circle_3pts(p1, p2, p3)`
Circumcircle of three points (or batches of three points).

**Args**
- p1: First point (3,) or (N, 3).
- p2: Second point (3,) or (N, 3).
- p3: Third point (3,) or (N, 3).

**Returns**
- center: Circumcenter (N, 3).
- normal: Circle plane normal (N, 3).
- radius: Circumradius (N,).

#### `plane_plane_intersection(n1, d1, n2, d2)`
Line of intersection of two planes n1 · x + d1 = 0 and n2 · x + d2 = 0.

**Args**
- n1: Normal of plane 1 (3,).
- d1: Offset of plane 1 (scalar h in n · x + h = 0), or a point on the plane (3,).
- n2: Normal of plane 2 (3,).
- d2: Offset of plane 2 (scalar h in n · x + h = 0), or a point on the plane (3,).

**Returns**
- (point_on_line, direction) tuple, or (None, None) if planes are parallel.

#### `clip_line_to_convex_face(point, direction, verts, *, eps=1e-12)`
Sutherland-Hodgman clipping of line point + t*direction against a convex polygon.

**Args**
- point: 3-vector lying in the face plane.
- direction: 3-vector lying in the face plane (non-zero).
- verts: (M, 3) array of face vertices in CCW or CW order.
- eps: Tolerance for zero/parallel detection (default: 1e-12).

**Returns**
- (t_min, t_max) parameter interval, or (None, None) if the line misses the face.

#### `reflect_point_line(point, line_point, line_direction)`
Reflect point(s) across a line defined by a point and a direction.

The reflection is 2·f − p, where f is the foot of p on the line.

**Args**
- point: Point to reflect (3,), or points (N, 3).
- line_point: A point on the line (3,).
- line_direction: Direction of the line (3,); need not be unit length.

**Returns**
- Reflected point (3,), or (N, 3) for batched input.

#### `reflect_point_plane(point, plane_normal, plane_distance)`
Reflect a point across the plane n · x + h = 0.

**Args**
- point: Point to reflect (3,).
- plane_normal: Unit normal of the plane (3,).
- plane_distance: Plane offset h in n · x + h = 0.

**Returns**
- Reflected point (3,).

#### `plane_normal(points)`
Compute the unit normal of a plane through N >= 3 points.

With exactly 4 points they must be in cyclic (quad) order: the normal is the
cross product of the diagonals p0→p2 and p1→p3.

- N == 3: cross product of the two edge vectors from the first point.
- N == 4: cross product of the two diagonals (robust for quads).
- N  > 4: SVD best-fit normal (least-squares plane).

**Args**
- points: (N, 3) array of 3-D points.

**Returns**
- Unit normal vector, shape (3,).

**Raises**
- ValueError: if fewer than 3 points or points are not 3-D.

#### `dist_point_plane(p, n, h)`
Signed distance from point(s) p to the plane n · x + h = 0.

**Args**
- p: Point (3,) or point cloud (N, 3).
- n: Plane normal (3,).
- h: Plane offset scalar, plane n · x + h = 0.

**Returns**
- Signed distance as a float for single points, or (N,) array for point clouds.

#### `project_point_plane(p, n, h)`
Project point(s) p onto the plane n · x + h = 0.

**Args**
- p: Point (3,) or point cloud (N, 3).
- n: Plane normal (3,).
- h: Plane offset scalar, plane n · x + h = 0.

**Returns**
- Projected point(s), same shape as p.

#### `clst_point_lines(p1, d1, p2, d2, tol=1e-10)`
Closest points between two lines; returns their intersection when lines are coplanar.

**Args**
- p1: Point on line 1 (3,).
- d1: Direction of line 1 (3,).
- p2: Point on line 2 (3,).
- d2: Direction of line 2 (3,).
- tol: Tolerance for zero/parallel detection (default: 1e-10).

**Returns**
- f1: Closest point on line 1 (3,).
- f2: Closest point on line 2 (3,).
- m: Midpoint of f1 and f2 (3,).

#### `foot_point_line(point, line_point, line_dir)`
Foot (closest point) on a line to a given point.

**Args**
- point: Query point (3,) or (N, 3).
- line_point: A point on the line (3,).
- line_dir: Direction vector of the line (3,); need not be unit length.

**Returns**
- Foot point (3,), or (N, 3) array for batched input.

#### `dist_point_line(point, line_point, line_dir)`
Distance from a point to a line defined by a point and direction.

**Args**
- point: Query point (3,) or (N, 3).
- line_point: A point on the line (3,).
- line_dir: Direction vector of the line (3,); need not be unit length.

**Returns**
- Scalar distance, or (N,) array for batched input.

#### `line_plane_inter(line, plane)`
Intersection of a line with a plane.

**Args**
- line: (p, v) tuple — point on the line (3,) and direction (3,).
- plane: (n, h) tuple — plane n · x + h = 0 (normal (3,) and offset scalar).

**Returns**
- Intersection point (3,), or None if the line is parallel to the plane.

#### `reflect_plane(n, h, m, j)`
Reflect plane (n, h) across mirror plane (m, j).

Planes are n · x + h = 0 (n unit normal). The reflection of a point p across
the mirror plane m · x + j = 0 is
    p' = p - 2*(m·p + j)*m
Applying this to the foot point p0 = -h*n (on the original plane) and to the
direction n gives the reflected plane.

**Args**
- n: Normal of the plane to reflect (3,) or (N, 3).
- h: Offset of the plane to reflect, scalar or (N,).
- m: Normal of the mirror plane (3,), unit vector.
- j: Offset of the mirror plane, scalar.

**Returns**
- n_r: Reflected plane normal, same shape as n.
- h_r: Reflected plane offset, same shape as h.

#### `reflect_point(p, n, h)`
Reflect point(s) p across the plane n · x + h = 0.

**Args**
- p: Point (3,) or point cloud (N, 3).
- n: Plane unit normal (3,).
- h: Plane offset scalar, plane n · x + h = 0.

**Returns**
- Reflected point(s), same shape as p.

#### `circle_3d(center, normal, radius, pts=100)`
Sample points on a 3-D circle.

**Args**
- center: Circle center (3,).
- normal: Circle plane normal (3,).
- radius: Circle radius.
- pts: Number of sample points (default: 100).

**Returns**
- Circle points (pts, 3).

#### `circular_arc(center, normal, radius, p0, p1, num_points=20)`
Points along the arc from p0 to p1 on a circle.

**Args**
- center: Circle center (3,).
- normal: Circle plane normal (3,).
- radius: Circle radius.
- p0: Start point on the circle (3,).
- p1: End point on the circle (3,).
- num_points: Number of sample points (default: 20).

**Returns**
- Arc points (num_points, 3).

#### `plane_patch(p0, n, size=(1, 1))`
Build a finite rectangular plane patch as a mesh.

**Args**
- p0:   Center of the patch (3,).
- n:    Plane normal (3,).
- size: (width, height) of the patch (default: (1, 1)).

**Returns**
- vertices: (4, 3) corner positions.
- faces:    [[0, 1, 2, 3]] single quad face.

#### `project_to_sphere(vertices, center, radius=1)`
Project vertices onto a sphere by normalising each offset from center.

**Args**
- vertices: Vertex positions (V, 3).
- center: Sphere center (3,).
- radius: Target sphere radius (default: 1).

**Returns**
- Projected vertex positions (V, 3).

#### `sphere_inversion(points, center, radius)`
Möbius inversion of points with respect to a sphere.

**Args**
- points: Points to invert (N, 3).
- center: Sphere center (3,).
- radius: Sphere radius.

**Returns**
- Inverted points (N, 3).


## construction

Building meshes and curves: normalization, primitive solids, subdivision, lofting, offsets, barycentric interpolation, and merging pieces into one mesh.

#### `normalize_vertices(v, factor=1)`
Translate and scale vertices so the longest bounding-box dimension equals factor.

**Args**
- v: Vertex positions (V, 3).
- factor: Target longest dimension (default: 1).

**Returns**
- Normalized vertex array (V, 3).

#### `cylinder(center, radius, normal, height, numPtsCircumference=20, numPtsHeight=20)`
Generate a quad-mesh cylinder aligned with normal.

**Args**
- center: Center of the cylinder base (3,).
- radius: Cylinder radius.
- normal: Axis direction (3,).
- height: Cylinder height.
- numPtsCircumference: Circumference sample count (default: 20).
- numPtsHeight: Height sample count (default: 20).

**Returns**
- V: Vertex positions (V, 3).
- F: Quad face indices (F, 4).

#### `loft_curves(c1, c2)`
Loft two curves into a quad mesh.

Given two curves of N points each, builds N-1 quads connecting them:
    face k = [c1[k], c1[k+1], c2[k+1], c2[k]]

**Args**
- c1: First curve, (N, 3) array or list of points.
- c2: Second curve, (N, 3) array or list of points.

**Returns**
- vertices: (2*N, 3) array — c1 points followed by c2 points.
- faces: list of (N-1) quad index lists.

#### `catmull_clark_subdivision(vertices, faces)`
One level of Catmull-Clark subdivision for general polygonal meshes.

**Args**
- vertices: Vertex positions (V, 3) or list of (3,) points.
- faces: Face index lists (each element is a list of vertex indices).

**Returns**
- new_vertices: Subdivided vertex positions as ndarray.
- new_faces: Subdivided quad face index lists.
- parent_map: Dict mapping original face index to list of new face indices.

#### `dodecahedron()`
Dodecahedron mesh with 20 vertices and 12 pentagonal faces.

**Returns**
- vertices: Vertex positions (20, 3).
- faces: List of 12 pentagonal face index lists.

#### `polysphere(center, radius, subdivision=2)`
Mesh approximation of a sphere (dodecahedron + Catmull-Clark subdivision, projected).

**Args**
- center: Sphere center (3,).
- radius: Sphere radius.
- subdivision: Number of Catmull-Clark subdivision levels (default: 2).

**Returns**
- vertices: Vertex positions (V, 3).
- faces: Quad face index lists.

#### `get_barycentric_coords(points, vertices, faces)`
Barycentric coordinates of arbitrary points projected onto a triangle mesh.

**Args**
- points: Query points (N, 3).
- vertices: Mesh vertex positions (V, 3).
- faces: Triangle face indices (F, 3) as a NumPy array.

**Returns**
- bary_coords: Barycentric coordinates (N, 3).
- idi: First vertex indices of the closest face (N,).
- idj: Second vertex indices of the closest face (N,).
- idk: Third vertex indices of the closest face (N,).

#### `interpolate_triangle_mesh(points, vertices, faces, values)`
Interpolate scalar or vector values at arbitrary points using barycentric coordinates.

**Args**
- points: Query points (N, 3).
- vertices: Mesh vertex positions (V, 3).
- faces: Triangle face indices (F, 3) as a NumPy array.
- values: Per-vertex values (V,) or (V, D).

**Returns**
- Interpolated values at each query point (N,) or (N, D).

#### `merge_meshes(V_list, F_list)`
Merge a list of meshes into a single mesh with re-indexed faces.

**Args**
- V_list: List of vertex arrays, each of shape (n_i, 3).
- F_list: List of face arrays; each element can be a NumPy array or list of index lists.

**Returns**
- V_merged: Concatenated vertex array (V_total, 3).
- F_merged: Face index list with globally re-indexed vertices.

#### `merge_curves(curve_list)`
Merge a list of curves into a single curve network with re-indexed edges.

**Args**
- curve_list: List of curve point arrays, each of shape (n_i, 3).

**Returns**
- merged_points: All points concatenated (total_points, 3).
- edges: Edge index array (E, 2) with globally re-indexed endpoints.

#### `offset_curve(curve, direction, offset_distance_out=1.0, offset_distance_in=1.0)`
Offset a curve in both directions and build connecting quad faces.

**Args**
- curve: Curve points (N, 3).
- direction: Per-point offset directions (N, 3).
- offset_distance_out: Outward offset distance (default: 1.0).
- offset_distance_in: Inward offset distance (default: 1.0).

**Returns**
- vertices: Offset vertices (2*N, 3) — outward then inward.
- faces: Quad face index lists connecting the two offset curves.


## measures

Per-face quality measures: normals, planarity, circularity, circumcircles.

#### `compute_face_normals(vertices, faces)`
Unit normals at each face for triangle, quad, and general n-gon meshes.

- Triangles : cross product of the two edge vectors from vertex 0.
- Quads     : cross product of the two diagonals (more robust than one triangle).
- n-gons    : mean of cross products over consecutive edge triplets.

**Args**
- vertices : (V, 3) vertex positions.
- faces    : list of face index lists (variable valence) or (F, K) int array.

**Returns**
- normals  : (F, 3) unit face normals.

#### `face_planarity(vertices, faces)`
Per-face planarity measure for a polygon mesh.

For each face the best-fit normal is computed via Newell's method, then
planarity is the maximum absolute distance from any vertex to that plane,
normalised by the mean edge length of the face.  A value of 0 means
perfectly planar.

**Args**
- vertices: (V, 3) array of vertex positions.
- faces:    list of index arrays, one per face (triangles, quads, n-gons).

**Returns**
- planarity: (F,) array, one scalar per face.

#### `compute_planarity(p1, p2, p3, p4)`
Planarity of a quad via normal-edge dot product.

**Args**
- p1: First quad vertex (N, 3).
- p2: Second quad vertex (N, 3).
- p3: Third quad vertex (N, 3).
- p4: Fourth quad vertex (N, 3).

**Returns**
- Planarity value array (N,); 0 means perfectly planar.

#### `planarity_measure_quad_mesh(quad_mesh)`
Planarity per face: diagonal closest-point gap divided by average edge length.

**Args**
- quad_mesh: Mesh object with vertices, faces, and edge_vertices() method.

**Returns**
- Planarity measure array (F,).

#### `compute_circumcircles_quad_mesh(vertices, faces)`
Compute circumcenters, normals, and radii for each face of a quad mesh.

**Args**
- vertices: Vertex positions (N, 3).
- faces: Quad face index array (M, 4).

**Returns**
- centers: Circumcenter positions (M, 3).
- normals: Face normals (M, 3).
- radii: Circumcircle radii (M,).


## conical

Cones of revolution and conical meshes: cones tangent to sphere pairs, cone strips, vertex cone axes and curvature spheres of conical meshes.

#### `oriented_cone(ci, ri, cj, rj)`
Oriented cone tangent to two spheres.

**Args**
- ci: Center of sphere i (3,).
- ri: Radius of sphere i.
- cj: Center of sphere j (3,).
- rj: Radius of sphere j.

**Returns**
- kappai: Contact circle on sphere i as (center, radius).
- kappaj: Contact circle on sphere j as (center, radius).
- axis: Cone axis unit vector (3,).
- tip: Cone apex (3,).
- angle: Half-aperture angle in radians.

#### `cone_strip(kappai, kappaj, axis, n=20)`
Quad mesh of the ruled strip between two contact circles.

**Args**
- kappai: Contact circle on sphere i as (center, radius).
- kappaj: Contact circle on sphere j as (center, radius).
- axis: Cone axis unit vector (3,).
- n: Number of circumference points (default: 20).

**Returns**
- vertices: Strip vertex positions (2*n, 3).
- faces: Quad face index lists.

#### `cone_strip_mesh(ci, ri, cj, rj, n=20)`
Convenience wrapper: oriented cone + strip mesh in one call.

**Args**
- ci: Center of sphere i (3,).
- ri: Radius of sphere i.
- cj: Center of sphere j (3,).
- rj: Radius of sphere j.
- n: Number of circumference points (default: 20).

**Returns**
- V: Vertex positions (2*n, 3).
- F: Quad face index lists.

#### `rotational_cone_radius(vertex, axis, half_angle, radius, n=50)`
Mesh of a rotational cone given apex, axis, half-angle and base circle radius.

**Args**
- vertex: Apex of the cone (3,).
- axis: Cone axis direction (3,).
- half_angle: Half-aperture angle in radians.
- radius: Base circle radius.
- n: Number of circumference points (default: 50).

**Returns**
- vertices: Vertex positions (n+1, 3).
- faces: Fan face index lists.

#### `half_angle_rotational_cone(axe, normals)`
Mean half-aperture angle between a cone axis and a set of face normals.

**Args**
- axe: Cone axis (3,).
- normals: Face normals (F, 3).

**Returns**
- Mean half-aperture angle in radians.

#### `cone_axis_from_planes(normals)`
Best-fit cone axis for a set of plane normals via SVD.

**Args**
- normals: Array of plane normals (N, 3).

**Returns**
- Unit cone axis vector (3,).

#### `compute_cone_axes(mesh)`
Cone axes and half-angles at every inner vertex of a conical quad mesh.

Boundary vertices use vertex normals with angle = -1 (ignored in optimisation).

**Args**
- mesh: Mesh object with vertices, face normals, and adjacency methods.

**Returns**
- axes: Cone axis at each vertex (V, 3).
- angle: Half-aperture angle in radians (V,); -1 for boundary vertices.

#### `sphere_center_on_cone_axis(cone, radius)`
Center of a sphere tangent to a cone's lateral surface, constrained to lie on the axis.

**Args**
- cone: Tuple (axis, half_angle, vertex) where axis is (..., 3), half_angle is (...,), and vertex is (..., 3).
- radius: Sphere radius (...,).

**Returns**
- Sphere center positions (..., 3).

#### `mesh_axes_intersections(vertices, axes, adjacent_vertices)`
Pairwise axis closest-point pairs used to estimate curvature sphere centers.

**Args**
- vertices: Vertex positions (V, 3).
- axes: Cone axis directions at each vertex (V, 3).
- adjacent_vertices: List of adjacency index lists, one per vertex.

**Returns**
- pts_u: List of lists of closest points in the u-direction (even neighbours).
- pts_v: List of lists of closest points in the v-direction (odd neighbours).

#### `conical_mesh_smallest_curvature_sphere(vertices, axes, half_angles, adjacent_vertices)`
Smallest curvature sphere at each vertex using cone half-angles to compute radii.

**Args**
- vertices: Vertex positions (V, 3).
- axes: Cone axis directions (V, 3).
- half_angles: Half-aperture angles (V,).
- adjacent_vertices: List of adjacency index lists, one per vertex.

**Returns**
- centers: Sphere centers (V, 3).
- radii: Sphere radii (V,) computed as distance * sin(half_angle).

#### `mesh_cone_axis_smallest_sphere(vertices, axes, adjacent_vertices)`
Nearest sphere at each vertex from axis-axis closest points, using distance as radius.

For each vertex, finds the closest footpoint between its axis and each adjacent axis.
The sphere center is at this footpoint and the radius is its distance to the vertex.
Unlike conical_mesh_smallest_curvature_sphere, this does not use half-angle information.

**Args**
- vertices: Vertex positions (V, 3).
- axes: Axis directions at each vertex (V, 3).
- adjacent_vertices: List of adjacency index lists, one per vertex.

**Returns**
- centers: Sphere centers (V, 3).
- radii: Sphere radii (V,).


## lie

Lie sphere geometry: oriented spheres as points of the Lie quadric, pencils, midpoints, and cyclidic families / envelopes.

#### `lie_inner_prod(lp1, lp2)`
Inner product for the Lie quadric with signature (+ + + + - -).

**Args**
- lp1: Point in Lie projective space (6,).
- lp2: Point in Lie projective space (6,).

**Returns**
- Scalar <lp1, lp2>_L.

#### `base_vector(n, i)`
Canonical basis vector e_i in R^n.

**Args**
- n: Dimension of the space.
- i: Index of the axis (0 to n-1).

**Returns**
- (n,) ndarray with 1 at position i and 0 elsewhere.

#### `set_lie_coordinates(val_n, val_0, val_einf, val_r)`
Assemble a Lie sphere from its positional and basis components.

**Args**
- val_n: Positional coordinates (3,).
- val_0: Coefficient for basis e0.
- val_einf: Coefficient for basis e_inf.
- val_r: Radius coefficient.

**Returns**
- Lie point as a (6,) ndarray.

#### `normalize_lie_sphere(lie_sphere)`
Normalize a Lie sphere with respect to the e0 coefficient.

**Args**
- lie_sphere: Lie sphere point (6,).

**Returns**
- Normalized Lie sphere (6,) with e0 coefficient equal to 1.

#### `map_lie_s_to_sphere(lieS)`
Convert a Lie sphere back to (center, radius).

**Args**
- lieS: Lie sphere point (6,).

**Returns**
- center: Sphere center (3,).
- radius: Sphere radius (float).

#### `boundary_lie_sphere_cyclide(x, xi, n)`
Boundary sphere of a Dupin cyclide (Bobenko & Huhnen-Venedey).

**Args**
- x: Point x on the surface (3,).
- xi: Adjacent point xi (3,).
- n: Surface normal at x (3,).

**Returns**
- Lie sphere (6,) representing the boundary sphere of the cyclide.

#### `lie_midpoint(x, xi, ti)`
Midpoint sphere in Lie representation between two surface points.

**Args**
- x: Point x (3,).
- xi: Point xi (3,).
- ti: Tangent direction at x toward xi (3,).

**Returns**
- Lie sphere (6,) at the midpoint between x and xi.

#### `get_tangent_vector(x, xi, u, v)`
Select the tangent direction at x toward xi from a local frame {u, v}.

**Args**
- x: Current surface point (3,).
- xi: Target surface point (3,).
- u: First tangent vector of the local frame (3,).
- v: Second tangent vector of the local frame (3,).

**Returns**
- The frame vector (u or v) most aligned with the direction x → xi.

#### `cyclidic_family_lie(lie_sphere_1, lie_sphere_2, lie_sphere_3)`
Define a one-parameter cyclidic family from three Lie spheres.

**Args**
- lie_sphere_1: First boundary Lie sphere (6,).
- lie_sphere_2: Midpoint Lie sphere (6,).
- lie_sphere_3: Second boundary Lie sphere (6,).

**Returns**
- sphere_matrix: (6, 3) matrix of the three Lie spheres as columns.
- coefficients: (3,) array of inner-product coefficients for evaluation.

#### `eval_cyclidic_family_lie(sphere_matrix, coefficients, t)`
Evaluate a cyclidic family at parameter t ∈ [0, 1].

**Args**
- sphere_matrix: (6, 3) matrix from cyclidic_family_lie.
- coefficients: (3,) coefficient array from cyclidic_family_lie.
- t: Evaluation parameter in [0, 1].

**Returns**
- Lie sphere (6,) at parameter t.

#### `envelope_point(cyclidic_f1, cyclidic_f2, t1, t2)`
Envelope point of two cyclidic families at parameter pair (t1, t2).

**Args**
- cyclidic_f1: First cyclidic family as (sphere_matrix, coefficients).
- cyclidic_f2: Second cyclidic family as (sphere_matrix, coefficients).
- t1: Parameter in [0, 1] for the first family.
- t2: Parameter in [0, 1] for the second family.

**Returns**
- Lie sphere (6,) — a point-sphere on the envelope.


## isotropic_geometry

#### `iso_sphere_to_sphere(i_sphere)`
Convert an isotropic 4-D point back to (center, radius).

**Args**
- i_sphere: Isotropic 4-D representation (4,).

**Returns**
- center: Sphere center (3,).
- radius: Sphere radius (float).

#### `i_inverse_point(point)`
Inversion of a point in isotropic space (divides by the squared xy-norm).

**Args**
- point: Point in isotropic space (3,).

**Returns**
- Inverted point (3,).

#### `i_scale_point(point, scale)`
Scale a point in isotropic space by a scalar factor.

**Args**
- point: Point (3,).
- scale: Scaling factor (float).

**Returns**
- Scaled point (3,).

#### `i_translate_point(point, translation)`
Translate a point in isotropic space by a given vector.

**Args**
- point: Point (3,).
- translation: Translation vector (3,).

**Returns**
- Translated point (3,).

#### `i_csphere_sphere(i_center, i_radius, center, radius)`
Express a Euclidean sphere in the coordinate frame of an isotropic cylindrical sphere.

**Args**
- i_center: 2-D center of the isotropic cylindrical sphere (2,).
- i_radius: Radius of the isotropic cylindrical sphere.
- center: Center of the Euclidean sphere (3,).
- radius: Radius of the Euclidean sphere.

**Returns**
- Isotropic cylindrical sphere representation (4,).

#### `i_point_to_or_plane(i_point)`
Convert a point in isotropic space to its oriented-plane representation.

**Args**
- i_point: Point in isotropic space (3,).

**Returns**
- Oriented plane as [nx, ny, nz, h] (4,).

#### `i_csphere_inverse_point(i_center, i_radius, point)`
Invert a point with respect to an isotropic cylindrical sphere.

**Args**
- i_center: 2-D center of the isotropic cylindrical sphere (2,).
- i_radius: Radius of the isotropic cylindrical sphere.
- point: Point to transform (3,).

**Returns**
- Inverted point (3,).

#### `get_ri_cyl_sphere_auto_inverse(v, angle, axis, r, mx, my)`
Function that compute the radius of a i-sphere of cylindrical type with center mx, my so that the sphere cx, cy, cz, r is auto_inverse w.r.t the cylindrical sphere. cx = v[0] + r/sin(angle) * axis[0] cy = v[1] + r/sin(angle) * axis[1] cz = v[2] + r/sin(angle) * axis[2] return ri**2

#### `compute_auto_inverse_sphere_radius(v, angle, axis, mx, my, ri2)`
Function that compute the radius of the sphere whose isotropic representation is auto_inverse w.r.t the cylindrical sphere of center mx, my and radius ri2 = ri**2 (can be negative).     cx = v[0] + r/sin(angle) * axis[0]     cy = v[1] + r/sin(angle) * axis[1]     cz = v[2] + r/sin(angle) * axis[2] return cx, cy, cz, r


## io

Colormaps and mesh file I/O (OBJ, OFF).

#### `get_color(cmap, value)`
Sample a color from a colormap at a scalar value.

**Args**
- cmap:  Matplotlib colormap, or one of 'viridis', 'bluered', 'sunset'.
- value: Scalar in [0, 1].

**Returns**
- (r, g, b) tuple in [0, 1].

#### `hex_to_norm_rgb(hex_color)`
Convert a #RRGGBB hex string to a normalized (r, g, b) tuple.

**Args**
- hex_color: Hex color string, e.g. '#FF8800'.

**Returns**
- (r, g, b) tuple with values in [0, 1].

#### `write_obj(filename, vertices, faces)`
Write vertices and faces to a Wavefront OBJ file.

**Args**
- filename: Output file path.
- vertices: Vertex positions (V, 3).
- faces:    Face index lists.

#### `triangulate_quads(faces)`
Split each quad face into two triangles.

**Args**
- faces: List of faces; each element is a list of 3 or 4 vertex indices.

**Returns**
- List of triangular face index lists.

#### `read_obj(filename)`
Read a Wavefront OBJ file.

**Args**
- filename: Path to the OBJ file.

**Returns**
- vertices: (V, 3) numpy array.
- faces:    List of face index lists.

#### `mathematica_v(v)`
Recursively format a vector, matrix, or array in Mathematica {…} notation.

**Args**
- v: Vector, list, tuple, or NumPy array of any dimension.

**Returns**
- Mathematica-formatted string, e.g. '{1, 2, 3}'.

#### `read_off(filename)`
Read an OFF (Object File Format) mesh file.

Supports the plain ``OFF`` header, the variants that carry per-vertex
normals / colors / texture coordinates (``NOFF``, ``COFF``, ``STOFF``,
``CNOFF``, ...), and the form where the counts share the header line
(``OFF 8 6 12``).  Only positions and face connectivity are returned:
a vertex line contributes its first three numbers, and any trailing
per-vertex attributes or per-face color values are ignored.  Comment
lines (starting with ``#``) and blank lines are skipped.

**Args**
- filename: Path to the OFF file.

**Returns**
- vertices: (V, 3) numpy array of vertex positions.
- faces:    List of face index lists (arbitrary polygon sizes).


## glyphs

`hanan.glyphs` (not part of `hanan.geometry`): returns plain arrays, draws nothing.

Glyphs — mesh data for drawing geometric objects.

#### `sphere(center, radius, subdivisions=3)`
Triangle mesh of a sphere (subdivided icosahedron).

**Args**
- center:       Sphere center (3,).
- radius:       Sphere radius; the sign is ignored (oriented spheres).
- subdivisions: Subdivision levels; 20 * 4**subdivisions triangles (default 3: 1280).

**Returns**
- V (n, 3), F (m, 3).

#### `spheres(centers, radii, subdivisions=2)`
Many spheres merged into one triangle mesh.

**Args**
- centers:      (k, 3).
- radii:        (k,); signs are ignored.
- subdivisions: Per sphere (default 2: 320 triangles each).

**Returns**
- V (k*n, 3), F (k*m, 3) — sphere i owns faces [i*m, (i+1)*m).

#### `circle(center, normal, radius, n=64)`
Closed polyline of a circle in 3-D.

**Args**
- center: (3,).
- normal: Normal of the circle's plane (3,).
- radius: Circle radius.
- n:      Number of points (default 64); the first point is not repeated.

**Returns**
- P (n, 3), E (n, 2).

#### `circles(centers, normals, radii, n=64)`
Many circles merged into one curve network.

**Returns**
- P (k*n, 3), E (k*n, 2) — circle i owns points [i*n, (i+1)*n).

#### `polyline(points, closed=False)`
Curve network through ``points`` in order.

**Returns**
- P (n, 3), E (n - 1, 2), or (n, 2) when ``closed``.

#### `segments(starts, ends)`
Independent line segments starts[i] -> ends[i].

**Returns**
- P (2k, 3), E (k, 2).

#### `cross_field(points, direction1, direction2, length)`
A cross field as two sets of segments centered at ``points``.

**Args**
- points:     (k, 3).
- direction1: (k, 3), normalized here.
- direction2: (k, 3), normalized here.
- length:     Half-length of each arm.

**Returns**
- ((P1, E1), (P2, E2)) — one curve network per direction.

#### `plane_patch(point, normal, size=(1, 1))`
Rectangular patch of the plane through ``point`` with normal ``normal``.

**Args**
- point:  Center of the patch (3,).
- normal: Plane normal (3,).
- size:   Half-extents (a, b) along the two in-plane directions.

**Returns**
- V (4, 3), F (1, 4).

#### `plane(n, h, near=(0.0, 0.0, 0.0), size=(1, 1))`
Patch of the plane n·x + h = 0, centered at the point of the plane closest to ``near``.

**Returns**
- V (4, 3), F (1, 4).

#### `plane_covering(n, h, points, margin=0.1)`
Patch of the plane n·x + h = 0 that covers the projection of ``points`` onto it.

Use it to show a plane at the position and scale of the geometry it belongs to
(e.g. a mesh), instead of a fixed square around some point. The rectangle is
aligned with the principal directions of the projected points, extends ``margin``
(a fraction of its size) beyond them, and its face normal points along ``n``.

**Args**
- n:      Plane normal (3,), any length.
- h:      Plane offset.
- points: (k, 3) points to cover.
- margin: Relative margin around the projected points (default 0.1).

**Returns**
- V (4, 3), F (1, 4).

#### `cone(apex, axis, half_angle, height, n=32)`
Lateral surface of a cone of revolution (triangle fan, no base).

**Args**
- apex:       (3,).
- axis:       Opening direction (3,).
- half_angle: Half-aperture in radians.
- height:     Distance from the apex to the base along ``axis``.
- n:          Points on the base circle (default 32).

**Returns**
- V (n+1, 3), F (n, 3).

#### `cone_strip(ci, ri, cj, rj, n=32)`
Quad strip of the oriented cone tangent to two oriented spheres, between the two contact circles.

**Args**
- ci, cj: Sphere centers (3,).
- ri, rj: Signed sphere radii.
- n:      Points per contact circle (default 32).

**Returns**
- V (2n, 3), F (n, 4).

**Raises**
- ValueError: if no oriented cone touches both spheres.

#### `cone_strips(ci, ri, cj, rj, n=32)`
Cone strips for many sphere pairs (ci[k], ri[k]) - (cj[k], rj[k]), merged.

Pairs without an oriented cone are skipped.

**Returns**
- V, F, kept — ``kept`` holds the indices k of the pairs that were drawn;
- pair kept[m] owns faces [m*n, (m+1)*n).
