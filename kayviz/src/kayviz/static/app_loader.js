/**
 * app_loader.js — App bootstrap layer.
 *
 * Reads ?app=<name> and ?mesh=<name> from the URL (without ?app= the
 * server's default app is used), fetches the app schema, loads the app's
 * custom panel from /api/<app>/panel.js when it ships one (otherwise the
 * schema-driven AutoCallbackPanel), and passes schema + ws to it so the
 * panel builds everything in one window.
 *
 * Every page also subscribes to the shared "script" channel, so geometry
 * pushed with kayviz.register_* from anywhere in the Python process shows up
 * whatever app is open.
 */

import { Viewer }      from './viewer.js';
import { WSClient }    from './ws.js';
import { ScenePanel }  from './gui/scene_panel.js';
import { EnergyPanel } from './gui/energy_panel.js';

const statusEl = document.getElementById('status');
const params   = new URLSearchParams(window.location.search);
const meshName = params.get('mesh') ?? '';

let appName = params.get('app');
if (!appName) {
  try {
    appName = (await (await fetch('/api/_info')).json()).default ?? 'script';
  } catch {
    appName = 'script';
  }
}

const scene  = window.__scene;
const viewer = new Viewer(scene);
window.__viewer = viewer;

// ── 1. Fetch app schema ────────────────────────────────────────────────────────
let schema;
try {
  const res = await fetch(`/api/${appName}/schema`);
  if (!res.ok) throw new Error(`Schema fetch failed: HTTP ${res.status}`);
  schema = await res.json();
} catch (err) {
  statusEl.textContent = `Failed to load schema for "${appName}": ${err.message}`;
  statusEl.className   = 'error';
  throw err;
}

// ── 2. WebSocket client ────────────────────────────────────────────────────────
const ws = new WSClient(
  `ws://${location.host}/api/${appName}/ws`,
  viewer,
  statusEl
);
window.__ws = ws;

// Shared scene channel (kayviz.register_* from the Python process).
if (appName !== 'script') {
  window.__scriptWs = new WSClient(`ws://${location.host}/api/script/ws`, viewer);
}

// ── 3. Panel — the app's custom panel.js, else AutoCallbackPanel ─────────────
let panel = null;
try {
  if (!schema.panel) throw new Error('no custom panel');
  const mod        = await import(`/api/${appName}/panel.js`);
  const PanelClass = mod.default ?? Object.values(mod)[0];
  if (PanelClass) {
    panel = new PanelClass(ws, schema.state ?? []);
    window.__panel = panel;
  }
} catch (customErr) {
  if (schema.panel) console.error(`Custom panel for "${appName}" failed:`, customErr);
  // No custom panel — use the schema-driven auto panel if there are widgets
  const widgetSchema = schema.state ?? [];
  if (widgetSchema.length > 0) {
    try {
      const { default: AutoCallbackPanel } =
        await import('/static/gui/auto_callback_panel.js');
      panel = new AutoCallbackPanel(ws, widgetSchema, appName);
      window.__panel = panel;
    } catch (autoErr) {
      console.warn(`AutoCallbackPanel load failed for "${appName}":`, autoErr.message);
    }
  }
}

// ── 4. Scene panel (left sidebar) ─────────────────────────────────────────────
const scenePanel  = new ScenePanel(viewer, { lights: window.__lights ?? {} });

// ── 5. Energy plot panel (bottom-right) ───────────────────────────────────────
const energyPanel = new EnergyPanel(ws, { position: 'bottom-right' });

// ── 6. Load initial mesh ───────────────────────────────────────────────────────
statusEl.textContent = meshName ? `Loading ${meshName}…` : 'Loading…';

try {
  const query = meshName ? `?mesh_name=${encodeURIComponent(meshName)}` : '';
  const res = await fetch(`/api/${appName}/load${query}`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();

  viewer.applyMessage(data);
  if (data.mesh_name) {
    statusEl.textContent =
      `Loaded ${data.mesh_name} — ${data.n_vertices}v ${data.n_faces}f`;
  } else {
    statusEl.textContent = 'Ready';
  }

  if (panel?.onLoad) panel.onLoad(data);

} catch (err) {
  statusEl.textContent = `Failed to load mesh: ${err.message}`;
  statusEl.className   = 'error';
}
