"""
Colormaps and mesh file I/O (OBJ, OFF).

Mesh data for drawing geometric objects (spheres, circles, planes, cones, …)
is in ``hanan.glyphs``; hanan itself draws nothing.
"""

import numpy as np

# ── Colormaps ─────────────────────────────────────────────────────────────────

viridis = None
bluered = None
sunset  = None


def _ensure_colormaps():
    global viridis, bluered, sunset
    if viridis is not None:
        return
    from matplotlib.colors import LinearSegmentedColormap
    viridis = LinearSegmentedColormap.from_list(
        'viridis_like',
        ['#440154', '#31688e', '#35b779', '#fde724'], N=256)
    bluered = LinearSegmentedColormap.from_list(
        'bluered',
        ["#2e7ead", '#92c5de', '#f7f7f7', '#f4a582', '#ca0020'], N=256)
    sunset = LinearSegmentedColormap.from_list(
        'sunset',
        ['#1a1a2e', '#16213e', '#e94560', '#f39c12', '#f9ca24'], N=256)


def get_color(cmap, value):
    """
    Sample a color from a colormap at a scalar value.

    Args:
        cmap:  Matplotlib colormap, or one of 'viridis', 'bluered', 'sunset'.
        value: Scalar in [0, 1].

    Returns:
        (r, g, b) tuple in [0, 1].
    """
    _ensure_colormaps()
    if isinstance(cmap, str):
        cmap = {'viridis': viridis, 'bluered': bluered, 'sunset': sunset}[cmap]
    rgba = cmap(value)  # type: ignore[misc]
    return rgba[:3]


def hex_to_norm_rgb(hex_color):
    """
    Convert a #RRGGBB hex string to a normalized (r, g, b) tuple.

    Args:
        hex_color: Hex color string, e.g. '#FF8800'.

    Returns:
        (r, g, b) tuple with values in [0, 1].
    """
    hex_color = hex_color.lstrip('#')
    return (int(hex_color[0:2], 16) / 255.0,
            int(hex_color[2:4], 16) / 255.0,
            int(hex_color[4:6], 16) / 255.0)


# ── OBJ I/O ───────────────────────────────────────────────────────────────────

def write_obj(filename, vertices, faces):
    """
    Write vertices and faces to a Wavefront OBJ file.

    Args:
        filename: Output file path.
        vertices: Vertex positions (V, 3).
        faces:    Face index lists.
    """
    with open(str(filename), 'w') as f:
        for v in vertices:
            f.write('v {} {} {}\n'.format(v[0], v[1], v[2]))
        for face in faces:
            f.write('f ' + ' '.join(str(idx + 1) for idx in face) + '\n')


def triangulate_quads(faces):
    """
    Split each quad face into two triangles.

    Args:
        faces: List of faces; each element is a list of 3 or 4 vertex indices.

    Returns:
        List of triangular face index lists.
    """
    tri_faces = []
    for f in faces:
        if len(f) == 3:
            tri_faces.append(f)
        elif len(f) == 4:
            tri_faces.append([f[0], f[2], f[1]])
            tri_faces.append([f[0], f[3], f[2]])
        else:
            raise ValueError("Face with more than 4 vertices encountered.")
    return tri_faces


def read_obj(filename):
    """
    Read a Wavefront OBJ file.

    Args:
        filename: Path to the OBJ file.

    Returns:
        vertices: (V, 3) numpy array.
        faces:    List of face index lists.
    """
    vertices_list = []
    faces_list = []
    with open(str(filename), encoding='utf-8') as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == 'v':
                try:
                    vertices_list.append([float(parts[1]),
                                          float(parts[2]),
                                          float(parts[3])])
                except ValueError:
                    print('WARNING: Issue with vertex line in OBJ file')
            elif parts[0] == 'f':
                try:
                    face = [int(p.split('/')[0]) - 1 for p in parts[1:]]
                except ValueError:
                    face = [int(p) - 1 for p in parts[1:-1]]
                faces_list.append(face)
    return np.array(vertices_list), faces_list


def mathematica_v(v):
    """
    Recursively format a vector, matrix, or array in Mathematica {…} notation.

    Args:
        v: Vector, list, tuple, or NumPy array of any dimension.

    Returns:
        Mathematica-formatted string, e.g. '{1, 2, 3}'.
    """
    def _convert_element(elem):
        if isinstance(elem, (list, tuple, np.ndarray)):
            return mathematica_v(elem)
        elif isinstance(elem, (complex,)) or np.iscomplexobj(elem):
            return f"{elem.real:.16g} + {elem.imag:.16g}I"
        elif isinstance(elem, (float, int)) or np.isreal(elem):
            return f"{float(elem):.16g}"
        else:
            return str(elem)

    if isinstance(v, np.ndarray):
        v = v.tolist()
    if not v:
        return "{}"
    return "{" + ", ".join(_convert_element(e) for e in v) + "}"


def read_off(filename):
    """
    Read an OFF (Object File Format) mesh file.

    Supports the plain ``OFF`` header, the variants that carry per-vertex
    normals / colors / texture coordinates (``NOFF``, ``COFF``, ``STOFF``,
    ``CNOFF``, ...), and the form where the counts share the header line
    (``OFF 8 6 12``).  Only positions and face connectivity are returned:
    a vertex line contributes its first three numbers, and any trailing
    per-vertex attributes or per-face color values are ignored.  Comment
    lines (starting with ``#``) and blank lines are skipped.

    Args:
        filename: Path to the OFF file.

    Returns:
        vertices: (V, 3) numpy array of vertex positions.
        faces:    List of face index lists (arbitrary polygon sizes).
    """
    def _lines(path):
        """Yield token lists per meaningful line, skipping comments and blanks."""
        with open(str(path), encoding='utf-8') as fh:
            for line in fh:
                line = line.split('#', 1)[0]
                if line.strip():
                    yield line.split()

    stream = _lines(filename)

    try:
        header = next(stream)
    except StopIteration:
        raise ValueError(f"Empty OFF file: {filename}")

    if not header[0].endswith('OFF'):
        raise ValueError(
            f"Not an OFF file (header {header[0]!r}): {filename}")

    # Counts may share the header line ("OFF 8 6 12") or sit on the next one.
    counts = header[1:]
    while len(counts) < 3:
        try:
            counts += next(stream)
        except StopIteration:
            raise ValueError(f"Malformed OFF counts line in: {filename}")
    try:
        n_vertices, n_faces = int(counts[0]), int(counts[1])
    except ValueError:
        raise ValueError(f"Malformed OFF counts line in: {filename}")

    vertices_list = []
    for _ in range(n_vertices):
        try:
            parts = next(stream)
            # Trailing normals / colors / texture coords are ignored.
            vertices_list.append([float(parts[0]), float(parts[1]),
                                  float(parts[2])])
        except (StopIteration, IndexError, ValueError):
            raise ValueError(
                f"Malformed or truncated vertex data in: {filename}")

    faces_list = []
    for _ in range(n_faces):
        try:
            parts = next(stream)
            valence = int(parts[0])
            face = [int(i) for i in parts[1:valence + 1]]
            if len(face) != valence:
                raise ValueError
            # Any per-face color after the indices is ignored.
            faces_list.append(face)
        except (StopIteration, IndexError, ValueError):
            raise ValueError(
                f"Malformed or truncated face data in: {filename}")

    return np.array(vertices_list), faces_list
