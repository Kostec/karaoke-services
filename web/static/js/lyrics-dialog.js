// Диалог «Найти текст» (LRCLIB через /api/lyrics/search): один на страницу, общий для формы
// новой песни и строки трека в «Импорт» → «Папка». Чистая логика — в lyrics-search.js.

import { api, errorText } from './api.js';
import { h, clear, songName } from './ui.js';
import { usableHits, previewLines, fmtSeconds, NOTHING_FOUND, SYNCED_LABEL } from './lyrics-search.js';

let dlg = null;
let seq = 0; // ответ, пришедший после закрытия или нового поиска, игнорируется

function ensure() {
  if (dlg) return dlg;
  const status = h('p', { class: 'small muted' });
  const list = h('div', { class: 'lyrics-hits' });
  const close = h('button', { type: 'button', onclick: () => dlg.el.close() }, 'Закрыть');
  const el = h('dialog', { class: 'lyrics-dlg', 'aria-labelledby': 'lyrics-dlg-title' },
    h('h3', { id: 'lyrics-dlg-title' }, 'Найти текст'), status, list, h('div', { class: 'actions' }, close));
  el.addEventListener('close', () => { seq++; });
  document.body.append(el);
  dlg = { el, status, list };
  return dlg;
}

/**
 * Открыть диалог и найти варианты текста «artist — title».
 * onPick(hit) → true/Promise<true> — закрыть диалог (false — оставить список открытым);
 * onSettled() — поиск закончился (успехом или ошибкой), даже если диалог уже закрыт;
 * hint — подсказка над списком; hits — уже найденные варианты (без повторного запроса).
 */
export async function openLyricsDialog({ artist, title, onPick, onSettled, hint, hits: known }) {
  const d = ensure();
  const my = ++seq;
  d.status.textContent = `Ищу текст «${songName(artist, title)}»…`;
  d.status.className = 'small muted';
  clear(d.list);
  if (!d.el.open) {
    if (typeof d.el.showModal === 'function') d.el.showModal(); else d.el.setAttribute('open', '');
  }
  let hits = [], error = '';
  if (known) {
    hits = known;
    onSettled?.();
  } else {
    try {
      hits = usableHits((await api.lyricsSearch(artist, title)).items);
    } catch (e) {
      error = errorText(e); // 503 и прочее — текст detail сервера
    } finally {
      onSettled?.();
    }
  }
  if (my !== seq) return;
  if (error || !hits.length) {
    d.status.textContent = error || NOTHING_FOUND;
    d.status.className = error ? 'banner err' : 'banner warn';
    return;
  }
  d.status.textContent = hint || 'Выберите вариант — текст попадёт в поле «Текст песни».';
  for (const hit of hits) {
    const meta = [hit.album, fmtSeconds(hit.duration), hit.synced ? SYNCED_LABEL : ''].filter(Boolean).join(' · ');
    const pick = async () => { if (await onPick(hit)) d.el.close(); };
    d.list.append(h('div', { class: 'card lyrics-hit' },
      h('div', {}, h('strong', {}, songName(hit.artist, hit.title))),
      meta ? h('div', { class: 'small muted' }, meta) : null,
      h('div', { class: 'small lyrics-preview' }, previewLines(hit.text).join('\n')),
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primary', onclick: pick }, 'Вставить'))));
  }
}
