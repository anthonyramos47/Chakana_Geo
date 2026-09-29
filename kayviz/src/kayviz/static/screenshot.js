/**
 * screenshot.js — server-driven canvas capture.
 *
 * The scripting API (ws.screenshot / ws.screenshot_grid) cannot read the WebGL
 * canvas directly: the pixels only exist in the browser.  So the browser polls
 * the server for pending capture requests, renders the scene from each
 * requested view, and POSTs the resulting PNGs back.
 *
 * Flow:
 *   python  ws.screenshot(...)  -> POST /api/script/screenshot/request
 *   browser GET  /api/script/screenshot/pending   (poll)
 *           -> render each view, canvas.toDataURL()
 *           -> POST /api/script/screenshot/result
 *   python  long-polls /api/script/screenshot/collect until the images land
 */

const POLL_MS = 400;

/** Bounding sphere of every visible mesh in the scene, ignoring helpers. */
function sceneBounds(THREE, scene, grid) {
  const box = new THREE.Box3();
  let found = false;
  scene.traverse((o) => {
    if (!o.visible) return;
    if (o === grid || o.isGridHelper) return;
    if (!(o.isMesh || o.isLine || o.isLineSegments || o.isPoints)) return;
    const g = o.geometry;
    if (!g) return;
    if (!g.boundingBox) g.computeBoundingBox();
    if (!g.boundingBox) return;
    const b = g.boundingBox.clone().applyMatrix4(o.matrixWorld);
    if (!found) { box.copy(b); found = true; } else { box.union(b); }
  });
  if (!found) return null;
  const center = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() * 0.5 || 1;
  return { center, radius };
}

/**
 * Render one view and return a data URL.
 * `dir` is a unit-ish direction; the camera is placed along it, framing the scene.
 */
function renderView(THREE, renderer, scene, camera, bounds, view, width, height) {
  const oldPos    = camera.position.clone();
  const oldUp     = camera.up.clone();
  const oldQuat   = camera.quaternion.clone();
  const oldNear   = camera.near;
  const oldFar    = camera.far;
  const oldAspect = camera.aspect;
  const oldSize   = renderer.getSize(new THREE.Vector2());
  const oldPR     = renderer.getPixelRatio();

  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;

  if (view.live) {
    // Reuse the viewer's current camera exactly as the user left it: same
    // position, same orientation, same distance -- only the aspect changes to
    // match the requested image size.  `orbit` (degrees) spins that camera
    // around the orbit target so a second view keeps the user's zoom level.
    const target = (window.__controls && window.__controls.target)
      ? window.__controls.target.clone()
      : bounds.center.clone();
    const offset = camera.position.clone().sub(target);

    if (view.orbit) {
      const axis = new THREE.Vector3(0, 1, 0);
      offset.applyAxisAngle(axis, THREE.MathUtils.degToRad(view.orbit));
    }
    if (view.zoom && view.zoom !== 1.0) offset.multiplyScalar(view.zoom);

    camera.position.copy(target).add(offset);
    camera.lookAt(target);
  } else {
    const dir = view.dir || [1, 1, 1];
    const up  = view.up  || [0, 1, 0];
    const d = new THREE.Vector3(dir[0], dir[1], dir[2]).normalize();
    // Distance that fits the bounding sphere in the vertical FOV, with margin.
    const fov  = THREE.MathUtils.degToRad(camera.fov);
    const fit  = bounds.radius / Math.sin(Math.min(fov, fov * camera.aspect) * 0.5);
    const dist = fit * (view.zoom || 1.0);

    camera.up.set(up[0], up[1], up[2]);
    camera.position.copy(bounds.center).addScaledVector(d, dist);
    camera.lookAt(bounds.center);
    camera.near = Math.max(dist - bounds.radius * 4, 1e-4);
    camera.far  = dist + bounds.radius * 4;
  }
  camera.updateProjectionMatrix();

  renderer.render(scene, camera);
  const url = renderer.domElement.toDataURL('image/png');

  // restore
  camera.position.copy(oldPos);
  camera.up.copy(oldUp);
  camera.quaternion.copy(oldQuat);
  camera.near   = oldNear;
  camera.far    = oldFar;
  camera.aspect = oldAspect;
  camera.updateProjectionMatrix();
  renderer.setPixelRatio(oldPR);
  renderer.setSize(oldSize.x, oldSize.y, false);

  return url;
}

export function startScreenshotBridge(THREE) {
  async function poll() {
    let job = null;
    try {
      const r = await fetch('/api/script/screenshot/pending');
      if (r.ok) job = await r.json();
    } catch (e) { /* server down — keep polling */ }

    if (job && job.id) {
      const renderer = window.__renderer;
      const scene    = window.__scene;
      const camera   = window.__camera;
      const grid     = window.__grid;
      let images = [], error = null;

      try {
        if (grid && job.hide_grid) grid.visible = false;
        const bounds = sceneBounds(THREE, scene, grid) ||
                       { center: new THREE.Vector3(), radius: 1 };
        for (const v of job.views) {
          images.push(renderView(
            THREE, renderer, scene, camera, bounds, v,
            job.width || 900, job.height || 700,
          ));
        }
      } catch (e) {
        error = String(e && e.message ? e.message : e);
      } finally {
        if (grid) grid.visible = true;
      }

      // Report the live camera alongside the images so ws.get_camera() can
      // show the user the numbers behind their current view.
      try {
        const cam = window.__camera, ctl = window.__controls;
        if (cam) {
          const t = (ctl && ctl.target) ? ctl.target : { x: 0, y: 0, z: 0 };
          window.__lastCamera = {
            position: [cam.position.x, cam.position.y, cam.position.z],
            target:   [t.x, t.y, t.z],
            up:       [cam.up.x, cam.up.y, cam.up.z],
            fov:      cam.fov,
            distance: Math.hypot(cam.position.x - t.x,
                                 cam.position.y - t.y,
                                 cam.position.z - t.z),
          };
        }
      } catch (e) { /* non-fatal */ }

      try {
        await fetch('/api/script/screenshot/result', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: job.id, images, error,
                                 camera: window.__lastCamera || null }),
        });
      } catch (e) { /* drop it; python will time out */ }
    }

    setTimeout(poll, POLL_MS);
  }
  poll();
}
