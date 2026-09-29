/**
 * auto_callback_panel.js — Schema-driven panel for CallbackApp.
 *
 * Renders sliders, dropdowns, checkboxes from the widget schema returned by
 * /api/<app>/schema (same format as AutoPanel), and adds a lil-gui button for
 * each "button" entry in the schema.
 *
 * Every widget change / button click sends:
 *   { action: "_callback", trigger: "<key or label>", state: { ...all values } }
 *
 * No custom JS required — the panel is fully driven by the Python callback's
 * widget declarations.
 */

import { Panel } from './panel.js';

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
    this._schema = schema;

    this._buildPanel(schema);
  }

  _buildPanel(schema) {
    // Seed state from schema defaults
    for (const f of schema) {
      if (f.kind !== 'button' && this._state[f.key] === undefined) {
        this._state[f.key] = f.default ?? null;
      }
    }

    // Group non-button widgets by section label (from Python `header()` ctx)
    const sections = {};   // sectionLabel → [{descriptor}]
    const order    = [];   // insertion order for sections
    const buttons  = [];   // button descriptors (rendered at bottom)

    for (const f of schema) {
      if (f.kind === 'button') {
        buttons.push(f);
        continue;
      }
      const sec = f.section ?? 'General';
      if (!sections[sec]) { sections[sec] = []; order.push(sec); }
      sections[sec].push(f);
    }

    let debounceTimer = null;
    const sendTrigger = (triggerKey) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        this._ws.send('_callback', {
          trigger: triggerKey,
          state:   { ...this._state },
        });
      }, 120);
    };

    // Render widget sections
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
            ctrl = folder.add(this._state, f.key).name(f.label);
            break;
          case 'text':
            ctrl = folder.add(this._state, f.key).name(f.label);
            break;
          default:
            continue;
        }
        ctrl.onChange(() => sendTrigger(f.key));
      }
    }

    // Render buttons
    if (buttons.length > 0) {
      const btnFolder = this.addSection('Actions', true);
      for (const f of buttons) {
        const proxy = {
          fn: () => {
            this._ws.send('_callback', {
              trigger: f.label,
              state:   { ...this._state },
            });
          },
        };
        btnFolder.add(proxy, 'fn').name(f.label);
      }
    }
  }
}
