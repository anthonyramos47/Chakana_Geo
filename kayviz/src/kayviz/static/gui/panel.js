/**
 * panel.js — Base panel class.
 *
 * Wraps lil-gui and mirrors the psim window pattern.
 * Every GUI panel in the app extends this class.
 *
 * Quick reference (see THREEJS_MIGRATION.md Part 5 for the full table):
 *
 *   this.addSection('Title')                → psim.CollapsingHeader()
 *   f.add(state, 'key', min, max, step)     → psim.SliderFloat / SliderInt
 *   f.add(state, 'boolKey')                 → psim.Checkbox
 *   f.add(state, 'strKey')                  → psim.InputText
 *   f.add({fn: ()=>…}, 'fn').name('Label')  → psim.Button
 *   f.add(state, 'key', ['a','b'])          → psim.RadioButton (as dropdown)
 *   f.add(state, 'key').disable()           → psim.Text (read-only)
 *   f.addFolder('──────')                   → psim.Separator
 *   panel.setVisible(false)                 → hide entire window
 */

import GUI from 'lil-gui';

export class Panel {
  /**
   * @param {string} title   — window title bar text
   * @param {object} opts    — { width: number }
   */
  constructor(title, opts = {}) {
    this.gui      = new GUI({ title, width: opts.width ?? 300 });
    this._folders = {};   // name → GUI folder
  }

  /**
   * Add a collapsible section.  Mirrors psim.CollapsingHeader().
   *
   * @param {string}  name  — section title
   * @param {boolean} open  — true = expanded by default
   * @returns {GUI}   lil-gui folder — call .add() on this to add controls
   *
   * Example:
   *   const f = this.addSection('Weights');
   *   f.add(state, 'lr', 0, 1, 0.01).name('Learning rate');
   */
  addSection(name, open = true) {
    const folder = this.gui.addFolder(name);
    if (!open) folder.close();
    this._folders[name] = folder;
    return folder;
  }

  /**
   * Remove a section by name (destroys its controllers).
   */
  removeSection(name) {
    const f = this._folders[name];
    if (f) { f.destroy(); delete this._folders[name]; }
  }

  /**
   * Show or hide the entire panel window.
   */
  setVisible(visible) {
    this.gui.domElement.style.display = visible ? '' : 'none';
  }

  /**
   * Force all controllers to re-read their values from state.
   * Call this after the server updates state fields.
   */
  refresh() {
    this.gui.controllersRecursive().forEach(c => c.updateDisplay());
  }

  destroy() { this.gui.destroy(); }
}
