/**
 * ws.js — WebSocket client.
 *
 * Replaces ps.set_user_callback(). The server pushes geometry updates after
 * every action; handlers registered via onMessage() receive the parsed JSON.
 */

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
    if (this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open — queuing action', action);
      this.ws.addEventListener('open', () => this.send(action, payload), { once: true });
      return;
    }
    this.ws.send(JSON.stringify({ action, ...payload }));
  }

  /** Register a callback for all server messages (after viewer.applyMessage). */
  onMessage(cb) { this._handlers.push(cb); }

  // ── Internals ─────────────────────────────────────────────────────────────

  _connect() {
    this._retryDelay = this._retryDelay ?? 1000;
    this.ws = new WebSocket(this._url);

    this.ws.onopen = () => {
      this._retryDelay = 1000;   // reset backoff on successful connect
      this._setStatus('Connected', false);
    };

    this.ws.onmessage = e => {
      let data;
      try { data = JSON.parse(e.data); }
      catch { console.error('Bad JSON from server:', e.data); return; }

      if (data.action === 'clear') {
        this.viewer.clearAll();
      } else if (data.action === 'remove' && data.name) {
        this.viewer.remove(data.name);
      } else if (data.objects?.length) {
        this.viewer.applyMessage(data);
      }
      this._handlers.forEach(cb => cb(data));

      if (data.action === 'error') {
        this._setStatus('Server: ' + data.message, true);
        console.error('Server error:', data.message);
      } else if (data.action) {
        this._setStatus(data.action.replace(/_/g, ' '), false);
      }
    };

    this.ws.onclose = e => {
      // code 1000 = normal closure (page unload etc.) — don't reconnect
      if (e.code === 1000) return;
      this._retryDelay = Math.min(this._retryDelay * 2, 10000);
      this._setStatus(`Disconnected (${e.code}) — retrying in ${this._retryDelay/1000}s…`, true);
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
