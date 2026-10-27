// Подозрительные места «Редактора нот» (истории 49–51): чистая логика без DOM.
// Короткие и длинные ноты, скачки выше октавы внутри строки одного певца, строки без пары в исходном тексте.

import { beatToMs, lines, voiceLines, parts } from './notes-model.js';

export const SHORT_MS = 60;
export const LONG_MS = 5000;
export const JUMP = 12;

// F — свободная нота, R/G — рэп: высота у них условная и не проверяется
const NO_PITCH = new Set(['F', 'R', 'G']);

const ru = (v) => String(+v.toFixed(2)).replace('.', ',');

/** Длительность ноты в мс по #BPM. */
export function noteMs(state, x) {
  return (x.length * 60000) / (Number(state.bpm) * 4);
}

/**
 * Подозрительные ноты: Map id ноты → причины по-русски.
 * `unmatchedLines` — номера (с 0) строк исходного текста без пары, ответ `unmatched_lines` сервера;
 * строки нот сопоставляются им по порядку (после «Строки как в тексте» их номера совпадают).
 * У дуэта строки текста не проверяются.
 */
export function suspects(state, { unmatchedLines = [] } = {}) {
  const out = new Map();
  const add = (id, reason) => {
    const list = out.get(id) || [];
    if (!list.includes(reason)) list.push(reason);
    out.set(id, list);
  };
  if (!state || !state.notes) return out;
  if (Number(state.bpm) > 0) {
    for (const x of state.notes) {
      const ms = noteMs(state, x);
      if (ms < SHORT_MS) add(x.id, `Нота короче ${SHORT_MS} мс (${Math.round(ms)} мс)`);
      else if (ms > LONG_MS) add(x.id, `Нота длиннее ${LONG_MS / 1000} с (${ru(ms / 1000)} с)`);
    }
  }
  const groups = state.duet ? parts(state).flatMap((v) => voiceLines(state, v)) : lines(state);
  for (const line of groups) {
    for (let i = 1; i < line.length; i += 1) {
      const a = line[i - 1];
      const b = line[i];
      if (NO_PITCH.has(a.type) || NO_PITCH.has(b.type)) continue;
      const d = Math.abs(b.pitch - a.pitch);
      if (d > JUMP) add(b.id, `Скачок на ${d} полутонов от предыдущей ноты`);
    }
  }
  if (!state.duet && unmatchedLines.length) {
    const bad = new Set(unmatchedLines);
    lines(state).forEach((line, i) => {
      if (bad.has(i)) for (const x of line) add(x.id, `Строка ${i + 1} не совпала с исходным текстом`);
    });
  }
  return out;
}

/** Ноты-подозреваемые по порядку времени: [{id, start}] — для перехода «!» к следующей. */
export function suspectOrder(state, map) {
  return state.notes.filter((x) => map.has(x.id)).sort((a, b) => a.start - b.start || a.id - b.id);
}

/** Следующая подозрительная нота после выбранной (по кругу); null — подозрительных нет. */
export function nextSuspect(state, map, currentId) {
  const order = suspectOrder(state, map);
  if (!order.length) return null;
  const cur = state.notes.find((x) => x.id === currentId);
  if (!cur) return order[0].id;
  const nxt = order.find((x) => x.start > cur.start || (x.start === cur.start && x.id > cur.id));
  return (nxt || order[0]).id;
}
