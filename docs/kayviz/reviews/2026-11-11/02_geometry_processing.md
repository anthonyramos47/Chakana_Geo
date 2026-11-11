# kayviz geometry pipeline review (geometry-processing expert)

## 1) Summary
- The data path (serializers, then binary wire, then `_buildMeshGeo`) is clean and fast. Ragged polygons, polygon-edge extraction and `trisPerFace` work for well-formed input: 200k ragged pentagons serialize in about 1 s. Nothing is validated, though.
- **Scalar colouring has four real bugs:** viridis is multiplied by the mesh colour; switching from a face scalar back to a vertex scalar leaves a colour buffer that no longer matches the geometry; a single NaN or Inf value throws and aborts the rest of the message batch; the 5-stop viridis is off by up to 0.16 per channel.
- **Shading does not suit polyhedral or planar-face meshes.** Normals are always smooth, area-weighted over the fan triangles (so they depend on which diagonal the fan picks), and there is no flat-shading option. A cube renders as a blob.
- **Colours on screen are not the colours passed in.** RGB tuples are read as linear, then tone-mapped (ACES, or Neutral in studio mode): (0.5,0.5,0.5) shows as about #c5c5c5, viridis purple #440154 as #9500a6. The panel swatch and colourbar are not colour-managed, so they don't match the mesh. Exact-colour figures are impossible today.
- **Scale and precision are assumed to be about 1.** The camera is fixed (near 0.001, far 100, no auto-fit). Default point, curve and vector sizes and the pick threshold are absolute. Vector magnitudes are thrown away. Coordinates are float32 with no recentring.

## 2) Findings
Line numbers refer to `kayviz/src/kayviz/` (static files under `static/`). VERIFIED = reproduced (Python against `serializers`, or the copied viewer.js/SceneEntry.js/LabelRenderer.js run in node against three@0.165.0).

| id | sev | file:line | finding | evidence | suggested fix |
|---|---|---|---|---|---|
| GEO1 | High | static/SceneEntry.js:133-155 | Scalar colours are multiplied by the mesh's base colour: `apply()` backs up `material.color` but never sets it to white; three multiplies `vColor` into `diffuseColor`. A red mesh with a scalar shows only the red channel; default 0.8 grey darkens the map 20%. `setColor` while a scalar is active also tints it. | VERIFIED: mesh colour [1,0,0] → `material.color` still [1,0,0] with vertexColors true | Set `material.color` to white while a scalar is active and restore on dispose; `setColor` only updates `e.color` then. |
| GEO2 | High | SceneEntry.js:137-142, 191-197 | After a face scalar the geometry stays non-indexed. Re-activating a vertex scalar writes nV colours for 3·nTri positions: wrong mapping, too-short attribute. | VERIFIED: cube positions 36, colours 8 | Keep the indexed geometry; build the non-indexed copy only while the face scalar is active, or expand vertex values through the original index. Better: per-vertex value attribute + shader colormap. |
| GEO3 | High | SceneEntry.js:113-118, 180/193; viewer.js:784-790 | NaN or ±Inf in a scalar throws ("reading 'map'"); the throw escapes `_applyObjects`, so the rest of the batch is lost, on every replay/reload. | VERIFIED: [0,NaN,1] and [0,Inf,1] | Min/max over finite values; NaN colour; clamp after NaN check; try/catch per object. |
| GEO4 | High | viewer.js:719 | Only `computeVertexNormals` (smooth) on the shared index: planar quads, circular/conical/PQ meshes look curved; normals depend on the fan diagonal (cube corner (0.667,0.333,0.667)). No flat-shading toggle. | VERIFIED (cube normal) | Per-mesh `shading="flat"|"smooth"` (flatShading or per-polygon normals), flat default for polygon meshes; angle-weighted smooth normals. |
| GEO5 | High | main.js:44-45; lib/MaterialLibrary.js:219; SceneEntry.js:200; gui/scene_panel.js:657, 808 | User RGB read as linear, then ACES (Neutral in studio: colours change between modes). Even `flat` is tone-mapped. Swatch and colourbar show raw sRGB, so the legend doesn't match. | VERIFIED: #808080→#c5c5c5; #3380cc→#9ac5d9; #440154→#9500a6; #fde725→#e4df97 | Read user colours as sRGB; "true colour" mode with NoToneMapping; toneMapped=false for flat and colormapped meshes. |
| GEO6 | High | main.js:58-71 | Fixed camera (0,1.5,4), near 0.001, far 100, target origin; no fit/reset view; no Python look_at/set_camera. Scenes > ~50 units clipped, far-from-origin scenes off-screen. | FROM CODE | Fit to bounds on first geometry and on a frame key/button; dynamic near/far; kv.look_at / kv.set_camera. |
| GEO7 | High | viewer.js:684-691 | Vector quantities lose magnitude: every arrow has length `length`. Wrong for gradients/forces/velocities. | VERIFIED: scales 1/1/1 for |v| = 1, 10, 0.01 | `vectortype="standard"|"ambient"` (Polyscope), colour by magnitude. |
| GEO8 | Med | static/LabelRenderer.js:105-115, 131-133, 158-171 | Face labels throw every frame once a face scalar made geometry non-indexed (`idx` null); triangle branch reads `verts[fi*3*3]` → wrong positions. | VERIFIED: throws "reading 'count'" | Centroids from opts.faces/trisPerFace, not geometry.index. |
| GEO9 | Med | main.js:433-457 | Click-inspect: after a face scalar, "vertices" are non-indexed buffer positions; quads without trisPerFace show no polygon index; no quantity values; points/vector fields/tube curves not pickable. | FROM CODE | Map triangle→polygon (fi/(faceSize-2)); vertex ids from opts.faces; show values; instanceId picking; tube edge id = faceIndex/(2·segs). |
| GEO10 | Med | serializers.py:86-89; viewer.js:710-716 | Fan triangulation from vertex 0 wrong for non-convex polygons (flipped triangles, area outside, z-fighting); non-planar polygons depend on first vertex. | VERIFIED: L-hexagon fan areas [1,2,0.5,−0.5] | Ear-clipping / projected constrained triangulation for non-convex polygons; planarity warning. |
| GEO11 | Med | serializers.py:89 | Degenerate faces (< 3 vertices) give tris_per_face 0 or −1, so sum ≠ #triangles; face scalars, vectors, labels, picking shift for later faces. | VERIFIED: tpf [2,0,−1,3], 5 tris, sum 4 | Clamp to max(len−2,0) and handle n=0 in the viewer, or reject/warn. |
| GEO12 | Med | viewer.js:784-790; scene_panel.js:808 | Viridis stops misplaced (1/3, 2/3 colours at 1/4, 3/4): max error 0.161 vs matplotlib; RGB per-vertex interpolation; colormap duplicated in two files. | VERIFIED | Shared colormap module, 256-entry LUTs (viridis, plasma, coolwarm, turbo, cyclic), lookup in the fragment shader. |
| GEO13 | Med | serializers.py:53-114, 156-173 | No input validation: (n,2) vertices flattened as xyz; out-of-range indices pass; −1 padding becomes 2^32−1 in the Uint32 index and an edge (−1,0); scalar/vector lengths and `defined_on` unchecked ("edges" accepted, ignored). | VERIFIED (all four) | Validate shapes, index range, dtype, padding convention, quantity lengths, defined_on; clear errors. |
| GEO14 | Med | serializers.py:55 vs viewer.js:294 | show_edges=True with defaults: 0.8-grey edges on 0.8-grey mesh (invisible); panel toggle uses 0.1. | FROM CODE | Default edge_color (0.1,0.1,0.1). |
| GEO15 | Med | serializers.py:117,131,177; script.py; main.js:391 | Absolute defaults (point radius 5e-4, curve 2e-3, vector length 0.05, pick threshold 0.02) while edge radius is relative. | FROM CODE | Defaults relative to the scene length scale. |
| GEO16 | Med | serializers.py:18-22 | float32 without recentring: resolution 0.0078 at 1e5; WebGL float32 jitter. | VERIFIED | Subtract a float64 origin in Python, send as mesh.position; warn when |x|/extent > 1e4. |
| GEO17 | Med | viewer.js:699-721; screenshot.js:43-63; Studio.js:208 | One NaN vertex makes the bounding box NaN → screenshot framing, studio refit, bounding sphere, NaN normals. | VERIFIED | Warn in Python; skip non-finite vertices in bounds. |
| GEO18 | Med | MaterialLibrary.js:224-253; viewer.js:128-137 | Transparency = alpha blend, depthWrite=false, per-object sort only: merged glyph meshes and self-overlapping surfaces (Dupin cyclide at 0.45) blend in arbitrary order. | FROM CODE | Depth peeling / weighted-blended OIT; cheaper two-pass back/front. |
| GEO19 | Low | MaterialLibrary.js:218 | Everything DoubleSide with flipped lighting: orientation errors invisible. | FROM CODE | Backface policy per mesh (same / other colour / cull). |
| GEO20 | Low | viewer.js:299-301 | Scalars only on surface_mesh; silently dropped on points/curves. | FROM CODE | Scalar/colour quantities on points, curves, edges. |
| GEO21 | Low | screenshot.js:43-63 | sceneBounds uses base geometry box of InstancedMesh: point clouds/vector fields ignored, origin box unioned in. | FROM CODE | InstancedMesh.computeBoundingBox / Box3.expandByObject. |
| GEO22 | Low | viewer.js:579-591 | radius=0 curves are 1 px lines; mesh edges are world-space tubes with 12 verts/edge and notched joints; heavy above ~1e6 edges. | FROM CODE | Screen-space wireframe (barycentric shader) or fat lines with pixel width. |

## 3) Missing features (ranked for a geometry researcher)
1. Flat/smooth shading control and true-colour rendering (paper figures).
2. Camera fit/reset, dynamic near/far, Python look_at/set_camera/set_up_dir; scale-relative default radii.
3. Colour quantities and colormaps (per-vertex/face RGB, diverging, cyclic, symmetric range, NaN colour, scalars on points/curves, edge scalars).
4. Vector magnitude modes, colour by magnitude; tangent-plane/line-field glyphs.
5. Richer picking (ids, quantity values, points/curves, callback to Python).
6. Isolines / contour bands on scalars.
7. Robust triangulation of non-convex polygons with planarity/convexity warnings.
8. Export to OBJ/PLY with colours/quantities; camera save/load.
9. Parameterization checker (UV grid).
10. Order-independent transparency.
11. Backface colouring / orientation check.
12. Screen-space wireframe of constant pixel width; float64 recentring.

## 4) Top 5 recommendations
1. Fix the scalar pipeline as one change (GEO1, 2, 3, 8, 9, 12).
2. Per-mesh flat/smooth shading (flat default for polygon meshes) and an exact-colour mode (GEO4, GEO5).
3. Scale-aware viewer (GEO6, 15, 16, 21).
4. Input validation in serializers (GEO11, 13, 17).
5. Vector magnitude modes and non-convex triangulation (GEO7, 10); fix show_edges default colour (GEO14).
