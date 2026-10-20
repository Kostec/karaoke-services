// Редактор строк (G05.1, G05.2): чистые операции над строками нот из GET /api/songs/{id}/notes.
//
// Строка: {break_beat: number|null, notes: [{type, start, length, pitch, text}]}.
// break_beat — бит разрыва «- N» после строки (у последней строки — null).
// Все функции возвращают новый массив строк и не меняют входной; тайминги и высоты
// нот не трогаются никогда — сервер (web/app/notes.py) это проверяет.

/** Время бита в мс (спека §9): GAP_ms + beat * 60000 / (BPM * 4). */
export function beatToMs(beat, gap, bpm) {
  return (Number(gap) || 0) + (beat * 60000) / (Number(bpm) * 4);
}

/** Отрезок строки в мс: от начала первой ноты до конца последней. */
export function lineRange(line, gap, bpm) {
  const first = line.notes[0];
  const last = line.notes[line.notes.length - 1];
  return { start: beatToMs(first.start, gap, bpm), end: beatToMs(last.start + last.length, gap, bpm) };
}

/** Текст строки: слоги подряд (пробелы — внутри слогов, как в .txt). */
export function lineText(line) {
  return line.notes.map((x) => x.text).join('').trim();
}

function copyLine(line, patch = {}) {
  return { break_beat: line.break_beat, notes: line.notes.map((x) => ({ ...x })), ...patch };
}

/** Исправить текст слога. */
export function setSyllable(lines, li, ni, text) {
  return lines.map((line, i) => (i !== li ? line
    : copyLine(line, { notes: line.notes.map((x, j) => (j === ni ? { ...x, text } : { ...x })) })));
}

/** Склеить строку li со следующей: разрыв между ними исчезает. */
export function mergeWithNext(lines, li) {
  if (li < 0 || li >= lines.length - 1) throw new Error('Это последняя строка — склеивать не с чем');
  const a = lines[li], b = lines[li + 1];
  const merged = { break_beat: b.break_beat, notes: [...a.notes, ...b.notes].map((x) => ({ ...x })) };
  return [...lines.slice(0, li), merged, ...lines.slice(li + 2)];
}

/** Разбить строку li перед нотой ni: новый разрыв — конец последней ноты первой части. */
export function splitBefore(lines, li, ni) {
  const line = lines[li];
  if (ni <= 0) throw new Error('Перед первым слогом строки разбивать нечего');
  if (ni >= line.notes.length) throw new Error('Нет такого слога');
  const head = line.notes.slice(0, ni).map((x) => ({ ...x }));
  const tail = line.notes.slice(ni).map((x) => ({ ...x }));
  const last = head[head.length - 1];
  return [...lines.slice(0, li),
    { break_beat: last.start + last.length, notes: head },
    { break_beat: line.break_beat, notes: tail },
    ...lines.slice(li + 1)];
}

/** Удалить ноту; опустевшая строка исчезает. Последнюю ноту песни удалить нельзя. */
export function deleteNote(lines, li, ni) {
  const total = lines.reduce((s, l) => s + l.notes.length, 0);
  if (total <= 1) throw new Error('В песне должна остаться хотя бы одна нота');
  const line = lines[li];
  if (line.notes.length > 1) {
    return lines.map((l, i) => (i !== li ? l : copyLine(l, { notes: l.notes.filter((_, j) => j !== ni).map((x) => ({ ...x })) })));
  }
  const out = lines.filter((_, i) => i !== li);
  if (li === lines.length - 1) out[out.length - 1] = copyLine(out[out.length - 1], { break_beat: null });
  return out;
}

/** Тело PUT /api/songs/{id}/notes. */
export function toPayload(lines) {
  return { lines: lines.map((l) => ({ break_beat: l.break_beat, notes: l.notes.map((x) => ({ ...x })) })) };
}

/** Есть ли несохранённые правки относительно исходных строк. */
export function isDirty(lines, original) {
  return JSON.stringify(toPayload(lines)) !== JSON.stringify(toPayload(original));
}

/** Можно ли проиграть строку: true или причина (для подсказки неактивной ▶). */
export function canPlay(song, data) {
  if (!song?.audio) return 'У песни нет аудиофайла';
  if (!(Number(data?.bpm) > 0)) return 'В песне нет #BPM — время строк неизвестно';
  return true;
}
