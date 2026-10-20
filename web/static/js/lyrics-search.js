// Поиск текста песни (LRCLIB через /api/lyrics/search): чистая логика без DOM — ради node-тестов.
// Диалог — в new-song.js.

export const MAX_HITS = 10;
export const NEED_FIELDS = 'Укажите исполнителя и название';
export const NOTHING_FOUND = 'Ничего не нашлось — проверьте исполнителя и название';
export const UNAVAILABLE = 'Сервис текстов недоступен, попробуйте позже';
export const REPLACE_QUESTION = 'Заменить текст в поле?';

const TIME_TAG = /\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]/g;
const META_LINE = /^\s*\[[a-zA-Z#]+:[^\]]*\]\s*$/;

/** Переводы строк → \n, пробелы в конце строк и пустые строки по краям убраны, не больше одной пустой подряд. */
function tidy(lines) {
  return lines.map((l) => l.trimEnd()).join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

/** LRC → чистый текст: метки [мм:сс.xx] срезаются, строки метаданных [ar:…] убираются. */
export function stripLrc(text) {
  const out = [];
  for (const line of String(text ?? '').replace(/\r\n?/g, '\n').split('\n')) {
    TIME_TAG.lastIndex = 0;
    const hasTime = TIME_TAG.test(line);
    if (META_LINE.test(line) && !hasTime) continue;
    out.push(hasTime ? line.replace(TIME_TAG, '').trim() : line);
  }
  return tidy(out);
}

/** Варианты, которые можно показать: с текстом, не инструменталы, текст очищен от LRC, до 10. */
export function usableHits(list) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const hit of list) {
    if (!hit || hit.instrumental) continue;
    const text = stripLrc(hit.text);
    if (!text) continue;
    out.push({ ...hit, text });
    if (out.length >= MAX_HITS) break;
  }
  return out;
}

/** Первые n непустых строк текста — превью варианта. */
export function previewLines(text, n = 3) {
  return String(text ?? '').split('\n').map((l) => l.trim()).filter(Boolean).slice(0, n);
}

/** Длительность в секундах → «м:сс»; нет/0 — пусто. */
export function fmtSeconds(sec) {
  const s = Math.round(Number(sec) || 0);
  if (s <= 0) return '';
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Почему поиск нельзя запустить (пусто — можно). */
export function searchBlocker(artist, title) {
  return String(artist ?? '').trim() && String(title ?? '').trim() ? '' : NEED_FIELDS;
}

/** Спрашивать ли «Заменить текст в поле?» перед вставкой. */
export function needsReplaceConfirm(current) {
  return !!String(current ?? '').trim();
}
