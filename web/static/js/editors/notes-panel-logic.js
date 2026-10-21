// Чистая логика панели текста и отстукивания редактора нот (таск 04; спека: истории 16, 21, 23) — без DOM.

import {
  msToBeat, inVoice, partOf, parts, voiceNotes,
} from './notes-model.js';
import { noteAt } from './timeline-math.js';

/**
 * Индекс строки, звучащей на бите beat (от начала первой ноты до конца последней), иначе −1.
 * voice (1 | 2) — только строки партии этого певца (со строками «оба»); порядок строк любой.
 */
export function lineAt(lines, beat, voice) {
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.length || (voice != null && !inVoice(line[0], voice))) continue;
    const last = line[line.length - 1];
    if (beat >= line[0].start && beat < last.start + last.length) return i;
  }
  return -1;
}

/** Форма слова по числу: forms = [1, 2–4, 5+] («нота», «ноты», «нот»). */
export function plural(n, forms) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b === 1) return forms[0];
  if (b >= 2 && b <= 4) return forms[1];
  return forms[2];
}

const NOTES = ['нота', 'ноты', 'нот'];
const NOTES_ACC = ['ноту', 'ноты', 'нот'];
const SYLS = ['слог', 'слога', 'слогов'];
const count = (n, forms) => `${n} ${plural(n, forms)}`;

/**
 * Строка под строкой панели (история 21): {kind: 'ok'|'warn', text, add[, addText]};
 * add — сколько нот не хватает слогам (кнопка «+ K нот»).
 */
export function lineStatus(syllables, notes) {
  if (syllables > notes) {
    const add = syllables - notes;
    return { kind: 'warn', text: `${count(syllables, SYLS)}, а нот ${notes}`, add, addText: `+ ${count(add, NOTES_ACC)}` };
  }
  if (syllables < notes) {
    return { kind: 'ok', text: `${count(syllables, SYLS)} на ${count(notes, NOTES)} — лишние ноты тянут гласную (~)`, add: 0 };
  }
  return { kind: 'ok', text: count(notes, NOTES), add: 0 };
}

/**
 * Отстукивание (история 16): нажатие в downMs, отпускание в upMs → {start, length} в битах:
 * начало — бит нажатия, конец — бит отпускания (оба округлены), длина не меньше 1 бита.
 */
export function tapTiming(downMs, upMs, gap, bpm) {
  const start = Math.round(msToBeat(downMs, gap, bpm));
  return { start, length: Math.max(1, Math.round(msToBeat(upMs, gap, bpm)) - start) };
}

/**
 * Порядок отстукивания: id нот с ноты fromId (нет такой — с первой) до конца песни —
 * у дуэта до конца партии этой ноты (певец 2 — его ноты и «оба», иначе — певца 1 и «оба»).
 */
export function tapQueue(notes, fromId) {
  const from = notes.find((x) => x.id === fromId);
  const sub = notes.filter((x) => inVoice(x, partOf(from)));
  const i = sub.indexOf(from);
  return sub.slice(Math.max(0, i)).map((x) => x.id);
}

/** Живые ноты на бите beat: в каждой партии своя (id; нота «оба» — один раз), у соло — одна. */
export function liveNotes(state, beat) {
  const now = new Set();
  for (const v of parts(state)) {
    const part = voiceNotes(state, v);
    const i = noteAt(part, beat);
    if (i >= 0) now.add(part[i].id);
  }
  return now;
}

/** Звучащие строки на бите beat: номера в lines (= M.lines(state)) — по одной в каждой партии. */
export function liveLines(state, lines, beat) {
  const now = new Set();
  for (const v of parts(state)) {
    const li = lineAt(lines, beat, state.duet ? v : undefined);
    if (li >= 0) now.add(li);
  }
  return now;
}

/**
 * Раскладка панели «Текст»: [{key, li, g, num}] в порядке на экране. Соло — строки по порядку (g 0);
 * дуэт — группа певца 1 (g 1, со строками «оба»), потом певца 2 (g 2, тоже с «оба»).
 * num — номер строки внутри группы, тот же, что в ошибках validate («Певец 2, строка 3»).
 */
export function panelRows(state, lines) {
  if (!state.duet) return lines.map((_, li) => ({ key: `0:${li}`, li, g: 0, num: li + 1 }));
  const out = [];
  for (const g of parts(state)) {
    let num = 0;
    lines.forEach((line, li) => {
      if (line.length && inVoice(line[0], g)) out.push({ key: `${g}:${li}`, li, g, num: ++num });
    });
  }
  return out;
}

