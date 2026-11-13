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

test('per-corner uv: a seam (one vertex, two uv) on quads fanned by the viewer', () => {
  const v = new Viewer(new THREE.Scene());
  // two quads sharing the edge 1-4; corners in face order, quad 2 starts its own chart
  const quads = { type: 'surface_mesh', name: 'Q', face_size: 4,
    vertices: new Float32Array([0,0,0, 1,0,0, 2,0,0, 0,1,0, 1,1,0, 2,1,0]),
    faces: new Int32Array([0,1,4,3, 1,2,5,4]) };
  const uv = new Float32Array([0,0, 1,0, 1,1, 0,1,   5,5, 6,5, 6,6, 5,6]);
  v.applyMessage({ objects: [quads, { type: 'parameterization_quantity', target: 'Q', name: 'c',
                                      uv, defined_on: 'corners', style: 'checker', scale: 1 }] });
  const e = v._objects.get('Q'), g = e.mesh.geometry;
  assert.equal(g.index, null);
  const a = Array.from(g.getAttribute('kvUV').array);
  // quad 1 triangles (0,1,2),(0,2,3) of its corners; quad 2 likewise from corner 4
  assert.deepEqual(a.slice(0, 12), [0,0, 1,0, 1,1,  0,0, 1,1, 0,1]);
  assert.deepEqual(a.slice(12, 24), [5,5, 6,5, 6,6,  5,5, 6,6, 5,6]);
  // a vertex scalar meanwhile is expanded through the index: vertex 4 is corner 2 of quad 1
  v.applyMessage({ objects: [{ type: 'scalar_quantity', target: 'Q', name: 's', defined_on: 'vertices',
                               values: new Float32Array([0, 1, 2, 3, 4, 5]) }] });
  assert.equal(e.mesh.geometry.index, null);
  const col = e.mesh.geometry.getAttribute('color').array;
  assert.notDeepEqual(Array.from(col.slice(0, 3)), Array.from(col.slice(6, 9)));   // vertices 0 vs 4
  e.removeChild('c', v.scene, e.mesh);
  assert.notEqual(e.mesh.geometry.index, null);    // nothing needs the copy: indexed again
});
