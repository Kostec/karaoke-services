// «Прогон» (web/static/js/play-logic.js): ноты → время, кадр в момент ms, причины отказа.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  timeline, frameAt, playProblem, melodyNotes, melodySlice, laneY, fmtClock,
  NO_AUDIO, NO_BPM, RELATIVE, NO_NOTES,
} from '../../web/static/js/play-logic.js';

// BPM 150 → бит = 60000 / (150 * 4) = 100 мс; GAP 1000 мс.
const n = (id, start, length, pitch, text, type = ':') => ({ id, type, start, length, pitch, text });

function solo() {
  return {
    editable: true, bpm: 150, gap: 1000, duet: false, singers: { p1: '', p2: '' }, headers: [['BPM', '150']],
    lines: [
      { break_beat: 6, notes: [n(0, 0, 2, 5, 'При'), n(1, 2, 2, 7, 'вет '), n(2, 4, 2, 9, 'мир~')] },
      { break_beat: null, notes: [n(3, 10, 4, 12, 'Ещё '), n(4, 14, 2, -3, 'раз', 'F')] },
    ],
  };
}

function duet() {
  return {
    editable: true, bpm: 150, gap: 0, duet: true, singers: { p1: 'Григорий', p2: 'Алёна' }, headers: [],
    lines: [
      { break_beat: 4, player: 1, notes: [n(0, 0, 4, 0, 'Раз ')] },
      { break_beat: null, player: 1, notes: [n(1, 10, 2, 2, 'два ')] },
      { break_beat: null, player: 2, notes: [n(2, 2, 6, 4, 'Три ')] },
    ],
  };
}

test('timeline переводит биты в мс как beatToMs редактора (gap + beat·60000/(bpm·4))', () => {
  const tl = timeline(solo());
  assert.equal(tl.lines.length, 2);
  const [a, b] = tl.lines;
  assert.equal(a.player, 1);
  assert.equal(a.startMs, 1000);
  assert.equal(a.endMs, 1600);
  assert.deepEqual(a.syllables.map((s) => [s.startMs, s.endMs, s.pitch]), [[1000, 1200, 5], [1200, 1400, 7], [1400, 1600, 9]]);
  assert.equal(b.startMs, 2000);
  assert.equal(b.endMs, 2600);
  assert.equal(b.syllables[1].type, 'F');
});

test('timeline: «~» продолжения не выводится, пробелы слогов сохраняются', () => {
  const tl = timeline(solo());
  assert.deepEqual(tl.lines[0].syllables.map((s) => s.text), ['При', 'вет ', 'мир']);
});

test('pitchRange — по нотам с высотой (F/R без высоты не учитываются)', () => {
  assert.deepEqual(timeline(solo()).pitchRange, { min: 5, max: 12 });
});

test('дуэт: строки по партиям с певцом, имена певцов', () => {
  const tl = timeline(duet());
  assert.equal(tl.duet, true);
  assert.deepEqual(tl.singers, { p1: 'Григорий', p2: 'Алёна' });
  assert.deepEqual(tl.lines.map((l) => [l.player, l.startMs]), [[1, 0], [1, 1000], [2, 200]]);
});

test('frameAt: внутри слога — текущая строка, следующая, номер слога и доля', () => {
  const tl = timeline(solo());
  const f = frameAt(tl, 1250);
  assert.equal(f.current, tl.lines[0]);
  assert.equal(f.next, tl.lines[1]);
  assert.equal(f.syllable, 1);
  assert.equal(f.progress, 0.25);
  assert.equal(f.sung, 2);
});

test('frameAt: пауза между строками — показывается подходящая строка, ничего не спето', () => {
  const tl = timeline(solo());
  const f = frameAt(tl, 1800);
  assert.equal(f.current, tl.lines[1]);
  assert.equal(f.next, null);
  assert.equal(f.syllable, null);
  assert.equal(f.progress, 0);
  assert.equal(f.sung, 0);
});

test('frameAt: до первой ноты — первая строка; после последней — пусто', () => {
  const tl = timeline(solo());
  assert.equal(frameAt(tl, 0).current, tl.lines[0]);
  assert.equal(frameAt(tl, 0).next, tl.lines[1]);
  const end = frameAt(tl, 5000);
  assert.equal(end.current, null);
  assert.equal(end.next, null);
});

test('frameAt: дуэт — кадр своей партии', () => {
  const tl = timeline(duet());
  const p1 = frameAt(tl, 300, 1);
  assert.equal(p1.current.player, 1);
  assert.equal(p1.current.startMs, 0);
  assert.equal(p1.next.startMs, 1000);
  assert.equal(p1.syllable, 0);
  const p2 = frameAt(tl, 300, 2);
  assert.equal(p2.current.player, 2);
  assert.equal(p2.next, null);
  assert.equal(p2.syllable, 0);
  // певец 1 в паузе: следующая его строка
  assert.equal(frameAt(tl, 600, 1).current.startMs, 1000);
});

test('playProblem: нет звука, нет #BPM, #RELATIVE, нет нот', () => {
  const song = { audio: 'a.mp3' };
  assert.equal(playProblem(song, solo()), null);
  assert.equal(playProblem({ audio: null }, solo()), NO_AUDIO);
  assert.equal(playProblem(song, { ...solo(), bpm: null }), NO_BPM);
  assert.equal(playProblem(song, { ...solo(), bpm: 0 }), NO_BPM);
  assert.equal(playProblem(song, { ...solo(), headers: [['relative', 'YES']] }), RELATIVE);
  assert.equal(playProblem(song, { ...solo(), lines: [] }), NO_NOTES);
  assert.match(NO_BPM, /#BPM/);
  assert.match(RELATIVE, /#RELATIVE/);
});

test('melodyNotes: ноты с высотой для синтезатора, без F/R/G и без повтора «оба»', () => {
  const m = melodyNotes(timeline(solo()));
  assert.deepEqual(m, [
    { pitch: 5, startMs: 1000, ms: 200 }, { pitch: 7, startMs: 1200, ms: 200 },
    { pitch: 9, startMs: 1400, ms: 200 }, { pitch: 12, startMs: 2000, ms: 400 },
  ]);
  const both = timeline({ ...duet(), lines: [
    { break_beat: null, player: 1, notes: [n(0, 0, 2, 3, 'а')] },
    { break_beat: null, player: 2, notes: [n(1, 0, 2, 3, 'а')] },
  ] });
  assert.equal(melodyNotes(both).length, 1);
});

test('melodySlice: первая порция берёт звучащую ноту, следующие — только начавшиеся после', () => {
  const m = melodyNotes(timeline(solo()));
  assert.deepEqual(melodySlice(m, 1100, 1500, true).map((x) => x.startMs), [1000, 1200, 1400]);
  assert.deepEqual(melodySlice(m, 1500, 2500, false).map((x) => x.startMs), [2000]);
  assert.deepEqual(melodySlice(m, 1100, 1300, false).map((x) => x.startMs), [1200]);
});

test('laneY: верх дорожки — самая высокая нота, низ — самая низкая (в процентах)', () => {
  const r = { min: 0, max: 12 };
  assert.ok(laneY(12, r) < laneY(0, r));
  assert.ok(laneY(12, r) >= 0 && laneY(0, r) <= 100);
  assert.equal(laneY(6, r), (laneY(0, r) + laneY(12, r)) / 2);
  assert.ok(Number.isFinite(laneY(5, { min: 5, max: 5 })));
});

test('fmtClock: м:сс', () => {
  assert.equal(fmtClock(84000), '1:24');
  assert.equal(fmtClock(5000), '0:05');
  assert.equal(fmtClock(NaN), '0:00');
});
