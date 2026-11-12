// Copies the frontend dependencies into src/kayviz/static/vendor/ so the viewer works
// offline and does not depend on a CDN. Run after changing a version in package.json:
//   npm install && npm run vendor
import { cpSync, mkdirSync, rmSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';

const out = 'src/kayviz/static/vendor';
const three = 'node_modules/three';
// add-ons the viewer imports; their own imports are followed below
const entry = ['controls/OrbitControls.js', 'environments/RoomEnvironment.js',
  'postprocessing/EffectComposer.js', 'postprocessing/GTAOPass.js',
  'postprocessing/OutputPass.js', 'postprocessing/Pass.js',
  'postprocessing/RenderPass.js', 'utils/BufferGeometryUtils.js',
  'lines/LineSegments2.js'];

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, 'three', 'addons'), { recursive: true });
cpSync(join(three, 'build', 'three.module.min.js'), join(out, 'three', 'three.module.min.js'));
cpSync(join(three, 'LICENSE'), join(out, 'three', 'LICENSE'));

const seen = new Set(), todo = [...entry];
while (todo.length) {
  const f = todo.pop();
  if (seen.has(f)) continue;
  seen.add(f);
  const src = readFileSync(join(three, 'examples', 'jsm', f), 'utf8');
  for (const [, spec] of src.matchAll(/from\s+'([^']+)'/g)) {
    if (spec !== 'three') todo.push(normalize(join(dirname(f), spec)));
  }
  mkdirSync(join(out, 'three', 'addons', dirname(f)), { recursive: true });
  cpSync(join(three, 'examples', 'jsm', f), join(out, 'three', 'addons', f));
}

mkdirSync(join(out, 'lil-gui'), { recursive: true });
cpSync('node_modules/lil-gui/dist/lil-gui.esm.min.js', join(out, 'lil-gui', 'lil-gui.esm.min.js'));
cpSync('node_modules/lil-gui/LICENSE.md', join(out, 'lil-gui', 'LICENSE.md'));

const v = name => JSON.parse(readFileSync(`node_modules/${name}/package.json`, 'utf8')).version;
writeFileSync(join(out, 'VERSIONS.txt'),
  `three ${v('three')} (MIT)\nlil-gui ${v('lil-gui')} (MIT)\n` +
  `three add-ons: ${[...seen].sort().join(', ')}\n`);
console.log(`vendored three ${v('three')} (+${seen.size} add-ons), lil-gui ${v('lil-gui')}`);
