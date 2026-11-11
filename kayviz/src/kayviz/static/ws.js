/**
 * ws.js — WebSocket client.
 *
 * Replaces ps.set_user_callback(). The server pushes geometry updates after
 * every action; handlers registered via onMessage() receive the parsed JSON.
 */

const RETRY_MIN_MS = 250;
const RETRY_MAX_MS = 2000;               // kayviz.show() waits 2.5 s for a tab to come back
const GIVE_UP_MS   = 15 * 60 * 1000;

// The server id this page was loaded from; a reconnect to a different server
// (a re-run of the script) reloads the page so panel and scene come from it.
let _instance = null;
let _instanceReady = fetch('/api/_info').then(r => r.json())
  .then(info => { _instance = info.instance ?? null; }).catch(() => {});

async function checkServerInstance() {
  await _instanceReady;
  try {
    const info = await (await fetch('/api/_info')).json();
    if (!_instance || !info.instance || info.instance === _instance) return;
    // A new server: reload. If it does not serve this page's app (another script
    // runs on the port now), switch to the app it serves, so the tab follows the
    // running script instead of failing to load.
    const app = new URLSearchParams(location.search).get('app');
    if (app && info.apps && !info.apps.includes(app)) {
      const url = new URL(location.href);
      url.searchParams.set('app', info.default);
      location.replace(url);
    } else {
      location.reload();
    }
  } catch (_) { /* server went away again; onclose retries */ }
}

// ── Binary frames (kayviz/webscope/wire.py) ───────────────────────────────────
// uint32 header length | JSON header | pad to 8 | arrays. In the header every array
// is {"__b": offset, "t": "f32"|"i32"|"u32", "n": length}, revived here as a typed
// array that owns its memory (a copy, so the frame buffer can be freed).
const _ARRAY_TYPES = { f32: Float32Array, i32: Int32Array, u32: Uint32Array };

export function decodeFrame(buf) {
  const headLen = new DataView(buf).getUint32(0, true);
  const header  = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, headLen)));
  const base    = (4 + headLen + 7) & ~7;
  const revive  = o => {
    if (Array.isArray(o)) {
      for (let i = 0; i < o.length; i++) if (o[i] && typeof o[i] === 'object') o[i] = revive(o[i]);
      return o;
    }
    if (o && typeof o === 'object') {
      if ('__b' in o) {
        const T = _ARRAY_TYPES[o.t], start = base + o.__b;
        return new T(buf.slice(start, start + o.n * T.BYTES_PER_ELEMENT));
      }
      for (const k in o) if (o[k] && typeof o[k] === 'object') o[k] = revive(o[k]);
    }
    return o;
  };
  return revive(header);
}

export class WSClient {
  /**
   * @param {string} url     WebSocket URL, e.g. 'ws://localhost:8000/api/lmesh/ws'
   * @param {Viewer} viewer  viewer.js Viewer instance
   * @param {HTMLElement} statusEl  optional status bar element
   */
  constructor(url, viewer, statusEl = null) {
    this.viewer    = viewer;
    this._handlers = [];
    this._status   = statusEl;
    this._url      = url;
    this._connect();
  }

  /** Send an action to the backend. Payload fields are merged into the message. */
  send(action, payload = {}) {
    const msg = JSON.stringify({ action, ...payload });
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(msg);
    else this._pending.push(msg);         // delivered by onopen after a reconnect
  }

  /** Register a callback for all server messages (after viewer.applyMessage). */
  onMessage(cb) { this._handlers.push(cb); }

  // ── Internals ─────────────────────────────────────────────────────────────

  _connect() {
    this._pending ??= [];
    this.ws = new WebSocket(this._url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      const reconnected = this._downSince != null;
      this._downSince  = null;
      this._retryDelay = RETRY_MIN_MS;
      this._setStatus('Connected', false);
      if (reconnected) checkServerInstance();
      for (const msg of this._pending.splice(0)) this.ws.send(msg);
    };

    this.ws.onmessage = e => {
      let data;
      try { data = typeof e.data === 'string' ? JSON.parse(e.data) : decodeFrame(e.data); }
      catch (err) { console.error('Bad message from server:', err); return; }

      const errors = this.viewer.errors ?? [];
      errors.length = 0;
      try {
        if (data.action === 'clear') {
          this.viewer.clearAll();
        } else if (data.action === 'remove' && data.name) {
          this.viewer.remove(data.name);
        } else if (data.action === 'view') {
          window.__applyView?.(data);
        } else if (data.objects?.length) {
          this.viewer.applyMessage(data);
        }
      } catch (err) {
        console.error('[kayviz] could not apply message:', err);
        errors.push(err.message);
      } finally {
        window.__invalidate?.();
      }
      for (const cb of this._handlers) {
        try { cb(data); } catch (err) { console.error('[kayviz] message handler failed:', err); }
      }

      if (errors.length) {
        this._setStatus(`Could not show ${errors.length} object(s): ${errors[0]}`, true);
        window.__toast?.(`Could not show ${errors.length} object(s):\n${errors.join('\n')}`);
      } else if (data.action === 'error') {
        this._setStatus('Server: ' + data.message, true);
        window.__toast?.(data.message);
        console.error('Server error:', data.message);
      } else if (data.action) {
        this._setStatus(data.action.replace(/_/g, ' '), false);
      }
    };

    this.ws.onclose = e => {
      // code 1000 = normal closure (page unload etc.) — don't reconnect
      if (e.code === 1000) return;
      this._downSince ??= Date.now();
      // Retry quickly (a script re-run restarts the server on the same port and
      // reuses this tab), but give up once the server has been gone for a while.
      if (Date.now() - this._downSince > GIVE_UP_MS) {
        window.__kayvizOffline = true;
        this._setStatus('Viewer server stopped — reload this page after restarting it.', true);
        return;
      }
      this._retryDelay = Math.min((this._retryDelay ?? RETRY_MIN_MS) * 2, RETRY_MAX_MS);
      this._setStatus(`Disconnected — reconnecting…`, true);
      setTimeout(() => this._connect(), this._retryDelay);
    };

    this.ws.onerror = () => {
      // onerror always fires before onclose — just log, let onclose handle retry
      this._setStatus('WebSocket error — check server is running', true);
    };
  }

  _setStatus(msg, isError) {
    if (!this._status) return;
    this._status.textContent = msg;
    this._status.className   = isError ? 'error' : '';
  }
}
