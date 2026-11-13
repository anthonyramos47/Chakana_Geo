// @ts-check
/**
 * OIT.js — order-independent transparency (weighted blended, McGuire & Bavoil 2013).
 *
 * three.js sorts translucent objects back to front, one depth per object: where
 * translucent shells intersect, or one folds over itself, the result depends on
 * the draw order. Here translucent fragments are summed instead, weighted by
 * alpha and depth, so the order does not matter:
 *
 *   1. the opaque scene into `opaque` (4x MSAA, depth kept as a texture);
 *   2. the translucent meshes twice, without depth test (each fragment compares
 *      itself with the opaque depth): accumulation sum(rgb*a*w, a*w) into `accum`,
 *      revealage prod(1 - a) into `reveal`;
 *   3. composite over `opaque`: avg colour = accum.rgb / accum.a, coverage 1 - reveal;
 *   4. out: tone mapping and colour space to the screen (OutputPass), or the
 *      linear result into the studio composer's buffer.
 *
 * Glass (transmission) keeps three's own path. Without translucent meshes in
 * view, a frame is a plain renderer.render.
 */

import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { setPatch } from './patches.js';

const LAYER = 31;          // the translucent meshes (and the lights) during passes 2

/** @param {THREE.Material} m */
const translucent = m => m.transparent && m.opacity < 1 &&
  !(/** @type {any} */ (m).transmission > 0) && !m.userData.glass;

const OIT_FRAGMENT = /* glsl */`
#include <dithering_fragment>
if (kvOitPass > 0) {
  float kvOpaqueZ = texture2D(kvOpaqueDepth, gl_FragCoord.xy / kvOitSize).r;
  if (gl_FragCoord.z > kvOpaqueZ) discard;            // behind an opaque surface
  float kvA = clamp(gl_FragColor.a, 0.0, 1.0);
  float kvZ = 1.0 - gl_FragCoord.z * 0.9;
  float kvW = clamp(pow(min(1.0, kvA * 10.0) + 0.01, 3.0) * 1e8 * kvZ * kvZ * kvZ, 1e-2, 3e3);
  if (kvOitPass == 1) gl_FragColor = vec4(gl_FragColor.rgb * kvA, kvA) * kvW;
  else gl_FragColor = vec4(kvA);
}`;

export class WeightedOIT {
  /** @param {THREE.WebGLRenderer} renderer */
  constructor(renderer) {
    this.renderer = renderer;
    const hf = { type: THREE.HalfFloatType };
    this.opaque = new THREE.WebGLRenderTarget(1, 1, {
      ...hf, samples: 4, depthTexture: new THREE.DepthTexture(1, 1),
    });
    this.accum  = new THREE.WebGLRenderTarget(1, 1, { ...hf, depthBuffer: false });
    this.reveal = new THREE.WebGLRenderTarget(1, 1, { ...hf, format: THREE.RedFormat, depthBuffer: false });
    this.uniforms = {
      kvOitPass:     { value: 0 },
      kvOpaqueDepth: { value: this.opaque.depthTexture },
      kvOitSize:     { value: new THREE.Vector2(1, 1) },
    };
    this._composite = new FullScreenQuad(new THREE.ShaderMaterial({
      uniforms: { tAccum: { value: this.accum.texture }, tReveal: { value: this.reveal.texture } },
      vertexShader: 'varying vec2 vUv;\nvoid main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: `uniform sampler2D tAccum; uniform sampler2D tReveal; varying vec2 vUv;
        void main() {
          vec4 acc = texture2D(tAccum, vUv);
          float coverage = 1.0 - texture2D(tReveal, vUv).r;
          if (coverage < 1e-4) discard;
          gl_FragColor = vec4(acc.rgb / clamp(acc.a, 1e-4, 5e4), coverage);
        }`,
      transparent: true, depthTest: false, depthWrite: false,
    }));
    this._copy = new FullScreenQuad(new THREE.MeshBasicMaterial({
      map: this.opaque.texture, depthTest: false, depthWrite: false, toneMapped: false,
    }));
    this._output = new OutputPass();
    this._size = new THREE.Vector2();
  }

  /** Give a translucent material the OIT output (a uniform picks the pass). */
  _patch(material) {
    if (material.userData.kvOit) return;
    material.userData.kvOit = true;
    const u = this.uniforms;
    setPatch(material, 'oit', shader => {
      Object.assign(shader.uniforms, u);
      shader.fragmentShader =
        'uniform int kvOitPass;\nuniform sampler2D kvOpaqueDepth;\nuniform vec2 kvOitSize;\n' +
        shader.fragmentShader.replace('#include <dithering_fragment>', OIT_FRAGMENT);
    });
  }

  /**
   * One frame. target null: the screen (tone mapped); a render target (the studio
   * composer's read buffer): the linear result.
   * @param {THREE.Scene} scene
   * @param {THREE.Camera} camera
   * @param {THREE.WebGLRenderTarget | null} target
   */
  render(scene, camera, target = null) {
    const r = this.renderer;
    /** @type {any[]} */
    const glassy = [];
    scene.traverseVisible((/** @type {any} */ o) => {
      if (o.isMesh && !o.userData.overlay && !o.userData.studioHelper &&
          !Array.isArray(o.material) && translucent(o.material)) glassy.push(o);
    });
    if (!glassy.length) {
      r.setRenderTarget(target);
      r.render(scene, camera);
      return;
    }
    if (target) this._size.set(target.width, target.height);
    else r.getDrawingBufferSize(this._size);
    const { x: w, y: h } = this._size;
    for (const t of [this.opaque, this.accum, this.reveal]) {
      if (t.width !== w || t.height !== h) t.setSize(w, h);
    }
    this.uniforms.kvOitSize.value.set(w, h);

    // 1. opaque
    for (const o of glassy) o.visible = false;
    r.setRenderTarget(this.opaque);
    r.clear();
    r.render(scene, camera);
    for (const o of glassy) o.visible = true;

    // 2. translucent only (a layer), no background, both sums
    const background = scene.background, mask = camera.layers.mask;
    scene.background = null;
    /** @type {any[]} */
    const lights = [];
    scene.traverse((/** @type {any} */ o) => { if (o.isLight) { lights.push(o); o.layers.enable(LAYER); } });
    for (const o of glassy) { o.layers.enable(LAYER); this._patch(o.material); }
    camera.layers.set(LAYER);
    const saved = glassy.map(o => {
      const m = o.material;
      return [m, m.blending, m.blendSrc, m.blendDst, m.blendEquation, m.depthTest, m.depthWrite];
    });
    const pass = (n, target, clear, src, dst) => {
      this.uniforms.kvOitPass.value = n;
      for (const o of glassy) {
        const m = o.material;
        m.blending = THREE.CustomBlending; m.blendEquation = THREE.AddEquation;
        m.blendSrc = src; m.blendDst = dst; m.depthTest = false; m.depthWrite = false;
      }
      r.setRenderTarget(target);
      r.setClearColor(clear, clear.a ?? 0);
      r.clear(true, false, false);
      r.render(scene, camera);
    };
    const clearColor = r.getClearColor(new THREE.Color()), clearAlpha = r.getClearAlpha();
    pass(1, this.accum, Object.assign(new THREE.Color(0, 0, 0), { a: 0 }),
         THREE.OneFactor, THREE.OneFactor);
    pass(2, this.reveal, Object.assign(new THREE.Color(1, 1, 1), { a: 1 }),
         THREE.ZeroFactor, THREE.OneMinusSrcColorFactor);
    this.uniforms.kvOitPass.value = 0;
    r.setClearColor(clearColor, clearAlpha);
    for (const [m, b, s, d, e, dt, dw] of saved) {
      m.blending = b; m.blendSrc = s; m.blendDst = d; m.blendEquation = e;
      m.depthTest = dt; m.depthWrite = dw;
    }
    camera.layers.mask = mask;
    for (const o of glassy) o.layers.disable(LAYER);
    for (const o of lights) o.layers.disable(LAYER);
    scene.background = background;

    // 3. composite over the opaque image
    r.setRenderTarget(this.opaque);
    this._composite.render(r);

    // 4. out
    if (target) {
      r.setRenderTarget(target);
      this._copy.render(r);
    } else {
      this._output.renderToScreen = true;
      this._output.render(r, null, this.opaque, 0, false);
    }
  }

  dispose() {
    for (const t of [this.opaque, this.accum, this.reveal]) t.dispose();
    this._composite.dispose();
    this._copy.dispose();
    this._output.dispose();
  }
}
