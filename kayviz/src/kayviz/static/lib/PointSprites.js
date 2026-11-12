/**
 * PointSprites.js — point clouds as sphere impostors.
 *
 * Instanced spheres cost ~170 triangles per point (1M points: 170M triangles).
 * Here each point is one camera-facing quad (2 triangles); the fragment shader
 * intersects the view ray with the point's sphere, discards what misses, writes
 * the sphere's depth (points cut into meshes correctly) and lights the sphere's
 * normal with the scene's lights (MeshPhongMaterial, patched in onBeforeCompile).
 *
 * The radius is a uniform: changing it rebuilds nothing. Sprites cast no shadow
 * and stay out of the studio's AO pass (userData.sphereSprites): a depth or
 * normal pass would see their quads, not spheres.
 */

import * as THREE from 'three';

const VERTEX_PRE = /* glsl */`
uniform float kvRadius;
varying vec3 vKvCenter;
varying vec3 vKvPos;
varying float vKvR;
`;

// Replaces <project_vertex>: the quad faces the camera, sits on the front of the
// sphere (so it covers the silhouette), with margin for off-axis spheres.
const VERTEX_PROJECT = /* glsl */`
vec4 kvCenter = modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0);
float kvR = kvRadius * length(modelMatrix[0].xyz);
vec4 mvPosition = kvCenter + vec4(position.xy * kvR * 1.5, kvR, 0.0);
gl_Position = projectionMatrix * mvPosition;
vKvCenter = kvCenter.xyz;
vKvPos = mvPosition.xyz;
vKvR = kvR;
`;

const FRAGMENT_PRE = /* glsl */`
uniform mat4 projectionMatrix;     // declared by three only in vertex shaders
varying vec3 vKvCenter;
varying vec3 vKvPos;
varying float vKvR;
`;

// Start of main(): the ray-sphere hit in view space, its depth and normal.
const FRAGMENT_HIT = /* glsl */`
vec3 kvRo = isOrthographic ? vec3(vKvPos.xy, 0.0) : vec3(0.0);
vec3 kvRd = isOrthographic ? vec3(0.0, 0.0, -1.0) : normalize(vKvPos);
vec3 kvOc = kvRo - vKvCenter;
float kvB = dot(kvOc, kvRd);
float kvH = kvB * kvB - (dot(kvOc, kvOc) - vKvR * vKvR);
if (kvH < 0.0) discard;
vec3 kvHit = kvRo + (-kvB - sqrt(kvH)) * kvRd;
vec3 kvNormal = (kvHit - vKvCenter) / vKvR;
vec3 kvViewPos = -kvHit;
vec4 kvClip = projectionMatrix * vec4(kvHit, 1.0);
gl_FragDepth = 0.5 * (kvClip.z / kvClip.w) + 0.5;
`;

/** The material: Phong lighting on the sphere normal of each fragment. */
export function spriteMaterial(color, radius) {
  const mat = new THREE.MeshPhongMaterial({ color });
  const kvRadius = { value: radius };
  mat.userData.kvRadius = kvRadius;
  mat.onBeforeCompile = shader => {
    shader.uniforms.kvRadius = kvRadius;
    shader.vertexShader = VERTEX_PRE + shader.vertexShader
      .replace('#include <project_vertex>', VERTEX_PROJECT);
    shader.fragmentShader = FRAGMENT_PRE + shader.fragmentShader
      .replace('void main() {', 'void main() {\n' + FRAGMENT_HIT)
      .replace('#include <normal_fragment_begin>',
               '#include <normal_fragment_begin>\nnormal = kvNormal;')
      .replace('#include <lights_fragment_begin>',
               THREE.ShaderChunk.lights_fragment_begin.replaceAll('vViewPosition', 'kvViewPos'));
  };
  mat.customProgramCacheKey = () => 'kayviz-sphere-sprite';
  return mat;
}

/** Bounds of one sprite (the sphere, not the larger quad) and of the whole cloud,
 *  from the points themselves: InstancedMesh.computeBoundingBox() multiplies a 4x4
 *  matrix per instance (~200 ms for 1M points). */
function setSpriteBounds(mesh, radius) {
  const geo = mesh.geometry;
  geo.boundingBox = new THREE.Box3(new THREE.Vector3(-radius, -radius, -radius),
                                   new THREE.Vector3(radius, radius, radius));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), radius);
  mesh.boundingBox = (mesh.userData.pointsBox ??= pointsBox(mesh.userData.points))
    .clone().expandByScalar(radius);
  mesh.boundingSphere = mesh.boundingBox.getBoundingSphere(new THREE.Sphere());
}

function pointsBox(pts) {
  let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
  for (let i = 0; i < pts.length; i += 3) {
    const x = pts[i], y = pts[i + 1], z = pts[i + 2];
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
    if (z < z0) z0 = z; if (z > z1) z1 = z;
  }
  return new THREE.Box3(new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x1, y1, z1));
}

/** An InstancedMesh drawing *count* points of *pts* (x, y, z each) as spheres. */
export function sphereSprites(pts, count, color, radius) {
  const mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2),
                                      spriteMaterial(color, radius), count);
  const M = mesh.instanceMatrix.array;
  for (let i = 0; i < count; i++) {
    M[16 * i + 12] = pts[3 * i];
    M[16 * i + 13] = pts[3 * i + 1];
    M[16 * i + 14] = pts[3 * i + 2];
  }
  mesh.instanceMatrix.needsUpdate = true;
  mesh.userData.sphereSprites = true;
  mesh.userData.points = pts;
  setSpriteBounds(mesh, radius);
  return mesh;
}

/** New radius: a uniform and the bounds, nothing rebuilt. */
export function setSpriteRadius(mesh, radius) {
  mesh.material.userData.kvRadius.value = radius;
  setSpriteBounds(mesh, radius);
}
