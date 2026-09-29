/**
 * script_panel.js — Minimal panel for the scripting / notebook API.
 *
 * No state widgets (the schema is always empty for ScriptApp).
 * Provides:
 *   - A live object count in the title.
 *   - A "Clear scene" button that POSTs to /api/script/push with action=clear.
 *
 * Handles the server-sent "clear" action to reset the viewer locally.
 */

import { Panel } from './panel.js';

export default class ScriptPanel extends Panel {
  /**
   * @param {WSClient} ws
   * @param {Array}    _schema  — always empty for ScriptApp; ignored
   */
  constructor(ws, _schema = []) {
    super('Script session', { width: 260 });
    this._ws         = ws;
    this._objCount   = 0;
    this._countLabel = null;
    this._build();
    ws.onMessage(msg => this.onMessage(msg));
  }

  _build() {
    const state = { count: 'No objects yet' };

    // Read-only status line showing current object count
    this._countLabel = this.gui.add(state, 'count').name('Scene').disable();
    this._countLabel._state = state;

    this.gui.add({ clear: () => this._clearScene() }, 'clear').name('Clear scene');
  }

  // Called by app_loader after initial /load response
  onLoad(data) {
    const n = (data.objects ?? []).length;
    this._setCount(n);
  }

  // Update count whenever the server pushes a scene_update
  onMessage(msg) {
    if (msg.action === 'scene_update') {
      this._objCount += (msg.objects ?? []).length;
      this._setCount(this._objCount);
    } else if (msg.action === 'clear') {
      this._objCount = 0;
      this._setCount(0);
    }
  }

  _setCount(n) {
    const label = n === 0 ? 'No objects' : `${n} object${n === 1 ? '' : 's'}`;
    if (this._countLabel) {
      this._countLabel._state.count = label;
      this._countLabel.updateDisplay();
    }
  }

  async _clearScene() {
    try {
      await fetch('/api/script/push', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ action: 'clear' }),
      });
      // The server broadcasts "clear" back over WS; onMessage handles viewer reset.
    } catch (err) {
      console.error('ScriptPanel: clear failed', err);
    }
  }
}
