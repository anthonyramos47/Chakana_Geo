// A push carrying seq is acknowledged once its frame is drawn (kayviz.evaluate).
import test from 'node:test';
import assert from 'node:assert/strict';
import './dom_stub.mjs';

class FakeSocket {
  static OPEN = 1;
  constructor() { this.readyState = 1; this.sent = []; FakeSocket.last = this; }
  send(msg) { this.sent.push(JSON.parse(msg)); }
  close() {}
}
globalThis.WebSocket = FakeSocket;
document.baseURI ??= 'http://127.0.0.1:8000/';
let frames = [];
globalThis.requestAnimationFrame = cb => frames.push(cb);
window.__renderFrame = () => { window.__drawn = (window.__drawn ?? 0) + 1; };

const { WSClient } = await import('../../src/kayviz/static/ws.js');
const viewer = { applyMessage() {}, errors: [] };
const message = seq => ({ data: JSON.stringify({ action: 'scene_update', seq, objects: [] }) });
const wait = ms => new Promise(r => setTimeout(r, ms));

test('acknowledged after the next animation frame, once', async () => {
  frames = [];
  const c = new WSClient('ws://x/api/script/ws', viewer);
  FakeSocket.last.onmessage(message(3));
  assert.deepEqual(FakeSocket.last.sent, []);          // not before the frame
  frames.shift()();
  await wait(300);                                     // the fallback must not send again
  assert.deepEqual(FakeSocket.last.sent, [{ action: 'applied', seq: 3 }]);
  c.ws = null;
});

test('without animation frames (window in background) it draws and acknowledges', async () => {
  frames = [];
  window.__drawn = 0;
  new WSClient('ws://x/api/script/ws', viewer);
  FakeSocket.last.onmessage(message(4));
  await wait(300);
  assert.equal(window.__drawn, 1);
  assert.deepEqual(FakeSocket.last.sent, [{ action: 'applied', seq: 4 }]);
});

test('a push without seq is not acknowledged', async () => {
  frames = [];
  new WSClient('ws://x/api/script/ws', viewer);
  FakeSocket.last.onmessage({ data: JSON.stringify({ action: 'scene_update', objects: [] }) });
  await wait(300);
  assert.equal(frames.length, 0);
  assert.deepEqual(FakeSocket.last.sent, []);
});
