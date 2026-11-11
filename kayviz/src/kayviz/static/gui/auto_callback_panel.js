/**
 * auto_callback_panel.js — Schema-driven panel for CallbackApp.
 *
 * Renders sliders, dropdowns, checkboxes, text fields and buttons from the widget
 * schema returned by /api/<app>/schema, grouped by their Python `header()`
 * sections (buttons included).
 *
 * Every widget change / button click sends
 *   { action: "_callback", trigger: "<key or label>", state: { ...all values },
 *     changed: [keys edited since the last message], button: <is a click> }
 * Python applies every key in `changed`, so editing two widgets quickly does not
 * lose the first edit. After each callback the server answers with
 *   { action: "gui_state", values: {...}, schema?: [...] }
 * — the widget values as Python left them (a "Reset" button moves the sliders) and,
 * when widgets appeared or went, the new layout (the panel is rebuilt).
 */

import { Panel } from './panel.js';

const DEBOUNCE_MS = 120;

export default class AutoCallbackPanel extends Panel {
  /**
   * @param {WSClient}  ws
   * @param {object[]}  schema   — widget descriptors from /api/<app>/schema
   * @param {string}    title    — panel window title (default "Controls")
   */
  constructor(ws, schema, title = 'Controls') {
    super(title, { width: 320 });
    this._ws     = ws;
    this._state  = {};
    this._dirty  = new Set();     // keys edited since the last message
    this._timer  = null;
    this._last   = null;          // trigger of the pending message
    this._buildPanel(schema);
    ws.onMessage(msg => this._onServer(msg));
  }

  // ── Messages ──────────────────────────────────────────────────────────────

  _send(trigger, button = false) {
    clearTimeout(this._timer);
    this._timer = null;
    this._ws.send('_callback', {
      trigger, button,
      state:   { ...this._state },
      changed: [...this._dirty],
    });
    this._dirty.clear();
  }

  _edited(key) {
    this._dirty.add(key);
    this._last = key;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this._send(this._last), DEBOUNCE_MS);
  }

  _onServer(msg) {
    if (msg.action !== 'gui_state') return;
    if (msg.schema) {
      this._rebuild(msg.schema);
    }
    let moved = false;
    for (const [key, value] of Object.entries(msg.values ?? {})) {
      // a widget being edited keeps the user's value (its message is on the way)
      if (this._dirty.has(key) || this._state[key] === value) continue;
      this._state[key] = value;
      moved = true;
    }
    if (moved) this.refresh();
  }

  // ── Layout ────────────────────────────────────────────────────────────────

  _rebuild(schema) {
    for (const name of Object.keys(this._folders)) this.removeSection(name);
    this._buildPanel(schema);
  }

  _buildPanel(schema) {
    // Seed state from schema defaults (kept for widgets that already exist)
    for (const f of schema) {
      if (f.kind !== 'button' && this._state[f.key] === undefined) {
        this._state[f.key] = f.default ?? null;
      }
    }

    // Group widgets, buttons included, by section label (Python `header()`)
    const sections = {};   // sectionLabel → [descriptor]
    const order    = [];
    for (const f of schema) {
      const sec = f.section ?? (f.kind === 'button' ? 'Actions' : 'General');
      if (!sections[sec]) { sections[sec] = []; order.push(sec); }
      sections[sec].push(f);
    }

    for (const secLabel of order) {
      const folder = this.addSection(secLabel, true);
      for (const f of sections[secLabel]) {
        let ctrl;
        switch (f.kind) {
          case 'slider':
          case 'int_slider':
            ctrl = folder.add(this._state, f.key, f.min, f.max, f.step).name(f.label);
            break;
          case 'dropdown':
            ctrl = folder.add(this._state, f.key, f.options).name(f.label);
            break;
          case 'checkbox':
          case 'text':
            ctrl = folder.add(this._state, f.key).name(f.label);
            break;
          case 'button': {
            const proxy = { fn: () => this._send(f.label, true) };   // flushes pending edits
            folder.add(proxy, 'fn').name(f.label);
            continue;
          }
          default:
            continue;
        }
        ctrl.onChange(() => this._edited(f.key));
      }
    }
  }
}
