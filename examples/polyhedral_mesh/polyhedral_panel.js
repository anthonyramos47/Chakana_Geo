/**
 * polyhedral_panel.js — Weight sliders + action buttons for the
 * Polyhedral Mesh Optimization GUI.
 *
 * Widgets are built explicitly from the @gui_state schema (rather than
 * relying on AutoPanel) so this file can interleave them with the
 * optimization action buttons in one panel.
 */

import { Panel } from 'kayviz/gui/panel.js';

export class PolyhedralPanel extends Panel {
  constructor(ws, schema) {
    super('Polyhedral Mesh', { width: 340 });
    this.ws      = ws;
    this.state   = {};
    this._schema = schema ?? [];

    for (const f of this._schema) {
      this.state[f.key] = f.default ?? null;
    }

    this._debounceTimer = null;
    this._scheduleSync  = () => {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = setTimeout(() => {
        ws.send('_set_state', { state: { ...this.state } });
      }, 120);
    };

    this._addSchemaCtrl(this.gui, 'experiment_name', 'Experiment Name');

    const weights = this.addSection('Optimization Weights');
    this._addSchemaCtrl(weights, 'planarity_w',   'Planarity Weight');
    this._addSchemaCtrl(weights, 'cyclicity_w',   'Cyclicity Weight');
    this._addSchemaCtrl(weights, 'conical_w',     'Conical Weight');
    this._addSchemaCtrl(weights, 'fairness_v_w',  'Fairness V');
    this._addSchemaCtrl(weights, 'fairness_nf_w', 'Fairness N');
    this._addSchemaCtrl(weights, 'damp_iteration','Fairness Damp Iter');

    const opt = this.addSection('Optimization');
    this._addSchemaCtrl(opt, 'max_iterations', 'Max Iterations');
    this._addSchemaCtrl(opt, 'show_circles',   'Show Circumcircles');
    opt.add({ fn: () => ws.send('setup_optimizer', {}) }, 'fn').name('Initialize Optimizer');
    opt.add({ fn: () => ws.send('step',            {}) }, 'fn').name('Step');
    opt.add({ fn: () => ws.send('run',             {}) }, 'fn').name('Run All');
    opt.add({ fn: () => ws.send('stop',            {}) }, 'fn').name('Stop');
    opt.add({ fn: () => ws.send('reset',           {}) }, 'fn').name('Reset');
    opt.add({ fn: () => ws.send('update_weights',  { ...this.state }) }, 'fn').name('Apply Weights');

    const exp = this.addSection('Export');
    exp.add({ fn: () => ws.send('export_obj', {}) }, 'fn').name('Export OBJ');
  }

  /** Add a control using schema metadata (range, step, options). */
  _addSchemaCtrl(target, key, label) {
    const f = this._schema.find(s => s.key === key);
    if (!f) return;

    const state = this.state;
    let ctrl;
    switch (f.kind) {
      case 'slider':
      case 'int_slider':
        ctrl = target.add(state, key, f.min, f.max, f.step).name(label);
        break;
      case 'dropdown':
        ctrl = target.add(state, key, f.options).name(label);
        break;
      case 'checkbox':
      case 'text':
        ctrl = target.add(state, key).name(label);
        break;
      default:
        return;
    }
    ctrl.onChange(this._scheduleSync);
  }
}

export default PolyhedralPanel;
