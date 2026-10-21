// Раздел «Песни»: список из индекса, поиск, удаление в корзину, перегенерация, минусовка, видео.

import { api, getDefaults, errorText } from './api.js';
import { h, clear, confirmDialog, runAction, toast, fmtDate, debounce, days, songName } from './ui.js';
import { createVideoBlock } from './video-block.js';
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
  if (song.video) tags.push(tag('видео', true));

  const actions = h('div', { class: 'actions' });
  actions.append(
    h('a', { class: 'btn', href: `#new?song=${encodeURIComponent(song.song_id)}`, 'aria-disabled': String(!enabled),
      onclick: (e) => { if (!enabled) e.preventDefault(); } }, 'Перегенерировать'),
    h('button', { type: 'button', disabled: !enabled || !song.audio, title: song.audio ? null : 'У песни нет аудиофайла',
      onclick: (e) => instrumental(e.target, song) }, song.instrumental ? 'Пересоздать минусовку' : 'Минусовка'),
    h('button', { type: 'button', disabled: !enabled, onclick: () => openVideoDialog(song) }, 'Видео…'),
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

/** Текущее #VIDEOGAP песни (из заголовков GET /notes); нет или ошибка — ''. */
async function currentVideoGap(song) {
  try {
    const { headers = [] } = await api.notes(song.song_id);
    const hit = headers.find(([k]) => String(k).toUpperCase() === 'VIDEOGAP');
    return hit ? String(hit[1]).trim().replace(',', '.') : '';
  } catch {
    return '';
  }
}

/** Диалог «Видео…»: своя ссылка с качеством или файл, смещение; у песни с видео — «Убрать видео». */
async function openVideoDialog(song) {
  const name = songName(song.artist, song.title);
  let d = {};
  try { d = await getDefaults(); } catch { /* умолчания блока */ }
  const block = createVideoBlock({ modes: ['url', 'file'], mode: 'url', gap: '0', maxMb: d.max_video_mb,
    heights: d.video_heights, defaultHeight: d.default_video_height });
  let gapTouched = false;
  block.el.querySelector('input[name="videogap"]').addEventListener('input', () => { gapTouched = true; }, { once: true });
  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const submit = h('button', { type: 'button', class: 'primary' }, song.video ? 'Заменить видео' : 'Прикрепить');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  const removeBtn = song.video
    ? h('button', { type: 'button', class: 'danger', onclick: () => removeVideo() }, 'Убрать видео') : null;
  const el = h('dialog', { class: 'video-dlg', 'aria-labelledby': 'video-dlg-title' },
    h('h3', { id: 'video-dlg-title' }, `Видео: ${name}`),
    song.video ? h('div', { class: 'banner warn' },
      `У песни уже есть видео «${song.video}». При замене старое видео удалится.`) : null,
    block.el, errEl,
    h('div', { class: 'actions' }, removeBtn, h('span', { class: 'spacer' }), cancel, submit));
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');
  currentVideoGap(song).then((gap) => { if (!gapTouched && gap) block.setGap(gap); });

  async function send(form, okText) {
    errEl.hidden = true;
    for (const b of [submit, removeBtn]) if (b) b.disabled = true;
    try {
      await api.video(song.song_id, form);
      el.close();
      toast(okText);
    } catch (e) {
      if (!block.showApiError(e)) {
        errEl.textContent = errorText(e);
        errEl.hidden = false;
      }
    } finally {
      for (const b of [submit, removeBtn]) if (b) b.disabled = false;
    }
  }

  submit.addEventListener('click', () => {
    if (block.validate()) send(block.fields(), 'Видео поставлено в очередь');
  });

  async function removeVideo() {
    if (!(await confirmDialog(`Убрать видео у "${name}"? Файл видео удалится, а #VIDEO и #VIDEOGAP уйдут из .txt.`,
      'Убрать', { danger: true }))) return;
    send({ remove: true }, 'Удаление видео поставлено в очередь');
  }
}
