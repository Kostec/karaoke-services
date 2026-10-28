// «Прогон» (#play): чистая логика без DOM — ноты из GET /notes во время, кадр на момент песни,
// причины отказа, ноты для «Мелодии нот». Экран — play.js.

import { beatToMs } from './editors/notes-model.js';

export const NO_AUDIO = 'Прогон недоступен: у песни нет аудиофайла — нечего проигрывать. Прикрепите звук или перегенерируйте песню.';
export const NO_BPM = 'Прогон недоступен: у песни нет #BPM — не из чего построить ноты. Откройте «Редактор нот» или переимпортируйте песню.';
export const RELATIVE = 'Прогон недоступен: ноты песни записаны в формате #RELATIVE — прогон его пока не понимает. Переимпортируйте песню в обычном формате.';
export const NO_NOTES = 'Прогон недоступен: в песне нет ни одной ноты.';

/** Типы нот без высоты: фристайл и рэп — синтезатор их не играет. */
const UNPITCHED = new Set(['F', 'R', 'G']);
const DEFAULT_RANGE = { min: 0, max: 12 };

function isRelative(headers) {
  return (headers || []).some(([k, v]) => String(k).trim().toUpperCase() === 'RELATIVE'
    && String(v).trim().toUpperCase() === 'YES');
}

/** Почему прогон нельзя запустить (текст для экрана) или null. song — карточка песни (`audio`). */
export function playProblem(song, payload) {
  if (!song?.audio) return NO_AUDIO;
  if (isRelative(payload?.headers)) return RELATIVE;
  const bpm = Number(payload?.bpm);
  if (payload?.bpm == null || !Number.isFinite(bpm) || bpm <= 0) return NO_BPM;
  if (!(payload.lines || []).some((l) => l.notes?.length)) return NO_NOTES;
  return null;
}

/**
 * Ноты в мс по `bpm/gap` (как `beatToMs` редактора), строки по партиям в порядке файла.
 * → {duet, singers:{p1,p2}, lines:[{player, startMs, endMs, syllables:[{text, startMs, endMs, pitch, type}]}],
 *    pitchRange:{min,max}, endMs}. «~» продолжения гласной из текста убирается.
 */
export function timeline(payload) {
  const { bpm, gap } = payload;
  const ms = (beat) => beatToMs(beat, gap, bpm);
  const lines = [];
  let min = Infinity;
  let max = -Infinity;
  let endMs = 0;
  for (const line of payload.lines || []) {
    if (!line.notes?.length) continue;
    const syllables = line.notes.map((x) => {
      if (!UNPITCHED.has(x.type)) {
        min = Math.min(min, x.pitch);
        max = Math.max(max, x.pitch);
      }
      return { text: String(x.text ?? '').replace(/~/g, ''), startMs: ms(x.start), endMs: ms(x.start + x.length),
        pitch: x.pitch, type: x.type };
    });
    const out = { player: payload.duet ? (line.player || 1) : 1, startMs: syllables[0].startMs,
      endMs: syllables[syllables.length - 1].endMs, syllables };
    endMs = Math.max(endMs, out.endMs);
    lines.push(out);
  }
  return {
    duet: !!payload.duet,
    singers: { p1: payload.singers?.p1 || '', p2: payload.singers?.p2 || '' },
    lines,
    pitchRange: min <= max ? { min, max } : { ...DEFAULT_RANGE },
    endMs,
  };
}

/** Строки партии (или все у соло / без player) по времени начала. */
export function voiceLines(tl, player = null) {
  const list = player == null ? tl.lines : tl.lines.filter((l) => l.player === player);
  return [...list].sort((a, b) => a.startMs - b.startMs);
}

/**
 * Кадр на момент ms: current — строка, которая поётся, а в паузе — подходящая следующая
 * (после последней — null); next — строка за ней; syllable — номер звучащего слога или null;
 * progress — доля звучащего слога 0…1; sung — сколько слогов строки уже начались.
 * У дуэта player выбирает партию.
 */
export function frameAt(tl, ms, player = null) {
  const lines = voiceLines(tl, player);
  const i = lines.findIndex((l) => l.endMs > ms);
  const current = i < 0 ? null : lines[i];
  const next = i < 0 ? null : (lines[i + 1] || null);
  let syllable = null;
  let progress = 0;
  let sung = 0;
  if (current) {
    current.syllables.forEach((s, k) => {
      if (s.startMs <= ms) sung += 1;
      if (s.startMs <= ms && ms < s.endMs) {
        syllable = k;
        progress = s.endMs > s.startMs ? (ms - s.startMs) / (s.endMs - s.startMs) : 1;
      }
    });
  }
  return { current, next, syllable, progress, sung };
}

/** Ноты для синтезатора [{pitch, startMs, ms}] по времени: без F/R/G, одинаковые ноты двух певцов — один раз. */
export function melodyNotes(tl) {
  const seen = new Set();
  const out = [];
  for (const line of tl.lines) {
    for (const s of line.syllables) {
      if (UNPITCHED.has(s.type)) continue;
      const key = `${s.startMs}|${s.endMs}|${s.pitch}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ pitch: s.pitch, startMs: s.startMs, ms: s.endMs - s.startMs });
    }
  }
  return out.sort((a, b) => a.startMs - b.startMs);
}

/**
 * Порция нот для планирования вперёд: начинающиеся в [fromMs, untilMs).
 * first — первая порция после старта/перемотки: берёт и ещё звучащие ноты.
 */
export function melodySlice(notes, fromMs, untilMs, first = false) {
  return notes.filter((x) => x.startMs < untilMs
    && (first ? x.startMs + x.ms > fromMs : x.startMs >= fromMs));
}

const PREV_GRACE_MS = 1000; // в первую секунду строки «назад» ведёт к предыдущей строке

/** Начала строк (обеих партий у дуэта) по времени, без повторов — для ↑/↓ и ⏮/⏭. */
export function lineStarts(tl) {
  return [...new Set((tl.lines || []).map((l) => l.startMs))].sort((a, b) => a - b);
}

/**
 * Куда перейти из момента ms к началу соседней строки: dir > 0 — следующей (после последней — null),
 * dir < 0 — предыдущей (из первой секунды строки — ещё на одну назад; раньше первой — 0).
 */
export function lineJump(starts, ms, dir) {
  if (dir > 0) return starts.find((s) => s > ms + 1) ?? null;
  let out = 0;
  for (const s of starts) if (s < ms - PREV_GRACE_MS) out = s;
  return out;
}

/** Вертикаль ноты на дорожке, % сверху: выше нота — выше на дорожке; поля 8 % сверху и снизу. */
export function laneY(pitch, range) {
  const lo = range.min - 1;
  const hi = range.max + 1;
  return 8 + ((hi - pitch) / (hi - lo)) * 84;
}

/** Время «м:сс». */
export function fmtClock(ms) {
  const s = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
