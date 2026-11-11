# kayviz user-experience report (geometry researcher writing scripts and notebooks)

Experiments in conda env Lproj with KAYVIZ_NO_BROWSER=1, a websocket/HTTP client standing in for the browser. Test suite passes (100). examples/polyhedral_mesh/run.py starts and serves its schema.

## 1) Summary (verdict)
1. Getting started is quick: install, kv.init(), register_*, show() work as documented; next free port, tab reuse and blocking until the tab closes behaved well.
2. Nothing checks the input: wrong shapes, out-of-range indices, NaN, wrong lengths, typo'd target names, typo'd defined_on/material all return without error; the browser drops the data or draws garbage.
3. The callback GUI has state bugs: only the widget that fired is recorded (a quick change to a second widget loses the first); integer dropdown values come back as strings; panel layout fixed at registration; kv.remove inside a callback comes back on reload.
4. The viewer depends on scale: fixed camera with far=100, no fit/reset, no shortcuts; default point radius 0.0005 below the slider's minimum; absolute slider ranges.
5. Verdict: good for quick looks at unit-scale meshes I already trust; risky for debugging (exactly when my arrays are wrong). Needs validation, fit view and a few Polyscope conventions before I'd recommend it.

## 2) Friction log
| id | sev | what I tried | what happened | expected | evidence |
|---|---|---|---|---|---|
| U1 | blocker | register_surface_mesh with V (10,2), V.T (3,10), F index 99, F=-1, float F, NaN V, complex V; point cloud (10,); curve edges (n,3) | All accepted and broadcast. Only F=None and color="red" raised; complex V only a ComplexWarning. | ValueError naming shape / index range | VERIFIED |
| U2 | blocker | add_scalar_quantity wrong length; target "Mesh_typo"; defined_on="vertex"; vertex-length values with defined_on="faces"; vectors (10,2); vectors on missing target | Nothing raised. Browser drops unknown parent silently; wrong-length scalar writes a wrong-size colour buffer; vector mismatch only console.warn; any defined_on ≠ "faces" treated as vertices. | Errors in Python naming structure and expected length | VERIFIED (Python); browser FROM CODE viewer.js:300, SceneEntry._writeColors |
| U3 | annoying | add_scalar_quantity("Early") before register_surface_mesh("Early") | Accepted; buffered before its mesh → dropped live and on every reload. | Error, or kept until mesh exists | VERIFIED |
| U4 | annoying | Register M, scalar h (10 values), re-register M with 4 vertices; then kv.remove("M") | Tab drops h, but server buffer keeps M::h; reload re-applies a stale wrong-length scalar; after remove the orphan stays buffered. | Re-register/remove drops buffered quantities | VERIFIED (/api/script/load) |
| U5 | blocker | Sliders A and B; browser sends trigger="b" with {a:5,b:2} | Python state["a"] stays 1.0 (only triggering key written back, imgui live mode); one 120 ms debounce for all widgets → moving A then B loses A's trigger; Python and browser disagree. | All payload values applied, or per-widget debounce | VERIFIED (server); debounce FROM CODE |
| U6 | annoying | imgui.dropdown with options [1,2,3] | state["mode"] becomes '2' (str); schema default '1'. | Original option type kept | VERIFIED |
| U7 | annoying | Conditional widget behind a checkbox; Python setting state["a"]=7 in a button | Schema captured once: conditional slider never appears; panel never shows Python-side changes; default stays after reload. | Immediate-mode rebuild/sync | VERIFIED |
| U8 | annoying | Two buttons labelled "Run"; button "a" next to slider key "a" | One click fired both; moving slider a fired button "a". Keyed by label, no warning. | Unique ids or warning | VERIFIED |
| U9 | annoying | Buttons inside `with kv.imgui.header("Tools")` | All buttons moved to one "Actions" folder; panel title is the app name. | Buttons stay in their section | FROM CODE auto_callback_panel.js:93-105, app_loader.js:80 |
| U10 | annoying | kv.remove("X") / kv.clear() inside a callback; top-level object before set_user_callback | remove not routed to app buffer → X back on reload; clear() clears the app buffer only → top-level objects return on reload. | Same live and after reload | VERIFIED |
| U11 | cosmetic | on_load= | Runs once at set_user_callback time, not per page load; studio_demo needs a no-op gui() just to seed a scene. | Name on_register / initial_scene or run per load | VERIFIED |
| U12 | annoying | Callback raising ValueError | Terminal traceback (good); browser shows only "Server: …" in the small grey status line bottom-left (z-index 10), covered by the scene panel (z-index 1000) once it has several objects; no type, no toast. | Visible error toast with type | VERIFIED / FROM CODE |
| U13 | blocker | Mesh at 100-1000 units or 1e-3 | Fixed camera (0,1.5,4), near 0.001, far 100, 4-unit grid; no fit; large mesh clipped or invisible. | Auto-fit on first push + fit button/key | FROM CODE main.js:58-70 |
| U14 | annoying | register_point_cloud default radius | 0.0005 practically invisible (README passes 0.01); slider 0.001-0.1 (default below minimum); tube/vector sliders absolute. | Radius relative to bounding box | VERIFIED / FROM CODE scene_panel.js:262 |
| U15 | annoying | show_edges=True with defaults | color and edge_color both 0.8 grey: invisible edges. | Dark default edge colour | VERIFIED |
| U16 | annoying | Polyscope habits: smooth_shade=, edge_width=, enabled=, cmap=, vminmax=, kv.screenshot() without path, curve type "line" | TypeError/ValueError (loud at least). No enabled (it's show), no colormap choice, no vminmax, screenshot needs a path, register_* returns None (string-keyed, typos silent). | Polyscope aliases, colormap/vminmax, structure handles | VERIFIED |
| U17 | annoying | kv.screenshot("shots/fig.png") | Writes fig_v0.png and fig_v1.png, no fig.png (two default views); view dict typo → bare KeyError 'dir'; tab that doesn't render → wait for timeout (30 s default). | One view from the current camera to fig.png | VERIFIED |
| U18 | annoying | material="glas", opacity=5, color=(200,100,50) | Accepted silently; unknown material falls back to global; 0-255 colours not detected. | Warnings | VERIFIED / FROM CODE |
| U19 | annoying | Re-push on slider move (Dupin pattern: clear + re-register) | Every colour, opacity, visibility tick or scalar range set in the scene panel resets on the next move. | Per-name UI overrides kept | FROM CODE viewer.js registerSurfaceMesh |
| U20 | annoying | kv.show() headless with KAYVIZ_NO_BROWSER=1 | Prints "Opening …" (misleading), then blocks forever without hint; with a tab that connects and closes it returns ~3 s after (good). | "No tab connected yet; open <url>" after N s | VERIFIED |
| U21 | annoying | kv.kill_servers() | Scans 8000-8099, ignores KAYVIZ_PORT; shuts down other users'/kernels' viewers without asking; not in user docs. | Default to KAYVIZ_PORT range; document | VERIFIED / FROM CODE |
| U22 | cosmetic | kv.init(); kv.init(port=...); show(app="dupni") | Second init ignores the port silently; typo'd app opens a tab with "Failed to load schema … 404" without listing apps; Python doesn't check the name. | Python raises unknown app with the list | VERIFIED |
| U23 | annoying | Offline / cluster without internet | three.js and lil-gui from cdn.jsdelivr.net → blank viewer. | Vendored copies | FROM CODE index.html |
| U24 | annoying | Python 3.9 (requires-python >= 3.9) | serializers.py uses `bool | None` without `from __future__ import annotations` → TypeError at import on 3.9. | Future import or require 3.10 | FROM CODE |
| U25 | cosmetic | GUI layout | Energy panel always bottom-right even in plain scripts; inspect panel opens on top of it (z 2000); gizmo/buttons hard-coded at left 288-528 px; scene-panel "×" removes locally with no undo and the object returns on reload. | Energy panel only with data; no overlaps; undo on remove | FROM CODE |
| U26 | annoying | Click-to-inspect | Triangle index and its vertex indices; after a face scalar the indices are meaningless (fi*3…); points not pickable; no scalar value, no polygon vertex list. | Original ids + quantity values (Polyscope pick panel) | FROM CODE main.js |
| U27 | cosmetic | Docs / discoverability | kv.checkbox/kv.slider (dataclass annotations) vs kv.imgui.checkbox/slider_float share names with different meanings; API.md omits slider_float step; get_camera docstring uses legacy ws.screenshot_views; docs table omits show/material/edge_color/edge_radius; no package README. | — | VERIFIED |
| U28 | positive | Busy port; bad KAYVIZ_URL; explicit busy port | Next free port chosen; clear RuntimeError for bad URL and busy explicit port. | — | VERIFIED |

## 3) Missing features (ranked)
1. Input validation with clear messages.
2. Fit view / reset camera (button + keys F/R), auto-fit on first push, near/far from bounds, scene-relative sizes.
3. Colormaps (diverging, symmetric, categorical) and vminmax from Python, colour bar also in screenshots.
4. Two-way immediate-mode GUI state (all payload values, Python changes synced, conditional widgets).
5. Polyscope-style structure handles, `enabled=` and other aliases.
6. Keyboard shortcuts; search/filter in the scene list.
7. Better picking (original ids, values, point clouds).
8. Bundled offline frontend.
9. Inline Jupyter display (IFrame / _repr_html_).
10. screenshot(path) → one file from the current camera; persistent per-structure UI state.

## 4) Top 5 changes
1. Validate in serializers and add_*_quantity; track registered names so missing targets / typos raise in Python (U1-U3, U18).
2. Scene-aware camera: auto-fit, fit/reset button and keys, near/far from bounds, relative radii and slider ranges (U13, U14); dark default edge colour (U15).
3. Fix the callback-state model: all payload keys, per-widget debounce, keep dropdown types, buttons in their headers, re-send schema + values after each callback (U5-U9).
4. Keep the server buffer consistent with the live tab: drop a target's quantities on re-register/remove, route remove through the callback sink, consistent clear() (U4, U10).
5. Visible errors (toast) and Polyscope gaps: colormap/vminmax + colour bar, enabled=, screenshot(path) single file; hide empty energy panel; kill_servers default to KAYVIZ_PORT (U12, U16, U17, U21, U25).
