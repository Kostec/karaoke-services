// «Мелодия нот»: синтезатор tone.js играет ноты песни в такт звуку — в «Прогоне» и «Редакторе нот».
// Ноты планируются порциями на MELODY_AHEAD_MS вперёд (часы AudioContext точнее кадров),
// следующая порция — когда до конца прежней меньше половины. Чистая часть — nextChunk, stateMelody.

import { melodySlice } from './play-logic.js';
import { toneSequence } from './tone.js';

export const MELODY_AHEAD_MS = 4000;
const KEEP_SEQS = 8; // давно отзвучавшие порции отбрасываются
/** Типы нот без высоты: фристайл и рэп — синтезатор их не играет. */
const UNPITCHED = new Set(['F', 'R', 'G']);

/**
 * Что планировать на момент песни ms: {chunk, until}. chunk — ноты новой порции (может быть пустым),
 * null — планировать нечего; until — до какого момента песни запланировано.
 * scheduledUntil null — старт или перемотка: первая порция берёт и ещё звучащие ноты.
 */
export function nextChunk(all, ms, scheduledUntil, aheadMs = MELODY_AHEAD_MS) {
  if (scheduledUntil == null) return { chunk: melodySlice(all, ms, ms + aheadMs, true), until: ms + aheadMs };
  if (scheduledUntil - ms < aheadMs / 2) {
    return { chunk: melodySlice(all, scheduledUntil, ms + aheadMs), until: ms + aheadMs };
  }
  return { chunk: null, until: scheduledUntil };
}

/**
 * Ноты состояния редактора [{type, start, length, pitch}] → [{pitch, startMs, ms}] по времени;
 * msOf(beat) — время бита. Без F/R/G; одинаковые ноты двух певцов звучат один раз.
 */
export function stateMelody(notes, msOf) {
  const seen = new Set();
  const out = [];
  for (const x of notes || []) {
    if (UNPITCHED.has(x.type)) continue;
    const startMs = msOf(x.start);
    const ms = msOf(x.start + x.length) - startMs;
    const key = `${startMs}|${ms}|${x.pitch}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ pitch: x.pitch, startMs, ms });
  }
  return out.sort((a, b) => a.startMs - b.startMs);
}

/**
 * Планировщик: notes() — ноты [{pitch, startMs, ms}], rate() — скорость проигрывания.
 * tick(ms, playing) — на каждом кадре (playing=false — тишина); stop() — тишина и сброс плана
 * (пауза, перемотка, смена скорости); invalidate() — ноты изменились, следующая порция — по новым.
 */
export function createMelody({ notes, rate = () => 1 }) {
  let all = null;
  let seqs = [];
  let until = null;

  function stop() {
    for (const s of seqs) s.stop();
    seqs = [];
    until = null;
  }

  function tick(ms, playing) {
    if (!playing) {
      if (until != null || seqs.length) stop();
      return;
    }
    if (!all) all = notes() || [];
    const r = nextChunk(all, ms, until, MELODY_AHEAD_MS);
    if (!r.chunk) return;
    until = r.until;
    if (r.chunk.length) seqs.push(toneSequence(r.chunk, ms, { rate: rate() }));
    if (seqs.length > KEEP_SEQS) seqs.shift();
  }

  return {
    tick,
    stop,
    invalidate() { all = null; },
  };
}
