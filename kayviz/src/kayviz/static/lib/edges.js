/**
 * edges.js — unique edges of a triangle mesh.
 *
 * Python sends polygon edges with polygon meshes only; for a triangle mesh the
 * edges are the triangles' sides, so the viewer finds them here, and only when the
 * edge overlay is first shown (for big meshes they were most of the data sent).
 */

/**
 * Unique undirected edges of indexed triangles, as index pairs (smaller first).
 * @param {ArrayLike<number>} faces  3 vertex indices per triangle
 * @returns {Uint32Array}            2 indices per edge
 */
export function triangleEdges(faces) {
  const m = faces.length - (faces.length % 3);
  let n = 0;
  for (let i = 0; i < m; i++) if (faces[i] > n) n = faces[i];
  n += 1;
  // One number per edge: exact in a double while n * n < 2^53 (n < 9e7 vertices).
  const keys = new Float64Array(m);
  for (let t = 0; t < m; t += 3) {
    for (let s = 0; s < 3; s++) {
      const a = faces[t + s], b = faces[t + (s + 1) % 3];
      keys[t + s] = a < b ? a * n + b : b * n + a;
    }
  }
  keys.sort();
  let u = 0;
  for (let i = 0; i < m; i++) if (i === 0 || keys[i] !== keys[i - 1]) u++;
  const E = new Uint32Array(2 * u);
  for (let i = 0, j = 0; i < m; i++) {
    if (i && keys[i] === keys[i - 1]) continue;
    const a = Math.floor(keys[i] / n);
    E[j++] = a;
    E[j++] = keys[i] - a * n;
  }
  return E;
}
