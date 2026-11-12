// Scalars on point clouds (one colour per point) and curve networks (per edge on
// tubes, per end on lines).
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');
const { sample } = await import('../../src/kayviz/static/lib/colormap.js');

const near = (a, b) => a.every((x, i) => Math.abs(x - b[i]) < 0.02);
const P = new Float32Array([0,0,0, 1,0,0, 2,0,0]);
const E = new Int32Array([0,1, 1,2]);

test('point cloud: each point takes its value\'s colour; off restores the colour', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerPointCloud('P', P, [0.2, 0.5, 0.8], 0.1);
  v.addScalarQuantity('P', 's', new Float32Array([0, 1, 2]), 'vertices');
  const m = v._objects.get('P').mesh, c = m.instanceColor.array;
  assert.ok(near([c[0], c[1], c[2]], sample(0)) && near([c[6], c[7], c[8]], sample(1)));
  v.setActiveScalar('P', null);
  assert.equal(m.instanceColor, null);
  assert.deepEqual(m.material.color.toArray().map(x => +x.toFixed(3)), [0.2, 0.5, 0.8]);
});

test('curve tubes: edge values per edge, vertex values as the mean of the ends', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerCurveNetwork('C', P, E, [1, 0, 0], 0.05);
  v.addScalarQuantity('C', 'e', new Float32Array([0, 10]), 'edges');
  let c = v._objects.get('C').mesh.instanceColor.array;
  assert.ok(near([c[0], c[1], c[2]], sample(0)) && near([c[3], c[4], c[5]], sample(1)));
  v.addScalarQuantity('C', 'n', new Float32Array([0, 1, 4]), 'vertices');
  v.setActiveScalar('C', 'n');
  c = v._objects.get('C').mesh.instanceColor.array;
  // edge 0: mean 0.5, edge 1: mean 2.5, range of the values 0..4
  assert.ok(near([c[0], c[1], c[2]], sample(0.5 / 4)) && near([c[3], c[4], c[5]], sample(2.5 / 4)));
  v.setCurveRadius('C', 0.1);                          // rebuilt tubes keep the colours
  assert.ok(v._objects.get('C').mesh.instanceColor);
});

test('curve lines (radius 0): a colour per end', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerCurveNetwork('L', P, E, [1, 0, 0], 0);
  v.addScalarQuantity('L', 'n', new Float32Array([0, 1, 2]), 'vertices');
  const col = v._objects.get('L').mesh.geometry.getAttribute('color').array;
  // ends of edge 0 are vertices 0, 1; of edge 1 vertices 1, 2
  assert.ok(near(Array.from(col.slice(3, 6)), sample(0.5)) && near(Array.from(col.slice(9, 12)), sample(1)));
});
