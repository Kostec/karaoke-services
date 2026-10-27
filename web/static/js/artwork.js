// Диалоги «Обложка…» и «Фон…» (задание artwork) и выбор обложки из сети (iTunes, Deezer, MusicBrainz).
// openCoverPicker зовёт и форма «Новая песня» (поле обложки → cover_url).
// Чистая логика — artwork-logic.js.

import { api, getDefaults, errorText } from './api.js';
import { h, confirmDialog, toast, songName, openModal } from './ui.js';
import {
  imageError, urlError, hitLabel, hitSize, searchNote, artworkFields, SOURCE_LABELS, IMAGE_ACCEPT,
} from './artwork-logic.js';
import { watchJob } from './song-actions.js';

const DEFAULT_MAX_MB = 10;

function showDialog(cls, labelId, ...body) {
  const el = openModal({ class: `artwork-dlg ${cls}`, 'aria-labelledby': labelId }, ...body);
  return el;
}

async function maxMb() {
  try { return (await getDefaults()).max_cover_mb || DEFAULT_MAX_MB; } catch { return DEFAULT_MAX_MB; }
}

/** Вкладки: [{id, label}] → {el, panels, current(), select(id)}. */
function tabs(list, onChange) {
  let cur = list[0].id;
  const buttons = new Map();
  const el = h('div', { class: 'subtabs', role: 'tablist' }, list.map((t) => {
    const b = h('button', { type: 'button', role: 'tab', onclick: () => select(t.id) }, t.label);
    buttons.set(t.id, b);
    return b;
  }));
  const panels = new Map(list.map((t) => [t.id, h('div', { class: 'artwork-panel', role: 'tabpanel' })]));
  function select(id) {
    cur = id;
    for (const [k, b] of buttons) b.setAttribute('aria-selected', String(k === id));
    for (const [k, p] of panels) p.hidden = k !== id;
    onChange?.(id);
  }
  select(cur);
  return { el, panels, current: () => cur, select };
}

/** Поиск обложки: поля исполнителя и названия, «Найти», сетка вариантов. */
function coverSearch({ artist = '', title = '' } = {}, onPick) {
  const artistIn = h('input', { type: 'text', value: artist, autocomplete: 'off' });
  const titleIn = h('input', { type: 'text', value: title, autocomplete: 'off' });
  const go = h('button', { type: 'button', class: 'primary' }, 'Найти');
  const grid = h('div', { class: 'cover-hits', role: 'listbox', 'aria-label': 'Варианты обложки' });
  const note = h('p', { class: 'small muted cover-note', role: 'status' });
  const err = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  let picked = null;
  let seq = 0;

  function pick(hit, card) {
    picked = hit;
    for (const c of grid.children) c.setAttribute('aria-selected', String(c === card));
    onPick?.(hit);
  }

  function card(hit) {
    const img = h('img', { src: hit.thumb || hit.url, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' });
    const c = h('button', { type: 'button', class: 'cover-hit', role: 'option', 'aria-selected': 'false',
      title: hitLabel(hit), onclick: () => pick(hit, c), ondblclick: () => { pick(hit, c); onPick?.(hit, true); } },
    img, h('span', { class: 'src' }, SOURCE_LABELS[hit.source] || hit.source),
    h('span', { class: 'al' }, hit.album || songName(hit.artist, hit.title)),
    h('span', { class: 'sz' }, hitSize(hit)));
    // у Cover Art Archive не у каждого релиза есть картинка — такой вариант просто прячем
    img.addEventListener('error', () => { if (picked === hit) picked = null; c.remove(); });
    return c;
  }

  async function run() {
    const my = ++seq;
    err.hidden = true;
    picked = null;
    onPick?.(null);
    if (!artistIn.value.trim() && !titleIn.value.trim()) {
      note.textContent = 'Укажите исполнителя или название';
      return;
    }
    go.disabled = true;
    note.textContent = 'Ищем в iTunes, Deezer и MusicBrainz…';
    grid.replaceChildren();
    try {
      const res = await api.coverSearch(artistIn.value.trim(), titleIn.value.trim());
      if (my !== seq) return;
      grid.replaceChildren(...res.items.map(card));
      note.textContent = searchNote(res);
    } catch (e) {
      if (my !== seq) return;
      note.textContent = '';
      err.textContent = errorText(e, 'Сервисы обложек недоступны, попробуйте позже');
      err.hidden = false;
    } finally {
      if (my === seq) go.disabled = false;
    }
  }

  go.addEventListener('click', run);
  for (const inp of [artistIn, titleIn]) {
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
  }
  const el = h('div', { class: 'cover-search' },
    h('div', { class: 'row2' },
      h('label', { class: 'field' }, h('span', {}, 'Исполнитель'), artistIn),
      h('label', { class: 'field' }, h('span', {}, 'Название'), titleIn)),
    go, err, grid, note);
  return { el, run, picked: () => picked };
}

/** Свой файл: выбор, проверка на месте. */
function filePanel(limitMb) {
  const input = h('input', { type: 'file', accept: IMAGE_ACCEPT });
  const err = h('div', { class: 'field-error', hidden: true, role: 'alert' });
  const el = h('div', { class: 'drop' },
    h('div', {}, `Выберите jpg, png или webp до ${limitMb} МБ`), input, err);
  return {
    el,
    file: () => input.files?.[0] || null,
    validate() {
      const msg = imageError(input.files?.[0] || null, limitMb);
      err.textContent = msg || '';
      err.hidden = !msg;
      return !msg;
    },
    showError(msg) { err.textContent = msg; err.hidden = false; },
    input,
  };
}

/** Ссылка на картинку. */
function urlPanel() {
  const input = h('input', { type: 'url', placeholder: 'https://…/cover.jpg', autocomplete: 'off' });
  const err = h('div', { class: 'field-error', hidden: true, role: 'alert' });
  const el = h('label', { class: 'field' }, h('span', {}, 'Адрес картинки'), input, err);
  return {
    el,
    url: () => input.value.trim(),
    validate() {
      const msg = urlError(input.value);
      err.textContent = msg || '';
      err.hidden = !msg;
      input.classList.toggle('invalid', !!msg);
      return !msg;
    },
    showError(msg) { err.textContent = msg; err.hidden = false; input.classList.add('invalid'); },
    input,
  };
}

function toForm(songId, fields) {
  const fd = new FormData();
  fd.append('song_id', songId);
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) fd.append(k, v);
  return fd;
}

/** Общий диалог задания artwork: kind — cover|background; current — имя текущего файла или null. */
async function openArtworkDialog(song, env, kind) {
  const isCover = kind === 'cover';
  const name = songName(song.artist, song.title);
  const limit = await maxMb();
  const list = isCover
    ? [{ id: 'search', label: 'Найти в сети' }, { id: 'file', label: 'Свой файл…' }, { id: 'url', label: 'По ссылке' }]
    : [{ id: 'file', label: 'Свой файл…' }, { id: 'url', label: 'По ссылке' }];
  const submit = h('button', { type: 'button', class: 'primary' }, 'Поставить');
  // tabs() сразу выбирает первую вкладку и зовёт onChange — до присваивания t и search
  let ready = false;
  const t = tabs(list, () => { if (ready) syncSubmit(); });
  const search = isCover ? coverSearch({ artist: song.artist, title: song.title }, (hit, now) => {
    syncSubmit();
    if (hit && now) submit.click();
  }) : null;
  const file = filePanel(limit);
  const link = urlPanel();
  if (search) t.panels.get('search').append(search.el);
  t.panels.get('file').append(file.el);
  t.panels.get('url').append(link.el);

  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const currentEl = h('div', { class: 'mrow artwork-current small muted' });
  const removeBtn = h('button', { type: 'button', class: 'danger', hidden: true },
    isCover ? 'Убрать обложку' : 'Убрать фон');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  const titleId = `artwork-dlg-${kind}`;
  const el = showDialog(isCover ? 'cover-dlg' : 'bg-dlg', titleId,
    h('h3', { id: titleId }, `${isCover ? 'Обложка' : 'Фон'} — ${name}`),
    isCover ? null : h('p', { class: 'small muted' },
      'Картинка пишется в ', h('code', {}, '#BACKGROUND'), ' и показывается за текстом в UltraStar и в шапке песни.'),
    currentEl, t.el, ...t.panels.values(), errEl,
    h('div', { class: 'actions' }, removeBtn, h('span', { class: 'spacer' }), cancel, submit));

  function syncSubmit() {
    submit.disabled = t.current() === 'search' && !search?.picked();
  }
  ready = true;
  syncSubmit();
  if (search) search.run();

  // текущая картинка: у списка «Песен» фона нет в данных — спрашиваем страницу песни
  let current = isCover ? (song.cover || null) : null;
  const showCurrent = () => {
    currentEl.replaceChildren();
    if (!current) { currentEl.append(isCover ? 'Обложки нет' : 'Фон не задан'); removeBtn.hidden = true; return; }
    currentEl.append(h('img', { class: isCover ? 'thumb' : 'bgprev', alt: '',
      src: api.fileUrl(song.song_id, current) }), h('span', {}, `Сейчас: ${current}`));
    removeBtn.hidden = false;
  };
  showCurrent();
  api.songDetails(song.song_id).then((d) => {
    current = d?.media?.[isCover ? 'cover' : 'background'] || null;
    showCurrent();
  }).catch(() => { /* остаётся то, что известно */ });

  async function send(fields, okText) {
    errEl.hidden = true;
    submit.disabled = removeBtn.disabled = true;
    try {
      const job = await api.artwork(song.song_id, toForm(song.song_id, fields));
      el.close();
      watchJob(job, () => env.reload?.());
      toast(okText);
    } catch (e) {
      const msg = errorText(e);
      if (e?.data?.field === 'image' && t.current() === 'file') file.showError(msg);
      else if (e?.data?.field === 'url' && t.current() === 'url') link.showError(msg);
      else { errEl.textContent = msg; errEl.hidden = false; }
    } finally {
      removeBtn.disabled = false;
      syncSubmit();
    }
  }

  submit.addEventListener('click', () => {
    const mode = t.current();
    if (mode === 'file' && !file.validate()) return;
    if (mode === 'url' && !link.validate()) return;
    if (mode === 'search' && !search.picked()) return;
    send(artworkFields({ kind, mode, file: file.file(), url: link.url(), hit: search?.picked() }),
      isCover ? 'Обложка поставлена в очередь' : 'Фон поставлен в очередь');
  });
  removeBtn.addEventListener('click', async () => {
    const what = isCover ? 'обложку' : 'фон';
    if (!(await confirmDialog(`Убрать ${what} у "${name}"? Файл удалится, а строка ${isCover ? '#COVER' : '#BACKGROUND'} уйдёт из .txt.`,
      'Убрать', { danger: true }))) return;
    send(artworkFields({ kind, mode: 'remove' }), isCover ? 'Удаление обложки поставлено в очередь' : 'Удаление фона поставлено в очередь');
  });
  return el;
}

/** «Обложка…»: найти в сети, свой файл или ссылка → задание artwork kind=cover. */
export function openCoverDialog(song, env) {
  return openArtworkDialog(song, env, 'cover');
}

/** «Фон…»: свой файл или ссылка, «Убрать фон» → задание artwork kind=background. */
export function openBackgroundDialog(song, env) {
  return openArtworkDialog(song, env, 'background');
}

/** Выбор обложки из сети без задания (форма «Новая песня»): Promise<CoverHit|null>. */
export function openCoverPicker({ artist = '', title = '' } = {}) {
  return new Promise((resolve) => {
    let result = null;
    const ok = h('button', { type: 'button', class: 'primary', disabled: true }, 'Выбрать');
    const search = coverSearch({ artist, title }, (hit, now) => {
      ok.disabled = !hit;
      if (hit && now) { result = hit; el.close(); }
    });
    const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
    const el = showDialog('cover-dlg', 'cover-picker-title',
      h('h3', { id: 'cover-picker-title' }, 'Обложка из сети'), search.el,
      h('div', { class: 'actions' }, cancel, ok));
    ok.addEventListener('click', () => { result = search.picked(); el.close(); });
    el.addEventListener('close', () => resolve(result));
    if (artist.trim() || title.trim()) search.run();
  });
}
