// Раздел «Песни»: список из индекса, поиск, удаление в корзину, перегенерация, минусовка.

import { api, getDefaults } from './api.js';
import { h, clear, confirmDialog, runAction, fmtDate, debounce, days, songName } from './ui.js';
import { songEditors, onEditorsChanged } from './extensions.js';

let trashDays = null; // из /api/defaults (TRASH_DAYS)

let root, search, listEl, infoEl, bannerEl, emptyEl, errEl, rescanBtn;
let data = null;
let scanTimer = null;
let seq = 0;
let waits = 0; // повторные запросы, пока идёт (или ещё не прошло) сканирование

export function mount(section) {
  root = section;
  search = h('input', { type: 'search', placeholder: 'Поиск по исполнителю или названию', 'aria-label': 'Поиск песен' });
  rescanBtn = h('button', { type: 'button', onclick: rescan }, 'Обновить');
  infoEl = h('div', { class: 'small muted' });
  bannerEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  errEl = h('div', { class: 'banner err', hidden: true });
  emptyEl = h('div', { class: 'card empty', hidden: true });
  listEl = h('div', { class: 'songs' });
  root.append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Песни')),
    h('div', { class: 'songs-tools' }, search, rescanBtn),
    infoEl, bannerEl, errEl, emptyEl, listEl);
  search.addEventListener('input', debounce(load, 300));
  onEditorsChanged(() => data && render());
}

export function show() {
  load();
  getDefaults().then((d) => { trashDays = d.trash_days; }).catch(() => {});
}

export function hide() {
  clearTimeout(scanTimer);
}

export async function load() {
  const my = ++seq;
  try {
    const res = await api.songs(search.value.trim());
    if (my !== seq) return;
    data = res;
    errEl.hidden = true;
    render();
    clearTimeout(scanTimer);
    waits = res.scanning || !res.scanned_at ? waits + 1 : 0;
    if (waits && waits < 30 && !root.hidden) scanTimer = setTimeout(load, 2000);
  } catch (e) {
    if (my !== seq) return;
    errEl.textContent = `Не удалось получить список песен: ${e.detail}`;
    errEl.hidden = false;
  }
}

async function rescan() {
  await runAction(rescanBtn, () => api.rescan());
  clearTimeout(scanTimer);
  scanTimer = setTimeout(load, 500);
}

function outputOk() {
  return !data || !data.output || data.output.ok !== false;
}

function render() {
  const out = data.output || {};
  const label = out.label || data.target?.label || '';
  bannerEl.hidden = outputOk();
  // out.error уже начинается с «Папка результата недоступна: …» (сервер)
  bannerEl.textContent = `${out.error || 'Папка результата недоступна'}. Показан последний индекс, действия с файлами отключены.`;
  const parts = [`Папка: ${label}`];
  parts.push(data.scanned_at ? `просканировано ${fmtDate(data.scanned_at)}` : 'ещё не сканировалась');
  if (data.scanning) parts.push('идёт сканирование…');
  parts.push(`песен: ${data.items.length}`);
  infoEl.textContent = parts.join(' · ');
  rescanBtn.disabled = !!data.scanning;

  const q = search.value.trim();
  clear(emptyEl);
  if (!data.items.length) {
    if (q) {
      emptyEl.append(h('p', {}, `Ничего не найдено по запросу «${q}»`));
    } else {
      emptyEl.append(
        h('p', {}, 'В папке пока нет песен'),
        h('p', { class: 'small muted' }, label),
        h('a', { class: 'btn primary', href: '#new' }, 'Добавить песню'));
    }
  }
  emptyEl.hidden = data.items.length > 0;
  const coll = new Intl.Collator('ru', { sensitivity: 'base', numeric: true });
  const items = [...data.items].sort((a, b) => coll.compare(a.artist, b.artist) || coll.compare(a.title, b.title));
  clear(listEl).append(...items.map(card));
}

function tag(text, on) {
  return h('span', { class: `tag${on ? ' on' : ''}` }, text);
}

function card(song) {
  const enabled = outputOk();
  const cover = song.cover
    ? h('img', { class: 'cover', src: api.coverUrl(song.song_id), alt: '', loading: 'lazy', onerror: (e) => e.target.replaceWith(noCover()) })
    : noCover();
  const tags = [];
  if (song.instrumental) tags.push(tag('есть минусовка', true));
  if (song.source) tags.push(tag('импорт', true));
  else if (song.own) tags.push(tag('создана сервисом', true));
  if (song.source === 'usdb') tags.push(tag('из usdb', true));
  if (song.is_duet) tags.push(tag('дуэт', true));

  const actions = h('div', { class: 'actions' });
  actions.append(
    h('a', { class: 'btn', href: `#new?song=${encodeURIComponent(song.song_id)}`, 'aria-disabled': String(!enabled),
      onclick: (e) => { if (!enabled) e.preventDefault(); } }, 'Перегенерировать'),
    h('button', { type: 'button', disabled: !enabled || !song.audio, title: song.audio ? null : 'У песни нет аудиофайла',
      onclick: (e) => instrumental(e.target, song) }, song.instrumental ? 'Пересоздать минусовку' : 'Минусовка'),
  );
  // Места для редакторов (таск 07): кнопки появляются, когда редактор зарегистрирован.
  const editors = h('span', { class: 'song-editors', style: 'display:contents' });
  for (const ed of songEditors()) {
    const st = ed.enabled ? ed.enabled(song) : true;
    editors.append(h('button', {
      type: 'button', dataset: { editor: ed.kind }, disabled: !enabled || st !== true,
      title: typeof st === 'string' ? st : null,
      onclick: () => ed.open(song, { reload: load }),
    }, ed.label));
  }
  actions.append(editors,
    h('button', { type: 'button', class: 'danger', disabled: !enabled, onclick: (e) => remove(e.target, song) }, 'Удалить'));

  return h('article', { class: 'card song', dataset: { id: song.song_id } },
    cover,
    h('div', { class: 'song-info' },
      h('div', { class: 'song-title' }, song.title || song.txt_name),
      h('div', { class: 'song-artist' }, song.artist || 'Исполнитель не указан'),
      h('div', { class: 'small muted' }, song.rel_dir),
      h('div', { class: 'tags' }, tags)),
    actions);
}

function noCover() {
  return h('div', { class: 'cover', 'aria-hidden': 'true' }, '♪');
}

async function remove(btn, song) {
  const name = songName(song.artist, song.title);
  const term = trashDays == null ? 'Песня уйдёт в корзину' : `Песня уйдёт в корзину на ${days(trashDays)}`;
  if (!(await confirmDialog(`Удалить "${name}"? ${term}`, 'Удалить', { danger: true }))) return;
  const res = await runAction(btn, () => api.deleteSong(song.song_id), `«${name}» перемещена в корзину`);
  if (res) load();
}

async function instrumental(btn, song) {
  const name = songName(song.artist, song.title);
  if (song.instrumental
    && !(await confirmDialog(`Пересоздать минусовку для "${name}"? Старый файл уйдёт в корзину.`, 'Пересоздать'))) return;
  await runAction(btn, () => api.instrumental(song.song_id, !!song.instrumental), 'Минусовка поставлена в очередь');
}
