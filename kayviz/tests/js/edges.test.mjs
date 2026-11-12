// Triangle meshes come without edges; the viewer finds them when they are shown.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');
const { triangleEdges } = await import('../../src/kayviz/static/lib/edges.js');

test('triangleEdges: unique pairs, smaller index first', () => {
  // two triangles sharing (0, 2): 5 edges
  const E = triangleEdges(new Uint32Array([0, 1, 2, 2, 3, 0]));
  const pairs = [];
  for (let i = 0; i < E.length; i += 2) pairs.push(`${E[i]}-${E[i + 1]}`);
  assert.deepEqual(pairs.sort(), ['0-1', '0-2', '0-3', '1-2', '2-3']);
});

test('a triangle mesh without poly_edges gets its edges when they are shown', () => {
  const v = new Viewer(new THREE.Scene());
  const vertices = new Float32Array([0,0,0, 1,0,0, 1,1,0, 0,1,0]);
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'T', vertices,
                               faces: new Int32Array([0, 1, 2, 2, 3, 0]), face_size: 3 }] });
  const e = v._objects.get('T');
  assert.equal(e.opts.edgeIdx, null);                 // nothing computed up front
  v.toggleEdges('T', true);
  assert.ok(e.children.has('edges'));
  assert.equal(e.opts.edgeIdx.length, 10);
});

test('show_edges on a triangle mesh draws the derived edges at once', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'S', show_edges: true,
                               vertices: new Float32Array([0,0,0, 1,0,0, 0,1,0]),
                               faces: new Int32Array([0, 1, 2]), face_size: 3 }] });
  assert.ok(v._objects.get('S').children.has('edges'));
});
