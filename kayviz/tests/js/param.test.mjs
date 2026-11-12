// Parameterizations: a uv attribute and a checker/grid shader patch.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

const quad = { type: 'surface_mesh', name: 'M', face_size: 3,
  vertices: new Float32Array([0,0,0, 1,0,0, 1,1,0, 0,1,0]), faces: new Int32Array([0,1,2, 0,2,3]) };
const uv = new Float32Array([0,0, 1,0, 1,1, 0,1]);

function compile(material) {
  const shader = { uniforms: {}, vertexShader: '#include <begin_vertex>',
                   fragmentShader: 'void main() {\n#include <color_fragment>\n}' };
  material.onBeforeCompile(shader);
  return shader;
}

test('checker on, unticked off, removed with the quantity', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [quad, { type: 'parameterization_quantity', target: 'M',
                                     name: 'uv', uv, style: 'checker', scale: 4 }] });
  const e = v._objects.get('M');
  assert.deepEqual(Array.from(e.mesh.geometry.getAttribute('kvUV').array), Array.from(uv));
  const sh = compile(e.mesh.material);
  assert.equal(sh.uniforms.kvParamScale.value, 4);
  assert.match(sh.fragmentShader, /floor\(vKvUV \* kvParamScale\)/);
  v.setChildVisible('M', 'uv', false);
  assert.ok(!e.mesh.material.userData.kvPatches?.param);
  v.setChildVisible('M', 'uv', true);
  assert.ok(e.mesh.material.userData.kvPatches?.param);
  v.removeChild?.('M', 'uv') ?? e.removeChild('uv', v.scene, e.mesh);
  assert.equal(e.mesh.geometry.getAttribute('kvUV'), undefined);
});

test('with a face scalar shown (non-indexed copy) the uv follow the corners', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [quad,
    { type: 'scalar_quantity', target: 'M', name: 'f', defined_on: 'faces', values: new Float32Array([0, 1]) },
    { type: 'parameterization_quantity', target: 'M', name: 'uv', uv, style: 'grid', scale: 1 }] });
  const g = v._objects.get('M').mesh.geometry;
  assert.equal(g.index, null);                                  // non-indexed while the face scalar shows
  // corners of triangle 1 are vertices 0, 2, 3
  assert.deepEqual(Array.from(g.getAttribute('kvUV').array.slice(6, 12)), [0,0, 1,1, 0,1]);
  assert.match(compile(v._objects.get('M').mesh.material).fragmentShader, /fwidth\(kvG\)/);
});
