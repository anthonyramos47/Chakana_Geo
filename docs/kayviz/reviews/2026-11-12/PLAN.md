# kayviz — plan for the open items, and an evaluator

Branch `debugging` after `94b333a`. The items are the "open" list of
`../2026-11-11/00_CHIEF_SUMMARY.md` plus the findings of the 2026-11-12 memory
comparison with Polyscope. Exact-colour mode is left out (owner: not a priority).

**Order: the evaluator comes first.** Every later phase is accepted by a number
the evaluator measures, so a feature cannot quietly make kayviz slower, heavier or
more fragile.

Sizes: S ≈ a few hours, M ≈ a day, L ≈ several days.

---

## Phase 0 — `kayviz.evaluate`: robustness, speed and memory (L)

A module shipped with the package, so users can run it on their own machine and
attach the output to a bug report:

```bash
python -m kayviz.evaluate                      # all suites, opens a tab
python -m kayviz.evaluate --suite speed,memory --scenes large
python -m kayviz.evaluate --compare baseline.json   # fails on regressions
python -m kayviz.evaluate --polyscope          # same scenes in Polyscope, if installed
```

Output: one JSON file (machine, browser, versions, every measurement) and a
Markdown/HTML report with tables. `--compare` checks against a stored baseline
with per-metric tolerances and exits non-zero on a regression.

### Scenes (one generator, shared by all suites)

| id | content | stresses |
|---|---|---|
| `empty` | nothing | fixed costs |
| `objects-1k` | 1,000 separate small meshes | per-object costs, draw calls, panel |
| `mesh-100k`, `mesh-2M` | one triangle mesh | throughput |
| `merged-12M` | 10,000 spheres in one mesh | the Polyscope comparison case |
| `ngon-200k` | quads, hexagons and non-convex polygons | triangulation, edges |
| `points-1M`, `curves-200k` | point cloud, curve network | instancing |
| `quantities` | 2M-tri mesh + vertex/face scalars + vectors | quantity path |

Scenes are generated with numpy only (no hanan), seeded, so runs are comparable.

### Speed suite

Measured per scene:
- **Python side**: serialize, validate, encode time; bytes on the wire.
- **Delivery**: time from `register_*` to the tab having drawn it. This needs a new
  acknowledgement: the tab answers `{action: "applied", seq}` after the first frame
  that contains a message.
- **Frames**: the existing `kv.benchmark()` numbers, plain and studio (GPU-synced
  frame times, triangles, draw calls).
- **Interaction**: callback round trip (slider event → Python → new geometry
  drawn), median and 95th percentile under 20 events/s.
- **Toggles**: time for studio on/off, edges on, face scalar on (catches FE16).

### Memory suite

| process | how | trust |
|---|---|---|
| Python | process footprint, plus `tracemalloc` snapshots split by kayviz module | exact |
| the tab | `performance.measureUserAgentSpecificMemory()`; it needs a cross-origin isolated page, i.e. the server sending COOP/COEP headers in evaluator mode (to verify on Vivaldi/Chrome) | exact per tab |
| JS heap | `performance.memory` (fallback) | Chrome only |
| GPU | buffer sizes from formats (as today) | estimate |

The GPU process is shared with every other tab, so the evaluator does not report
its footprint as a kayviz number (we saw it swing 0.8–2.6 GB with nothing changing).

For each scene the report shows memory per MB of geometry: Python, tab, GPU
estimate, and their ratio to the raw float32 geometry.

### Robustness suite

Each check passes or fails; most of them run in CI.
- **Input fuzzing**: random and malformed arrays for every serializer and
  `add_*_quantity` (NaN/inf, wrong shapes and dtypes, out-of-range and negative
  indices, empty, degenerate and non-planar polygons, huge counts). The only
  allowed outcome is a `ValueError` naming the object, or success. No crash, no
  partly buffered scene.
- **Protocol fuzzing**: malformed, truncated and oversized WebSocket messages;
  unknown actions; binary frames from a browser. The server stays up and the
  other tabs keep working.
- **Lifecycle**:
  - the tab closes during a callback;
  - the server restarts with the tab open;
  - two tabs;
  - a slow tab gets dropped (`MAX_PENDING`) and recovers from the snapshot;
  - 1,000 pushes in a burst;
  - re-running a notebook cell 50 times.
- **Leaks**: push → clear repeated 200 times, and studio on/off 100 times. Python
  footprint, JS heap and the three.js counts (`renderer.info.memory`) must
  level off. A slope above a threshold fails.
- **Security**: the existing `LocalOnlyMiddleware` cases, run as a suite.

### Browser automation

- Default: attach to the tab that is already open, as `kv.benchmark()` does. This
  gives real GPU numbers.
- `--headless`: start Chromium with Playwright, an optional dev dependency, so
  robustness and Python-side speed can run in CI. Headless Chromium renders on the
  CPU (SwiftShader), so its frame times are not reported as GPU numbers.

### Acceptance

- One command produces the report for all scenes on this Mac.
- The 2026-11-12 numbers are reproduced (±10 %) and stored as the first baseline.
- The CI job runs fuzzing, protocol, lifecycle and leak checks headless.

---

## Phase 1 — what users notice (M)

1. **Studio buffers** (~620 MB at 2744×1518). Render the studio passes at pixel
   ratio 1 by default, with an option for full resolution in `save picture`.
   Check whether the two MSAA half-float targets can become one plus a resolve.
   - Target: studio adds ≤ 200 MB on this screen, and the frame time does not get worse.
2. **Python memory, 843 MB for 293 MB of geometry.** Measure first with `tracemalloc`
   (Phase 0). Part of it is probably the benchmark script's own float64/int64
   sphere arrays (~460 MB), not kayviz; that is unverified. kayviz keeps one float32
   copy by design (the snapshot buffer); check for a second one (the encoded frame,
   the validated copies).
   - Target: kayviz's own share ≤ 1.2× the geometry.
3. **Studio toggle freeze (FE16).** Compile the studio programs with
   `renderer.compileAsync` before switching, keep plain mode drawing meanwhile.
   - Target: no frame over 50 ms when toggling.
4. **CPU copies in the tab** (JS heap ≈ 1.7× geometry). Measure what holds them
   (decoded frame plus three.js attributes, or only the attributes). Drop the
   decoded frame as soon as it is applied. Freeing the attribute arrays
   (`onUpload`) would make edges, face scalars and flat shading need a re-send;
   only as an opt-in for huge meshes.

## Phase 2 — data path and the thread trap (M)

5. **Attach mode sends binary (BE13).** `python -m kayviz` shared server: POST
   pushes as the `wire` binary format instead of JSON lists.
6. **GUIApp `/load` returns binary (BE12)**, or sends its scene over the WebSocket
   like everything else.
7. **Pushes from threads a callback starts (SE22).** Replace the thread-local push
   sink with a `contextvars.ContextVar`. `asyncio.to_thread` copies the context,
   and a small `kv.thread(fn)` helper does the same for user threads, so their
   pushes go to the callback's buffer. Keep the current behaviour for plain
   `threading.Thread` and document it.
   - Target: a lifecycle test for each of the three cases.

## Phase 3 — large scenes (L)

8. **Point impostors.** Points are instanced 12×8 spheres today (~170 triangles
   each, so 1M points ≈ 170M triangles). Use one camera-facing quad per point with
   a sphere shader (depth and normal written in the fragment shader).
   - Target: `points-1M` at ≥ 60 fps plain.
9. **Instanced tubes for curve networks** (one cylinder instanced per edge, plus
   joints), the same approach as vectors.
10. **Float64 recentring (GEO16).** Subtract the scene centre in float64 in Python
    before converting to float32. Send the offset; the viewer applies it to the
    camera and to picked coordinates. This fixes jitter far from the origin
    (geo-referenced data).

## Phase 4 — geometry features (L, one item at a time)

| item | approach | size |
|---|---|---|
| backface colour (GEO19) | `gl_FrontFacing` in the material via `onBeforeCompile`, colour option per mesh | S |
| scalars on points and curves (GEO20) | per-instance colour from the LUT already used by meshes | M |
| isolines | fragment shader on the scalar: lines at a spacing, width in pixels with `fwidth` | M |
| screen-space wireframe (GEO22) | barycentric attribute plus `fwidth`; polygon edges only (uses `poly_edges`) | M |
| order-independent transparency (GEO18) | weighted blended OIT: two extra targets, one composite pass | L |
| picking points and vectors (FE25) | instance ID in the pick pass | M |
| OBJ/PLY export | `kv.export(name, path)` from the Python buffer, so it needs no browser | S |
| parameterization checker | `add_parameterization_quantity` (UV per vertex or corner) + checkerboard or grid shader | M |

## Phase 5 — engineering (M)

11. Split `runtime/script.py` (1,031 lines) into: init/modes, registration,
    view/camera, capture (screenshots and benchmark), lifecycle.
12. `// @ts-check` with JSDoc types in the frontend, checked by `tsc --noEmit` in CI.
13. Panel layout without fixed pixel offsets (FE29), and the rest of the
    accessibility list (FE28).

---

## Order and checkpoints

| step | depends on | checkpoint |
|---|---|---|
| Phase 0 | — | first baseline committed |
| Phase 1 | Phase 0 (memory suite) | evaluator shows the targets |
| Phase 2 | Phase 0 (lifecycle suite) | — |
| Phase 3 | Phase 0 (speed suite) | — |
| Phase 4 | Phase 3 for points/curves scalars | owner chooses which items |
| Phase 5 | anytime; best before the release | — |

Every phase ends with pytest, `npm test`, the evaluator compared against the
baseline, and an update of the docs (`docs/kayviz/` and `CLAUDE.md`).

---

## Status (2026-11-12, branch `debugging`)

| item | result | commit |
|---|---|---|
| P0-A evaluator (speed, memory, report, compare) | done | `a746510` |
| P0-B browser suite (delivery, frames, toggles, tab memory) | done | `5731800` |
| P0-C robustness suite (fuzz, protocol, lifecycle, leaks) | done; found an unbounded send buffer for a stuck tab, fixed | `fcf3009`, `18478b0` |
| P1-A studio buffers | done, pixel ratio 1 by default (owner's choice) | `2829abe` |
| P1-B Python memory | done: no edges sent, single-buffer encoder, blocked convexity check (merged-12M peak 1686 → 440 MB, kept 1.67x → 1.0x) | `4015388`, `905d94b`, `401aa51` |
| P1-C studio toggle freeze | investigated, not changed: ~60 ms, 14 of 20 new programs are shadow-map/GTAO internals compileAsync cannot reach | — |
| P1-D tab CPU copies | measured, no redundant copies; the excess was curve tubes (→ P3-B) | — |
| P2-A / P2-B binary attach pushes and /load | done | `b34caed` |
| P2-C pushes from threads (kv.thread) | done | `51a7082` |
| P3-A point sprites | done: 1M points 113 → 20 ms per frame | `5f5998a` |
| P3-B instanced tubes | done: 200k edges 55 → 12 MB, inspect gets edge ids | `98d4f54` |
| P3-C float64 recentring | done (kv.set_origin, automatic for far data) | `28e4e49` |
| Phase 4 features, Phase 5 engineering | open; Phase 4 order is the owner's choice | — |

### Phases 4-5 (2026-11-13)

| item | result | commit |
|---|---|---|
| OBJ/PLY export (`kv.export`) | done: polygons as registered, PLY with scalars, far coordinates | `fa7f5ab` |
| back colour (`back_color`) | done | `8279a1b` |
| scalars on points and curves | done (`defined_on="edges"` for curves) | `80b8a45`, `d3e86cc` |
| picking points and vectors | done | `7cba345` |
| isolines (`isolines=True`) + combinable shader patches | done | `2a63085` |
| screen-space wireframe (`show_wireframe=True`) | done (fat lines) | `1da0c60` |
| parameterization checker | done, per-vertex and per-corner uv (corners: triangle and quad meshes) | `2c4d1bb`, `6470632` |
| order-independent transparency | done, opt-in (`kv.set_transparency("weighted")`), plain and studio | `09ba813` |
| P5-A split `runtime/script.py` | done: state in script.py, API in register/view/capture/lifecycle, same 85 names | `061d2b0` |
| P5-B type checking (`npm run typecheck`) | done, every frontend module | `d13314f`, `fe25971` |
| P5-C layout | checked at 1000x640 and 760x560: no overlaps; clipped panel titles fixed | `597ddb9` |
