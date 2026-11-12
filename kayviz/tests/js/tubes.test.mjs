// Curve tubes are one instanced cylinder: instance k spans edge k.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

test('each instance spans its edge, keeps the outward winding; a zero edge draws nothing', () => {
  const v = new Viewer(new THREE.Scene());
  const V = new Float32Array([0,0,0, 1,0,0, 1,2,0, 5,5,5, 0,0,3]);
  const E = new Int32Array([0,1, 1,2, 2,4, 3,3]);       // the last edge has length 0
  v.registerCurveNetwork('C', V, E, [1, 0, 0], 0.1);
  const mesh = v._objects.get('C').mesh;
  assert.ok(mesh.isInstancedMesh);
  assert.equal(mesh.count, 4);
  const m = new THREE.Matrix4(), p = new THREE.Vector3();
  for (let k = 0; k < 3; k++) {
    mesh.getMatrixAt(k, m);
    const a = [V[3*E[2*k]], V[3*E[2*k]+1], V[3*E[2*k]+2]];
    const b = [V[3*E[2*k+1]], V[3*E[2*k+1]+1], V[3*E[2*k+1]+2]];
    p.set(0, -0.5, 0).applyMatrix4(m);
    assert.deepEqual(p.toArray().map(x => +x.toFixed(5)), a);
    p.set(0, 0.5, 0).applyMatrix4(m);
    assert.deepEqual(p.toArray().map(x => +x.toFixed(5)), b);
    assert.ok(m.determinant() > 0, `edge ${k} turned inside out`);
    p.set(1, 0, 0).applyMatrix4(m).sub(new THREE.Vector3(0, 0, 0).applyMatrix4(m));
    assert.ok(Math.abs(p.length() - 0.1) < 1e-6, 'radius');
  }
  mesh.getMatrixAt(3, m);
  assert.equal(Math.abs(m.determinant()), 0);
  // bounds cover the instances, not the unit cylinder at the origin
  assert.ok(mesh.boundingBox.max.y >= 2 && mesh.boundingBox.max.z >= 3);
});
