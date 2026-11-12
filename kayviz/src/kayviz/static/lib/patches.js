/**
 * patches.js — several shader patches on one material.
 *
 * three.js has one onBeforeCompile per material; kayviz features that change a
 * surface's shader (back colour, isolines, wireframe, …) each register a named
 * patch here and all of them run. The program cache key names the patches, so
 * materials with different patches get different programs.
 *
 *   setPatch(material, 'back', shader => { ... })   // add or replace
 *   setPatch(material, 'back', null)                // remove
 */

export function setPatch(material, name, patch) {
  const ud = material.userData;
  ud.kvPatches ??= {};
  if (patch) ud.kvPatches[name] = patch;
  else if (name in ud.kvPatches) delete ud.kvPatches[name];
  else return;
  const patches = ud.kvPatches;
  material.onBeforeCompile = shader => { for (const p of Object.values(patches)) p(shader); };
  material.customProgramCacheKey = () => 'kayviz:' + Object.keys(patches).sort().join('|');
  material.needsUpdate = true;
}

export function hasPatch(material, name) {
  return !!material.userData.kvPatches?.[name];
}
