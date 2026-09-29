/**
 * auto_panel.js — Schema-driven widget builder.
 *
 * Adds lil-gui controls for every field in a server widget schema into a
 * given lil-gui GUI instance (or folder).  Does NOT create its own panel
 * window — it is always embedded inside another panel.
 *
 * Usage inside a Panel subclass:
 *   import { buildSchemaWidgets } from './auto_panel.js';
 *
 *   buildSchemaWidgets(this.gui, schema, state, ws);
 *   // or into a specific folder:
 *   buildSchemaWidgets(folder, schema, state, ws);
 */

/**
 * Populate `target` (a lil-gui GUI or folder) with controls derived from
 * `schema`.  Mutates `state` with the defaults and wires onChange → debounced
 * `_set_state` push over `ws`.
 *
 * @param {GUI}       target   — lil-gui GUI or folder to add sections into
 * @param {object[]}  schema   — widget descriptor array from /api/<app>/schema
 * @param {object}    state    — plain object; fields are set from schema defaults
 * @param {WSClient}  ws       — WebSocket client
 * @param {number}    [debounceMs=120]
 */
export function buildSchemaWidgets(target, schema, state, ws, debounceMs = 120) {
  // Initialise state defaults
  for (const f of schema) {
    if (state[f.key] === undefined) state[f.key] = f.default ?? null;
  }

  // Group by prefix (everything before first underscore)
  const sections = {};
  const order    = [];
  for (const f of schema) {
    const key = _sectionKey(f.key);
    if (!sections[key]) { sections[key] = []; order.push(key); }
    sections[key].push(f);
  }

  let debounceTimer = null;
  const scheduleSync = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      ws.send('_set_state', { state: { ...state } });
    }, debounceMs);
  };

  for (const key of order) {
    const folder = target.addFolder(_sectionLabel(key));
    folder.close();
    for (const f of sections[key]) {
      let ctrl;
      switch (f.kind) {
        case 'slider':
        case 'int_slider':
          ctrl = folder.add(state, f.key, f.min, f.max, f.step).name(f.label);
          break;
        case 'dropdown':
          ctrl = folder.add(state, f.key, f.options).name(f.label);
          break;
        case 'checkbox':
          ctrl = folder.add(state, f.key).name(f.label);
          break;
        case 'text':
          ctrl = folder.add(state, f.key).name(f.label);
          break;
        default:
          continue;
      }
      ctrl.onChange(scheduleSync);
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _sectionKey(key) {
  const idx = key.indexOf('_');
  return idx > 0 ? key.slice(0, idx) : 'general';
}

function _sectionLabel(key) {
  return key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' ');
}
