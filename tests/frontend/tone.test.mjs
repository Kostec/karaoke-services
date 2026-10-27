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
