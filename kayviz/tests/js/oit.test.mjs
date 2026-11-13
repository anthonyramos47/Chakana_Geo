// Order-independent transparency: which meshes take part, and the shader patch.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { WeightedOIT } = await import('../../src/kayviz/static/lib/OIT.js');

function stubRenderer() {
  const calls = [];
  return { calls, setRenderTarget: t => calls.push(['target', t]), render: () => calls.push(['render']),
           getDrawingBufferSize: v => v.set(8, 8), clear() {}, getClearColor: c => c,
           getClearAlpha: () => 1, setClearColor() {} };
}

test('without translucent meshes a frame is a plain render', () => {
  const r = stubRenderer(), oit = new WeightedOIT(/** @type {any} */ (r));
  const scene = new THREE.Scene();
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial()));
  const glass = new THREE.Mesh(new THREE.BoxGeometry(),
    new THREE.MeshPhysicalMaterial({ transmission: 1, transparent: true, opacity: 0.5 }));
  scene.add(glass);                                     // glass keeps three's path
  oit.render(scene, new THREE.PerspectiveCamera(), null);
  assert.deepEqual(r.calls, [['target', null], ['render']]);
});

test('translucent materials get the OIT output; the uniform picks the pass', () => {
  const r = stubRenderer(), oit = new WeightedOIT(/** @type {any} */ (r));
  const m = new THREE.MeshPhongMaterial({ transparent: true, opacity: 0.4 });
  oit._patch(m);
  const shader = { uniforms: {}, fragmentShader: 'void main() {\n#include <dithering_fragment>\n}' };
  m.onBeforeCompile(/** @type {any} */ (shader), /** @type {any} */ (null));
  assert.equal(shader.uniforms.kvOitPass, oit.uniforms.kvOitPass);
  assert.match(shader.fragmentShader, /if \(gl_FragCoord.z > kvOpaqueZ\) discard;/);
  assert.match(shader.fragmentShader, /kvOitPass == 1/);
});
