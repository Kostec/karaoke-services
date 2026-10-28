// Диалог «Найти текст» (LRCLIB, NetEase, Genius через /api/lyrics/search): один на страницу, общий для
// формы новой песни и строки трека в «Импорт» → «Папка». Чистая логика — в lyrics-search.js.
// Источники опрашиваются параллельно по одному (source=…), варианты дорисовываются по мере ответа.

import { api, errorText } from './api.js';
import { h, clear, songName } from './ui.js';
import {
  usableHits, mergeHits, previewLines, fmtSeconds, hitLines, isLinkHit, stripLrc,
  NOTHING_FOUND, SYNCED_LABEL, SOURCE_LABELS, GENIUS_HINT,
} from './lyrics-search.js';

export const ALL_DOWN = 'Сервисы текстов недоступны, попробуйте позже';
const PASTE_LABEL = 'Вставьте сюда текст со страницы Genius';

let dlg = null;
let seq = 0; // ответ, пришедший после закрытия или нового поиска, игнорируется

function ensure() {
  if (dlg) return dlg;
  const status = h('p', { class: 'small muted', role: 'status' });
  const failed = h('div', { class: 'lyrics-failed small' });
  const list = h('div', { class: 'lyrics-hits' });
  const listView = h('div', {}, status, failed, list);
  const preview = h('div', { class: 'lyrics-view', hidden: true });
  const close = h('button', { type: 'button', onclick: () => dlg.el.close() }, 'Закрыть');
  const el = h('dialog', { class: 'lyrics-dlg', 'aria-labelledby': 'lyrics-dlg-title' },
    h('h3', { id: 'lyrics-dlg-title' }, 'Найти текст'), listView, preview, h('div', { class: 'actions' }, close));
  el.addEventListener('close', () => { seq++; });
  document.body.append(el);
  dlg = { el, status, failed, list, listView, preview };
  return dlg;
}

function showList(d) {
  d.preview.hidden = true;
  d.listView.hidden = false;
}

// адрес варианта приходит из внешнего API: в href попадает только страница Genius (не javascript:…)
const SAFE_LINK_PREFIX = 'https://genius.com/';
const safeUrl = (url) => typeof url === 'string' && url.startsWith(SAFE_LINK_PREFIX);
/** Варианты для показа: ссылка с чужим адресом отбрасывается. */
const shownHits = (list) => usableHits(list).filter((x) => !isLinkHit(x) || safeUrl(x.url));

function sourceLink(hit) {
  if (!safeUrl(hit.url)) return null;
  const name = SOURCE_LABELS[hit.source] || 'источнике';
  return h('a', { href: hit.url, target: '_blank', rel: 'noopener noreferrer' }, `Открыть на ${name} ↗`);
}

function metaLine(hit, extra = []) {
  return [SOURCE_LABELS[hit.source] || hit.source, hit.album, fmtSeconds(hit.duration),
    hit.synced ? SYNCED_LABEL : '', ...extra].filter(Boolean).join(' · ');
}

/** Панель просмотра: текст целиком (или ссылка + поле вставки для Genius) → «Вставить» / «← К списку». */
function openPreview(d, hit, onPick) {
  const link = isLinkHit(hit);
  const paste = link ? h('textarea', { rows: 12, name: 'lyrics-paste', 'aria-label': PASTE_LABEL, class: 'lyrics-paste' }) : null;
  const body = link ? paste : h('pre', { class: 'lyrics-full' }, hit.text);
  const lines = h('span', {});
  const pick = h('button', { type: 'button', class: 'primary' }, 'Вставить');
  const current = () => (link ? stripLrc(paste.value) : hit.text);
  const refresh = () => {
    const n = hitLines(current());
    lines.textContent = n ? `строк: ${n}` : '';
    pick.disabled = !n;
  };
  paste?.addEventListener('input', refresh);
  pick.addEventListener('click', async () => {
    const text = current();
    const out = link ? { ...hit, text, synced: null, url: null } : hit;
    if (await onPick(out)) d.el.close();
  });
  clear(d.preview);
  d.preview.append(
    h('div', {}, h('strong', {}, songName(hit.artist, hit.title))),
    h('div', { class: 'small muted' }, metaLine(hit), ' ', lines),
    link ? h('p', { class: 'small' }, sourceLink(hit), ' · ', PASTE_LABEL.replace('Вставьте', 'вставьте')) : null,
    body,
    h('div', { class: 'actions' },
      h('button', { type: 'button', onclick: () => showList(d) }, '← К списку'), pick));
  refresh();
  d.listView.hidden = true;
  d.preview.hidden = false;
  (paste || pick).focus();
}

function renderHits(d, hits, onPick) {
  clear(d.list);
  for (const hit of hits) {
    const link = isLinkHit(hit);
    const actions = [h('button', { type: 'button', onclick: () => openPreview(d, hit, onPick) }, 'Просмотр')];
    if (!link) {
      actions.push(h('button', {
        type: 'button', class: 'primary',
        onclick: async () => { if (await onPick(hit)) d.el.close(); },
      }, 'Вставить'));
    }
    d.list.append(h('div', { class: 'card lyrics-hit' },
      h('div', {}, h('strong', {}, songName(hit.artist, hit.title))),
      h('div', { class: 'small muted' }, metaLine(hit)),
      link ? h('div', { class: 'small' }, sourceLink(hit), ' — ', GENIUS_HINT)
        : h('div', { class: 'small lyrics-preview' }, previewLines(hit.text).join('\n')),
      h('div', { class: 'actions' }, actions)));
  }
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
  clear(d.failed);
  showList(d);
  if (!d.el.open) {
    if (typeof d.el.showModal === 'function') d.el.showModal(); else d.el.setAttribute('open', '');
  }
  let hits = [];
  const fail = [];
  const render = () => {
    if (my !== seq) return;
    renderHits(d, hits, onPick);
    clear(d.failed);
    for (const f of fail) d.failed.append(h('div', { class: 'banner warn' }, f));
  };
  const finish = () => {
    if (my !== seq) return;
    const text = hint || 'Выберите вариант — текст попадёт в поле «Текст песни».';
    if (hits.length) {
      d.status.textContent = text;
      d.status.className = 'small muted';
    } else if (fail.length >= Object.keys(SOURCE_LABELS).length) {
      d.status.textContent = ALL_DOWN;
      d.status.className = 'banner err';
    } else {
      d.status.textContent = NOTHING_FOUND;
      d.status.className = 'banner warn';
    }
  };
  if (known) {
    hits = known.filter((x) => !isLinkHit(x) || safeUrl(x.url));
    onSettled?.();
    render();
    finish();
    return;
  }
  const ids = Object.keys(SOURCE_LABELS);
  try {
    await Promise.all(ids.map(async (id) => {
      try {
        const res = await api.lyricsSearch(artist, title, id);
        if (my !== seq) return;
        hits = mergeHits(hits, shownHits(res.items));
        if (hits.length) d.status.textContent = `Найдено вариантов: ${hits.length}…`;
      } catch (e) {
        if (my !== seq) return;
        fail.push(e?.status === 503 && e.message ? errorText(e) : `${SOURCE_LABELS[id]} не ответил`);
      }
      render();
    }));
  } finally {
    onSettled?.();
  }
  finish();
}
