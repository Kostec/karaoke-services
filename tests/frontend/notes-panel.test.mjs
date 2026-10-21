// Панель текста и отстукивание редактора нот (таск 04): web/static/js/editors/notes-panel-logic.js — без DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  lineAt, lineStatus, tapTiming, tapQueue,
} from '../../web/static/js/editors/notes-panel-logic.js';

const n = (start, length) => ({ start, length });
// строки: [0..6), [10..16), [20..24)
const LINES = [[n(0, 2), n(3, 3)], [n(10, 4), n(14, 2)], [n(20, 4)]];

test('звучащая строка — та, в чьих границах (от начала первой ноты до конца последней) стоит бит', () => {
  assert.equal(lineAt(LINES, 0), 0);
  assert.equal(lineAt(LINES, 2.5), 0); // пауза внутри строки — строка всё ещё звучит
  assert.equal(lineAt(LINES, 5.9), 0);
  assert.equal(lineAt(LINES, 12), 1);
  assert.equal(lineAt(LINES, 23), 2);
});

test('между строками, до первой и после последней — ни одна строка не звучит', () => {
  assert.equal(lineAt(LINES, 6), -1);
  assert.equal(lineAt(LINES, 8), -1);
  assert.equal(lineAt(LINES, -3), -1);
  assert.equal(lineAt(LINES, 24), -1);
  assert.equal(lineAt([], 1), -1);
});

test('счётчик под строкой: слогов столько же, сколько нот — просто число нот', () => {
  assert.deepEqual(lineStatus(4, 4), { kind: 'ok', text: '4 ноты', add: 0 });
  assert.deepEqual(lineStatus(1, 1), { kind: 'ok', text: '1 нота', add: 0 });
  assert.deepEqual(lineStatus(11, 11), { kind: 'ok', text: '11 нот', add: 0 });
});

test('слогов больше нот — предупреждение и сколько нот добавить', () => {
  assert.deepEqual(lineStatus(5, 3), { kind: 'warn', text: '5 слогов, а нот 3', add: 2, addText: '+ 2 ноты' });
  assert.deepEqual(lineStatus(2, 1), { kind: 'warn', text: '2 слога, а нот 1', add: 1, addText: '+ 1 ноту' });
  assert.deepEqual(lineStatus(21, 15), { kind: 'warn', text: '21 слог, а нот 15', add: 6, addText: '+ 6 нот' });
});

test('слогов меньше нот — лишние ноты тянут гласную', () => {
  assert.deepEqual(lineStatus(3, 5), { kind: 'ok', text: '3 слога на 5 нот — лишние ноты тянут гласную (~)', add: 0 });
});

// BPM 300 → бит = 60000 / (300 × 4) = 50 мс; #GAP 1000 мс → бит 0 на 1000 мс
test('отстукивание: начало ноты — бит нажатия, длина — удержание, округление до бита', () => {
  assert.deepEqual(tapTiming(1500, 1720, 1000, 300), { start: 10, length: 4 }); // 10 → 14,4
  assert.deepEqual(tapTiming(1526, 1800, 1000, 300), { start: 11, length: 5 }); // 10,52 → 16
  assert.deepEqual(tapTiming(2000, 2400, 0, 300), { start: 40, length: 8 });
});

test('отстукивание: короткое касание — нота в 1 бит, не короче', () => {
  assert.deepEqual(tapTiming(1500, 1505, 1000, 300), { start: 10, length: 1 });
  assert.deepEqual(tapTiming(1500, 1400, 1000, 300), { start: 10, length: 1 });
});

test('очередь отстукивания — с выбранной ноты до конца песни, без выбора — с первой', () => {
  const notes = [{ id: 7 }, { id: 3 }, { id: 9 }];
  assert.deepEqual(tapQueue(notes, 3), [3, 9]);
  assert.deepEqual(tapQueue(notes, null), [7, 3, 9]);
  assert.deepEqual(tapQueue(notes, 42), [7, 3, 9]);
});


// дуэт: строки в порядке списка, партии перекрываются по времени
const v = (start, length, voice, id) => ({ id, start, length, voice });
const DUET = [[v(0, 4, 1, 0), v(4, 2, 1, 1)], [v(0, 3, 2, 2)], [v(8, 4, 'both', 3)], [v(14, 2, 2, 4)], [v(13, 2, 1, 5)]];

test('дуэт: звучащая строка — в партии певца (с «оба»), порядок строк по времени не обязателен', () => {
  assert.equal(lineAt(DUET, 1, 1), 0);
  assert.equal(lineAt(DUET, 1, 2), 1);
  assert.equal(lineAt(DUET, 9, 2), 2, '«оба» — в обеих партиях');
  assert.equal(lineAt(DUET, 9, 1), 2);
  assert.equal(lineAt(DUET, 13.5, 1), 4);
  assert.equal(lineAt(DUET, 14.5, 2), 3);
  assert.equal(lineAt(DUET, 5, 2), -1);
  assert.equal(lineAt(DUET, 13.5), 4, 'без певца — любая звучащая строка');
});

test('дуэт: отстукивание идёт до конца партии ноты', () => {
  const notes = DUET.flat();
  assert.deepEqual(tapQueue(notes, 2), [2, 3, 4]);
  assert.deepEqual(tapQueue(notes, 1), [1, 3, 5]);
  assert.deepEqual(tapQueue(notes, 99), [0, 1, 3, 5], 'нет такой — с первой ноты партии певца 1');
});
