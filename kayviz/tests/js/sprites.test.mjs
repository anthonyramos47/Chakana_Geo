// Point clouds are sphere sprites by default: one quad per point, radius a uniform.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

const P = new Float32Array([0,0,0, 1,2,3, -1,0,4]);

test('sprites: a quad per point at the point, bounds of the spheres', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerPointCloud('P', P, [1, 0, 0], 0.5);
  const mesh = v._objects.get('P').mesh;
  assert.ok(mesh.isInstancedMesh && mesh.userData.sphereSprites);
  assert.equal(mesh.geometry.index.count / 3, 2);           // 2 triangles each
  const m = new THREE.Matrix4(), p = new THREE.Vector3();
  mesh.getMatrixAt(1, m);
  assert.deepEqual(p.setFromMatrixPosition(m).toArray(), [1, 2, 3]);
  assert.deepEqual(mesh.boundingBox.min.toArray(), [-1.5, -0.5, -0.5]);
  assert.deepEqual(mesh.boundingBox.max.toArray(), [1.5, 2.5, 4.5]);
});

test('setRadius changes the uniform and the bounds, not the geometry', () => {
  const v = new Viewer(new THREE.Scene());
  v.registerPointCloud('P', P, [1, 0, 0], 0.5);
  const mesh = v._objects.get('P').mesh, geo = mesh.geometry;
  v.setRadius('P', 1);
  assert.equal(mesh.geometry, geo);
  assert.equal(mesh.material.userData.kvRadius.value, 1);
  assert.deepEqual(mesh.boundingBox.max.toArray(), [2, 3, 5]);
});

test("render: 'sphere' keeps real sphere geometry", () => {
  const v = new Viewer(new THREE.Scene());
  v.registerPointCloud('S', P, [1, 0, 0], 0.5, 'sphere');
  const mesh = v._objects.get('S').mesh;
  assert.ok(!mesh.userData.sphereSprites);
  assert.ok(mesh.geometry.index.count / 3 > 100);
});
