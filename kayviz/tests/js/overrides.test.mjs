// Scene-panel changes survive Python re-registering the object (kv.clear() + register).
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Viewer } = await import('../../src/kayviz/static/viewer.js');

const V = new Float32Array([0,0,0, 1,0,0, 1,1,0]);
const F = new Int32Array([0, 1, 2]);
const push = (v, extra = {}) => v.applyMessage({ objects: [
  { action: 'clear' },
  { type: 'surface_mesh', name: 'M', vertices: V, faces: F, color: [0.8, 0.8, 0.8], ...extra },
] });

test('hidden, recoloured and scalar range stay after re-registration', () => {
  const v = new Viewer(new THREE.Scene());
  push(v);
  v.setEnabled('M', false); v.remember('M', 'visible', false);
  v.setColor('M', [1, 0, 0]); v.remember('M', 'color', [1, 0, 0]);
  push(v);                                            // same values from Python
  const e = v.objects.get('M');
  assert.equal(e.visible, false);
  assert.deepEqual(e.color, [1, 0, 0]);
});

test('a value Python changes wins over the panel', () => {
  const v = new Viewer(new THREE.Scene());
  push(v);
  v.setColor('M', [1, 0, 0]); v.remember('M', 'color', [1, 0, 0]);
  push(v, { color: [0, 0, 1] });                      // Python sends a new colour
  assert.deepEqual(v.objects.get('M').color, [0, 0, 1]);
  push(v, { color: [0, 0, 1] });
  assert.deepEqual(v.objects.get('M').color, [0, 0, 1]);   // the override is gone
});
