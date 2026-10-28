// Высота ноты → частота (web/static/js/tone.js): чистая часть без Web Audio.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pitchHz, toneMs, TONE_MIN_MS, TONE_MAX_MS } from '../../web/static/js/tone.js';

test('pitch 0 — до первой октавы (261,63 Гц), pitch 9 — ля 440 Гц', () => {
  assert.ok(Math.abs(pitchHz(0) - 261.63) < 0.01);
  assert.equal(pitchHz(9), 440);
});

test('октава — ровно в два раза, отрицательные высоты ниже', () => {
  assert.ok(Math.abs(pitchHz(21) - 880) < 1e-9);
  assert.ok(Math.abs(pitchHz(-3) - 220) < 1e-9);
});

test('длительность звучания ограничена 0,15…2 с', () => {
  assert.equal(TONE_MIN_MS, 150);
  assert.equal(TONE_MAX_MS, 2000);
  assert.equal(toneMs(40), 150);
  assert.equal(toneMs(500), 500);
  assert.equal(toneMs(9000), 2000);
  assert.equal(toneMs(NaN), 150);
});

// ---------------------------------------------------------------- Web Audio через подмену AudioContext

import { toneSequence, closeTone, pitchName } from '../../web/static/js/tone.js';

/** Подмена AudioContext: записывает старты осцилляторов и закрытие. */
function fakeAudio() {
  const log = { created: 0, closed: 0, starts: [], stops: [] };
  class FakeCtx {
    constructor() { log.created += 1; this.currentTime = 10; this.state = 'running'; this.destination = {}; }
    createOscillator() {
      return { type: '', frequency: { value: 0 }, connect: (x) => x,
        start: (t) => log.starts.push(t), stop: (t) => log.stops.push(t) };
    }
    createGain() {
      const g = { value: 0, setValueAtTime() {}, linearRampToValueAtTime() {}, cancelScheduledValues() {} };
      return { gain: g, connect: (x) => x };
    }
    close() { log.closed += 1; this.state = 'closed'; return Promise.resolve(); }
  }
  globalThis.AudioContext = FakeCtx;
  return log;
}

test('toneSequence: rate 0,5 — старт нот вдвое позже (по часам AudioContext)', () => {
  closeTone();
  const log = fakeAudio();
  toneSequence([{ pitch: 0, startMs: 1000, ms: 200 }, { pitch: 2, startMs: 2000, ms: 200 }], 0, { rate: 0.5 });
  const t0 = log.starts[0] - 2; // первая нота через 1 с песни → 2 с на скорости 0,5
  assert.ok(Math.abs(log.starts[1] - t0 - 4) < 1e-9, 'вторая нота через 4 с');
  assert.ok(Math.abs(t0 - 10.02) < 1e-9);
  closeTone();
  delete globalThis.AudioContext;
});

test('toneSequence без rate — время как в песне', () => {
  closeTone();
  const log = fakeAudio();
  toneSequence([{ pitch: 0, startMs: 1500, ms: 200 }], 500);
  assert.ok(Math.abs(log.starts[0] - (10.02 + 1)) < 1e-9);
  closeTone();
  delete globalThis.AudioContext;
});

test('closeTone закрывает контекст, следующий звук создаёт новый; без контекста — без ошибок', () => {
  closeTone();
  const log = fakeAudio();
  closeTone();
  assert.equal(log.closed, 0);
  toneSequence([{ pitch: 0, startMs: 0, ms: 300 }], 0);
  assert.equal(log.created, 1);
  const stopsBefore = log.stops.length;
  closeTone();
  assert.equal(log.closed, 1);
  assert.ok(log.stops.length > stopsBefore, 'звучащее остановлено');
  toneSequence([{ pitch: 0, startMs: 0, ms: 300 }], 0);
  assert.equal(log.created, 2);
  closeTone();
  delete globalThis.AudioContext;
});

test('pitchName: имя ноты по-русски и по-латински', () => {
  assert.equal(pitchName(9), 'ля 4 · A4');
  assert.equal(pitchName(0), 'до 4 · C4');
  assert.equal(pitchName(1), 'до♯ 4 · C♯4');
  assert.equal(pitchName(-1), 'си 3 · B3');
  assert.equal(pitchName(19), 'соль 5 · G5');
});
