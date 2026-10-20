// Чистая логика панели текста и отстукивания редактора нот (таск 04; спека: истории 16, 21, 23) — без DOM.

import { msToBeat } from './notes-model.js';

/** Индекс строки, звучащей на бите beat (от начала первой ноты до конца последней), иначе −1. */
export function lineAt(lines, beat) {
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.length) continue;
    const last = line[line.length - 1];
    if (beat >= line[0].start && beat < last.start + last.length) return i;
    if (beat < line[0].start) return -1;
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

/** Порядок отстукивания: id нот с ноты fromId (нет такой — с первой) до конца песни. */
export function tapQueue(notes, fromId) {
  const i = notes.findIndex((x) => x.id === fromId);
  return notes.slice(Math.max(0, i)).map((x) => x.id);
}

