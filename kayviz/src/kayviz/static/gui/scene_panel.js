/**
 * scene_panel.js — Structure list panel.
 *
 * Mirrors polyscope's left-side structure list: every registered mesh / curve
 * network / point cloud gets a row with:
 *   ● visibility toggle    (eye checkbox)
 *   ● colour picker        (colour swatch)
 *   ● opacity slider       (surface meshes only)
 *   ● radius slider        (point clouds only)
 *   ● material dropdown    (surface meshes only — from MaterialLibrary)
 *   ● remove button        (× button)
 *
 * Children (EdgeChild, ScalarChild, VectorChild) each get their own typed row
 * built by _buildEdgeChildRow / _buildScalarChildRow / _buildVectorChildRow.
 *
 * The panel rebuilds itself whenever the viewer emits 'viewer-changed'.
 * It does NOT use lil-gui so it can render a dynamic list — it builds plain
 * HTML and applies a minimal inline style that matches the dark lil-gui theme.
 *
 * Usage (main.js):
 *   import { ScenePanel } from './gui/scene_panel.js';
 *   const scenePanel = new ScenePanel(viewer);
 */

import { Materials }      from '../lib/MaterialLibrary.js';
import { LightingPanel }  from './lighting_panel.js';

export class ScenePanel {
  /**
   * @param {Viewer} viewer  — the viewer.js Viewer instance
   * @param {object} opts    — { width: number (px), lights: { ambient, keyLight, fillLight } }
   */
  constructor(viewer, opts = {}) {
    this._viewer = viewer;
    this._width  = opts.width ?? 280;
    this._root   = this._buildRoot();
    document.body.appendChild(this._root);

    // Embed lighting panel above the structure list if lights are provided
    if (opts.lights) {
      const { ambient, keyLight, fillLight } = opts.lights;
      const slot = document.createElement('div');
      this._root.insertBefore(slot, this._root.querySelector('#scene-panel-body'));
      new LightingPanel(slot, ambient, keyLight, fillLight);
    }

    // Rebuild whenever the viewer's object list changes
    document.addEventListener('viewer-changed', () => this._rebuild());
    this._rebuild();
  }

  // ── DOM construction ──────────────────────────────────────────────────────

  _buildRoot() {
    const root = document.createElement('div');
    Object.assign(root.style, {
      position:        'fixed',
      top:             '0',
      left:            '0',
      width:           this._width + 'px',
      maxHeight:       '100vh',
      overflowY:       'auto',
      background:      '#1f1f1f',
      color:           '#eee',
      fontFamily:      'monospace',
      fontSize:        '12px',
      zIndex:          '1000',
      boxSizing:       'border-box',
      borderRight:     '1px solid #333',
      userSelect:      'none',
    });

    // Header bar
    const header = document.createElement('div');
    Object.assign(header.style, {
      padding:         '8px 10px',
      fontWeight:      'bold',
      fontSize:        '13px',
      background:      '#2a2a2a',
      borderBottom:    '1px solid #444',
      display:         'flex',
      justifyContent:  'space-between',
      alignItems:      'center',
      cursor:          'pointer',
    });
    header.textContent = 'Scene';

    // Collapse toggle
    const toggle = document.createElement('span');
    toggle.textContent = '▾';
    toggle.style.fontSize = '10px';
    header.appendChild(toggle);

    const body = document.createElement('div');
    body.id = 'scene-panel-body';

    header.addEventListener('click', () => {
      const collapsed = body.style.display === 'none';
      body.style.display = collapsed ? 'block' : 'none';
      toggle.textContent  = collapsed ? '▾' : '▸';
    });

    root.appendChild(header);
    root.appendChild(body);
    return root;
  }

  _rebuild() {
    const body = this._root.querySelector('#scene-panel-body');
    body.innerHTML = '';

    if (this._viewer.objects.size === 0) {
      const empty = document.createElement('div');
      Object.assign(empty.style, { padding: '8px 10px', color: '#666', fontStyle: 'italic' });
      empty.textContent = 'No structures registered.';
      body.appendChild(empty);
      return;
    }

    for (const [name, entry] of this._viewer.objects) {
      body.appendChild(this._buildRow(name, entry));
      for (const [childKey, child] of entry.children) {
        let row;
        switch (child.type) {
          case 'edges':  row = this._buildEdgeChildRow(name, childKey, child, entry);  break;
          case 'scalar': row = this._buildScalarChildRow(name, childKey, child, entry); break;
          case 'vector': row = this._buildVectorChildRow(name, childKey, child, entry); break;
          default:       row = this._buildGenericChildRow(name, childKey, child);
        }
        body.appendChild(row);
      }
    }
  }

  // ── Parent row ────────────────────────────────────────────────────────────

  _buildRow(name, entry) {
    const row = document.createElement('div');
    Object.assign(row.style, {
      borderBottom: '1px solid #2e2e2e',
      padding:      '6px 8px',
    });

    // ── Top line: eye + label + type badge + × ────────────────────────────
    const topLine = document.createElement('div');
    Object.assign(topLine.style, {
      display:    'flex',
      alignItems: 'center',
      gap:        '6px',
    });

    // Visibility checkbox (eye)
    const eye = document.createElement('input');
    eye.type    = 'checkbox';
    eye.checked = entry.visible;
    eye.title   = 'Toggle visibility';
    eye.style.cursor = 'pointer';
    eye.addEventListener('change', () => this._viewer.setEnabled(name, eye.checked));

    // Name label
    const label = document.createElement('span');
    label.textContent = name;
    label.style.flex  = '1';
    label.style.overflow = 'hidden';
    label.style.textOverflow = 'ellipsis';
    label.style.whiteSpace   = 'nowrap';
    label.title = name;

    // Type badge
    const badge = document.createElement('span');
    const badgeInfo = {
      surface_mesh:  { text: 'mesh',    bg: '#2a4a6a' },
      curve_network: { text: 'curve',   bg: '#3a3a2a' },
      point_cloud:   { text: 'points',  bg: '#2a4a3a' },
      vector_field:  { text: 'vectors', bg: '#3a2a4a' },
    }[entry.type] ?? { text: entry.type, bg: '#333' };
    badge.textContent = badgeInfo.text;
    Object.assign(badge.style, {
      fontSize:   '10px',
      padding:    '1px 5px',
      borderRadius: '3px',
      background: badgeInfo.bg,
      color:      '#bbb',
      flexShrink: '0',
    });

    // Remove button
    const removeBtn = document.createElement('button');
    removeBtn.textContent = '×';
    Object.assign(removeBtn.style, {
      background:  'none',
      border:      'none',
      color:       '#888',
      cursor:      'pointer',
      fontSize:    '14px',
      lineHeight:  '1',
      padding:     '0 2px',
    });
    removeBtn.title = 'Remove from scene';
    removeBtn.addEventListener('click', () => this._viewer.remove(name));

    topLine.append(eye, label, badge, removeBtn);
    row.appendChild(topLine);

    // ── Controls line ─────────────────────────────────────────────────────
    const ctrlLine = document.createElement('div');
    Object.assign(ctrlLine.style, {
      display:        'flex',
      alignItems:     'center',
      gap:            '8px',
      marginTop:      '5px',
      paddingLeft:    '20px',
    });

    // Color picker (all types)
    const colorPicker = this._colorPicker(entry.color, hex => {
      this._viewer.setColor(name, this._hexToRgb(hex));
    });
    ctrlLine.appendChild(colorPicker);

    // Opacity slider (surface meshes only)
    if (entry.type === 'surface_mesh') {
      const { wrap } = this._slider(
        'opacity', entry.opacity, 0, 1, 0.01,
        v => this._viewer.setOpacity(name, v)
      );
      ctrlLine.appendChild(wrap);
    }

    // Radius slider (point clouds only)
    if (entry.type === 'point_cloud') {
      const { wrap } = this._slider(
        'radius', entry.radius ?? 0.01, 0.001, 0.1, 0.001,
        v => this._viewer.setRadius(name, v)
      );
      ctrlLine.appendChild(wrap);
    }

    row.appendChild(ctrlLine);

    // ── Vector field: length + radius sliders — own rows ──────────────────
    if (entry.type === 'vector_field') {
      row.appendChild(this._subRow([
        this._label('length'),
        this._sliderOnly(entry.opts.length ?? 0.05, 0.001, 0.5, 0.001,
          v => this._viewer.setVectorLength(name, v)),
      ]));
      row.appendChild(this._subRow([
        this._label('radius'),
        this._sliderOnly(entry.opts.radius ?? 0.002, 0.0002, 0.05, 0.0002,
          v => this._viewer.setVectorRadius(name, v)),
      ]));
    }

    // ── Curve network: tube radius — own row ──────────────────────────────
    if (entry.type === 'curve_network') {
      row.appendChild(this._subRow([
        this._label('tube r'),
        this._sliderOnly(entry.radius ?? 0, 0, 0.02, 0.0005,
          v => this._viewer.setCurveRadius(name, v)),
      ]));
    }

    // Material dropdown (surface meshes only) — on its own line below
    if (entry.type === 'surface_mesh') {
      const matLine = document.createElement('div');
      Object.assign(matLine.style, {
        display:     'flex',
        alignItems:  'center',
        gap:         '6px',
        marginTop:   '4px',
        paddingLeft: '20px',
      });

      const matLabel = document.createElement('span');
      matLabel.textContent = 'shader';
      Object.assign(matLabel.style, { color: '#888', fontSize: '10px', flexShrink: '0' });

      const matSelect = document.createElement('select');
      Object.assign(matSelect.style, {
        flex:        '1',
        background:  '#2a2a2a',
        color:       '#eee',
        border:      '1px solid #444',
        borderRadius: '3px',
        fontSize:    '11px',
        padding:     '1px 3px',
        cursor:      'pointer',
      });
      for (const mName of Materials.list()) {
        const opt   = document.createElement('option');
        opt.value   = mName;
        opt.text    = mName;
        opt.selected = (mName === (entry.opts?.material ?? 'physical'));
        matSelect.appendChild(opt);
      }
      matSelect.addEventListener('change', e => {
        this._viewer.setMaterial(name, e.target.value);
      });

      matLine.append(matLabel, matSelect);
      row.appendChild(matLine);

      // Show edges checkbox
      const edgeLine = document.createElement('div');
      Object.assign(edgeLine.style, {
        display:     'flex',
        alignItems:  'center',
        gap:         '6px',
        marginTop:   '4px',
        paddingLeft: '20px',
      });

      const edgeChk = document.createElement('input');
      edgeChk.type    = 'checkbox';
      edgeChk.checked = entry.children.has('edges') && (entry.children.get('edges').visible ?? true);
      edgeChk.style.cursor = 'pointer';
      edgeChk.addEventListener('change', () => {
        this._viewer.toggleEdges(name, edgeChk.checked);
      });

      const edgeLabel = document.createElement('span');
      edgeLabel.textContent = 'show edges';
      Object.assign(edgeLabel.style, { color: '#888', fontSize: '10px' });

      edgeLine.append(edgeChk, edgeLabel);
      row.appendChild(edgeLine);

      // Index label checkboxes (surface mesh)
      row.appendChild(this._labelCheckbox(
        'vertex indices', entry.opts?.showVertexIndices ?? false,
        v => this._viewer.setLabelVisible(name, 'showVertexIndices', v)));
      row.appendChild(this._labelCheckbox(
        'face indices', entry.opts?.showFaceIndices ?? false,
        v => this._viewer.setLabelVisible(name, 'showFaceIndices', v)));
    }

    // Index label checkboxes (curve network)
    if (entry.type === 'curve_network') {
      row.appendChild(this._labelCheckbox(
        'vertex indices', entry.opts?.showVertexIndices ?? false,
        v => this._viewer.setLabelVisible(name, 'showVertexIndices', v)));
      row.appendChild(this._labelCheckbox(
        'edge indices', entry.opts?.showEdgeIndices ?? false,
        v => this._viewer.setLabelVisible(name, 'showEdgeIndices', v)));
    }

    return row;
  }

  /** Build a small checkbox + label row for toggling an index overlay. */
  _labelCheckbox(labelText, checked, onChange) {
    const line = document.createElement('div');
    Object.assign(line.style, {
      display:     'flex',
      alignItems:  'center',
      gap:         '6px',
      marginTop:   '4px',
      paddingLeft: '20px',
    });
    const chk = document.createElement('input');
    chk.type    = 'checkbox';
    chk.checked = checked;
    chk.style.cursor = 'pointer';
    chk.addEventListener('change', () => onChange(chk.checked));

    const lbl = document.createElement('span');
    lbl.textContent = labelText;
    Object.assign(lbl.style, { color: '#888', fontSize: '10px' });

    line.append(chk, lbl);
    return line;
  }

  // ── Child row skeleton ────────────────────────────────────────────────────

  /**
   * Build the shared head of a child row: container + connector + toggle + label + badge + ×.
   * Returns { row, topLine } for callers to append type-specific controls into `row`.
   * `toggleEl` is either a checkbox (edges) or a radio (scalar/vector), determined by caller.
   */
  _buildChildRowSkeleton(parentName, childKey, child, badgeText, badgeBg, toggleEl) {
    const row = document.createElement('div');
    Object.assign(row.style, {
      borderBottom:  '1px solid #2e2e2e',
      padding:       '4px 8px 4px 24px',
      display:       'flex',
      flexDirection: 'column',
      gap:           '4px',
      background:    '#1a1a1a',
    });

    const topLine = document.createElement('div');
    Object.assign(topLine.style, { display: 'flex', alignItems: 'center', gap: '6px' });

    const connector = document.createElement('span');
    connector.textContent = '└';
    Object.assign(connector.style, { color: '#555', fontSize: '11px', flexShrink: '0' });

    const label = document.createElement('span');
    label.textContent = childKey;
    label.style.flex  = '1';
    label.style.overflow    = 'hidden';
    label.style.textOverflow = 'ellipsis';
    label.style.whiteSpace   = 'nowrap';
    label.style.fontSize     = '11px';
    label.title = `${parentName} / ${childKey}`;

    const badge = document.createElement('span');
    badge.textContent = badgeText;
    Object.assign(badge.style, {
      fontSize: '10px', padding: '1px 5px', borderRadius: '3px',
      background: badgeBg, color: '#bbb', flexShrink: '0',
    });

    const removeBtn = document.createElement('button');
    removeBtn.textContent = '×';
    Object.assign(removeBtn.style, {
      background: 'none', border: 'none', color: '#888',
      cursor: 'pointer', fontSize: '14px', lineHeight: '1', padding: '0 2px',
    });
    removeBtn.addEventListener('click', () =>
      this._viewer.removeChild(parentName, childKey));

    topLine.append(connector, toggleEl, label, badge, removeBtn);
    row.appendChild(topLine);

    return { row, topLine };
  }

  // ── Edge child row ────────────────────────────────────────────────────────

  _buildEdgeChildRow(parentName, childKey, child, parentEntry) {
    const eye = document.createElement('input');
    eye.type    = 'checkbox';
    eye.checked = child.visible ?? true;
    eye.title   = 'Toggle visibility';
    eye.style.cursor = 'pointer';
    eye.addEventListener('change', () =>
      this._viewer.setChildVisible(parentName, childKey, eye.checked));

    const { row } = this._buildChildRowSkeleton(
      parentName, childKey, child, 'edges', '#3a2a2a', eye);

    // Color + tube radius sub-row
    const colorPicker = this._colorPicker(child.color ?? [0.1, 0.1, 0.1], hex => {
      this._viewer.setEdgeColor(parentName, this._hexToRgb(hex));
    });
    const subRow = this._subRow([
      colorPicker,
      this._label('tube r'),
      this._sliderOnly(child.radius ?? 0, 0, 0.02, 0.0005,
        v => this._viewer.setEdgeRadius(parentName, v)),
    ]);
    subRow.style.paddingLeft = '20px';
    row.appendChild(subRow);

    return row;
  }

  // ── Scalar child row ──────────────────────────────────────────────────────

  _buildScalarChildRow(parentName, childKey, child, parentEntry) {
    // Radio button — only one scalar active at a time per parent
    const radio = document.createElement('input');
    radio.type    = 'radio';
    radio.name    = `scalar-active-${parentName}`;
    radio.checked = (parentEntry.activeScalar === childKey);
    radio.title   = 'Make active scalar';
    radio.style.cursor = 'pointer';

    // Clicking an already-checked radio deactivates
    let lastChecked = radio.checked;
    radio.addEventListener('click', () => {
      if (lastChecked) {
        radio.checked = false;
        lastChecked = false;
        this._viewer.setActiveScalar(parentName, null);
      } else {
        lastChecked = true;
        this._viewer.setActiveScalar(parentName, childKey);
      }
    });
    radio.addEventListener('change', () => {
      if (radio.checked) {
        lastChecked = true;
        this._viewer.setActiveScalar(parentName, childKey);
      }
    });

    const { row } = this._buildChildRowSkeleton(
      parentName, childKey, child, 'scalar', '#2a4a3a', radio);

    // Histogram sub-section (collapsed by default)
    const { dataMin, dataMax } = child;
    const range = dataMax - dataMin || 1;
    const step  = range / 500;
    const fmt   = v => v.toExponential(3);

    const scalarHeader = document.createElement('div');
    Object.assign(scalarHeader.style, {
      display: 'flex', alignItems: 'center', gap: '6px',
      marginTop: '2px', paddingLeft: '20px',
      cursor: 'pointer', userSelect: 'none',
    });
    const scalarToggle = document.createElement('span');
    scalarToggle.textContent = '▸';
    Object.assign(scalarToggle.style, { fontSize: '10px', color: '#888', flexShrink: '0' });
    const scalarLabel = document.createElement('span');
    scalarLabel.textContent = `[${fmt(dataMin)}, ${fmt(dataMax)}]`;
    Object.assign(scalarLabel.style, { color: '#888', fontSize: '10px' });
    scalarHeader.append(scalarToggle, scalarLabel);

    const scalarBody = document.createElement('div');
    scalarBody.style.display = 'none';

    // Histogram canvases
    const W = this._width - 60;
    const H = 48;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    Object.assign(canvas.style, {
      display: 'block', marginLeft: '28px', marginTop: '4px',
      borderRadius: '3px', background: '#111',
    });

    const gradCanvas = document.createElement('canvas');
    gradCanvas.width = W; gradCanvas.height = 8;
    Object.assign(gradCanvas.style, {
      display: 'block', marginLeft: '28px', marginTop: '2px', borderRadius: '2px',
    });

    const drawHistogram = () =>
      child.drawHistogram(canvas, gradCanvas, this._viridis.bind(this));

    let scalarOpen = false;
    scalarHeader.addEventListener('click', () => {
      scalarOpen = !scalarOpen;
      scalarBody.style.display = scalarOpen ? 'block' : 'none';
      scalarToggle.textContent = scalarOpen ? '▾' : '▸';
      if (scalarOpen) drawHistogram();
    });

    scalarBody.appendChild(canvas);
    scalarBody.appendChild(gradCanvas);

    // vmin / vmax sliders
    const { wrap: vminWrap, input: vminInput, valDisplay: vminDisp } =
      this._slider('vmin', child.vmin, dataMin - range, dataMax, step, v => {
        child.vmin = v;
        this._viewer.setScalarRange(parentName, childKey, child.vmin, child.vmax);
        if (scalarOpen) drawHistogram();
      }, fmt);

    const { wrap: vmaxWrap, input: vmaxInput, valDisplay: vmaxDisp } =
      this._slider('vmax', child.vmax, dataMin, dataMax + range, step, v => {
        child.vmax = v;
        this._viewer.setScalarRange(parentName, childKey, child.vmin, child.vmax);
        if (scalarOpen) drawHistogram();
      }, fmt);

    // Reset button
    const resetBtn = document.createElement('button');
    resetBtn.textContent = 'reset';
    Object.assign(resetBtn.style, {
      background: '#2a2a2a', border: '1px solid #444',
      color: '#bbb', cursor: 'pointer', fontSize: '10px',
      borderRadius: '3px', padding: '1px 6px',
    });
    resetBtn.addEventListener('click', () => {
      child.vmin = dataMin; child.vmax = dataMax;
      vminInput.value = dataMin; vmaxInput.value = dataMax;
      vminDisp.textContent = fmt(dataMin);
      vmaxDisp.textContent = fmt(dataMax);
      this._viewer.setScalarRange(parentName, childKey, dataMin, dataMax);
      if (scalarOpen) drawHistogram();
    });

    scalarBody.appendChild(this._subRow([vminWrap]));
    scalarBody.appendChild(this._subRow([vmaxWrap]));
    scalarBody.appendChild(this._subRow([resetBtn]));

    row.appendChild(scalarHeader);
    row.appendChild(scalarBody);

    return row;
  }

  // ── Vector child row ──────────────────────────────────────────────────────

  _buildVectorChildRow(parentName, childKey, child, parentEntry) {
    // Radio button — only one vector active at a time per parent
    const radio = document.createElement('input');
    radio.type    = 'radio';
    radio.name    = `vector-active-${parentName}`;
    radio.checked = (parentEntry.activeVector === childKey);
    radio.title   = 'Make active vector';
    radio.style.cursor = 'pointer';

    // Clicking an already-checked radio deactivates
    let lastChecked = radio.checked;
    radio.addEventListener('click', () => {
      if (lastChecked) {
        radio.checked = false;
        lastChecked = false;
        this._viewer.setActiveVector(parentName, null);
      } else {
        lastChecked = true;
        this._viewer.setActiveVector(parentName, childKey);
      }
    });
    radio.addEventListener('change', () => {
      if (radio.checked) {
        lastChecked = true;
        this._viewer.setActiveVector(parentName, childKey);
      }
    });

    const { row } = this._buildChildRowSkeleton(
      parentName, childKey, child, 'vector', '#3a2a4a', radio);

    // Color + length + radius sub-row
    const colorPicker = this._colorPicker(child.color ?? [0.2, 0.8, 0.4], hex => {
      this._viewer.setVectorChildColor(parentName, childKey, this._hexToRgb(hex));
    });
    const subRow = this._subRow([
      colorPicker,
      this._label('length'),
      this._sliderOnly(child.length ?? 0.05, 0.001, 0.5, 0.001,
        v => this._viewer.setChildVectorLength(parentName, childKey, v)),
    ]);
    subRow.style.paddingLeft = '20px';
    row.appendChild(subRow);

    const radiusRow = this._subRow([
      this._label('radius'),
      this._sliderOnly(child.radius ?? 0.002, 0.0002, 0.05, 0.0002,
        v => this._viewer.setChildVectorRadius(parentName, childKey, v)),
    ]);
    radiusRow.style.paddingLeft = '20px';
    row.appendChild(radiusRow);

    return row;
  }

  // ── Generic child row (fallback) ──────────────────────────────────────────

  _buildGenericChildRow(parentName, childKey, child) {
    const eye = document.createElement('input');
    eye.type    = 'checkbox';
    eye.checked = child.visible ?? true;
    eye.style.cursor = 'pointer';
    eye.addEventListener('change', () =>
      this._viewer.setChildVisible(parentName, childKey, eye.checked));

    const { row } = this._buildChildRowSkeleton(
      parentName, childKey, child, child.type, '#333', eye);
    return row;
  }

  // ── Widget helpers ────────────────────────────────────────────────────────

  /** Compact colour swatch that opens a colour picker on click. */
  _colorPicker(rgb, onChange) {
    const wrap  = document.createElement('label');
    wrap.title  = 'Color';
    Object.assign(wrap.style, { cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' });

    const swatch = document.createElement('span');
    Object.assign(swatch.style, {
      display:      'inline-block',
      width:        '16px',
      height:       '16px',
      borderRadius: '3px',
      border:       '1px solid #555',
      background:   this._rgbToHex(rgb),
      flexShrink:   '0',
    });

    const input  = document.createElement('input');
    input.type   = 'color';
    input.value  = this._rgbToHex(rgb);
    input.style.display = 'none';    // hide native input, use swatch as trigger
    input.addEventListener('input', e => {
      swatch.style.background = e.target.value;
      onChange(e.target.value);
    });

    wrap.append(swatch, input);
    swatch.addEventListener('click', () => input.click());
    return wrap;
  }

  /** Compact labelled range slider. Returns { wrap, input, valDisplay }.
   *  Pass a custom `fmtFn` to override the value display format. */
  _slider(labelText, value, min, max, step, onChange, fmtFn = null) {
    const decimals = step < 0.01 ? 4 : step < 0.1 ? 3 : 2;
    const fmt = fmtFn ?? (v => v.toFixed(decimals));

    const wrap  = document.createElement('label');
    Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '4px', flex: '1' });

    const lbl = document.createElement('span');
    lbl.textContent = labelText;
    lbl.style.color = '#888';
    lbl.style.fontSize = '10px';
    lbl.style.flexShrink = '0';

    const valDisplay = document.createElement('span');
    valDisplay.textContent = fmt(value);
    valDisplay.style.color  = '#bbb';
    valDisplay.style.fontSize = '10px';
    valDisplay.style.minWidth = '56px';
    valDisplay.style.textAlign = 'right';
    valDisplay.style.flexShrink = '0';

    const input = document.createElement('input');
    input.type  = 'range';
    input.min   = min;
    input.max   = max;
    input.step  = step;
    input.value = value;
    Object.assign(input.style, { flex: '1', cursor: 'pointer', accentColor: '#4a9eff' });
    input.addEventListener('input', e => {
      const v = parseFloat(e.target.value);
      valDisplay.textContent = fmt(v);
      onChange(v);
    });

    wrap.append(lbl, input, valDisplay);
    return { wrap, input, valDisplay };
  }

  /** A padded flex sub-row for secondary controls. */
  _subRow(children) {
    const div = document.createElement('div');
    Object.assign(div.style, {
      display:     'flex',
      alignItems:  'center',
      gap:         '6px',
      marginTop:   '4px',
      paddingLeft: '20px',
    });
    children.forEach(c => div.appendChild(c));
    return div;
  }

  /** Tiny muted label span. */
  _label(text) {
    const span = document.createElement('span');
    span.textContent = text;
    Object.assign(span.style, { color: '#888', fontSize: '10px', flexShrink: '0' });
    return span;
  }

  /** Slider + value display only (no outer label), fills available width. */
  _sliderOnly(value, min, max, step, onChange) {
    const decimals = step < 0.01 ? 4 : step < 0.1 ? 3 : 2;
    const fmt = v => v.toFixed(decimals);

    const wrap = document.createElement('div');
    Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '4px', flex: '1' });

    const input = document.createElement('input');
    input.type  = 'range';
    input.min   = min;
    input.max   = max;
    input.step  = step;
    input.value = value;
    Object.assign(input.style, { flex: '1', cursor: 'pointer', accentColor: '#4a9eff' });

    const valDisplay = document.createElement('span');
    valDisplay.textContent = fmt(value);
    Object.assign(valDisplay.style, {
      color: '#bbb', fontSize: '10px', minWidth: '36px',
      textAlign: 'right', flexShrink: '0',
    });

    input.addEventListener('input', e => {
      const v = parseFloat(e.target.value);
      valDisplay.textContent = fmt(v);
      onChange(v);
    });

    wrap.append(input, valDisplay);
    return wrap;
  }

  // ── Color utilities ───────────────────────────────────────────────────────

  _viridis(t) {
    const s = [[0.267,0.005,0.329],[0.190,0.407,0.574],[0.128,0.566,0.551],
               [0.208,0.718,0.473],[0.993,0.906,0.144]];
    const i = Math.min(Math.floor(t*(s.length-1)), s.length-2);
    const f = t*(s.length-1)-i;
    return s[i].map((c,k) => c + f*(s[i+1][k]-c));
  }

  _rgbToHex([r, g, b]) {
    const h = v => Math.round(v * 255).toString(16).padStart(2, '0');
    return `#${h(r)}${h(g)}${h(b)}`;
  }

  _hexToRgb(hex) {
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    return [r, g, b];
  }
}
