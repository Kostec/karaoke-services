// Поиск текста песни (LRCLIB через /api/lyrics/search): чистая логика без DOM — ради node-тестов.
// Диалог — в new-song.js.
//
// Два разборщика LRC, и это намеренно:
//   stripLrc — для показа: превращает text варианта в читаемый текст (метки срезаны, строки как в файле);
//   parseLrc/lrcPlainText — паритет с lrc_timing.parse_lrc форка UltraSinger (--lyrics_timing):
//     строка с N метками разворачивается N раз, [offset] учитывается. Текст, который уходит
//     в поле вместе с LRC, строится только им — иначе строки не совпадут с метками.

export const MAX_HITS = 10;
export const NEED_FIELDS = 'Укажите исполнителя и название';
export const NOTHING_FOUND = 'Ничего не нашлось — проверьте исполнителя и название';
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

export const SOURCE_LABELS = { lrclib: 'LRCLIB', netease: 'NetEase', genius: 'Genius' };
const SOURCE_ORDER = Object.keys(SOURCE_LABELS);
export const GENIUS_HINT = 'Genius отдаёт текст только браузеру: откройте страницу, скопируйте текст и вставьте в поле вручную';

/** Вариант-ссылка (Genius): есть адрес страницы, текста нет — «Вставить» недоступно. */
export function isLinkHit(hit) {
  return !!hit && !String(hit.text ?? '').trim() && !!hit.url;
}

/** Синхронные первыми, затем порядок источников; остальное — как пришло. */
export function sortHits(list) {
  const rank = (h) => { const i = SOURCE_ORDER.indexOf(h?.source ?? 'lrclib'); return i < 0 ? SOURCE_ORDER.length : i; };
  return [...list]
    .map((h, i) => [h, i])
    .sort((a, b) => (!!b[0].synced - !!a[0].synced) || (rank(a[0]) - rank(b[0])) || (a[1] - b[1]))
    .map(([h]) => h);
}

/** Добавить варианты очередного источника к уже показанным (повтор по id отбрасывается), отсортировать. */
export function mergeHits(prev, next) {
  const seen = new Set((prev || []).map((h) => h.id));
  const fresh = (next || []).filter((h) => !seen.has(h.id));
  return sortHits([...(prev || []), ...fresh]);
}

/** Число непустых строк текста. */
export function hitLines(text) {
  return String(text ?? '').split('\n').filter((l) => l.trim()).length;
}

/** Варианты, которые можно показать: с текстом (или ссылкой Genius), не инструменталы, LRC очищен, до 10. */
export function usableHits(list) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const hit of list) {
    if (!hit || hit.instrumental) continue;
    const text = stripLrc(hit.text);
    if (!text && !hit.url) continue;
    out.push({ ...hit, text, synced: typeof hit.synced === 'string' && hit.synced.trim() ? hit.synced : null });
  }
  return sortHits(out).slice(0, MAX_HITS);
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

// ---------------------------------------------------------------- тайминги строк из LRC (G06)
export const SYNCED_LABEL = 'есть синхронизация';
export const LRC_TIMING_LABEL = 'Использовать тайминги строк';
export const DURATION_MISMATCH = 'Длительность не совпадает с mp3 — тайминги, скорее всего, от другой версии';
export const DURATION_UNKNOWN = 'Длительность mp3 неизвестна — включайте тайминги, если уверены в версии';
export const MAX_DURATION_DIFF_S = 3;

// Как lrc_timing.parse_lrc форка UltraSinger (--lyrics_timing): несколько меток на строку
// разворачиваются по времени, [offset:±мс] сдвигает метки, строки без метки пропускаются.
const LRC_TAG = /^\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]/;
const LRC_OFFSET = /^\s*\[offset:\s*([+-]?\d+)\s*\]\s*$/i;

/** LRC → [[секунды, строка]] по времени. */
export function parseLrc(text) {
  let offset = 0;
  const entries = [];
  for (const raw of String(text ?? '').replace(/^﻿+/, '').split(/\r\n|\r|\n/)) {
    const off = LRC_OFFSET.exec(raw);
    if (off) { offset = Number(off[1]) / 1000; continue; }
    let line = raw.trim();
    const times = [];
    for (let m = LRC_TAG.exec(line); m; m = LRC_TAG.exec(line)) {
      times.push(Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number(m[3]) / 10 ** m[3].length : 0));
      line = line.slice(m[0].length).trimStart();
    }
    if (!times.length) continue;
    line = line.replace(/\s+/g, ' ').trim();
    for (const t of times) entries.push([t, line]);
  }
  return entries
    .map(([t, line]) => [Math.round(Math.max(t - offset, 0) * 1000) / 1000, line])
    .sort((a, b) => a[0] - b[0]);
}

/** Чистый текст для поля из LRC — строки в развёрнутом порядке (строка с N метками — N раз). */
export function lrcPlainText(lrc) {
  return tidy(parseLrc(lrc).map(([, line]) => line));
}

/** Галочка «Использовать тайминги строк»: включена, если длительности LRCLIB и mp3 разнятся ≤ 3 с. */
export function lrcTimingDefault(lrcDuration, mp3Duration) {
  const a = Number(lrcDuration), b = Number(mp3Duration);
  if (!(a > 0) || !(b > 0)) return { checked: false, hint: DURATION_UNKNOWN };
  return Math.abs(a - b) <= MAX_DURATION_DIFF_S ? { checked: true, hint: '' } : { checked: false, hint: DURATION_MISMATCH };
}

// LRC, который держит форма (held):
//   {lrc: string, duration} — вариант из поиска, уходит файловой частью lyrics_lrc;
//   LRC_SAVED — перегенерация с сохранённым source/lyrics.lrc (показать галочку, поле не слать);
//   LRC_DROP — текст явно очищен или заменён на перегенерации: сохранённый удалить (пустая часть);
//   null — ничего: поле не слать. Сервер (api_jobs.generate): нет части — берёт сохранённый,
//   пустая часть — удаляет, пустой текст — удаляет сам.
export const LRC_SAVED = Object.freeze({ lrc: null, duration: null });
export const LRC_DROP = Object.freeze({ lrc: '', duration: null });

/** LRC после правки поля: очищено — сброс (на перегенерации — явный LRC_DROP), иначе тот же. */
export function lrcAfterEdit(held, text, regen = false) {
  if (String(text ?? '').trim()) return held;
  return regen || held === LRC_DROP ? LRC_DROP : null;
}

/** LRC, когда текст поля заменён целиком (вставка варианта, файл): hit — {synced, duration} или null. */
export function lrcForNewText(hit, regen = false) {
  const synced = hit && typeof hit.synced === 'string' && hit.synced.trim() ? hit.synced : null;
  if (synced) return { lrc: synced, duration: hit.duration ?? null };
  return regen ? LRC_DROP : null;
}

/** Часть lyrics_lrc для generateForm: строка — передать ('' — сбросить сохранённый), undefined — не трогать. */
export function lrcFormPart(held) {
  return held && typeof held.lrc === 'string' ? held.lrc : undefined;
}

/** Показывать ли галочку «Использовать тайминги строк». */
export function lrcShown(held) {
  return !!held && held !== LRC_DROP;
}

/** Спрашивать ли «Заменить текст в поле?» перед вставкой. */
export function needsReplaceConfirm(current) {
  return !!String(current ?? '').trim();
}
