// Подозрительные места редактора нот (web/static/js/editors/notes-checks.js): чистая логика.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { suspects, SHORT_MS, LONG_MS, JUMP } from '../../web/static/js/editors/notes-checks.js';
import * as M from '../../web/static/js/editors/notes-model.js';

// bpm 300: бит = 60000/(300*4) = 50 мс
const BPM = 300;
const n = (id, start, length, pitch, extra = {}) => ({ id, type: ':', start, length, pitch, text: 'а ', ...extra });
const solo = (lines) => M.fromPayload({
  editable: true, bpm: BPM, gap: 0, headers: [], duet: false, singers: { p1: '', p2: '' },
  lines: lines.map((notes, i) => ({ break_beat: i < lines.length - 1 ? 100 * (i + 1) : null, notes })),
});

test('константы порогов', () => {
  assert.deepEqual([SHORT_MS, LONG_MS, JUMP], [60, 5000, 12]);
});

test('нота короче 60 мс и длиннее 5 с отмечаются с причиной по-русски', () => {
  const st = solo([[n(0, 0, 1, 0), n(1, 2, 1, 0), n(2, 4, 101, 0), n(3, 200, 100, 0)]]);
  // 1 бит = 50 мс < 60; 101 бит = 5050 мс > 5000; 100 бит = ровно 5000 — не длиннее
  const s = suspects(st);
  assert.deepEqual([...s.keys()].sort(), [0, 1, 2]);
  assert.match(s.get(0)[0], /^Нота короче 60 мс \(50 мс\)/);
  assert.match(s.get(2)[0], /^Нота длиннее 5 с \(5,05 с\)/);
});

test('нормальные ноты не подозрительны; без bpm длительность не проверяется', () => {
  assert.equal(suspects(solo([[n(0, 0, 4, 0), n(1, 4, 4, 2)]])).size, 0);
  const noBpm = { ...solo([[n(0, 0, 1, 0)]]), bpm: 0 };
  assert.equal(suspects(noBpm).size, 0);
});

test('скачок больше октавы — отмечается вторая нота; ровно октава — нет', () => {
  const st = solo([[n(0, 0, 4, 0), n(1, 4, 4, 12), n(2, 8, 4, 25)]]);
  const s = suspects(st);
  assert.deepEqual([...s.keys()], [2]);
  assert.equal(s.get(2)[0], 'Скачок на 13 полутонов от предыдущей ноты');
});

test('скачок считается внутри строки, между строками — нет', () => {
  const st = solo([[n(0, 0, 4, 0)], [n(1, 100, 4, 30)]]);
  assert.equal(suspects(st).size, 0);
});

test('F и R-ноты по высоте не проверяются, скачок через них — тоже', () => {
  const st = solo([[n(0, 0, 4, 0), n(1, 4, 4, 40, { type: 'F' }), n(2, 8, 4, 0, { type: 'R' }), n(3, 12, 4, 1)]]);
  assert.equal(suspects(st).size, 0);
});

test('дуэт: скачок между нотами разных певцов не считается, внутри партии — считается', () => {
  const st = M.fromPayload({
    editable: true, bpm: BPM, gap: 0, headers: [], duet: true, singers: { p1: 'А', p2: 'Б' },
    lines: [
      { break_beat: 40, player: 1, notes: [n(0, 0, 4, 0), n(1, 4, 4, 2)] },
      { break_beat: null, player: 2, notes: [n(2, 10, 4, 30), n(3, 14, 4, 31), n(4, 18, 4, 60)] },
    ],
  });
  const s = suspects(st);
  assert.deepEqual([...s.keys()], [4]);
});

test('строки без пары в тексте: подсвечиваются все ноты строки, нумерация с 1', () => {
  const st = solo([[n(0, 0, 4, 0), n(1, 4, 4, 1)], [n(2, 100, 4, 0)], [n(3, 200, 4, 0)]]);
  const s = suspects(st, { unmatchedLines: [1] });
  assert.deepEqual([...s.keys()], [2]);
  assert.equal(s.get(2)[0], 'Строка 2 не совпала с исходным текстом');
});

test('у дуэта строки текста не проверяются; несколько причин у одной ноты складываются', () => {
  const st = solo([[n(0, 0, 1, 0), n(1, 1, 1, 30)]]);
  assert.deepEqual(suspects(st).get(1).length, 2);
  const duet = { ...st, duet: true };
  assert.equal(suspects(duet, { unmatchedLines: [0] }).get(0).some((r) => r.startsWith('Строка')), false);
});

test('nextSuspect идёт по времени, по кругу; без выбора — к первой; без подозрительных — null', async () => {
  const { nextSuspect } = await import('../../web/static/js/editors/notes-checks.js');
  const st = solo([[n(0, 0, 1, 0), n(1, 4, 4, 0), n(2, 8, 1, 0)]]);
  const s = suspects(st);
  assert.deepEqual([...s.keys()], [0, 2]);
  assert.equal(nextSuspect(st, s, null), 0);
  assert.equal(nextSuspect(st, s, 0), 2);
  assert.equal(nextSuspect(st, s, 1), 2);
  assert.equal(nextSuspect(st, s, 2), 0);
  assert.equal(nextSuspect(st, new Map(), 1), null);
});
