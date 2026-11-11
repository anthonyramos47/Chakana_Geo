// Arrow magnitude, scene-relative sizes, flat shading and colormaps.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');
const { sample } = await import('../../src/kayviz/static/lib/colormap.js');

const stretch = (mesh, i) => {
  const m = new THREE.Matrix4(); mesh.getMatrixAt(i, m);
  return +new THREE.Vector3().setFromMatrixScale(m).y.toFixed(3);
};
const O = new Float32Array([0,0,0, 1,0,0, 2,0,0]);
const Vv = new Float32Array([0,1,0, 0,2,0, 0,4,0]);       // |v| = 1, 2, 4

test('vectortype: standard compares magnitudes, ambient is true length, unit is equal', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerVectorField('S', O, Vv, 1.0, null, [0, 1, 0], 'standard');
  v.registerVectorField('A', O, Vv, 1.0, null, [0, 1, 0], 'ambient');
  v.registerVectorField('U', O, Vv, 1.0, null, [0, 1, 0], 'unit');
  const s = n => [0, 1, 2].map(i => stretch(v.objects.get(n).mesh, i));
  assert.deepEqual(s('S'), [0.25, 0.5, 1]);
  assert.deepEqual(s('A'), [1, 2, 4]);
  assert.deepEqual(s('U'), [1, 1, 1]);
});

test('default sizes follow the size of the object, in any unit', () => {
  const v = new Viewer(new THREE.Scene());
  const big = new Float32Array([0,0,0, 1000,0,0]), tiny = new Float32Array([0,0,0, 0.001,0,0]);
  v.registerPointCloud('Big', big);
  v.registerPointCloud('Tiny', tiny);
  assert.equal(v.objects.get('Big').opts.radius, 5);
  assert.ok(Math.abs(v.objects.get('Tiny').opts.radius - 5e-6) < 1e-12);
});

test('flat shading follows what Python resolved, and survives a shader change', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'Q', vertices: new Float32Array(12),
                               faces: new Int32Array([0, 1, 2, 3]), face_size: 4, shading: 'flat' }] });
  const e = v.objects.get('Q');
  assert.equal(e.mesh.material.flatShading, true);
  v.setGlobalMaterial('phong');
  assert.equal(e.mesh.material.flatShading, true);
});

test('colormaps: diverging rdbu runs blue to red, unknown names fall back to viridis', () => {
  const [r0, , b0] = sample(0, 'rdbu'), [r1, , b1] = sample(1, 'rdbu');
  assert.ok(b0 > r0 && r1 > b1);
  assert.deepEqual(sample(0.5, 'nope'), sample(0.5, 'viridis'));
});
