/**
 * edges.js — the edges of a surface mesh, for the edge overlay.
 *
 * Python sends no edges: they were most of its work and up to 40% of the data
 * sent. The viewer finds them here, and only when the overlay is first shown:
 * the sides of the original polygons, not the diagonals of their triangulation.
 */

/** Sorted unique edges from one key per edge side (a * n + b, a < b). */
function uniquePairs(keys, count, n) {
  const k = keys.subarray(0, count).sort();
  let u = 0;
  for (let i = 0; i < count; i++) if (i === 0 || k[i] !== k[i - 1]) u++;
  const E = new Uint32Array(2 * u);
  for (let i = 0, j = 0; i < count; i++) {
    if (i && k[i] === k[i - 1]) continue;
    const a = Math.floor(k[i] / n);
    E[j++] = a;
    E[j++] = k[i] - a * n;
  }
  return E;
}

function vertexCount(faces, m) {
  let n = 0;
  for (let i = 0; i < m; i++) if (faces[i] > n) n = faces[i];
  return n + 1;      // keys a * n + b are exact in a double while n < 9e7
}

/**
 * Unique undirected edges of indexed triangles, as index pairs (smaller first).
 * @param {ArrayLike<number>} faces  3 vertex indices per triangle
 * @returns {Uint32Array}            2 indices per edge
 */
export function triangleEdges(faces) {
  return polygonEdges(faces, 3, null);
}

/**
 * Unique sides of the polygons a mesh was sent as.
 * @param {ArrayLike<number>} faces        faceSize indices per face, or triangles
 * @param {number} faceSize                vertices per face in `faces`
 * @param {ArrayLike<number>|null} trisPerFace  triangles per original polygon when
 *        Python triangulated them (in face order), else null
 * @returns {Uint32Array}                  2 indices per edge
 */
export function polygonEdges(faces, faceSize, trisPerFace) {
  const m = faces.length - (faces.length % faceSize);
  const n = vertexCount(faces, m);
  const keys = new Float64Array(m);
  const key = (a, b) => (a < b ? a * n + b : b * n + a);
  let count = 0;
  if (!trisPerFace) {
    // each face as it is: its consecutive vertices
    for (let f = 0; f < m; f += faceSize) {
      for (let s = 0; s < faceSize; s++) {
        keys[count++] = key(faces[f + s], faces[f + (s + 1) % faceSize]);
      }
    }
    return uniquePairs(keys, count, n);
  }
  // Triangulated polygons: inside one polygon a diagonal is shared by two of its
  // triangles and a side belongs to one, for a fan as for ear clipping.
  const local = [];
  let t = 0;
  for (let p = 0; p < trisPerFace.length; p++) {
    local.length = 0;
    for (let i = 0; i < trisPerFace[p]; i++, t += 3) {
      for (let s = 0; s < 3; s++) local.push(key(faces[t + s], faces[t + (s + 1) % 3]));
    }
    local.sort((x, y) => x - y);
    for (let i = 0; i < local.length; i++) {
      const dup = (i > 0 && local[i] === local[i - 1]) ||
                  (i + 1 < local.length && local[i] === local[i + 1]);
      if (!dup) keys[count++] = local[i];
    }
  }
  return uniquePairs(keys, count, n);
}
