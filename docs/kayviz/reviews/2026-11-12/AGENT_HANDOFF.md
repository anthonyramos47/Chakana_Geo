# kayviz — task cards for coding agents

This file is the brief for agents (agy, Claude, others) implementing
`PLAN.md` (same folder). **Read all of section 0 before touching code.** Then do
exactly one task card (section 2 onwards). A card is done only when its
acceptance checks pass.

---

## 0. Rules for every task

### 0.1 Where you work
- You work in a **git worktree** on your own branch (`agy/<card-id>`), created
  from `debugging`. Never switch branches, never touch `main` or `debugging`,
  never push, never rebase, never force anything.
- The repository root of the worktree contains `kayviz/` (the package),
  `hanan/` (a geometry library: **do not edit it, do not import it from kayviz**)
  and `docs/`.
- Only edit files your card lists, plus new files it asks for, plus tests and
  docs. If you believe another file must change, change it minimally and say so
  in your final report.

### 0.2 Running things (important: the Python env)
Always use `kayviz/tools/check.sh` from the worktree. It activates the conda
env `Lproj` and puts **this worktree's** `kayviz/src` first on `PYTHONPATH`
(the env has an editable install of a different checkout; plain `python` would
test the wrong code; base Python has numpy 2.x and breaks imports).

```bash
kayviz/tools/check.sh                    # all checks: pytest + npm test
kayviz/tools/check.sh py -k wire -q      # some Python tests
kayviz/tools/check.sh js                 # frontend tests (node, no browser)
kayviz/tools/check.sh run some_script.py # run a script with this checkout
```

Baseline before you start: **145 Python tests and 15 frontend tests pass.** They
must still pass at the end (plus your new ones). Do not delete or weaken an
existing test to make it pass; if one is wrong, explain why in the report.

There is no browser available to you. Code that needs a real tab (WebGL) must
also have a part that is tested without one (pure functions in node tests, or a
Python websocket client standing in for the tab, as in `kayviz/tests/test_runtime.py`).
`KAYVIZ_NO_BROWSER=1` stops kayviz from opening a tab. Other agents run tests
at the same time in other worktrees: never use fixed ports. `check.sh` exports
`KAYVIZ_TEST_PORT_BASE` (a 300-port range for this checkout); new tests use
`BASE + 100` … `BASE + 240` (see `BASE` in `tests/test_runtime.py`; offsets 0–99
and 250 are taken). Never use port 8000, and never call `kv.kill_servers()`
without a `ports=` range inside your own range.

### 0.3 Commits
- Small commits, each one passing `tools/check.sh`.
- Message style: gitmoji code + short imperative summary, then a body explaining
  *why*. Examples from history: `:bug: Phase D: ordered per-tab delivery, ...`,
  `:zap: kayviz: registering many objects no longer stalls the tab`,
  `:sparkles: ...`, `:white_check_mark: ...`, `:memo: ...`.
- **No co-author, "Generated with" or any AI attribution lines in commits.**
- Commit as the configured git user (do not change git config).

### 0.4 Code style
- Match the surrounding code: comment density, naming, idiom. Comments say
  *why*, in plain English, briefly. No banners, no emoji in code.
- Python ≥ 3.10, numpy only in `kayviz` (plus the existing deps: fastapi,
  uvicorn, requests, websockets). New runtime dependencies are **not allowed**;
  dev/test-only ones must be optional (import inside a function, skip the test
  when missing) and listed in `kayviz/pyproject.toml` under an extra.
- Frontend: plain ES modules, no build step, three.js 0.165 from `static/vendor`
  via the import map (`import * as THREE from 'three'`). No new npm runtime
  dependencies; never edit files in `static/vendor/`.
- Surgical edits: change what the card needs, no drive-by refactors or reformatting.
- Errors from bad user input: `ValueError` naming the object (see
  `kayviz/src/kayviz/serializers.py` helpers).

### 0.5 Architecture you must not break
Read `CLAUDE.md` (repository root) section "kayviz runtime" first. The
invariants most often broken:
- **Pushes never go over HTTP in local/hosted mode**; `script._send` runs
  `ScriptApp.push` on the server loop.
- **Handlers never run on the event loop**: user callbacks run in
  `asyncio.to_thread`; never call blocking code from an `async def` on the loop.
- **Outbound order**: all broadcasts go through `BroadcastMixin` (one queue +
  one sender task per tab, `_order_lock`). Do not `ws.send` directly to a tab.
- **Wire format** (`runtime/wire.py`): `encode(msg)` returns `str` (no arrays)
  or `bytes` (binary frame); `decode` is its inverse; `jsonable` for HTTP.
  Serializer arrays are float32/int32 copies.
- **Security** (`security.py`, `LocalOnlyMiddleware`): every new route is
  covered automatically; do not bypass or weaken it.
- **Render on demand**: after changing anything visible in the frontend call
  `window.__invalidate?.()`; frames are drawn with `window.__renderFrame()`.
- `viewer-changed` events can arrive thousands of times in a burst; listeners
  must be O(1) or coalesced (see `gui/scene_panel.js`, `bounds()` in `main.js`).

### 0.6 Docs
Update the docs your change affects: `docs/kayviz/API.md` (Python API),
`docs/kayviz/FRONTEND_API.md` (frontend), `CLAUDE.md` (architecture notes) — they
are kept consistent with each other.

### 0.7 Final report (print it as your last message)
1. What you changed, file by file (one line each).
2. Commits (hash + subject).
3. `tools/check.sh` output summary (numbers of tests passed).
4. What you could not verify (e.g. needs a real browser), and how to check it.
5. Anything you were unsure about or deviated from in the card.

Do not claim something works unless a test or a run showed it.

---

## 1. Map of the code (kayviz/src/kayviz/)

| file | role |
|---|---|
| `runtime/script.py` | public `kv.*` API (init modes, register_*, quantities, view, screenshots, `benchmark()`, `show()`); `_send`, push sink (`_sink_local`) |
| `runtime/broadcast_mixin.py` | per-tab queues, `push`, `do_clear`, `_buffer_objects` (the snapshot buffer), `MAX_PENDING = 16` |
| `runtime/script_app.py` | `ScriptApp` routes: `/ping`, `/push`, `/view`, `/remove`, `/wait`, `/screenshot/*`, `/benchmark/request` |
| `runtime/callback_app.py` | `CallbackApp` (`kv.set_user_callback`), `_enqueue`, `_run_callback`, `_CallbackPushCapture` (sets the push sink) |
| `runtime/app.py` | `GUIApp` base: `handle_websocket`, `initial_scene` (POST `/api/<app>/load`), action dispatch |
| `runtime/wire.py` | binary frame encoder/decoder |
| `runtime/registry.py` | app registry, mounting |
| `serializers.py` | object dicts + validation + polygon triangulation |
| `server.py` | `create_app`, `BackgroundServer`, `WS_MAX_SIZE` (4 MB), ports |
| `security.py` | `LocalOnlyMiddleware` |
| `__main__.py` | `python -m kayviz` (shared server; `--host`, `--allow-network`) |
| `static/main.js` | renderer, camera, lights, `bounds()`/`fitView`, buttons, benchmark panel, toasts (`window.__toast`), click-to-inspect (raycaster); exposes `window.__renderer/__scene/__studio/__renderFrame/__invalidate/__setStudio` |
| `static/viewer.js` | `Viewer.applyMessage` (dispatch on `type`), points (instanced spheres, ~l.920), vectors (instanced arrows, ~l.784), edges |
| `static/SceneEntry.js` | one object's mesh, scalar child (LUT), flat/indexed geometry |
| `static/lib/Studio.js` | studio mode: EffectComposer with 2× half-float 4× MSAA targets, GTAO, VSM shadow 2048² |
| `static/benchmark.js` | `benchmark()` frame times + memory estimates; `runBenchmarkJob` posts results to `/api/script/screenshot/result` |
| `static/ws.js` | `WSClient`, `decodeFrame` |
| `static/app_loader.js` | resolves app, opens app WS + script WS, `viewer.applyMessage(data)` (~l.109) |
| `tests/test_runtime.py` | end-to-end: each scenario in a subprocess with a websocket client as the tab (`_run(body)`) |
| `tests/js/*.test.mjs` | node tests; `dom_stub.mjs` fakes the DOM |

Python→tab job pattern to copy (screenshots, benchmark): Python POSTs
`/api/script/<x>/request` → server sends `{action: "<x>", id, ...}` on the script
WebSocket to the newest tab → the tab POSTs `/api/script/screenshot/result` with
`{id, result | error}` → Python GETs `/api/script/screenshot/collect?id=`.

---

## 2. Phase 0 — evaluator (`kayviz.evaluate`)

Three cards, in this order (P0-B and P0-C build on P0-A's package skeleton).

### P0-A — evaluator skeleton, scenes, Python-side speed and memory, report, compare

**Create** `kayviz/src/kayviz/evaluate/`:
- `__init__.py`, `__main__.py` (CLI: `python -m kayviz.evaluate`).
- `scenes.py`: `SCENES: dict[str, Callable[[], list[tuple[str, dict]]]]` — each
  returns a list of `(kind, kwargs)` registration calls, generated with numpy
  only, seeded (`np.random.default_rng(0)`). Scenes (ids exactly):
  `empty`, `objects-1k` (1,000 icospheres, 1,280 triangles each, built by a local
  icosphere helper, separate objects), `mesh-100k`, `mesh-2M` (one triangle mesh;
  a subdivided grid surface is fine), `merged-12M` (10,000 icospheres in one
  mesh; **only with `--scenes large`**), `ngon-200k` (mix of quads, hexagons and
  non-convex L-shaped polygons as ragged face lists), `points-1M`,
  `curves-200k`, `quantities` (2M-triangle mesh + vertex scalar + face scalar +
  vertex vectors). Groups: `--scenes small` (default: all except the 2M/12M/1M
  ones), `--scenes large` (all).
- `speed.py`: per scene, time (median of 5, `time.perf_counter`) each phase on
  the Python side without a server: serializer call (`kayviz.serializers.*`),
  `wire.encode`, and the encoded size in bytes. Report MB/s.
- `memory.py`: per scene, in a **fresh subprocess** (`sys.executable -m
  kayviz.evaluate._probe <scene>`, so scenes don't pollute each other):
  `tracemalloc` peak and current after registering into a running local server
  (`kv.init()` with `KAYVIZ_NO_BROWSER=1`, port ≥ 18700), grouped by top-level
  module (`tracemalloc` snapshot `statistics("filename")`, summed per
  `kayviz/...` file vs. `numpy` vs. other), plus the process physical footprint:
  on macOS parse `footprint <pid>` (fallback `vmmap --summary`), on Linux
  `/proc/self/status` `VmRSS`; return `None` when unavailable. Also report
  `raw_geometry_mb` = bytes of float32 vertices + int32 faces of the scene,
  and the ratios `kayviz_mb / raw_geometry_mb`.
- `report.py`: write `evaluate-<date>-<host>.json` (schema below) and a Markdown
  report with one table per suite.
- `compare.py`: `--compare baseline.json` → per metric relative change; a metric
  regresses when it gets worse by more than its tolerance (defaults: time +25 %,
  memory +15 %, bytes +5 %); print a table; exit code 1 on any regression.

JSON schema (keep it stable, P0-B/C add to it):
```json
{"version": 1, "date": "...", "machine": {"platform": "...", "python": "...",
 "kayviz": "...", "numpy": "..."},
 "results": [{"suite": "speed|memory|browser|robustness", "scene": "...",
              "metric": "encode_ms", "value": 12.3, "unit": "ms",
              "better": "lower|higher", "note": null}]}
```
Flat `results` rows make `compare` trivial; don't nest.

CLI flags: `--suite speed,memory` (default: everything available),
`--scenes small|large|<id>,<id>`, `--out DIR` (default cwd), `--compare FILE`,
`--quick` (1 repetition, small scenes; for CI and tests).

**Tests** `kayviz/tests/test_evaluate.py`: every scene generator returns valid
input (run the serializers on it, small scenes only); `--quick --suite speed`
runs and writes a JSON matching the schema; `compare` flags a synthetic
regression and passes an identical file.

**Acceptance**: `kayviz/tools/check.sh run -m kayviz.evaluate --quick` finishes
in < 2 minutes and writes both files; all checks pass.

### P0-B — browser suite: delivery time, frames, tab memory

Needs P0-A merged into your base (the human will tell you; otherwise stop).

1. **Applied acknowledgement.** In the tab, after a `scene_update` message has
   been applied *and the next frame drawn*, send on the script WebSocket
   `{action: "applied", seq}`, where `seq` comes from the message. Only when the
   message carries `seq` (normal pushes don't, so nothing changes for users).
   Python side: `ScriptApp` records `applied` events (`seq → monotonic time`);
   new route `GET /api/script/applied?seq=&timeout=` waits for it.
   `evaluate.browser` pushes each scene with a `seq` (add an internal
   `script._push_with_seq(objects, seq)`; do not change public signatures) and
   measures register → applied.
2. **Frames**: call the existing `kv.benchmark(frames=60, show=False)` per scene;
   store its fields as flat rows (`plain_median_ms`, `studio_median_ms`,
   `triangles`, `draw_calls`, `gpu_est_mb`, `js_heap_mb`).
3. **Tab memory**: when the server is started by the evaluator, it sends
   `Cross-Origin-Opener-Policy: same-origin` and
   `Cross-Origin-Embedder-Policy: require-corp` (a `create_app(...,
   isolated=True)` flag; **default off** — it can break user panels that load
   cross-origin resources). In the tab, `benchmark.js` adds
   `memory_mb.tab = (await performance.measureUserAgentSpecificMemory()).bytes / MB`
   when `crossOriginIsolated` is true; this API is async, so make
   `runBenchmarkJob` await it, and keep the 📊 button's sync path unchanged.
4. **Toggles**: new benchmark option `toggles: true` times studio on, studio off,
   edges on for the largest mesh, flat shading on (each until the next frame
   finishes; reuse `frameTimes` sync method).
5. The suite needs an open tab: `--browser attach` (default: wait up to 60 s
   for a tab on the evaluator's server and print its URL) or
   `--browser playwright` (optional dependency; launches Chromium with
   `--enable-gpu --use-angle=metal` on macOS, headless elsewhere; mark frame times
   with `note: "software rendering"` when `renderer` in `WEBGL_debug_renderer_info`
   contains "SwiftShader").

**Tests**: Python — the applied handshake with a websocket client standing in
for the tab (pattern of `test_runtime.py`); a request with `isolated=True`
carries the two headers, without it does not. Node — the toggle timing helper
and the `seq` acknowledgement logic as pure functions.

**Acceptance**: all checks pass; report how a human verifies it in a browser
(`python -m kayviz.evaluate --suite browser --scenes small`).

### P0-C — robustness suite

Needs P0-A. Each check produces a row `{suite: "robustness", metric: <check id>,
value: 1 (pass) | 0 (fail), note: <failure detail>}`. Put the checks in
`evaluate/robustness.py` **and** run them in pytest (`tests/test_robustness.py`,
marked `@pytest.mark.slow` for the long ones; register the marker in
`pyproject.toml`; default pytest run excludes `slow`; `check.sh` stays fast).

Checks (ids exactly):
- `fuzz-serializers`: 2,000 seeded random cases over every public
  `kv.register_*` / `kv.add_*_quantity` signature: NaN/inf coordinates, wrong
  ndim/shape/dtype (object, complex, bool, strings), negative and out-of-range
  indices, `-1` padding misuse, empty arrays, faces with < 3 vertices, repeated
  vertices in a face, colours out of range, unknown `defined_on`. Pass = each
  call either succeeds or raises `ValueError` whose message contains the object
  name; and after the run the script buffer contains only the successful objects
  (check `registry.get_app("script")._buffer`). NaN/inf: decide per field
  whether to reject or allow; document it in `docs/kayviz/API.md`.
- `fuzz-protocol`: against a running server: random bytes, truncated binary
  frames, invalid JSON, JSON that is not an object, unknown actions, a 5 MB
  message (above `WS_MAX_SIZE`), 1,000 messages in a burst. Pass = server still
  answers `/api/script/ping` and a second, well-behaved client still receives a
  push.
- `lifecycle-tab-closes-in-callback`, `lifecycle-server-restart`,
  `lifecycle-two-tabs`, `lifecycle-slow-tab-dropped` (a client that never reads;
  the other client unaffected; the slow one after reconnecting gets the
  snapshot), `lifecycle-push-burst` (1,000 pushes; the client receives them in
  order, final snapshot equals the buffer), `lifecycle-cell-rerun` (re-register
  the same app 50 times; no growth in threads, open sockets or tasks).
- `leak-push-clear`: 200× (push 10 meshes, clear); Python footprint and
  `tracemalloc` current must not grow by more than 10 % between iteration 50 and
  200 (fit a line through samples; report the slope in MB/100 iterations).
- `leak-browser` (only with a tab, P0-B): same loop, reading
  `performance.memory` and `renderer.info.memory.{geometries,textures}` through a
  benchmark-style job; counts must return to their starting value after clear.

Fixes: if a check finds a real bug, **do not fix it in this card** unless the
fix is ≤ 10 lines and obvious; otherwise mark the test `xfail(strict=True)` with
the reason and list it in the report. The human decides.

**Acceptance**: all non-slow checks pass or are documented xfails;
`kayviz/tools/check.sh py -m slow` runs the long ones.

---

## 3. Phase 1 — what users notice

### P1-A — studio render buffers
Files: `static/lib/Studio.js`, `static/main.js` (save picture), `static/benchmark.js`
(`bufferBytes` must stay correct).
- Studio passes render at pixel ratio `min(devicePixelRatio, studioPixelRatio)`
  with `studioPixelRatio = 1` by default; the final output still fills the
  canvas. `window.__studio.setPixelRatioCap(x)` changes it.
- "Save picture" in studio mode temporarily uses the full ratio (quality), then
  restores it.
- Investigate whether the composer can use one MSAA target (render pass) + a
  non-MSAA ping-pong target for the post passes; do it only if the image is the
  same (GTAO and output pass don't need MSAA).
- Update `bufferBytes` to the new formats.
- Node test: `bufferBytes` for a 2744×1518 canvas at ratio 2 with the cap 1
  reports studio + shadow ≤ 200 MB.
- Report: before/after numbers from `bufferBytes`; a human checks the image.

### P1-B — Python memory
Needs P0-A. Use `evaluate.memory` on `mesh-2M` and `merged-12M`. Find every
copy kayviz keeps (the snapshot buffer `_buffer` holds the float32 dicts by
design; check whether the encoded `bytes` of a push, validated temporaries or
`script._structures` keep more). Remove copies that are not needed; keep one.
**Measure before claiming**: put the before/after table in the commit body.
Target: kayviz's own share ≤ 1.2× raw geometry.

### P1-C — studio toggle without a freeze (FE16)
Files: `static/lib/Studio.js`, `static/main.js` (`__setStudio`).
- When studio is switched on the first time, call
  `renderer.compileAsync(scene, camera)` with the studio materials/override in
  place, keep drawing plain frames until the promise resolves, then switch.
  Show "preparing studio…" with the existing `window.__toast(message, kind)` (`main.js` ~l.517).
- Toggle must stay synchronous for `benchmark.js` (it calls `__setStudio`
  directly): add `__setStudio(on, { wait: true })` or keep a sync path there.
- Node test with a stub renderer: the switch happens after the promise resolves.

### P1-D — tab CPU copies
Files: `static/ws.js`, `static/viewer.js`, `static/SceneEntry.js`.
- Find what holds the decoded arrays after a message is applied (the decoded
  frame object, `opts`, three.js attributes). Drop references that are not needed
  after upload (e.g. the whole decoded message, duplicate `edgeVerts` that equal
  the mesh vertices).
- Do **not** free three.js attribute arrays (edges, face scalars, flat shading
  re-read them).
- Node test: after applying a mesh message, the message object is not retained
  by the viewer (use a `WeakRef` + `--expose-gc` if needed, or check fields).

---

## 4. Phase 2 — data path

### P2-A — attach mode sends binary (BE13)
Files: `runtime/script.py` (`_send`, attached branch), `runtime/script_app.py`
(`/push`).
- In attached mode POST the `wire.encode` bytes with
  `Content-Type: application/x-kayviz-frame` to `/api/script/push`; the route
  accepts both that and the JSON body (old clients). Decode with `wire.decode`.
- Limit the body size (e.g. 1 GB, constant next to `WS_MAX_SIZE`); refuse more
  with 413.
- `LocalOnlyMiddleware` already guards the route; a non-browser POST has no
  Origin header — keep it that way.
- Test (test_runtime style): `python -m kayviz` shared server in a subprocess,
  a client in attached mode pushes a 100k-triangle mesh; a websocket client
  receives it identical (`np.array_equal`) to what was sent.

### P2-B — GUIApp `/load` without JSON lists (BE12)
Files: `runtime/app.py`, `static/app_loader.js`.
- Option chosen: `/load` returns `{ok: true, via: "ws"}` and the initial scene
  is sent as the first message on the app's WebSocket after it opens (through
  the same encoder). Keep the old JSON response when the request has
  `?format=json` (compatibility).
- Make sure the snapshot ordering rules (snapshot never overtakes an update)
  hold for GUIApps too.
- Tests: an app with a 100k mesh; the WS client receives it as one binary frame.

### P2-C — pushes from threads started inside a callback (SE22)
Files: `runtime/script.py` (`_sink_local`, `_push_sink`, `_set_push_sink`),
`runtime/callback_app.py`.
- Replace the thread-local with `contextvars.ContextVar("kayviz_push_sink",
  default=None)`. `asyncio.to_thread` copies the context, so the callback's
  pushes keep working; set/reset with the token (`var.reset(token)`), not by
  assigning `None`.
- Add `kv.thread(fn, *args, **kwargs) -> threading.Thread` (started, daemon)
  that runs `fn` in a copy of the current context, so pushes from it go where the
  caller's pushes go. Plain `threading.Thread` keeps today's behaviour (goes to
  the script channel): document both in `docs/kayviz/API.md`.
- Tests: three scenarios — push inside the callback, push from `kv.thread`
  started in the callback (lands in the callback's buffer), push from a plain
  thread (lands in the script channel); and the main thread pushing at the same
  time as a callback is unaffected.

---

## 5. Phase 3 — large scenes

### P3-A — point impostors
Files: `static/viewer.js` (point cloud, ~l.920), new `static/lib/PointSprites.js`.
- One instanced quad per point (`InstancedBufferGeometry`, per-instance position,
  radius, colour), vertex shader expands the quad facing the camera, fragment
  shader discards outside the circle and writes sphere normal and
  `gl_FragDepth` so points intersect meshes correctly. Must work with the
  existing lighting (use `onBeforeCompile` on a `MeshStandardMaterial`, or a
  `ShaderMaterial` that reads the scene lights; flat-looking points are not
  acceptable) and with studio mode (GTAO depth pass) and shadows.
- Keep the old instanced spheres when `point_render="sphere"` is passed
  (serializer option, default `"sprite"`).
- Click-to-inspect (`main.js` ~l.560, a `THREE.Raycaster`) must keep working for
  points: give the sprite mesh a `raycast` that tests the point spheres.
- Node test: buffer layout for N points; Python test: the new serializer option.
- Report: what a human must look at in the browser.

### P3-B — instanced tubes for curve networks
Same approach as vectors (`viewer.js` ~l.784): one cylinder instanced per edge
plus a sphere instanced per node; colour per edge/node. Replaces the current
per-network tube geometry only above a size threshold (e.g. 20k edges) if the
visual differs; otherwise everywhere. Tests as P3-A.

### P3-C — float64 recentring (GEO16)
Files: `serializers.py`, `runtime/script.py`, `static/viewer.js`, `static/main.js`.
- Python: before casting coordinates to float32, subtract a scene origin chosen
  once per scene (first object's bounding-box centre rounded to a power of two;
  `kv.set_origin(...)` overrides). Messages carry `origin` (float64 list).
- Viewer: objects stay in local (recentred) coordinates; the origin is added
  back only where coordinates meet the user: inspect/picking readouts, and
  `look_at` / `{action: "view"}` targets (subtract it on the way in). Document it.
- Test: a mesh at 1e6 + small offsets keeps its shape (max error < 1e-6 relative
  after a round trip through serializer + decode + origin).

---

## 6. Phase 4 — geometry features (each its own card; owner picks the order)

For each: Python API in `runtime/script.py` + serializer + viewer + docs + tests.

| card | API | approach | tests |
|---|---|---|---|
| P4-backface | `register_surface_mesh(..., back_color=None)` | `onBeforeCompile`, `gl_FrontFacing ? diffuse : back` | serializer validation; node: material define set |
| P4-scalars-points-curves | `add_scalar_quantity` on point clouds / curve networks (`defined_on="nodes"/"edges"`) | per-instance colour from the existing LUT (`lib/colormap.js`) | length validation; node: colours from LUT |
| P4-isolines | `add_scalar_quantity(..., isolines=True, iso_spacing=None, iso_width=1.0)` | fragment shader on the interpolated scalar, `fwidth` for pixel width | node: shader chunk injected |
| P4-wireframe | `show_wireframe=True` (screen-space) | barycentric attribute on non-indexed geometry; only polygon edges (`poly_edges`) | node: barycentrics per polygon |
| P4-oit | `transparency="weighted"` per viewer | weighted blended OIT (McGuire & Bavoil): accumulation + revealage targets, composite pass; plain and studio | node: targets created/disposed |
| P4-pick-points-vectors | click-to-inspect works on points and vectors | `main.js` ~l.560 uses a `THREE.Raycaster`; report `intersection.instanceId` for instanced meshes (point index / vector index and its value) | node: raycast on an instanced mesh returns the instance |
| P4-export | `kv.export(name, path)` → `.obj` / `.ply` from the Python buffer (no browser) | polygons from the original faces (not triangles); scalars into PLY properties | round trip read-back test |
| P4-param | `add_parameterization_quantity(mesh, name, uv, defined_on="vertices"|"corners", style="checker"|"grid", scale=1.0)` | UV attribute + checker/grid in the fragment shader | validation; node: attribute |

---

## 7. Phase 5 — engineering

### P5-A — split `runtime/script.py`
Into `runtime/script/` package or sibling modules: `modes.py` (init, attach,
hosted), `register.py` (register_*, quantities, `_track`), `view.py`
(look_at, set_up_dir, reset_camera), `capture.py` (screenshots, `benchmark`),
`lifecycle.py` (show, kill_servers, wait). `kayviz.runtime.script` must keep
re-exporting every public name and the private names tests and other modules use
(`grep -rn "script\._" kayviz/`). **Pure move**: no behaviour change in the same
commit. Do it when no other card is open (it conflicts with everything).

### P5-B — `// @ts-check`
Add `// @ts-check` + JSDoc types to `static/*.js` (not `vendor/`), a
`jsconfig.json`, and `npm run typecheck` (`tsc --noEmit`, TypeScript as a dev
dependency only). Fix real type errors; for false positives use
`/** @type {any} */`, never blanket `// @ts-ignore` on whole files.

### P5-C — layout and accessibility (FE28, FE29)
Panels positioned with CSS (flex/grid regions) instead of fixed pixel offsets;
every button has `aria-label` and is keyboard-reachable; focus visible; colour
contrast ≥ 4.5:1 for panel text in both themes. Node tests with `dom_stub.mjs`
for aria attributes.
