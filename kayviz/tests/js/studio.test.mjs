// Studio render buffers: pixel-ratio cap, single-MSAA composer setup, and bufferBytes.
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

const THREE = await import('three');
const { Studio } = await import('../../src/kayviz/static/lib/Studio.js');
const { bufferBytes } = await import('../../src/kayviz/static/benchmark.js');

const MB = 1024 * 1024;

function makeStudio(drawW = 2744, drawH = 1518, pr = 2) {
  let ratio = pr;
  const renderer = {
    toneMapping: THREE.ACESFilmicToneMapping,
    shadowMap: { type: THREE.PCFSoftShadowMap, needsUpdate: false },
    getPixelRatio: () => ratio,
    setPixelRatio: (r) => { ratio = r; },
    getSize: (v) => v.set(drawW / ratio, drawH / ratio),
    getDrawingBufferSize: (v) => v.set(drawW, drawH),
  };
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, drawW / drawH, 0.01, 100);
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
  const ambient = new THREE.AmbientLight(0xffffff, 0.5);
  const grid = new THREE.Object3D();
  const studio = new Studio(renderer, scene, camera, { keyLight, ambient, grid });
  studio._envTex = new THREE.Texture();   // avoid PMREMGenerator needing a WebGL context
  studio.setEnabled(true);
  return { renderer, studio };
}

test('bufferBytes for a 2744x1518 canvas at ratio 2 with cap 1 reports studio + shadow <= 200 MB', () => {
  const { renderer, studio } = makeStudio(2744, 1518, 2);
  assert.equal(studio.studioPixelRatio, 1);
  const buf = bufferBytes(renderer, studio);
  assert.equal(buf.width, 2744);
  assert.equal(buf.height, 1518);
  const studioPlusShadowMB = (buf.composer + buf.shadow) / MB;
  assert.ok(studioPlusShadowMB <= 200, `expected <= 200 MB, got ${studioPlusShadowMB.toFixed(1)} MB`);
  // 1372x759 studio pixels * 88 B/px = 87.39 MB; 2048^2 * 20 B/px shadow = 80.00 MB
  assert.equal(buf.composer, 1372 * 759 * 88);
  assert.equal(buf.shadow, 2048 * 2048 * 20);
});

test('setPixelRatioCap changes studio target sizes and bufferBytes', () => {
  const { renderer, studio } = makeStudio(2744, 1518, 2);
  studio._syncSize();
  assert.equal(studio.composer.renderTarget2.width, 1372);
  assert.equal(studio.composer.renderTarget2.height, 759);
  assert.equal(studio.composer.renderTarget2.samples, 4);
  assert.equal(studio.composer.renderTarget2.depthBuffer, true);
  assert.equal(studio.composer.renderTarget1.samples, 0);
  assert.equal(studio.composer.renderTarget1.depthBuffer, false);

  studio.setPixelRatioCap(2);
  studio._syncSize();
  assert.equal(studio.composer.renderTarget2.width, 2744);
  assert.equal(studio.composer.renderTarget2.height, 1518);
  assert.equal(bufferBytes(renderer, studio).composer, 2744 * 1518 * 88);

  studio.setPixelRatioCap(1);
  studio._syncSize();
  assert.equal(studio.composer.renderTarget2.width, 1372);
  assert.equal(bufferBytes(renderer, studio).composer, 1372 * 759 * 88);
});
