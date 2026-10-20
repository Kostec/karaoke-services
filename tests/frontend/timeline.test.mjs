// Расчёты таймлайна редактора нот (таск 03): web/static/js/editors/timeline-math.js — без DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  octaveLabel, clampZoom, zoomScroll, hitZone, peaks, noteAt, rulerStep, pitchRange, ensureVisible,
} from '../../web/static/js/editors/timeline-math.js';

test('подписи октав: высота 0 в UltraStar — C4, подписываются только «до»', () => {
  assert.equal(octaveLabel(0), 'C4');
  assert.equal(octaveLabel(12), 'C5');
  assert.equal(octaveLabel(-12), 'C3');
  assert.equal(octaveLabel(-24), 'C2');
  assert.equal(octaveLabel(7), null);
  assert.equal(octaveLabel(-5), null);
});

test('масштаб — от 4 до 48 px на бит', () => {
  assert.equal(clampZoom(2), 4);
  assert.equal(clampZoom(100), 48);
  assert.equal(clampZoom(16), 16);
});

test('при смене масштаба центр видимой области остаётся на том же бите', () => {
  // видно 0…1000 px при 10 px/бит → центр — бит 50; при 20 px/бит он на 1000 px, левый край — 500
  assert.equal(zoomScroll({ scrollLeft: 0, width: 1000, ppb: 10 }, 20), 500);
  // отдаление к началу песни не уводит прокрутку в минус
  assert.equal(zoomScroll({ scrollLeft: 0, width: 1000, ppb: 20 }, 10), 0);
});

test('край ноты: 10 px с краю (у короткой — треть ширины) тянут длительность, середина двигает', () => {
  assert.equal(hitZone(3, 100), 'left');
  assert.equal(hitZone(95, 100), 'right');
  assert.equal(hitZone(50, 100), 'move');
  assert.equal(hitZone(4, 12), 'move'); // у ноты в 12 px краевая зона — 4 px
  assert.equal(hitZone(3, 12), 'left');
});

test('пики волны — максимум модуля по каждому окну во всех каналах', () => {
  // 1000 отсчётов/с, окно 10 мс = 10 отсчётов
  const a = new Float32Array(25); const b = new Float32Array(25);
  a[3] = 0.5; b[7] = -0.8; a[12] = -0.25; b[24] = 0.1;
  const p = peaks([a, b], 1000, 10);
  assert.equal(p.length, 3);
  assert.ok(Math.abs(p[0] - 0.8) < 1e-6);
  assert.ok(Math.abs(p[1] - 0.25) < 1e-6);
  assert.ok(Math.abs(p[2] - 0.1) < 1e-6);
});

test('звучащая нота по биту: внутри ноты — её индекс, в паузе — −1', () => {
  const ns = [{ start: 0, length: 4 }, { start: 6, length: 2 }, { start: 10, length: 5 }];
  assert.equal(noteAt(ns, 0), 0);
  assert.equal(noteAt(ns, 3.9), 0);
  assert.equal(noteAt(ns, 4), -1);
  assert.equal(noteAt(ns, 7), 1);
  assert.equal(noteAt(ns, 14.5), 2);
  assert.equal(noteAt(ns, 15), -1);
  assert.equal(noteAt(ns, -3), -1);
  assert.equal(noteAt([], 1), -1);
});

test('шаг подписей линейки — не теснее 60 px', () => {
  assert.equal(rulerStep(100), 1000); // 100 px/с → каждая секунда
  assert.equal(rulerStep(40), 2000); // 1 с = 40 px — тесно, через 2 с = 80 px
  assert.equal(rulerStep(15), 5000);
  assert.equal(rulerStep(3), 30000);
});

test('диапазон высот — от самой низкой до самой высокой ноты с запасом', () => {
  assert.deepEqual(pitchRange([{ pitch: 3 }, { pitch: -2 }, { pitch: 10 }], 4), { min: -6, max: 14 });
  assert.deepEqual(pitchRange([], 4), { min: -4, max: 16 });
});

test('прокрутка за курсором: в видимой области — без изменений, за краем — курсор на четверти ширины', () => {
  assert.equal(ensureVisible(500, 0, 1000), 0);
  assert.equal(ensureVisible(1200, 0, 1000), 950);
  assert.equal(ensureVisible(100, 400, 1000), 0);
});

test('бит после сдвига #GAP: то же время звучания в координатах прежнего #GAP', async () => {
  const { rebaseBeat } = await import('../../web/static/js/editors/timeline-math.js');
  // BPM 300 → бит = 50 мс; #GAP уменьшился на 100 мс → бит 0 нового состояния = бит −2 прежнего
  assert.equal(rebaseBeat(0, 900, 1000, 300), -2);
  assert.equal(rebaseBeat(10, 1000, 1000, 300), 10);
});
