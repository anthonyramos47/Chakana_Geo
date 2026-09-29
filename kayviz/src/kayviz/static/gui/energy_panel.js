/**
 * energy_panel.js — Live energy convergence plot.
 *
 * Draws a line chart on an HTML <canvas> showing energy vs. iteration.
 * Fed by scene_update messages from the WebSocket server.
 *
 * Usage (in a custom app panel or app_loader.js):
 *
 *   import { EnergyPanel } from './gui/energy_panel.js';
 *   const energyPanel = new EnergyPanel(ws);
 *
 * The panel floats at the bottom-right of the viewport.
 * Call energyPanel.reset() to clear the history (e.g. on re-initialization).
 */

export class EnergyPanel {
  /**
   * @param {WSClient} ws       — WebSocket client; subscribes to onMessage
   * @param {object}   [opts]   — { width, height, maxPoints, position }
   *   position: 'bottom-right' (default) | 'bottom-left' | 'top-right' | 'top-left'
   */
  constructor(ws, opts = {}) {
    this._width     = opts.width     ?? 320;
    this._height    = opts.height    ?? 180;
    this._maxPoints = opts.maxPoints ?? 500;
    this._position  = opts.position  ?? 'bottom-right';

    this._history   = [];   // { iter, energy }
    this._visible   = true;
    this._logScale  = false;

    this._root   = this._buildRoot();
    this._canvas = this._root.querySelector('canvas');
    this._ctx    = this._canvas.getContext('2d');

    document.body.appendChild(this._root);

    ws.onMessage(data => {
      if (data.action === 'scene_update' &&
          data.energy != null &&
          data.iteration != null) {
        this._push(data.iteration, data.energy);
      }
      if (data.action === 'optimization_complete') {
        this._drawFinalMarker();
      }
      // Clear history whenever the optimizer is (re-)initialized so the
      // plot starts fresh for the new setup.
      if (data.action === 'setup_done') {
        this.reset();
      }
    });

    this._draw();
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  reset() {
    this._history = [];
    this._draw();
  }

  setVisible(v) {
    this._visible = v;
    this._root.style.display = v ? 'block' : 'none';
  }

  // ── DOM construction ───────────────────────────────────────────────────────

  _buildRoot() {
    const root = document.createElement('div');
    const posStyle = this._positionStyle();
    Object.assign(root.style, {
      position:     'fixed',
      ...posStyle,
      width:        this._width + 'px',
      background:   '#1a1a1a',
      border:       '1px solid #333',
      borderRadius: '4px',
      zIndex:       '1000',
      fontFamily:   'monospace',
      fontSize:     '11px',
      color:        '#ccc',
      userSelect:   'none',
    });

    // Header bar
    const header = document.createElement('div');
    Object.assign(header.style, {
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'space-between',
      padding:        '4px 8px',
      background:     '#2a2a2a',
      borderBottom:   '1px solid #333',
      cursor:         'pointer',
    });

    const title = document.createElement('span');
    title.textContent = 'Energy';
    title.style.fontWeight = 'bold';

    // Log scale toggle
    const logBtn = document.createElement('button');
    logBtn.textContent = 'log';
    Object.assign(logBtn.style, {
      background: '#333', border: '1px solid #555', color: '#aaa',
      fontSize: '10px', padding: '1px 5px', borderRadius: '3px', cursor: 'pointer',
    });
    logBtn.title = 'Toggle log scale';
    logBtn.addEventListener('click', e => {
      e.stopPropagation();
      this._logScale = !this._logScale;
      logBtn.style.background = this._logScale ? '#2a5a2a' : '#333';
      this._draw();
    });

    // Reset button
    const resetBtn = document.createElement('button');
    resetBtn.textContent = '↺';
    Object.assign(resetBtn.style, {
      background: 'none', border: 'none', color: '#888',
      fontSize: '13px', cursor: 'pointer', padding: '0 2px',
    });
    resetBtn.title = 'Clear history';
    resetBtn.addEventListener('click', e => { e.stopPropagation(); this.reset(); });

    // Collapse toggle
    const collapseBtn = document.createElement('span');
    collapseBtn.textContent = '▾';
    collapseBtn.style.fontSize = '10px';
    collapseBtn.style.cursor   = 'pointer';

    const canvasWrap = document.createElement('div');
    header.addEventListener('click', () => {
      const collapsed = canvasWrap.style.display === 'none';
      canvasWrap.style.display = collapsed ? 'block' : 'none';
      collapseBtn.textContent  = collapsed ? '▾' : '▸';
    });

    header.append(title, logBtn, resetBtn, collapseBtn);
    root.appendChild(header);

    // Canvas
    const canvas = document.createElement('canvas');
    canvas.width  = this._width;
    canvas.height = this._height;
    Object.assign(canvas.style, { display: 'block' });
    canvasWrap.appendChild(canvas);
    root.appendChild(canvasWrap);

    return root;
  }

  _positionStyle() {
    const margin = '12px';
    switch (this._position) {
      case 'bottom-left':  return { bottom: margin, left:  margin };
      case 'top-right':    return { top:    margin, right: margin };
      case 'top-left':     return { top:    margin, left:  margin };
      default:             return { bottom: margin, right: margin };
    }
  }

  // ── Data ───────────────────────────────────────────────────────────────────

  _push(iter, energy) {
    // Keep only unique iterations; server may resend same iter on re-runs
    if (this._history.length > 0 &&
        this._history[this._history.length - 1].iter === iter &&
        iter !== 0) {
      // New run starting — reset history if iteration resets
    }
    if (iter === 0 || (this._history.length > 0 &&
        iter < this._history[this._history.length - 1].iter)) {
      this._history = [];   // optimization restarted
    }
    this._history.push({ iter, energy });
    if (this._history.length > this._maxPoints) {
      this._history.shift();
    }
    this._draw();
  }

  // ── Drawing ────────────────────────────────────────────────────────────────

  _draw() {
    const ctx = this._ctx;
    const W   = this._width;
    const H   = this._height;
    const PAD = { top: 12, right: 12, bottom: 28, left: 52 };

    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(0, 0, W, H);

    const data = this._history;

    if (data.length < 2) {
      ctx.fillStyle = '#555';
      ctx.font      = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for data…', W / 2, H / 2);
      return;
    }

    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top  - PAD.bottom;

    // Value ranges
    const minIter = data[0].iter;
    const maxIter = data[data.length - 1].iter;
    const energies = data.map(d => d.energy).filter(e => isFinite(e) && e > 0);
    if (energies.length === 0) return;

    let minE = Math.min(...energies);
    let maxE = Math.max(...energies);
    if (minE === maxE) { minE *= 0.9; maxE *= 1.1; }

    const toLogSafe = v => Math.log10(Math.max(v, 1e-12));
    const minY = this._logScale ? toLogSafe(minE) : minE;
    const maxY = this._logScale ? toLogSafe(maxE) : maxE;
    const rangeY = maxY - minY || 1;
    const rangeX = maxIter - minIter || 1;

    const px = iter  => PAD.left + ((iter  - minIter) / rangeX) * plotW;
    const py = energy => {
      const v = this._logScale ? toLogSafe(energy) : energy;
      return PAD.top + plotH - ((v - minY) / rangeY) * plotH;
    };

    // Grid lines
    ctx.strokeStyle = '#2a2a2a';
    ctx.lineWidth   = 1;
    const nGridY = 4;
    for (let i = 0; i <= nGridY; i++) {
      const y = PAD.top + (i / nGridY) * plotH;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + plotW, y);
      ctx.stroke();
    }

    // Axes
    ctx.strokeStyle = '#444';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.left, PAD.top);
    ctx.lineTo(PAD.left, PAD.top + plotH);
    ctx.lineTo(PAD.left + plotW, PAD.top + plotH);
    ctx.stroke();

    // Y axis labels
    ctx.fillStyle  = '#666';
    ctx.font       = '9px monospace';
    ctx.textAlign  = 'right';
    for (let i = 0; i <= nGridY; i++) {
      const frac  = i / nGridY;
      const val   = this._logScale
        ? Math.pow(10, minY + frac * rangeY)
        : minE + frac * rangeY;
      const label = val < 0.001 ? val.toExponential(1) : val.toPrecision(3);
      const y     = PAD.top + plotH - frac * plotH;
      ctx.fillText(label, PAD.left - 4, y + 3);
    }

    // X axis labels
    ctx.textAlign = 'center';
    const nGridX  = Math.min(5, data.length - 1);
    for (let i = 0; i <= nGridX; i++) {
      const iter  = minIter + Math.round((i / nGridX) * rangeX);
      const x     = px(iter);
      ctx.fillText(iter, x, PAD.top + plotH + 12);
    }

    // Axis titles
    ctx.fillStyle  = '#888';
    ctx.font       = '9px monospace';
    ctx.textAlign  = 'center';
    ctx.fillText('iteration', PAD.left + plotW / 2, H - 4);

    ctx.save();
    ctx.translate(10, PAD.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(this._logScale ? 'log₁₀ E' : 'energy', 0, 0);
    ctx.restore();

    // Energy curve — gradient from orange to green
    const grad = ctx.createLinearGradient(PAD.left, 0, PAD.left + plotW, 0);
    grad.addColorStop(0, '#e06020');
    grad.addColorStop(1, '#40b060');

    ctx.beginPath();
    ctx.strokeStyle = grad;
    ctx.lineWidth   = 1.5;
    let first = true;
    for (const d of data) {
      if (!isFinite(d.energy) || d.energy <= 0) continue;
      const x = px(d.iter);
      const y = py(d.energy);
      if (first) { ctx.moveTo(x, y); first = false; }
      else        { ctx.lineTo(x, y); }
    }
    ctx.stroke();

    // Last value label
    const last = data[data.length - 1];
    if (isFinite(last.energy) && last.energy > 0) {
      ctx.fillStyle  = '#c0e080';
      ctx.font       = '10px monospace';
      ctx.textAlign  = 'left';
      const label    = last.energy < 0.001
        ? last.energy.toExponential(2)
        : last.energy.toPrecision(4);
      ctx.fillText(label, px(last.iter) + 4, py(last.energy) - 4);
    }
  }

  _drawFinalMarker() {
    if (this._history.length === 0) return;
    const ctx  = this._ctx;
    const last = this._history[this._history.length - 1];
    const PAD  = { top: 12, right: 12, bottom: 28, left: 52 };
    const plotW = this._width  - PAD.left - PAD.right;
    const plotH = this._height - PAD.top  - PAD.bottom;
    const data  = this._history;

    const minIter = data[0].iter;
    const maxIter = data[data.length - 1].iter;
    const rangeX  = maxIter - minIter || 1;
    const x = PAD.left + ((last.iter - minIter) / rangeX) * plotW;

    ctx.strokeStyle = '#6090ff';
    ctx.lineWidth   = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, PAD.top);
    ctx.lineTo(x, PAD.top + plotH);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}
