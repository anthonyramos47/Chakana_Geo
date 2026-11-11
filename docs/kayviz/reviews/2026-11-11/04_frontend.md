# kayviz frontend review (frontend / WebGL expert, branch `debugging`)

## 1) Summary
- Fixed and checked: render-on-demand, instanced arrows, one scene load per page (studio demo: one 348 KB binary frame, `/load?objects=false` empty), batched panel rebuilds (B19), scalar Math.min crash (B4). Still open: B8, B9, B10, B11, B18, B20.
- 4 new crashes / wrong results confirmed in node with three r165: (a) face labels after a face scalar throw every frame; (b) vertex scalar after a face scalar gets a wrong-size colour buffer; (c) with `normal`, `depth`, `blinn_phong` shaders, setColor and addScalarQuantity throw; (d) inspect box shows wrong vertex ids after a face scalar.
- Weakest area: panel/viewer state sync. The scene panel is rebuilt from scratch on every server message: during a streaming optimisation no scene-panel slider can be dragged and open histograms close; each update resets the user's visibility, colour, scalar range.
- AutoCallbackPanel has one debounce timer shared by all widgets; with imgui applying only the triggering key, a quick second change silently drops the first one on the Python side.
- Performance levers: colormap LUT + reused colour attribute (80 ms → 3 ms per range step at 1M values), instanced tubes, point impostors, swapping only the template geometry for radius/length, studio AO only when the camera is still. Page cannot run offline (three.js and lil-gui from the jsdelivr CDN); `ws://` and root-absolute paths block HTTPS / proxied deployment.

## 2) Findings (VERIFIED = node with three 0.165 or the running demo; FROM CODE = reading)
| id | sev | file:line | finding | evidence | suggested fix |
|---|---|---|---|---|---|
| FE1 | High | LabelRenderer.js:105,113,131,143 | Face labels crash once a face scalar made the geometry non-indexed (`idx.getX` on null), every frame, filling the status bar. | VERIFIED | Centroids from opts.faces/trisPerFace, cached per entry. |
| FE2 | High | SceneEntry.js:137-142,192-200 | Vertex scalar after face scalar: non-indexed geometry (12 verts) but colour attribute of values.length (6). | VERIFIED | Expand vertex values through opts.faces when non-indexed, or keep separate geometries. |
| FE3 | High | viewer.js:124, SceneEntry.js:148 | setColor / ScalarChild.apply assume material.color; MeshNormal/MeshDepth/ShaderMaterial (blinn_phong) have none → colour picker and scalars throw under those shaders. | VERIFIED | Guard `material.color?.`; for shader materials set uniforms.uColor. |
| FE4 | Med | SceneEntry.js:148-153 | Scalar colours multiplied by the mesh colour (material.color stays 0.8 grey/user colour). | VERIFIED | White material colour while a scalar is active. |
| FE5 | Med | main.js:445-453 | After face-scalar conversion inspect shows [3fi..] not real vertex ids. | VERIFIED: [6,7,8] vs [1,4,5] | Read ids from entry.opts.faces. |
| FE6 | High | scene_panel.js:51,138-140 | Every viewer-changed (one per server message) rebuilds the whole panel (innerHTML=''): sliders detach mid-drag, histograms collapse, type-in edits and focus lost; O(objects) DOM per message. | FROM CODE (mechanism = B11, verified) | Update rows in place keyed by name/child; skip focused/dragged controls. |
| FE7 | High | viewer.js:162,268,257,403,425,381 | Tube-radius (curve, edges), vector length/radius sliders and edge/vector colour pickers emit viewer-changed per input step → widget detached (B11 open). | VERIFIED: 1 emit per call, 6 setters | Don't emit from continuous setters, or FE6. |
| FE8 | Med | viewer.js:46,56-61,494 | Re-registration creates a fresh entry: hidden objects reappear; user colour, opacity, scalar range, show-edges reset every iteration. | FROM CODE | Per-name map of UI overrides re-applied after re-registration. |
| FE9 | High | auto_callback_panel.js:55-64 + webscope/imgui.py:120 | One debounce timer for all widgets + Python applies only payload[trigger]: change A then B (or slider then "Run") within 120 ms → A's value never reaches Python; browser and server disagree. | FROM CODE | Per-key timers / send changed keys, or live mode applies every differing payload key. |
| FE10 | Med | viewer.js:139-149 (B8, B10) | Point-cloud setRadius doesn't dispose old InstancedMesh and rebuilds with e.opts.color → picked colour reverts. | VERIFIED | Swap only mesh.geometry; keep material/instanceMatrix. |
| FE11 | Med | SceneEntry.js:200,214 (B9) | Each scalar-range step new Float32BufferAttribute via setAttribute; r165 WebGLAttributes is a WeakMap, no deleteBuffer → GPU buffers freed only at GC; VAO rebuilt each step. | VERIFIED (three source) | Allocate once, write .array, needsUpdate. |
| FE12 | Med | SceneEntry.js:193-196, viewer.js:784 | _viridis allocates per value: 80 ms per slider step at 1M vertices. | VERIFIED: 79.8 vs 3.0 ms with 256 LUT | Shared precomputed LUT (duplicated in scene_panel.js:808). |
| FE13 | Med | screenshot.js:165 | `finally { grid.visible = true }` unconditional: kv.screenshot in studio mode makes the grid appear. | FROM CODE | Save/restore grid.visible. |
| FE14 | Med | screenshot.js:46-55 | sceneBounds uses geometry.boundingBox: InstancedMesh = one glyph at origin; fitted screenshots ignore points/vector fields. | VERIFIED | box.expandByObject(o). |
| FE15 | Med | Studio.js:24,201-202 | Refit every 30 drawn frames or on child count change; with render-on-demand an in-place update leaves floor/shadow camera stale → clipped shadows. | FROM CODE | Refit-dirty flag on viewer-changed. |
| FE16 | Low | Studio.js:181-184 | Studio toggle: synchronous program recompilation, visible hitch. | FROM CODE | renderer.compileAsync before switching. |
| FE17 | Low | main.js:39-40 | preserveDrawingBuffer: true permanently, not needed (render+read in same task); costly on tile GPUs (Apple). | FROM CODE | Drop it. |
| FE18 | Low | main.js:41,110; LabelRenderer.js:24; scene_panel.js:514; energy_panel.js:147 | DPR uncapped, read once (monitor change), 2D canvases ignore DPR (blurry); studio MSAA targets plus unused default-framebuffer MSAA. | FROM CODE | Cap DPR at 2, listen for DPR change, scale 2D canvases, lower composer DPR. |
| FE19 | Low | LabelRenderer.js:27-42,59 | Full-window DPR² label canvas (~20 MB) cleared every frame even with no labels; per-label allocations; no occlusion. | VERIFIED (0.8 ms/frame for 3000 faces) | Lazy canvas, cached centroids. |
| FE20 | Med | ws.js:104-117 | If applyMessage throws, handlers and __invalidate are skipped: stale picture, half-updated panel; one throwing handler stops the rest. | FROM CODE | try/catch per step, invalidate in finally, error in status. |
| FE21 | Low | ws.js:82,101 | _pending unbounded; flushed before checkServerInstance → stale events to a new server just before reload. | FROM CODE | Coalesce pending; flush after instance check. |
| FE22 | Med | app_loader.js:51,59; all fetch('/api/…') | Hard-coded ws:// and root-absolute URLs break HTTPS and path-prefixed proxies (JupyterHub, jupyter-server-proxy, VS Code remote). | FROM CODE | URLs from document.baseURI; protocol from location.protocol. |
| FE23 | Med | index.html:29-38 | three.js and lil-gui from jsdelivr: no offline use, no integrity pinning. | VERIFIED: no vendored copy | Vendor three 0.165 + addons and lil-gui under static/vendor (MIT). |
| FE24 | Low | screenshot.js:17,198 (B7) | Every tab polls /screenshot/pending every 400 ms forever; job goes to whichever tab polls first. | FROM CODE | Push capture requests over the script WS to one chosen client. |
| FE25 | Low | main.js:394-400 | Drag-vs-click uses mousedown (touch/pen); tube edges "no edge ID" though edge = faceIndex/(2·segs); points/vectors not inspectable. | FROM CODE | pointerdown; tube→edge map. |
| FE26 | Low | viewer.js:200-210 (B18) | setMaterial doesn't set opts.pinned. | FROM CODE | pinned = true. |
| FE27 | Low | energy_panel.js:216; app_loader.js:92 | Linear mode drops energies ≤ 0; panel always shown ("Waiting for data…"). | FROM CODE | Filter only in log mode; create panel on first energy message. |
| FE28 | Med | scene_panel.js:127,531,656-666; main.js:205-335 | Accessibility: colour input display:none behind non-focusable span; collapse headers are clickable divs (no keyboard, no aria-expanded); unlabeled ranges; emoji-only buttons (no aria-label/aria-pressed); save menu doesn't close on Escape/outside click; 9-10 px text; #666 on #1a1a1a ≈ 3:1; userSelect:none. | FROM CODE | Buttons, visually-hidden colour input, aria-*, ≥ 11-12 px, contrast ≥ 4.5. |
| FE29 | Low | main.js:117,209,248,309; scene_panel.js:35 | Fixed pixel layout (288/416/456/496 px); lil-gui, energy panel and inspect box share bottom-right; below ~900 px the panels cover the canvas. | FROM CODE | CSS variables, flex/grid overlay, collapsible side panel. |
| FE30 | Low | static/ | ~19 window.__* globals as inter-module API; two module scripts relying on document order; scene panel reads viewer._objects; inline styles; gui/script_panel.js dead (B20). | FROM CODE | One entry module with a ctx object; kayviz.css. |
| FE31 | Low | viewer.js:95,57,73 | registerPointCloud always copies; on the JSON path plain arrays stay in opts beside typed copies (2-4× memory); toNonIndexed triples vertex memory while opts.vertices keeps the original. | FROM CODE | Normalise to typed arrays once in applyMessage. |

Render-on-demand caveat: viewer mutations called from code (console, timers) do not invalidate; small fix: call __invalidate inside Viewer._emit and setters.

## 3) Performance / memory opportunities
| change | expected gain | basis |
|---|---|---|
| Colormap LUT + reuse colour attribute (FE11, FE12) | 80 → 3 ms per range step at 1M vertices; no per-step GPU allocation | measured |
| Radius/length change swaps only the template geometry (FE10) | O(1) instead of 22 ms (1M points) / 11 ms (100k arrows); fixes leak | measured |
| Instanced tubes instead of baked prisms | 28.8 → 6.4 MB per 100k edges (4.5×); radius change = geometry swap | measured |
| Point clouds as sphere impostors | 1M points: 168M → 2M triangles/frame (~80×), 64 → 12 B/point | measured |
| Studio: plain render while moving, AO/VSM when still; refit on change; composer DPR ≤ 1.5 | orbit at plain cost | code + earlier measurement |
| Incremental scene-panel updates (FE6) | no per-message DOM rebuild; fixes slider/histogram loss | code |
| In-place position update when topology unchanged | no GPU realloc per iteration; with FE8 keeps user overrides | code |
| Drop preserveDrawingBuffer, cap DPR 2, no default MSAA in studio | less bandwidth/memory, esp. Apple GPUs | code |
| Lazy label canvas | ~20 MB less | arithmetic |
| decodeFrame zero-copy | not worth it (28 MB copy = 1.9 ms) | measured |

## 4) Top 5 recommendations
1. Fix FE1-FE5 and FE13 (each a few lines); add node-based frontend regression tests (three from npm + DOM stubs).
2. Rework panel/viewer state sync: in-place row updates (FE6, FE7), keep user overrides across re-registration (FE8), fix shared debounce / trigger-only update (FE9).
3. Remove remaining leaks and per-step rebuilds (FE10-FE12); then instanced tubes and point impostors.
4. Make it releasable: vendor three.js/lil-gui (FE23), baseURI-derived URLs and WS protocol (FE22), screenshots over WS (FE24), drop preserveDrawingBuffer, cap DPR (FE17, FE18).
5. `// @ts-check` + JSDoc + `tsc --noEmit` against @types/three (no build step); replace window.__* with a context module; CSS file; accessible controls (FE28-FE30).
