/**
 * Studio.js — "studio" render mode: a presentation look for figures and screenshots.
 *
 * Off (default) the viewer draws with renderer.render() as before. On, frames go
 * through an EffectComposer:
 *
 *   RenderPass -> [hide floor/grid/lines/translucent] -> GTAOPass -> [restore] -> OutputPass
 *
 * plus a soft (VSM) shadow from the key light onto an invisible shadow-catcher floor
 * under the scene, a softbox environment map for the PBR shader, a vertical gradient
 * backdrop, neutral tone mapping and 4x MSAA. Recipe adapted from the MIT-licensed
 * teardown project (github.com/elvarofficial/teardown, sims/v8-shared/stage.js).
 *
 * Everything that depends on the scene size (AO radius, shadow frustum, floor height)
 * is refitted to the bounding box of the visible objects every REFIT frames.
 */
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass }     from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass }       from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass }     from 'three/addons/postprocessing/OutputPass.js';
import { Pass }           from 'three/addons/postprocessing/Pass.js';

const REFIT = 30;   // frames between bounding-box refits

const BACKDROPS = {
  light: ['#f3f3f4', '#e9eaec', '#e3e4e6'],
  dark:  ['#2e3034', '#232427', '#18191b'],
};

// A pass that only runs a callback (used to hide objects around the AO pass).
class CallbackPass extends Pass {
  constructor(fn) { super(); this.needsSwap = false; this.fn = fn; }
  render() { this.fn(); }
}

function gradientTexture([top, mid, low]) {
  const c = document.createElement('canvas');
  c.width = 4; c.height = 512;
  const g = c.getContext('2d');
  const gr = g.createLinearGradient(0, 0, 0, 512);
  gr.addColorStop(0, top); gr.addColorStop(0.55, mid); gr.addColorStop(1, low);
  g.fillStyle = gr; g.fillRect(0, 0, 4, 512);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// Softbox studio for the environment map: a big top box, two side strips, a front kicker.
function studioEnvironment(renderer) {
  const env = new THREE.Scene();
  env.background = new THREE.Color('#d9dadd');
  const box = (w, h, pos, k) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 1, 1).multiplyScalar(k),
                                    side: THREE.DoubleSide }));
    m.position.copy(pos); m.lookAt(0, 0, 0); env.add(m);
  };
  box(12, 12, new THREE.Vector3(0, 14, 2), 2.6);
  box(3, 14, new THREE.Vector3(-12, 4, 6), 3.4);
  box(3, 14, new THREE.Vector3(12, 4, -4), 2.2);
  box(18, 2, new THREE.Vector3(0, 2, 14), 1.6);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(40, 32),
    new THREE.MeshBasicMaterial({ color: '#c9cacd', side: THREE.DoubleSide }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -2; env.add(ground);
  const pm = new THREE.PMREMGenerator(renderer);
  const tex = pm.fromScene(env, 0.02).texture;
  pm.dispose();
  return tex;
}

export class Studio {
  /**
   * @param {THREE.WebGLRenderer} renderer
   * @param {THREE.Scene} scene
   * @param {THREE.Camera} camera
   * @param {{keyLight: THREE.DirectionalLight, ambient: THREE.AmbientLight,
   *          grid: THREE.Object3D}} opts
   */
  constructor(renderer, scene, camera, { keyLight, ambient, grid, up = 'y' }) {
    this.renderer = renderer;
    this.scene    = scene;
    this.camera   = camera;
    this.keyLight = keyLight;
    this.ambient  = ambient;
    this.grid     = grid;
    this.up       = up;           // 'y' or 'z': the floor lies across it
    this.enabled  = false;
    this.theme    = 'dark';
    this.studioPixelRatio = 1;
    this._frame   = 0;
    this._size    = new THREE.Vector2();
    this._pr      = 0;
    this._saved   = null;   // viewer state restored by disable()
    this._hidden  = [];
    this._R       = 1;      // scene half-diagonal from the last refit
    // ao: AO blend strength; aoRadius: AO reach as a fraction of the scene half-diagonal;
    // shadow: darkness of the floor shadow.
    this.params   = { ao: 0.8, aoRadius: 0.2, shadow: 0.3 };

    // RenderPass draws into readBuffer (renderTarget2, 4x MSAA + depth); the post
    // passes (GTAO blend, OutputPass) only draw full-screen quads into writeBuffer
    // (renderTarget1) or the screen, so renderTarget1 needs neither MSAA nor depth.
    // This relies on an even number of swapping passes per frame (GTAO, Output):
    // disabling or adding one would make the next RenderPass draw into renderTarget1.
    const target = new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(renderer, target);
    this.composer.renderTarget1.samples = 0;
    this.composer.renderTarget1.depthBuffer = false;
    this.composer.addPass(new RenderPass(scene, camera));
    this.gtao = new GTAOPass(scene, camera, 4, 4);
    this.gtao.output = GTAOPass.OUTPUT.Default;
    this.gtao.blendIntensity = this.params.ao;
    this.gtao.updateGtaoMaterial({ distanceExponent: 1, scale: 1, samples: 16, distanceFallOff: 1,
                                   screenSpaceRadius: false });
    this.gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6,
                                 rings: 2, samples: 16 });
    this.composer.addPass(new CallbackPass(() => this._hideForAO()));
    this.composer.addPass(this.gtao);
    this.composer.addPass(new CallbackPass(() => this._restoreAfterAO()));
    this.composer.addPass(new OutputPass());

    // Shadow catcher: invisible floor that only shows the shadow.
    this.floor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
      new THREE.ShadowMaterial({ color: '#4d535c', opacity: 0.3, polygonOffset: true,
                                 polygonOffsetFactor: -4, polygonOffsetUnits: -8 }));
    if (up === 'y') this.floor.rotation.x = -Math.PI / 2;   // PlaneGeometry faces +z
    this.floor.receiveShadow = true;
    this.floor.visible = false;
    this.floor.userData.studioHelper = true;
    scene.add(this.floor);

    this._envTex = null;   // built lazily on first enable
    // geometry replaced in place keeps the child count: refit on every scene change
    this._refitDue = false;
    document.addEventListener?.('viewer-changed', () => { this._refitDue = true; });
    this._backdrops = { light: gradientTexture(BACKDROPS.light),
                        dark:  gradientTexture(BACKDROPS.dark) };
  }

  // ── public ──────────────────────────────────────────────────────────────────

  setEnabled(on) {
    if (on === this.enabled) return;
    const r = this.renderer, s = this.scene, k = this.keyLight;
    if (on) {
      this._envTex ??= studioEnvironment(r);
      this._saved = {
        environment: s.environment, envIntensity: s.environmentIntensity,
        toneMapping: r.toneMapping, shadowType: r.shadowMap.type,
        gridVisible: this.grid.visible, castShadow: k.castShadow,
        shadowMapSize: k.shadow.mapSize.clone(),
        keyIntensity: k.intensity, ambientIntensity: this.ambient?.intensity,
        keyPosition: k.position.clone(),
      };
      // Studio lighting: flat ambient light washes the shadows out, so the environment map
      // does the fill and the key light carries the shadow. Restored by setEnabled(false).
      s.environment = this._envTex;
      s.environmentIntensity = 0.7;
      k.intensity = 2.0;
      if (this.ambient) this.ambient.intensity = 0.1;
      r.toneMapping = THREE.NeutralToneMapping;
      r.shadowMap.type = THREE.VSMShadowMap;
      this.grid.visible = false;
      k.castShadow = true;
      // 2048: a VSM map is two RGBA half-float targets, 4096² cost ~270 MB of GPU memory
      k.shadow.mapSize.set(2048, 2048);
      k.shadow.radius = 8;
      k.shadow.blurSamples = 24;
      s.add(k.target);
      this.floor.visible = true;
      this.enabled = true;
      this._frame = 0;
      this.applyTheme(this.theme);
    } else {
      const sv = this._saved;
      s.environment = sv.environment;
      s.environmentIntensity = sv.envIntensity;
      r.toneMapping = sv.toneMapping;
      r.shadowMap.type = sv.shadowType;
      this.grid.visible = sv.gridVisible;
      k.castShadow = sv.castShadow;
      k.intensity = sv.keyIntensity;
      k.position.copy(sv.keyPosition);
      if (this.ambient) this.ambient.intensity = sv.ambientIntensity;
      k.target.position.set(0, 0, 0);
      k.target.updateMatrixWorld();
      this.floor.visible = false;
      this.enabled = false;
      this._releaseGPU(sv.shadowMapSize);
    }
    r.shadowMap.needsUpdate = true;
    // Shadow-map type and tone mapping are baked into compiled programs.
    s.traverse(o => {
      if (!o.material) return;
      for (const m of [o.material].flat()) m.needsUpdate = true;
    });
  }

  setAO(v)            { this.params.ao = v; this.gtao.blendIntensity = v; }
  setAORadius(v)      { this.params.aoRadius = v; this._applyAORadius(); }
  setShadow(v)        { this.params.shadow = v; this.floor.material.opacity = v; }
  setPixelRatioCap(x) { this.studioPixelRatio = x > 0 ? x : 1; window.__invalidate?.(); }

  /** 'light' | 'dark': picks the gradient backdrop (only while enabled). */
  applyTheme(name) {
    this.theme = name === 'light' ? 'light' : 'dark';
    if (this.enabled) this.scene.background = this._backdrops[this.theme];
  }

  /** Draw one frame (call instead of renderer.render while enabled). */
  render() {
    this._syncSize();
    // Refit when objects are added/removed, and every REFIT frames for edits in place.
    const n = this.scene.children.length;
    if (this._refitDue || this._frame++ % REFIT === 0 || n !== this._nChildren) {
      this._nChildren = n; this._refitDue = false; this.refit();
    }
    this._markShadowCasters();
    this.composer.render();
  }

  /** Refit AO radius, shadow frustum and floor to the visible objects. */
  refit() {
    const box = new THREE.Box3();
    this.scene.traverseVisible(o => {
      if (o === this.floor || o === this.grid || o.isLight || o.userData.studioHelper) return;
      if ((o.isMesh || o.isLine || o.isPoints) && o.geometry) box.expandByObject(o);
    });
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const R = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6);
    this._R = R;
    this._applyAORadius();

    if (this.up === 'z') this.floor.position.set(c.x, c.y, box.min.z - 0.002 * R);
    else                 this.floor.position.set(c.x, box.min.y - 0.002 * R, c.z);
    this.floor.scale.set(20 * R, 20 * R, 1);

    // Directional shadow: aim the key light at the centre, ortho frustum around the box.
    const k = this.keyLight, sc = k.shadow.camera;
    // Same direction as the plain key light (position seen from the origin), placed
    // relative to the scene: an absolute position lights a far-away scene sideways.
    const dir = this._saved?.keyPosition.clone().normalize() ?? new THREE.Vector3(0, 0, 1);
    k.position.copy(c).addScaledVector(dir, 4 * R);
    k.target.position.copy(c);
    k.target.updateMatrixWorld();
    const d = k.position.distanceTo(c);
    const ext = 1.6 * R;   // covers the shadow's spread onto the floor
    Object.assign(sc, { left: -ext, right: ext, top: ext, bottom: -ext,
                        near: Math.max(d - 4 * R, 1e-3), far: d + 4 * R });
    sc.updateProjectionMatrix();
    k.shadow.bias = -0.0004;
    k.shadow.normalBias = 0.002 * R;
  }

  // ── internals ───────────────────────────────────────────────────────────────

  _applyAORadius() {
    const u = this.gtao.gtaoMaterial.uniforms, r = this.params.aoRadius * this._R;
    u.radius.value = r;
    u.thickness.value = 2 * r;
  }

  /**
   * Free the studio's GPU buffers (~1 GB at DPR 2: multisampled half-float composer
   * targets, GTAO targets, VSM shadow maps). On Apple silicon this is system RAM.
   * three.js reallocates the composer targets on the next studio frame.
   */
  _releaseGPU(shadowMapSize) {
    this.composer.renderTarget1.dispose();
    this.composer.renderTarget2.dispose();
    this.gtao.normalRenderTarget.dispose();
    this.gtao.gtaoRenderTarget.dispose();
    this.gtao.pdRenderTarget.dispose();
    const sh = this.keyLight.shadow;
    sh.map?.dispose();     sh.map = null;       // rebuilt by the renderer when needed
    sh.mapPass?.dispose(); sh.mapPass = null;
    sh.mapSize.copy(shadowMapSize);
  }

  _syncSize() {
    const r = this.renderer;
    r.getSize(this._size);
    const pr = Math.min(r.getPixelRatio(), this.studioPixelRatio);
    const key = `${this._size.x}x${this._size.y}@${pr}`;
    if (key === this._sizeKey) return;
    this._sizeKey = key;
    this._pr = pr;
    this.composer.setPixelRatio(pr);
    this.composer.setSize(this._size.x, this._size.y);
  }

  // Opaque-ish meshes cast shadows; very translucent ones and helpers don't. Opaque meshes
  // also receive them, so objects shade each other and not only the floor.
  _markShadowCasters() {
    this.scene.traverse(o => {
      if (!o.isMesh || o === this.floor) return;
      const m = Array.isArray(o.material) ? o.material[0] : o.material;
      o.castShadow = !!m && !m.userData.glass && !(m.transparent && m.opacity < 0.5);
      o.receiveShadow = !!m && !m.transparent;
    });
  }

  // The AO pass sees only solid surfaces: no floor, grid, lines, points or translucent shells
  // (a translucent shell would otherwise darken everything inside it). The background goes
  // too: GTAO renders its normal/depth buffer with scene.overrideMaterial, which also catches
  // the plane three.js draws a texture background with, so the backdrop would land in the
  // depth buffer as a large dark quad.
  _hideForAO() {
    this._background = this.scene.background;
    this.scene.background = null;
    const hide = this._hidden;
    this.scene.traverseVisible(o => {
      if (o === this.floor || o === this.grid || o.isLine || o.isPoints || o.isSprite) {
        hide.push(o); return;
      }
      const m = o.material && (Array.isArray(o.material) ? o.material[0] : o.material);
      if (o.isMesh && m && m.transparent && (m.opacity < 1 || m.userData.glass)) hide.push(o);
    });
    for (const o of hide) o.visible = false;
  }

  _restoreAfterAO() {
    for (const o of this._hidden) o.visible = true;
    this._hidden.length = 0;
    this.scene.background = this._background;
  }
}
