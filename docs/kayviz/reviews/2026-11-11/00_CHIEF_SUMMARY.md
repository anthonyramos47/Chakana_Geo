# kayviz — chief engineer's consolidated review (branch `debugging`, 2026-11-11)

Sources: software_engineer.md (SE), geometry.md (GEO), user.md (U), frontend.md (FE), backend.md (BE), plus docs/kayviz/REVIEW_2026-11.md (B*). Paths are under `kayviz/src/kayviz/` (frontend under `static/`) unless written otherwise.

## Executive summary

- The redesign from Phases 0, 1 and 3 is working. Callbacks run off the event loop, slider events coalesce, the wire format is binary and each page loads the scene once. All 100 tests pass in 15 s. Keep this architecture.
- The worst open problems are **wrong pictures that look plausible**:
  - Scalar colours are multiplied by the mesh colour.
  - A face scalar breaks later vertex scalars, face labels and picking.
  - One NaN or Inf in a scalar wipes out the rest of a message.
  - Arrows lose their magnitude.
  - Colours are tone-mapped, and every mesh is smooth-shaded, so planar polyhedra render as blobs.
- **Nothing checks the input.** Wrong shapes, out-of-range or −1 indices, typo'd targets and wrong lengths are all accepted. The browser then draws garbage or drops data without telling anyone. This is exactly when a researcher is debugging.
- **The server's scene buffer drifts from what the tab shows.** Removed or re-registered objects keep their quantities, and `kv.remove` or `kv.clear` inside a callback come back on reload. The callback GUI also loses widget values (one shared debounce timer, and Python applies only the widget that fired).
- **Concurrency gaps came with the threading change.** Two callbacks or two streaming runs can drive one state at the same time. Restarting the server in the same process breaks `/wait`. Pushes made from a streaming handler can arrive out of order.
- **Release blockers:**
  - Any web page can drive or shut down a local server (no Origin, Host or token check).
  - The package claims Python ≥ 3.9, but `import kayviz` fails on 3.9.
  - three.js and lil-gui come from a CDN, so the viewer does not work offline.
- Most of these are small, local fixes. The roadmap below puts about two weeks of focused work ahead of a public release; nothing needs a rewrite.

## Verdict per area

- **Software engineering:** clean layering and fast tests. There are concurrency regressions in GUIApp, restart-unsafe asyncio primitives, two scene buffers, dead code and drift between API signatures.
- **Geometry:** the data path is fast and correct for well-formed triangle and quad meshes. The scalar pipeline, shading, colour fidelity, vector magnitude, non-convex polygons and scale assumptions are not yet good enough for research figures.
- **User:** quick to start and pleasant for unit-scale meshes the user already trusts. It is risky for debugging (silent acceptance, lost GUI state, a fixed camera).
- **Frontend:** render-on-demand and binary decode are good. Weak spots: four reproduced crashes, the scene panel being rebuilt on every message, no offline use, and hard-coded `ws://` with root-absolute URLs.
- **Backend:** the threading model is sound. Weak spots: cancel-unsafe locking, no ordered single sender per client, a buffer that can drift, no security at all, and port probing on macOS.

## Consolidated issues

Status values:
- **C-run**: I reproduced it.
- **C-code**: I confirmed it by reading the cited lines.
- **R**: reported by the specialists, not re-checked by me.

Severity: H = high, M = medium, L = low.

### (a) Correctness: wrong pictures or lost data

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K1 | H | Scalar colour maths is wrong: (1) the colormap is multiplied by `material.color`, which is never set to white; (2) NaN or Inf makes `_viridis` throw (`s[NaN]`), and `_applyObjects` aborts the whole batch on every reload; (3) the 5 viridis stops are misplaced (error up to 0.16); (4) one allocation per value plus a new GPU attribute per range step (leak, 80 ms per step at 1M values) | GEO1, GEO3, GEO12, FE4, FE11, FE12, B9 | C-code (SceneEntry.js:113-118, 145-200; viewer.js:784-790) | SceneEntry.js, viewer.js:784, gui/scene_panel.js:808 |
| K2 | H | A face scalar calls `toNonIndexed()` and never goes back. After that: a vertex scalar gets an nV-long colour buffer for 3·nTri positions; face labels throw on every frame; inspect shows buffer ids (`[6,7,8]`), not the real vertex ids | GEO2, GEO8, GEO9, FE1, FE2, FE5, U26 | C-code (SceneEntry.js:137-142, 192-197) | SceneEntry.js, LabelRenderer.js:105-171, main.js:433-457 |
| K3 | M | `setColor` and scalars assume `material.color`; under the `normal`, `depth` and `blinn_phong` (ShaderMaterial) shaders they throw | FE3 | C-code (viewer.js:124) | viewer.js:124, SceneEntry.js:148, lib/MaterialLibrary.js:278 |
| K4 | H | The server buffer drifts from the tab: `do_remove` pops only `name` and leaves `name::field`; re-registering keeps old quantities, which replay before the mesh with the old size; `kv.remove` ignores the callback sink; `kv.clear` in a callback clears only the app buffer; schema capture pushes at registration; a quantity sent before its mesh is dropped; one unencodable object empties every new tab's snapshot (`except: pass`) | SE4, SE5, SE6, BE4, BE5, BE6, U3, U4, U10 | C-code (broadcast_mixin.py:110-112; script.py:232-234) | webscope/broadcast_mixin.py:80-112, script.py:232-240, callback_app.py:88-98, 217-235, script_app.py:74-79 |
| K5 | H | No input validation. Accepted without error: V of shape (10,2) flattened as xyz, index 99 on 10 vertices, −1 padding (becomes 2³²−1), degenerate faces (`tris_per_face` of 0 or −1 shifts later faces), wrong-length scalars and vectors, unknown target, `defined_on` typos, unknown material, 0-255 colours, NaN vertices (NaN bounds break framing), unknown app name | GEO11, GEO13, GEO17, U1, U2, U3, U18, U22, SE13 | C-run (V(10,2), F=99 and −1 accepted; tpf `[1,0,-1,3]`) | serializers.py:18-177, script.py:127-240, scene.py |
| K6 | M | Wire encode: a list of `np.float32` raises TypeError (it checks only `o[0]`); NaN is written as a bare `NaN`, so the browser's JSON.parse drops the whole message; int64 values above 2³¹ wrap silently to int32 | SE9, BE7 | C-run (float32 list → TypeError; `{"v":NaN}` emitted) | webscope/wire.py:35-76 |
| K7 | H | The callback GUI loses state: one 120 ms debounce timer is shared by all widgets, and live mode applies only `payload[trigger]`, so changing A then B loses A; dropdown values come back as `str`; duplicate labels, or a button and a slider with the same key, fire each other; buttons leave their headers; the schema is captured once, so conditional widgets never appear and Python-side changes never reach the panel; `bool("false")` is True | U5, U6, U7, U8, U9, FE9, BE18, B15 | C-code (gui/auto_callback_panel.js:55-64; webscope/imgui.py:120) | gui/auto_callback_panel.js, webscope/imgui.py, state_schema.py:127-143, app_loader.js:80 |
| K8 | H | Vector quantities lose their magnitude: every arrow has length `length` (scale `one`) | GEO7 | C-code (viewer.js:680-691) | viewer.js:680-691, serializers.py:177 |
| K9 | H | Only smooth `computeVertexNormals` is available, and the normals depend on the fan diagonal. There is no flat shading, so planar-quad, PQ, circular and conical meshes look curved and a cube looks like a blob | GEO4 | C-code (viewer.js:719; no `flatShading` in static/) | viewer.js:699-721, lib/MaterialLibrary.js |
| K10 | H | User RGB is read as linear and then tone-mapped (ACES; Neutral in studio). (0.5,0.5,0.5) shows as about #c5c5c5. The swatch and colour bar are not colour-managed, so the legend does not match the mesh. Exact-colour figures are impossible | GEO5, B-review §3 | C-code (main.js:44-45; `new THREE.Color(r,g,b)` in MaterialLibrary.js:219, viewer.js:764) | main.js, lib/MaterialLibrary.js, lib/Studio.js:150, gui/scene_panel.js:657, 808 |
| K11 | M | The fan triangulation from vertex 0 is wrong for non-convex polygons (flipped and overlapping triangles); non-planar polygons depend on which vertex is first | GEO10 | R | serializers.py:86-89, viewer.js:710-716 |

### (b) Concurrency and robustness

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K12 | H | GUIApp has no execution policy: a second "run" starts a second streaming task on the same state; sync actions run in a thread while a stream mutates state; `_set_state` from another tab applies without the lock; replies go only to the sending tab | SE1, SE2, SE17, BE18 | C-code (webscope/app.py:116-133) | webscope/app.py:110-160 |
| K13 | H | The CallbackApp lock is not cancel-safe: when a tab disconnects during a callback, `worker.cancel()` releases `_handler_lock` while the thread keeps running, so the next event starts a second callback on the same dict; the cancelled run's pushes are discarded | BE1 | C-code (callback_app.py:153-155, 191-193) | webscope/callback_app.py |
| K14 | H | Not restart-safe: the `asyncio.Event`/`Lock` are created once per app and bound to the first loop; after `kill_servers()` and `init()`, `/wait` returns 500 and `_wait_until_idle` retries a non-200 without sleeping (about 300 req/s); `_seen_client`/`_clients` are not reset; `show(block=True)` waits 24 h with no tab and no hint | SE3, SE16, BE2, BE16, B13, U20 | C-code (broadcast_mixin.py:27; script.py:798-811, no sleep on the 500 path) | webscope/broadcast_mixin.py, app.py:146, callback_app.py:191, script.py:640-811 |
| K15 | M | Pushes from the loop are fire-and-forget: `_loop.create_task` keeps no reference and has no error reporting, and each push encodes in its own thread, so messages leave in finish order (a scalar can arrive before its mesh and be dropped); `_loop is None` reaches `create_task` | BE3, SE11 | C-code (pattern, script.py:731-741); reordering R | webscope/script.py:731-741, broadcast_mixin.py:78-104 |
| K16 | M | No per-client outbound queue: one stalled client blocks every main-thread push for up to 10 s; the snapshot and broadcasts race on one socket, so an older snapshot can overtake a newer update; the deprecated `websockets.legacy` implementation is used | BE8, BE14 | R | webscope/broadcast_mixin.py:78-99, server.py:139-141 |
| K17 | M | Frontend message handling is fragile: a throw in `applyMessage` skips the other handlers and `__invalidate`, leaving a stale picture; on reconnect the queued messages flush before `checkServerInstance` and go to a new server; `_pending` is unbounded | FE20, FE21, SE23, GEO3 (batch abort) | R | static/ws.js:82-117, viewer.js `_applyObjects` |
| K18 | M | On macOS the port probe (with SO_REUSEADDR) reports a port held by a 0.0.0.0 server as free, so kayviz binds it and shadows that server; there is a probe-to-bind race between processes | BE9 | C-run (listener on 0.0.0.0:18861 → `find_free_port` returned 18861) | server.py:113-126 |
| K19 | M | Re-running a notebook cell replaces the app, but open sockets stay bound to the old instance with its old `gui()` closure; `_mounted` leaks FastAPI instances; `extra_routes` stays bound to the first instance | BE11, SE15 | R | webscope/registry.py:33-35, 96-117, server.py:52-57 |
| K20 | M | Screenshot handshake: any tab (or a foreign page) claims a job by polling every 400 ms; jobs are not cancelled on timeout and late results leak; size is uncapped; requests go over HTTP to the server's own address (`None/api` in hosted mode; blocks the loop if called from a streaming handler); `finally` forces the grid visible; bounds ignore InstancedMesh; `screenshot("fig.png")` writes `fig_v0/_v1` | B7, B16, BE10, FE13, FE14, FE24, GEO21, SE10, U17 | R | webscope/script_app.py:128-167, script.py:319-336, static/screenshot.js:17-198 |
| K21 | L | The push sink and imgui context are thread-local: threads the user starts inside a callback push to the script channel; the pool thread stays in live mode | SE22, BE19 | R | webscope/script.py:64-72, imgui.py:40, 71-79 |

### (c) Security (public release)

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K22 | H | There is no Origin, Host or token check anywhere: any web page can open `ws://127.0.0.1:<port>/api/<app>/ws` (read the scene, run callbacks and exports that write files), `POST /api/_shutdown` with text/plain, and take screenshot jobs; DNS rebinding exposes all HTTP routes; `--host 0.0.0.0` exposes everything; `ws_max_size=256 MB` for incoming messages | SE7, BE §3, BE15, BE10 (size cap) | C-code (grep: no origin, host or token handling; server.py:91-99) | server.py:48-141, webscope/registry.py:96-114, script_app.py:101-167, __main__.py:25 |
| K23 | M | `kill_servers()` scans 8000-8099 regardless of `KAYVIZ_PORT` and shuts down other users' and kernels' servers without asking; `__main__` ignores `KAYVIZ_PORT` | U21, BE17, SE19 | C-code (script.py:569) | webscope/script.py:569-600, __main__.py |

### (d) Geometry-research features missing compared with Polyscope

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K24 | H | The camera is fixed: (0,1.5,4), near 0.001, far 100, a 4-unit grid; no fit or reset, no F/R keys, no `kv.look_at`/`set_camera`/up direction; scenes larger than about 50 units are clipped | GEO6, U13, B-review §3 | C-code (main.js:58-71) | main.js:50-72, lib/Studio.js, script.py |
| K25 | M | Sizes and precision are absolute: point radius 5e-4 (below the slider minimum), curve radius 2e-3, vector length 0.05, pick threshold 0.02; slider ranges are absolute; float32 is sent without recentring (resolution 0.0078 at 1e5) | GEO15, GEO16, U14 | R (defaults C-code: serializers.py:117, 131, 177) | serializers.py, gui/scene_panel.js:262, main.js:391 |
| K26 | M | `show_edges=True` with the defaults draws 0.8-grey edges on a 0.8-grey mesh, so the edges are invisible | GEO14, U15 | R (trivial) | serializers.py:55, viewer.js:294 |
| K27 | M | Colormaps: viridis only; no vminmax, symmetric or diverging maps, cyclic maps, NaN colour, categorical maps, colour quantities, scalars on points or curves or edges, colour bar in screenshots, or isolines | GEO12, GEO20, U16, GEO §3 | R | viewer.js:299-301, SceneEntry.js, serializers.py |
| K28 | M | Picking gives triangle ids, not polygon ids; no quantity values; points, vectors and tube curves are not pickable; drag-versus-click uses `mousedown`; there is no Python pick callback | GEO9, FE25, U26 | R | main.js:391-457 |
| K29 | L | Polyscope conveniences are missing: `enabled=`, `smooth_shade=`, `cmap=`/`vminmax=`, structure handles, `screenshot()` writing one file from the current camera, `on_load` naming | U11, U16, U17 | R | script.py, serializers.py |
| K30 | L | Later: order-independent transparency (alpha blend with `depthWrite=false`), a backface or orientation policy, a screen-space wireframe at constant pixel width | GEO18, GEO19, GEO22 | R | lib/MaterialLibrary.js:218-253, viewer.js:128-137, 579-591 |

### (e) UX

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K31 | H | The scene panel is rebuilt from scratch (`innerHTML=''`) on every `viewer-changed`; continuous setters emit it, so sliders detach mid-drag, histograms close and focus is lost, which makes the panel unusable during streaming | FE6, FE7, B11, B17 | C-code (gui/scene_panel.js:140) | gui/scene_panel.js:51-140, viewer.js:162-425 |
| K32 | M | Re-registration resets the user's visibility, colour, opacity, scalar range and show-edges every iteration (the Dupin clear-and-re-register pattern) | FE8, U19 | R | viewer.js:46-61, 494 |
| K33 | M | Errors are not visible: only a grey status line, covered by the panel; there is no toast with the exception type | U12 | R | static/app_loader.js, main.js |
| K34 | L | Layout and accessibility: the energy panel always shows "Waiting…"; inspect overlaps it; pixel-fixed offsets; linear mode drops energies ≤ 0; emoji-only buttons; div headers that the keyboard cannot reach; 9-10 px text at about 3:1 contrast; the "×" button removes without undo | U25, FE27, FE28, FE29 | R | main.js:117-335, gui/scene_panel.js, gui/energy_panel.js:216, app_loader.js:92 |

### (f) Performance and memory

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K35 | M | Point-radius change: the old InstancedMesh is not disposed (GPU leak) and the colour reverts to `opts.color` | FE10, B8, B10 | R | viewer.js:139-149 |
| K36 | L | Render cost: `preserveDrawingBuffer` is always on; DPR is uncapped and read once; 2D canvases ignore DPR; the label canvas (about 20 MB) is cleared every frame; studio refit happens on a 30-frame counter (stale shadows under render-on-demand) and compiles synchronously; tubes are baked (4.5× memory) instead of instanced; points are spheres rather than impostors (80× triangles) | FE15-FE19, GEO22, FE §3 | R | main.js:39-41, 110; LabelRenderer.js; lib/Studio.js:24, 181-202; viewer.js |
| K37 | L | `/load` defaults to `objects=True` (57.8 MB of JSON for 1M points, `_buffer` read from another thread); attach mode buffers Python lists and sends JSON forever; the viewer keeps two to four copies of arrays | BE12, BE13, FE31 | R | webscope/registry.py:96-102, script.py:772-777, script_app.py:101-108, viewer.js:57-95 |

### (g) Engineering hygiene

| id | sev | title | sources | status | files |
|---|---|---|---|---|---|
| K38 | H | `requires-python>=3.9` is false: `serializers.py` is the only module without `from __future__ import annotations`, and `bool \| None` in its signatures raises at import on 3.9 | SE8, U24 | C-code (serializers.py:157, 177; grep) | serializers.py, pyproject.toml:12 |
| K39 | H | Packaging for release: no package README, URLs or classifiers; the version is defined twice (pyproject.toml:7, `__init__.py`:31); `psutil` is undeclared (lazy import at script.py:666); three.js and lil-gui come from jsdelivr (no offline use, no integrity hash); hard-coded `ws://` and root-absolute `/api` URLs break HTTPS and proxies (JupyterHub, VS Code remote) | SE19, FE22, FE23, U23 | C-code (index.html:32-34, app_loader.js:51, 59) | pyproject.toml, __init__.py, static/index.html, app_loader.js, all `fetch('/api…')` |
| K40 | M | The docs' own streaming example calls the heavy step on the loop (it freezes every tab); docstrings reference `ser.lmesh_scene`, which is gone; API.md omits `show`, `material`, `edge_*` and `slider_float` step; two GUI APIs share names (`kv.slider` from dataclass annotations vs `kv.imgui.slider_float`) | SE21, U27 | C-code (CLAUDE.md:154) | Chakana_Geo/CLAUDE.md, docs/kayviz/COOKBOOK.md:126, TUTORIAL.md:155, examples/polyhedral_mesh/app.py:95-99, API.md |
| K41 | M | Dead code and drift: unreachable branches, `_handle_callback`, `_apply_client_state`, `_make_scene_update`, `_ping`, `autostart`, `gui/script_panel.js`, about 19 `window.__*` globals; signatures drift between `Scene`, `kv` and `ser` (point radius 0.01 vs 0.0005; `edge_radius`/`radius` missing; `target` vs `target_name`) | SE12, SE14, B20, FE26, FE30 | R (SE verified with inspect) | webscope/scene.py:49-78, script.py:127-213, app.py:167-173, callback_app.py:30-38, 226-235, static/gui/script_panel.js |
| K42 | M | Test gaps: no tests for imgui, Scene, the screenshot handshake, restart, GUIApp concurrency, remove with quantities or wire edge cases; no JS tests at all; the fixed port 18700 and sleep-based timing block parallel runs; tests poke private `registry._apps` | SE20, FE §4 | R | kayviz/tests/ |
| K43 | L | `script.py` (811 lines) mixes session, push API, capture and process scanning; the legacy name `webscope` and the `ws.` docstring prefix clash with `ws` for a WebSocket; `WEBSCOPE_URL` is still accepted | SE18 | R | webscope/script.py, webscope/ |

## Roadmap

Every phase ends with `pytest` green, a manual browser check on `examples/polyhedral_mesh` and the Dupin playground, and one commit. Phases A to E are the pre-release line.

### Phase A — cheap release blockers and one-liners (S, about 1 day)

Closes K38, K26, K40, K23, K6, and the small parts of K14, K3 and K20 (FE13), plus FE26.

- `serializers.py`: add `from __future__ import annotations`. Decide on 3.9 vs 3.10 (see the open questions) and add a CI matrix with the lowest and newest versions.
- `serializers.py:55`: default `edge_color=(0.1,0.1,0.1)`, matching viewer.js:294.
- Docs: change the streaming example to `await asyncio.to_thread(comp.optimization_step, state)` in CLAUDE.md, COOKBOOK.md, TUTORIAL.md and examples/polyhedral_mesh/app.py. Remove the `lmesh_scene` references and fill the API.md table.
- `script.py:569`: `kill_servers(ports=None)` → `range(_DEFAULT_PORT, _DEFAULT_PORT+100)`. `__main__` reads `KAYVIZ_PORT`.
- `script.py:798-811`: sleep on every non-success path.
- `wire.py`:
  - walk lists whose first element is not a list or dict, converting `np.generic`;
  - map non-finite values to `None` and dump with `allow_nan=False`;
  - range-check int64 → int32, raising if out of range;
  - use explicit `'<f4'` and `'<i4'`.
- Frontend one-liners:
  - `material.color?.` and the `uniforms.uColor` path (K3);
  - save and restore `grid.visible` in screenshot.js:165;
  - `pinned=true` in `setMaterial`.
- Verify: tests for wire (float32 list, NaN, int64 overflow) and for the edge-colour default; run `python3.9 -c "import kayviz"` (or the 3.10 floor) in CI.

### Phase B — scalar pipeline, done once and properly (M, 2-3 days)

Closes K1, K2, K17 (per-object isolation), and the leak and allocation halves of K35 (FE11, FE12).

- New `static/lib/colormap.js`: 256-entry LUTs (viridis exact, plus `coolwarm` and `turbo` ready for K27) and a NaN colour, shared by SceneEntry.js and scene_panel.js:808.
- `ScalarChild`:
  - compute min and max over finite values only;
  - set `material.color` to white while the scalar is active and restore it on dispose;
  - `setColor` updates only the stored colour while a scalar is active;
  - allocate the colour attribute once, then write `.array` and set `needsUpdate`.
- Face scalars: keep the original indexed geometry on the entry, build the non-indexed display geometry while a face scalar is active, and go back to the indexed one when a vertex scalar is shown or the scalar is removed. LabelRenderer and inspect compute centroids and ids from `opts.faces` and `trisPerFace`, never from `geometry.index`.
- `viewer._applyObjects`: a try/catch per object, an error shown in the status line, and `__invalidate` in `finally` (ws.js:104-117).
- Verify: add node tests under `kayviz/tests/js/` (three@0.165 as an npm devDependency; no bundler; `node --test`). Cases:
  - a red mesh with a scalar has `material.color == white`;
  - face scalar → vertex scalar gives `colors.count == positions.count`;
  - `[0,NaN,1]` and `[0,Inf,1]` do not throw, and the next object in the batch still applies;
  - face labels after a face scalar;
  - inspect ids equal `opts.faces`;
  - LUT matches matplotlib within 1/255.

### Phase C — validation and one consistent scene buffer (M, 2-3 days)

Closes K5, K4, K15 (ordering part), K11 (degenerate part), and U22.

- `serializers.py`: shared `_vertices(V)`, which requires shape (n,3), a real dtype and finite values, else raises ValueError naming the object. Also `_faces(F, nV)`, which checks the index range and the −1 padding convention (strip the padding and send ragged), and rejects polygons with fewer than 3 vertices. Quantities check their length against `defined_on ∈ {vertices, faces}` (and `edges` once supported). Warn on unknown materials, on colours > 1 and on opacity outside [0,1].
- `script.py` and `scene.py`: keep a set of registered names so that a missing target, or a quantity sent before its mesh, raises in Python. `show(app=…)` checks registered apps and lists them.
- `broadcast_mixin.py`:
  - `do_remove` and re-register drop the `name::*` keys and the edge children;
  - buffer insertion keeps targets before quantities;
  - `push` encodes (or validates encodability) before buffering and raises;
  - the snapshot skips and logs one bad object instead of `except: pass`.
- `script.py:232`: `remove` and `clear` go through the callback sink as markers. `callback_app.py:88-98` runs `_capture_schema` under `_CallbackPushCapture` and discards (or seeds) what it captures.
- Verify: one pytest per bullet, reusing the specialists' reproductions (V(10,2), F=99, F=−1, tpf, typo'd target, remove with a quantity followed by `/api/script/load`, `kv.remove` inside a callback followed by reload, an unencodable object followed by a new client snapshot).

### Phase D — concurrency and restart safety (M, 2 days)

Closes K12, K13, K14, K15, K16, K21.

- `app.py`: per-app policy. There is at most one streaming task per action (a second "run" gets an error or is ignored). Sync handlers and `_set_state` take `_handler_lock`. An allow-list (`stop`) bypasses it. The stream takes the lock around each `to_thread` step. Results go to all clients of the app (track clients as CallbackApp does).
- `callback_app.py:191`: `asyncio.shield` the `to_thread` future while holding the lock. On cancel, await it, then buffer and broadcast its pushes.
- Loop-bound primitives (`_idle_event`, `_handler_lock`) are created in a `_bind_loop()` hook called at server start; `BroadcastMixin.reset()` runs on stop (`_seen_client`, `_clients`). `show(block=True)` prints "no tab connected; open <url>" after the connect timeout.
- One outbound path per client: an `asyncio.Queue` plus a single sender task that keeps the latest message per object name. Producers return after buffering. The client is registered after its snapshot. `_run_on_loop` puts work on that ordered queue and keeps task references with a done-callback that logs errors. Switch uvicorn to `ws="websockets-sansio"`.
- Document that threads started by the user inside a callback push to the script channel, or switch to `contextvars` (which `to_thread` copies).
- Verify: regression tests for two concurrent "run" actions (peak concurrency 1), "reset" during "run", disconnect during a callback (max concurrency 1, pushes kept), `kill_servers()` + `init()` + `/wait` returning 200, a stalled client not blocking another client's push for more than 100 ms, and order kept for clear/mesh/scalar from a streaming handler.

### Phase E — localhost security (S-M, 1-2 days)

Closes K22 and the rest of K20 (size cap).

- `server.py`:
  - add TrustedHostMiddleware (127.0.0.1, localhost, plus the configured host);
  - check WS Origin against the Host;
  - use a per-server random token, set as an HttpOnly SameSite=Strict cookie by `/` and required on WS, POST and screenshot routes;
  - `_shutdown` requires the token, which `kill_servers` reads from a per-port lock file in the user's runtime directory (that also stops other users' servers from being killed);
  - set `ws_max_size` to about 1 MB;
  - clamp screenshot size to about 12 Mpx.
- Attach mode (`KAYVIZ_URL`) reads the token from the same lock file; document what to do for remote use.
- Verify: TestClient cases: a foreign Origin WS gets 403; a text/plain `_shutdown` without a token gets 403; `Host: attacker.example` gets 400; a same-origin page still works; `kill_servers` still works.

### Phase F — GUI state and panel sync (M, 2-3 days)

Closes K7, K31, K32, K33.

- `auto_callback_panel.js`: use a timer per key, and send `changed` keys together with the full state. `imgui.py` live mode applies every payload key that differs from the state (coerced to the widget type: dropdowns keep option types; strict bool parsing), and `trigger` decides only the return value of `changed`.
- Widget identity: key by `(section, kind, key)` and warn in Python on duplicates (U8). Buttons stay in their header (auto_callback_panel.js:93-105).
- After each callback, send `{action:"state", values}` plus a fresh schema if it changed, so Python-side resets move the sliders and conditional widgets appear (B15).
- `scene_panel.js`: update rows in place, keyed by object or child name; skip controls that have focus or are being dragged; continuous setters do not emit `viewer-changed` (K31). `viewer.js` keeps a per-name map of UI overrides that is re-applied after re-registration, with a "reset overrides" entry (K32).
- Show an error toast with the exception type (K33).
- Verify: server tests for multi-key payloads, dropdown int types, a Python reset reflected in the state message, and duplicate-key warnings. A node or jsdom test that a slider element survives 10 `viewer-changed` events. A manual drag during a Dupin stream.

### Phase G — research-grade viewing (M-L, 3-5 days)

Closes K24, K25, K9, K10, K8, K28, and the core of K27.

- Camera: fit to bounds (`Box3.expandByObject`, finite values only) on the first geometry; a fit/reset button and F/R keys; near and far set from the bounds; `kv.look_at`, `kv.set_camera`, `kv.set_up_dir`; save and load the camera. Also fix the bounds in screenshot.js and Studio.js (K20, GEO21).
- Scale-relative defaults: default radii and lengths, and slider ranges, are fractions of the scene's bounding-box diagonal (computed in the viewer when the value is `None`). Optional float64 recentring in Python, sent as `mesh.position`.
- Shading: per-mesh `shading="flat"|"smooth"`. Flat uses per-polygon normals from the polygon (Newell) normal, not the fan. Smooth uses angle-weighted normals. The default is an open question.
- Colour: interpret user colours as sRGB (`setRGB(..., SRGBColorSpace)`); add a `true_colour` render mode (`NoToneMapping`; `toneMapped=false` on flat and colormapped materials); swatches and the colour bar use the same transform.
- Vectors: `vectortype="standard"|"ambient"`, where ambient uses the true magnitude times `length` scale, plus colour by magnitude.
- Colormaps: `cmap=`, `vminmax=`, `symmetric=` on `add_scalar_quantity`, and scalars on points and curves (K27).
- Picking: triangle → polygon via a prefix sum of `trisPerFace`; vertex ids from `opts.faces`; quantity values in the panel; `instanceId` picking for points and vectors; `pointerdown` (K28).
- Verify: node tests for normals (cube face normal is axis-aligned under flat), sRGB round-trip (#808080 in true-colour mode reads back #808080 from a 1×1 render), and arrow scale proportional to |v|. Screenshot tests at scales 1e-3 and 1e3 with non-empty coverage.

### Phase H — packaging, screenshots, lifecycle (M, 2 days)

Closes K39, K20, K18, K19, K29 (screenshot part).

- Vendor three@0.165 (module build plus the addons actually used) and lil-gui under `static/vendor/` (MIT notices). Update the importmap in index.html; this needs no build step.
- In app_loader.js and every `fetch`, build URLs from `document.baseURI` and take the protocol from `location.protocol` (`ws`/`wss`).
- Packaging: one version source (`dynamic = ["version"]` or `importlib.metadata`), a package README, URLs and classifiers, and a `psutil` extra.
- Screenshots: the job goes over the script WebSocket to one chosen client (the most recent), with a TTL, cancel on timeout and a drop of uncollected results. In-process `run_coroutine_threadsafe` when local; refuse on the loop thread. `screenshot(path)` writes one file from the current camera; `views=` keeps the grid.
- Server lifecycle: bind uvicorn to a socket kayviz already holds (`server.run(sockets=[s])`), plus a `connect_ex` probe and retry. On app replacement, close old sockets with a reload code and drop the instance from `_mounted`.
- Verify: an offline test (block jsdelivr; the page must load); a test under a path prefix through a tiny proxy fixture; screenshot timeout and late-result tests; on macOS a test with a wildcard listener plus `find_free_port` skipping it.

### Phase I — hygiene and performance (L, ongoing, after release)

Closes K41, K42, K43, K34, K35, K36, K37, K30, K11 (non-convex part), K21.

- Delete dead code. Add a signature-comparison test (`inspect.signature` of `Scene`, `kv` and `ser` must agree), or generate the wrappers.
- Test infrastructure: a registry fixture, a free port per test, no sleeps, and `node --test` in CI.
- Split `script.py` into `session.py`, `capture.py` and `servers.py`. Rename `webscope` → `runtime` with an import alias at the 1.0 boundary.
- Add `// @ts-check` with JSDoc, and `tsc --noEmit` against `@types/three` in CI only. Replace the `window.__*` globals with a context module; add `kayviz.css`; the accessibility fixes in FE28.
- Performance: swap the template geometry on radius and length changes (fixes the K35 leak and colour revert); instanced tubes; point impostors; studio AO only while the camera is still; drop `preserveDrawingBuffer`; cap DPR at 2; lazy label canvas; `/load` defaults to `objects=False`; binary `/push` in attach mode.
- Geometry extras: ear-clipping for non-convex polygons with planarity warnings; OIT or a two-pass transparency; backface colour; a screen-space wireframe; isolines.

## Keep

- The threading model (callbacks via `to_thread`, coalescing of the latest event) and render-on-demand. They fixed the freezes, as measured in REVIEW_2026-11.
- The binary wire format (a JSON header plus typed arrays), with JSON as the attach fallback. FE measured that zero-copy would save only 1.9 ms.
- Numpy-only serializers returning plain dicts, the string-keyed Polyscope-mirroring API, and keeping hanan and kayviz independent.
- No build step: an importmap plus ES modules. Vendoring keeps it that way.
- Tab reuse and the instance-id reload; the clear port and URL errors (U28).
- A fast test suite (15 s) as the gate for every phase.

## Do not do

- **A TypeScript or bundler migration.** It costs about 4,000 lines of churn; JSDoc with `@ts-check` and `tsc --noEmit` gives most of the type safety without breaking "no build step".
- **A rewrite of the server in Rust or C++, a WebGPU renderer, or a native viewer.** The bottlenecks were the data format and threading, and both are fixed. WebGPU in three r165 is immature, and a native viewer loses the web UI.
- **Zero-copy `decodeFrame`.** It saves 1.9 ms per 28 MB, which is not worth the complexity.
- **A true immediate-mode GUI (re-running `gui()` per frame in the browser).** Re-sending the schema and state after each callback (Phase F) fixes U7 and B15 with the current design.
- **OIT, impostors or instanced tubes before Phases B to E.** They are nice, but they don't fix wrong pictures, and they touch the same files as the scalar rework.
- **Structure-handle classes that replace the string API.** If handles are added, make them thin wrappers that hold the name; existing scripts and the Dupin pattern depend on string keys.
- **Merging the two scene buffers into one class right now.** Phase C gives the same user-visible consistency (sink markers, prefix removal, ordering) with far less risk. Revisit at the `script.py` split.
- **Playwright as a required CI job early.** Node tests with three from npm cover the frontend bugs found; keep Playwright as an optional smoke test.

## Open questions for the owner

1. **Release Python version.** Python 3.9 has been end-of-life since October 2025. Recommend `requires-python>=3.10` with CI on 3.10 and 3.13; the fix in Phase A keeps 3.9 importable either way.
2. **Default shading.** Flat for polygon meshes (face size > 3 or ragged) and smooth for triangle meshes, as recommended for PQ and circular work? Or smooth everywhere, as Polyscope does, with `smooth_shade=` opt-in?
3. **Colour management.** Should user colours be exact sRGB by default (no tone mapping for flat and colormapped materials, with ACES only in studio), or should the current filmic look stay the default with a "true colour" toggle? This changes every existing figure.
4. **Security model.** Is a token cookie plus Host and Origin checks acceptable, given that they make `--host 0.0.0.0` and attach mode need the token from a lock file? Should `--host 0.0.0.0` be refused without an explicit `--insecure`?
5. **`kill_servers` semantics.** Should it kill only servers started by this user (via the lock files), or keep the current scan of the port range?
6. **Two GUI APIs.** Keep both `GUIApp` (dataclass annotations, `kv.slider`) and `CallbackApp` (`kv.imgui.*`) in 1.0, or deprecate one? They share widget names with different meanings (U27).
7. **Package naming.** Rename `webscope` → `runtime` before the first public release (one break now) or never? Also drop `WEBSCOPE_URL`?
8. **Licence.** The package is GPL-3.0-or-later. Confirm this is intended for a viewer library meant for wide adoption (it affects who can embed it). Vendored three.js and lil-gui are MIT, which is compatible.
9. **Scale conventions.** Should default sizes be relative to the bounding-box diagonal, as in Polyscope, which changes the meaning of existing explicit `radius=` arguments only when they are omitted? And should the up axis be y (current) or z?

## Not confirmed by me

These were reported by the specialists and not re-checked: the actual message reordering in K15, the 10 s stall in K16, the K20 screenshot behaviour, the stale sockets in K19, the K36 and K37 measurements, and the K11 triangulation numbers. The code patterns behind K15 and K20 match the descriptions.

---

## Status after implementation (branch `debugging`, 2026-11-12)

| phase | closes | commit |
|---|---|---|
| A — cheap blockers | K38, K26, K40, K23, K6, parts of K14/K3/K20 | `bd5e6c3` |
| B — scalar pipeline | K1, K2, K17 (per object) | `c9a1abc` |
| C — validation, one consistent buffer | K5, K4, degenerate faces | `52c5c86` |
| D — concurrency | K12–K16, BE14 | `2bd4dd6` |
| E — security | K22, screenshot cap | `dbee099` |
| F — GUI state and panel | K7, K31, K32, K33, energy panel | `9f0ab05` |
| G — research-grade viewing | K24, K25, K9, K8, K27 (core), z up | `24028a9` |
| H — packaging and lifecycle | K39, K20, K18, K19 | `9156f7b` |
| I — hygiene | rename webscope → runtime, K41 (part), K11 | `5662c2f`, `29a6b75` |
| leftovers | B8/B10, U17, U20, FE15/17/18/19, part of K34 | `c1c778c` |

Tests: 144 Python (pytest) + 15 frontend (`npm test`, node + three 0.165).

Open, by choice (not needed for the release, or a decision of the owner):
- Geometry features: float64 recentring (GEO16), order-independent transparency (GEO18),
  backface colouring (GEO19), scalars on points/curves (GEO20), screen-space wireframe
  (GEO22), isolines, OBJ/PLY export, parameterization checker, picking of points/vectors
  (FE25), exact-colour mode (owner: not a priority).
- Performance for very large scenes: instanced tubes, point impostors.
- Attach mode (`python -m kayviz` shared server) still sends JSON lists (BE13); a GUIApp's
  `/load` returns its scene as JSON (BE12).
- Engineering: split `runtime/script.py` (SE18), `// @ts-check` in CI, layout without fixed
  pixel offsets (FE29) and the rest of the accessibility list (FE28), compileAsync on the
  studio toggle (FE16), pushes from threads a callback starts itself (SE22: documented
  behaviour, thread-local sink).
