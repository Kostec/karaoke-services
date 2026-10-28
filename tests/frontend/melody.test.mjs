// Планировщик «Мелодии нот» (web/static/js/melody.js): какую порцию нот планировать на момент песни.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nextChunk, stateMelody, MELODY_AHEAD_MS } from '../../web/static/js/melody.js';

const notes = [
  { pitch: 0, startMs: 0, ms: 500 },
  { pitch: 2, startMs: 900, ms: 300 },
  { pitch: 4, startMs: 3000, ms: 400 },
  { pitch: 5, startMs: 4500, ms: 400 },
  { pitch: 7, startMs: 9000, ms: 400 },
];

test('порция — 4 с вперёд', () => {
  assert.equal(MELODY_AHEAD_MS, 4000);
});

test('первая порция после старта берёт и ещё звучащую ноту', () => {
  const r = nextChunk(notes, 1000, null, 4000);
  assert.deepEqual(r.chunk.map((x) => x.pitch), [2, 4, 5]);
  assert.equal(r.until, 5000);
});

test('пока до конца порции ≥ 2 с — ничего не планируется', () => {
  assert.deepEqual(nextChunk(notes, 2500, 5000, 4000), { chunk: null, until: 5000 });
  assert.deepEqual(nextChunk(notes, 3000, 5000, 4000), { chunk: null, until: 5000 });
});

test('меньше 2 с до конца — следующая порция с конца прежней, без повторов', () => {
  const r = nextChunk(notes, 3100, 5000, 4000);
  assert.deepEqual(r.chunk.map((x) => x.pitch), []);
  assert.equal(r.until, 7100);
  const r2 = nextChunk(notes, 5200, 7100, 4000);
  assert.deepEqual(r2.chunk.map((x) => x.pitch), [7]);
  assert.equal(r2.until, 9200);
});

test('нота, начавшаяся до старта порции, во второй порции не повторяется', () => {
  const r = nextChunk(notes, 5100, 4600, 4000);
  assert.deepEqual(r.chunk.map((x) => x.pitch), [7]);
});

test('ноты редактора: без F/R/G, «оба» и одинаковые ноты двух певцов — один раз, по времени', () => {
  const msOf = (beat) => beat * 100;
  const st = [
    { id: 1, type: ':', start: 10, length: 2, pitch: 5, voice: 1 },
    { id: 2, type: 'F', start: 12, length: 2, pitch: 0, voice: 1 },
    { id: 3, type: '*', start: 4, length: 3, pitch: 7, voice: 'both' },
    { id: 4, type: ':', start: 10, length: 2, pitch: 5, voice: 2 },
    { id: 5, type: 'R', start: 20, length: 2, pitch: 0, voice: 2 },
    { id: 6, type: 'G', start: 22, length: 2, pitch: 0, voice: 2 },
    { id: 7, type: ':', start: 30, length: 1, pitch: -2, voice: 2 },
  ];
  assert.deepEqual(stateMelody(st, msOf), [
    { pitch: 7, startMs: 400, ms: 300 },
    { pitch: 5, startMs: 1000, ms: 200 },
    { pitch: -2, startMs: 3000, ms: 100 },
  ]);
});
