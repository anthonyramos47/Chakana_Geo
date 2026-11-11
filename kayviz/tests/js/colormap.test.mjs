import test from 'node:test';
import assert from 'node:assert/strict';
import { sample, finiteRange, NAN_COLOR } from '../../src/kayviz/static/lib/colormap.js';

test('viridis ends match matplotlib', () => {
  assert.deepEqual(sample(0).map(x => Math.round(x * 255)), [0x44, 0x01, 0x54]);
  assert.deepEqual(sample(1).map(x => Math.round(x * 255)), [0xfd, 0xe7, 0x25]);
});

test('non-finite values get the NaN colour and are ignored by the range', () => {
  assert.equal(sample(NaN), NAN_COLOR);
  assert.deepEqual(finiteRange([0, NaN, Infinity, 2, -1]), [-1, 2]);
  assert.deepEqual(finiteRange([NaN]), [0, 1]);
});
