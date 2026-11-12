// Scalar quantities, face labels and message robustness, run against the real
// viewer modules and three.js (no WebGL: only CPU-side state is checked).
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');
const { LabelRenderer } = await import('../../src/kayviz/static/LabelRenderer.js');
const { NAN_COLOR } = await import('../../src/kayviz/static/lib/colormap.js');

// two quads, fan-triangulated by the server (trisPerFace = [2, 2])
const V = new Float32Array([0,0,0, 1,0,0, 1,1,0, 0,1,0, 2,0,0, 2,1,0]);
const F = new Int32Array([0,1,2, 0,2,3, 1,4,5, 1,5,2]);

function mesh(color = [1, 0, 0], material = null) {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'M', vertices: V, faces: F,
                               tris_per_face: [2, 2], color, material }] });
  return [v, v.objects.get('M')];
}
const rgb = c => [c.r, c.g, c.b].map(x => +x.toFixed(3));

test('the colormap is not tinted by the mesh colour, which comes back afterwards', () => {
  const [v, e] = mesh([1, 0, 0]);
  v.addScalarQuantity('M', 'h', new Float32Array([0, 1, 2, 3, 4, 5]));
  assert.deepEqual(rgb(e.mesh.material.color), [1, 1, 1]);
  v.setColor('M', [0, 0, 1]);                       // while the scalar is shown
  assert.deepEqual(rgb(e.mesh.material.color), [1, 1, 1]);
  v.setActiveScalar('M', null);
  assert.deepEqual(rgb(e.mesh.material.color), [0, 0, 1]);
  assert.equal(e.mesh.material.vertexColors, false);
});

test('face scalar then vertex scalar: indexed geometry comes back, buffers match', () => {
  const [v, e] = mesh();
  const indexed = e.mesh.geometry;
  v.addScalarQuantity('M', 'f', new Float32Array([0, 1]), 'faces');
  assert.equal(e.mesh.geometry.index, null);
  assert.equal(e.mesh.geometry.attributes.color.count, 12);   // 4 triangles x 3 corners
  v.addScalarQuantity('M', 'h', new Float32Array([0, 1, 2, 3, 4, 5]));
  v.setActiveScalar('M', 'h');
  assert.equal(e.mesh.geometry, indexed);
  assert.equal(e.mesh.geometry.attributes.color.count, e.mesh.geometry.attributes.position.count);
});

test('NaN and Inf values do not throw and get the NaN colour', () => {
  const [v, e] = mesh();
  v.addScalarQuantity('M', 'h', new Float32Array([0, NaN, 1, Infinity, 2, 3]));
  const c = e.mesh.geometry.attributes.color.array;
  assert.deepEqual(Array.from(c.slice(3, 6)), NAN_COLOR);
  const s = e.children.get('h');
  assert.deepEqual([s.dataMin, s.dataMax], [0, 3]);
});

test('changing the range rewrites the same colour buffer', () => {
  const [v, e] = mesh();
  v.addScalarQuantity('M', 'h', new Float32Array([0, 1, 2, 3, 4, 5]));
  const attr = e.mesh.geometry.attributes.color;
  v.setScalarRange('M', 'h', 1, 2);
  assert.equal(e.mesh.geometry.attributes.color, attr);
});

test('face labels work while a face scalar is shown', () => {
  const [v, e] = mesh();
  v.addScalarQuantity('M', 'f', new Float32Array([0, 1]), 'faces');
  e.opts.showFaceIndices = true;
  const labels = [];
  const lr = new LabelRenderer();
  lr._drawLabel = (text) => labels.push(text);
  const cam = new THREE.PerspectiveCamera(45, 4 / 3, 0.01, 100);
  cam.position.set(1, 0.5, 4); cam.lookAt(1, 0.5, 0); cam.updateMatrixWorld();
  lr.render(v, cam);
  assert.deepEqual(labels, ['0', '1']);
});

test('colour and scalars on shaders without a colour do not throw', () => {
  for (const shader of ['normal', 'depth', 'blinn_phong']) {
    const [v] = mesh([0.5, 0.5, 0.5], shader);
    v.setColor('M', [1, 0, 0]);
    v.addScalarQuantity('M', 'h', new Float32Array([0, 1, 2, 3, 4, 5]));
  }
});

test('one bad object does not lose the rest of the message', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [
    { type: 'surface_mesh', name: 'Bad', vertices: V, faces: null },
    { type: 'point_cloud', name: 'Good', points: V },
  ] });
  assert.ok(v.objects.has('Good'));
  assert.equal(v.errors.length, 1);
});

test('isolines: a scalar attribute and a shader patch, removed with the scalar', async () => {
  const { Viewer } = await import('../../src/kayviz/static/viewer.js');
  const THREE = await import('three');
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ type: 'surface_mesh', name: 'M', face_size: 3,
    vertices: new Float32Array([0,0,0, 1,0,0, 0,1,0]), faces: new Int32Array([0,1,2]) },
    { type: 'scalar_quantity', target: 'M', name: 'h', defined_on: 'vertices',
      values: new Float32Array([0, 5, 10]), isolines: { spacing: null, width: 2 } }] });
  const m = v._objects.get('M').mesh;
  assert.deepEqual(Array.from(m.geometry.getAttribute('kvScalar').array), [0, 5, 10]);
  const shader = { uniforms: {}, vertexShader: '#include <begin_vertex>',
                   fragmentShader: 'void main() {\n#include <color_fragment>\n}' };
  m.material.onBeforeCompile(shader);
  assert.equal(shader.uniforms.kvIsoSpacing.value, 1);       // a tenth of 0..10
  assert.equal(shader.uniforms.kvIsoWidth.value, 2);
  assert.match(shader.fragmentShader, /fwidth\(kvF\)/);
  v.setScalarRange('M', 'h', 0, 20);
  assert.equal(shader.uniforms.kvIsoSpacing.value, 2);       // follows the range
  v.setActiveScalar('M', null);
  assert.equal(m.geometry.getAttribute('kvScalar'), undefined);
  assert.ok(!m.material.userData.kvPatches?.isolines);
});
