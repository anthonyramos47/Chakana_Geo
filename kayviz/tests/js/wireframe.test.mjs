// Screen-space wireframe: polygon edges as fat lines, a child of the mesh.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

test('the wireframe draws the polygon sides only, follows the mesh, and goes away', () => {
  const v = new Viewer(new THREE.Scene());
  // one quad sent as two fan triangles: 4 sides, no diagonal
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'Q', face_size: 3,
    vertices: new Float32Array([0,0,0, 1,0,0, 1,1,0, 0,1,0]),
    faces: new Int32Array([0,1,2, 0,2,3]), tris_per_face: new Int32Array([2]),
    show_wireframe: true, wireframe_width: 2 }] });
  const e = v._objects.get('Q'), line = e.opts.wireframe;
  assert.ok(line?.isLineSegments2 && line.parent === e.mesh);
  assert.equal(line.geometry.getAttribute('instanceStart').count, 4);
  assert.equal(line.material.linewidth, 2);
  v.setWireframe('Q', false);
  assert.equal(e.opts.wireframe, null);
  assert.equal(e.mesh.children.length, 0);
});
