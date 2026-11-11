/**
 * urls.js — server URLs relative to the page, so the viewer also works behind a
 * path prefix (JupyterHub, jupyter-server-proxy, VS Code remote) and over HTTPS.
 */

/** http(s) URL of an API route, e.g. api('script/ws') */
export function api(path) {
  return new URL(`api/${path}`, document.baseURI).href;
}

/** ws(s) URL of a WebSocket route, e.g. wsUrl('script/ws') */
export function wsUrl(path) {
  const url = new URL(`api/${path}`, document.baseURI);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}

/** URL of a frontend module, for dynamic import() (resolved against the page,
 *  not against the importing module). */
export function staticUrl(path) {
  return new URL(`static/${path}`, document.baseURI).href;
}
