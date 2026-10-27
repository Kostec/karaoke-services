// Выбор песен в «Песнях» (режим «Выбрать») — чистая логика без DOM ради node-тестов:
// набор отмеченных id, «скрыты фильтром», итог массовой операции, состояние кнопок нижней панели.

import { plural, STORAGE_OFF as UNAVAILABLE } from './ui.js';

export const MAX_BULK_SONGS = 1000; // как web/app/params.py
export const MAX_ZIP_SONGS = 500;
export { UNAVAILABLE };
export const NOTHING = 'Ничего не выбрано';
const NO_OTHERS = 'Других хранилищ нет — добавьте их в «Настройках»';

/** Набор отмеченных песен по song_id (порядок отметки сохраняется). Смена фильтра его не трогает. */
export function createSelection() {
  const set = new Set();
  return {
    has: (id) => set.has(id),
    /** Переключить; вернуть, отмечена ли теперь. */
    toggle(id) {
      if (set.has(id)) { set.delete(id); return false; }
      set.add(id);
      return true;
    },
    /** Отметить все `ids` (on=false — снять их), прочие отмеченные остаются. */
    setAll(ids, on = true) {
      for (const id of ids) { if (on) set.add(id); else set.delete(id); }
    },
    /** Все `ids` отмечены (пустой список — нет). */
    allIn(ids) {
      const list = [...ids];
      return list.length > 0 && list.every((id) => set.has(id));
    },
    clear: () => set.clear(),
    ids: () => [...set],
    get size() { return set.size; },
    /** Сколько отмеченных не видно под фильтром (shownIds — массив или Set показанных id). */
    hiddenCount(shownIds) {
      const shown = shownIds instanceof Set ? shownIds : new Set(shownIds);
      let n = 0;
      for (const id of set) if (!shown.has(id)) n += 1;
      return n;
    },
  };
}

/** Подпись панели: {main: «Выбрано N», sub: «ещё M скрыты фильтром» | ''}. */
export function selectionLabel(size, hidden) {
  if (!size) return { main: NOTHING, sub: '' };
  const sub = hidden ? `ещё ${hidden} ${plural(hidden, 'скрыта', 'скрыты', 'скрыты')} фильтром` : '';
  return { main: `Выбрано ${size}`, sub };
}

/** Кнопки панели: {tags, copy, zip, instrumental, delete} → false (можно) или причина.
 *  Недоступное хранилище гасит всё, кроме «Теги…» (теги — в базе сервиса, файлы не трогаются). */
export function bulkButtons({ count = 0, outputOk = true, others = 0 } = {}) {
  if (!count) return { tags: NOTHING, copy: NOTHING, zip: NOTHING, instrumental: NOTHING, delete: NOTHING };
  const many = count > MAX_BULK_SONGS ? `За один раз — не больше ${MAX_BULK_SONGS} песен` : false;
  const off = outputOk === false ? UNAVAILABLE : false;
  return {
    tags: many,
    copy: off || many || (others ? false : NO_OTHERS),
    zip: off || (count > MAX_ZIP_SONGS ? `В один архив — не больше ${MAX_ZIP_SONGS} песен` : false),
    instrumental: off || many,
    delete: off || many,
  };
}

/** Итог массовой операции → {text: «Готово: N. Пропущено: M», lines: [{song_id, name, reason}]}.
 *  result — ответ любого массового эндпоинта: {updated}|{removed}|{queued}, skipped (список
 *  {song_id, reason} или число у копирования), errors [{song_id, detail}]; nameOf(id) → «А — Т». */
export function bulkSummary(result = {}, nameOf = (id) => id) {
  const name = (id) => nameOf(id) || id;
  const done = typeof result.updated === 'number' ? result.updated
    : Array.isArray(result.removed) ? result.removed.length
      : Array.isArray(result.queued) ? result.queued.length : 0;
  const lines = [];
  let skipped = 0;
  if (Array.isArray(result.skipped)) {
    for (const s of result.skipped) lines.push({ song_id: s.song_id, name: name(s.song_id), reason: s.reason });
    skipped += result.skipped.length;
  } else if (result.skipped) {
    lines.push({ song_id: null, name: '', reason: `уже есть в хранилище: ${result.skipped}` });
    skipped += result.skipped;
  }
  for (const e of result.errors || []) lines.push({ song_id: e.song_id, name: name(e.song_id), reason: e.detail });
  skipped += (result.errors || []).length;
  return { text: skipped ? `Готово: ${done}. Пропущено: ${skipped}` : `Готово: ${done}`, lines };
}
