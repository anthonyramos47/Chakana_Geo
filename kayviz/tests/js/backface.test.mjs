// back_color: faces seen from behind take another colour, also after a shader swap.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

const mesh = { type: 'surface_mesh', name: 'M', face_size: 3,
               vertices: new Float32Array([0,0,0, 1,0,0, 0,1,0]), faces: new Int32Array([0,1,2]) };

function patched(material) {
  const shader = { uniforms: {}, fragmentShader: 'void main() {\n#include <color_fragment>\n}' };
  material.onBeforeCompile(shader);
  return shader;
}

test('back_color patches the fragment shader with gl_FrontFacing', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ ...mesh, back_color: [1, 0, 0] }] });
  const sh = patched(v._objects.get('M').mesh.material);
  assert.match(sh.fragmentShader, /if \(!gl_FrontFacing\) diffuseColor.rgb = kvBackColor;/);
  assert.deepEqual(sh.uniforms.kvBackColor.value.toArray(), [1, 0, 0]);
});

test('a swapped material keeps it; null removes it', () => {
  const v = new Viewer(new THREE.Scene());
  v.applyMessage({ objects: [{ ...mesh, back_color: [0, 0, 1] }] });
  const other = v.matLib.list().find(n => n !== v._objects.get('M').opts.material);
  v.setMaterial('M', other);
  assert.match(patched(v._objects.get('M').mesh.material).fragmentShader, /gl_FrontFacing/);
  v.setBackColor('M', null);
  assert.ok(!v._objects.get('M').mesh.material.userData.kvBack);
});
