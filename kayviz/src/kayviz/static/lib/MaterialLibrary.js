/**
 * MaterialLibrary.js — Named material / shader registry.
 *
 * Provides a catalogue of built-in materials and lets you register custom
 * ones (including raw GLSL shaders).  The Viewer calls `get(name)` to
 * resolve a material instance; hot-swapping is done via `viewer.setMaterial()`.
 *
 * Built-in names
 * ──────────────
 *   'lambert'    MeshLambertMaterial  — fast diffuse, no specular
 *   'phong'      MeshPhongMaterial    — diffuse + specular highlights
 *   'matcap'     MeshMatcapMaterial   — view-space shading from a texture
 *   'normal'     MeshNormalMaterial   — RGB = world-space normals (debug)
 *   'wireframe'  MeshBasicMaterial    — wireframe overlay
 *   'flat'       MeshBasicMaterial    — unlit flat colour
 *   'depth'      MeshDepthMaterial    — depth visualisation
 *   'toon'       MeshToonMaterial     — cel-shaded cartoon look
 *   'physical'   MeshPhysicalMaterial — PBR (metalness / roughness)
 *
 * Custom GLSL shaders
 * ───────────────────
 *   MaterialLibrary.register('myShader', {
 *     type: 'shader',
 *     vertexShader:   '...',   // GLSL string
 *     fragmentShader: '...',   // GLSL string
 *     uniforms: { uTime: { value: 0 } },
 *   });
 *
 * Parameterised built-ins
 * ───────────────────────
 *   MaterialLibrary.register('gold', {
 *     type: 'physical',
 *     color: [1.0, 0.76, 0.33],
 *     metalness: 1.0,
 *     roughness: 0.2,
 *   });
 */

import * as THREE from 'three';

// ── Default GLSL shaders ────────────────────────────────────────────────────

const _DEFAULT_VERT = /* glsl */ `
varying vec3 vNormal;
varying vec3 vPosition;

void main() {
  vNormal   = normalMatrix * normal;
  vPosition = (modelViewMatrix * vec4(position, 1.0)).xyz;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const _DEFAULT_FRAG = /* glsl */ `
// Minimal Blinn-Phong with two hardcoded lights.
// Replace or extend as needed.
uniform vec3  uColor;
uniform float uShininess;

varying vec3 vNormal;
varying vec3 vPosition;

void main() {
  vec3 N = normalize(vNormal);
  vec3 V = normalize(-vPosition);

  // Key light
  vec3 L1    = normalize(vec3(4.0, 8.0, 6.0) - vPosition);
  float diff = max(dot(N, L1), 0.0);
  vec3  H1   = normalize(L1 + V);
  float spec = pow(max(dot(N, H1), 0.0), uShininess);

  // Fill light (soft, from opposite side)
  vec3 L2     = normalize(vec3(-4.0, 2.0, -4.0) - vPosition);
  float diff2 = max(dot(N, L2), 0.0) * 0.3;

  vec3 ambient  = uColor * 0.15;
  vec3 diffuse  = uColor * (diff + diff2);
  vec3 specular = vec3(0.4) * spec;

  gl_FragColor = vec4(ambient + diffuse + specular, 1.0);
}
`;

const _MATCAP_FRAG = /* glsl */ `
// View-space matcap — works without a texture by deriving a gradient from
// the normal.  Replace uMatcap with a sampler2D for a real matcap texture.
varying vec3 vNormal;

void main() {
  vec3 N = normalize(vNormal);
  // Map view-space XY normal to a simple warm-cool colour gradient.
  vec3 warm = vec3(0.95, 0.70, 0.30);
  vec3 cool = vec3(0.15, 0.40, 0.75);
  float t  = 0.5 + 0.5 * N.y;
  gl_FragColor = vec4(mix(cool, warm, t), 1.0);
}
`;

// ── Built-in material definitions ───────────────────────────────────────────

const _BUILTINS = {
  lambert: {
    type: 'lambert',
    color: [0.8, 0.8, 0.8],
    side: 'double',
  },
  phong: {
    type: 'phong',
    color: [0.8, 0.8, 0.8],
    shininess: 60,
    side: 'double',
  },
  matcap: {
    type: 'shader',
    vertexShader:   _DEFAULT_VERT,
    fragmentShader: _MATCAP_FRAG,
    uniforms: {},
    side: 'double',
  },
  normal: {
    type: 'normal',
    side: 'double',
  },
  wireframe: {
    type: 'basic',
    color: [0.5, 0.5, 0.5],
    wireframe: true,
  },
  flat: {
    type: 'basic',
    color: [0.8, 0.8, 0.8],
    side: 'double',
  },
  depth: {
    type: 'depth',
  },
  toon: {
    type: 'toon',
    color: [0.8, 0.8, 0.8],
  },
  physical: {
    type: 'physical',
    color: [0.8, 0.8, 0.8],
    metalness: 0.0,
    roughness: 0.5,
    side: 'double',
  },
  blinn_phong: {
    type: 'shader',
    vertexShader:   _DEFAULT_VERT,
    fragmentShader: _DEFAULT_FRAG,
    uniforms: {
      uColor:     { value: new THREE.Color(0.8, 0.8, 0.8) },
      uShininess: { value: 64.0 },
    },
    side: 'double',
  },
};

// ── MaterialLibrary ─────────────────────────────────────────────────────────

export class MaterialLibrary {
  constructor() {
    // name → definition object (plain config, not a THREE material instance)
    this._defs = new Map(Object.entries(_BUILTINS));
  }

  /**
   * Register a named material definition.
   *
   * @param {string} name     — unique key used in viewer.setMaterial()
   * @param {object} def      — definition object; see file header for shape
   *
   * Definition shapes
   * ─────────────────
   * Built-in type shorthand:
   *   { type: 'lambert' | 'phong' | 'physical' | 'toon' | 'basic' | 'normal' | 'depth',
   *     color?: [r,g,b],  metalness?: n, roughness?: n, shininess?: n,
   *     wireframe?: bool, side?: 'front'|'back'|'double' }
   *
   * Custom GLSL:
   *   { type: 'shader',
   *     vertexShader: string, fragmentShader: string,
   *     uniforms?: { [name]: { value: any } },
   *     side?: 'front'|'back'|'double' }
   */
  register(name, def) {
    this._defs.set(name, def);
  }

  /**
   * Returns true if a definition with this name is registered.
   * @param {string} name
   */
  has(name) {
    return this._defs.has(name);
  }

  /**
   * Return a list of all registered material names.
   * @returns {string[]}
   */
  list() {
    return [...this._defs.keys()];
  }

  /**
   * Instantiate a THREE.Material from the named definition, tinted to `color`.
   *
   * @param {string}   name   — registered material name
   * @param {number[]} color  — [r,g,b] in 0-1 (tints the material's base color)
   * @param {number}   opacity — 0-1 opacity (1 = fully opaque)
   * @returns {THREE.Material}
   */
  build(name, color = [0.8, 0.8, 0.8], opacity = 1.0) {
    const def = this._defs.get(name);
    if (!def) throw new Error(`MaterialLibrary: unknown material "${name}"`);

    const side        = this._side(def.side ?? 'double');
    const col         = new THREE.Color(...(color ?? def.color ?? [0.8, 0.8, 0.8]));
    const transparent = opacity < 1.0;

    switch (def.type) {
      case 'lambert':
        return new THREE.MeshLambertMaterial({ color: col, side, transparent, opacity });

      case 'phong':
        return new THREE.MeshPhongMaterial({
          color: col, shininess: def.shininess ?? 60,
          side, transparent, opacity,
        });

      case 'physical':
        return new THREE.MeshPhysicalMaterial({
          color: col,
          metalness:  def.metalness  ?? 0.0,
          roughness:  def.roughness  ?? 0.5,
          side, transparent, opacity,
        });

      case 'toon':
        return new THREE.MeshToonMaterial({ color: col, side, transparent, opacity });

      case 'basic':
        return new THREE.MeshBasicMaterial({
          color: col, wireframe: def.wireframe ?? false, side, transparent, opacity,
        });

      case 'normal':
        return new THREE.MeshNormalMaterial({ side });

      case 'depth':
        return new THREE.MeshDepthMaterial();

      case 'shader': {
        // Deep-clone uniforms so each object gets independent state
        const uniforms = THREE.UniformsUtils.clone(def.uniforms ?? {});
        // Tint the shader via uColor if it exists; otherwise leave as-is
        if (uniforms.uColor) uniforms.uColor.value = new THREE.Color(...color);
        return new THREE.ShaderMaterial({
          vertexShader:   def.vertexShader,
          fragmentShader: def.fragmentShader,
          uniforms,
          side,
          transparent,
          opacity,
        });
      }

      default:
        throw new Error(`MaterialLibrary: unknown material type "${def.type}"`);
    }
  }

  /**
   * Build a material and immediately apply it to an existing THREE.Mesh.
   * The old material is disposed.
   *
   * @param {THREE.Mesh} mesh
   * @param {string}     name
   * @param {number[]}   color
   * @param {number}     opacity
   */
  applyTo(mesh, name, color, opacity) {
    const old = mesh.material;
    mesh.material = this.build(name, color, opacity);
    if (old && old !== mesh.material) old.dispose();
  }

  // ── Internals ─────────────────────────────────────────────────────────────

  _side(s) {
    return s === 'front' ? THREE.FrontSide
         : s === 'back'  ? THREE.BackSide
         :                 THREE.DoubleSide;
  }
}

// Singleton export — import this instance everywhere.
export const Materials = new MaterialLibrary();
