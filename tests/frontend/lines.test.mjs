// Логика редактора строк (G05.1, G05.2): чистые функции web/static/js/editors/lines.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  beatToMs, lineRange, setSyllable, mergeWithNext, splitBefore, deleteNote, toPayload, isDirty, lineText,
} from '../../web/static/js/editors/lines.js';

const n = (start, length, text, pitch = 5, type = ':') => ({ type, start, length, pitch, text });

// Песня из трёх строк, разрывы «- 10» и «- 22».
function song() {
  return {
    editable: true, bpm: 300, gap: 1000, headers: [['TITLE', 'T']],
    lines: [
      { break_beat: 10, notes: [n(0, 2, 'Hel'), n(2, 3, 'lo'), n(6, 2, ' world')] },
      { break_beat: 22, notes: [n(12, 4, 'Sec'), n(16, 2, 'ond')] },
      { break_beat: null, notes: [n(24, 4, 'Last', 7, '*')] },
    ],
  };
}

test('время бита: GAP_ms + beat*60000/(BPM*4)', () => {
  // 1000 + 100*60000/1200 = 6000 (разобрано вручную)
  assert.equal(beatToMs(100, 1000, 300), 6000);
  assert.equal(beatToMs(0, 1000, 300), 1000);
  // дробный BPM: 0 + 10*60000/(250.5*4) = 598.802…
  assert.ok(Math.abs(beatToMs(10, 0, 250.5) - 598.8024) < 0.001);
});

test('отрезок строки: от начала первой ноты до конца последней', () => {
  const s = song();
  // строка 2: биты 12..18 → 1000+12*50=1600 … 1000+18*50=1900
  assert.deepEqual(lineRange(s.lines[1], s.gap, s.bpm), { start: 1600, end: 1900 });
  assert.deepEqual(lineRange(s.lines[0], s.gap, s.bpm), { start: 1000, end: 1400 });
});

test('исправление слога меняет только его текст', () => {
  const s = song();
  const out = setSyllable(s.lines, 0, 1, 'LO');
  assert.equal(out[0].notes[1].text, 'LO');
  assert.equal(s.lines[0].notes[1].text, 'lo', 'исходный массив не меняется');
  assert.deepEqual(out[0].notes.map((x) => [x.start, x.length, x.pitch]), [[0, 2, 5], [2, 3, 5], [6, 2, 5]]);
  assert.deepEqual(out.slice(1), s.lines.slice(1));
});

test('склейка со следующей: ноты подряд, разрыв берётся у следующей строки', () => {
  const out = mergeWithNext(song().lines, 0);
  assert.equal(out.length, 2);
  assert.deepEqual(out[0].notes.map((x) => x.text), ['Hel', 'lo', ' world', 'Sec', 'ond']);
  assert.equal(out[0].break_beat, 22);
  assert.deepEqual(out[1], song().lines[2]);
  assert.throws(() => mergeWithNext(song().lines, 2), /последн/i);
});

test('разбивка перед слогом: разрыв — конец последней ноты первой части, ноты не меняются', () => {
  const out = splitBefore(song().lines, 0, 2);
  assert.equal(out.length, 4);
  assert.deepEqual(out[0], { break_beat: 5, notes: [n(0, 2, 'Hel'), n(2, 3, 'lo')] });
  assert.deepEqual(out[1], { break_beat: 10, notes: [n(6, 2, ' world')] });
  assert.throws(() => splitBefore(song().lines, 0, 0), /перв/i);
});

test('склейка после разбивки возвращает исходные строки', () => {
  const s = song();
  assert.deepEqual(mergeWithNext(splitBefore(s.lines, 1, 1), 1), s.lines);
});

test('удаление ноты; пустая строка исчезает; последняя нота песни остаётся', () => {
  const s = song();
  const a = deleteNote(s.lines, 0, 1);
  assert.deepEqual(a[0].notes.map((x) => x.text), ['Hel', ' world']);
  const b = deleteNote(s.lines, 2, 0);
  assert.equal(b.length, 2);
  assert.equal(b[1].break_beat, null, 'у новой последней строки нет разрыва');
  const c = deleteNote(deleteNote(s.lines, 1, 0), 1, 0);
  assert.equal(c.length, 2);
  assert.equal(c[0].break_beat, 10);
  const one = [{ break_beat: null, notes: [n(0, 1, 'x')] }];
  assert.throws(() => deleteNote(one, 0, 0), /хотя бы одна/i);
});

test('тело PUT: строки с разрывами и нотами; признак несохранённых правок', () => {
  const s = song();
  assert.deepEqual(toPayload(s.lines), {
    lines: s.lines.map((l) => ({ break_beat: l.break_beat, notes: l.notes })),
  });
  assert.equal(isDirty(s.lines, song().lines), false);
  assert.equal(isDirty(setSyllable(s.lines, 0, 0, 'X'), s.lines), true);
  assert.equal(lineText(s.lines[0]), 'Hello world');
});
