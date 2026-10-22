// Раздел «Песни»: хранилище, фильтры, список из индекса, zip, «Копировать в…», удаление в корзину,
// перегенерация, минусовка, видео.

import { api, getDefaults, errorText, probeDownload, JOB_FINAL } from './api.js';
import { h, clear, confirmDialog, runAction, toast, fmtDate, debounce, days, songName } from './ui.js';
import { createVideoBlock } from './video-block.js';
import { songEditors, onEditorsChanged } from './extensions.js';
import {
  filterSongs, artistCounts, parseFilter, filterParams, isDefaultFilter, SORTS, DEFAULT_FILTER,
} from './songs-filter.js';

let trashDays = null; // из /api/defaults (TRASH_DAYS)

const TARGET_KEY = 'songs.target';
const IMPORT_SOURCES = ['usdb', 'files', 'url'];

let root, listEl, infoEl, bannerEl, emptyEl, errEl, rescanBtn, targetSel, copyAllBtn, resetBtn;
const ctl = {}; // элементы фильтров: q, artist, instrumental, video, duet, cover, origin, sort
let data = null;
let target = ''; // выбранное хранилище ('' — основная цель)
let filter = { ...DEFAULT_FILTER };
let shown = []; // песни под фильтром (для «Копировать показанные»)
let scanTimer = null;
let seq = 0;
let waits = 0; // повторные запросы, пока идёт (или ещё не прошло) сканирование
const watched = new Set(); // задания (видео, минусовка), по завершении которых список перечитывается
const WATCH_MS = 3000;

function stored() {
  try { return localStorage.getItem(TARGET_KEY) || ''; } catch { return ''; }
}

function remember(id) {
  try {
    if (id) localStorage.setItem(TARGET_KEY, id); else localStorage.removeItem(TARGET_KEY);
  } catch { /* приватное окно */ }
}

/** Следить за заданием песни: дошло до конца (done/failed/cancelled) — перечитать список, если он на экране. */
function watchJob(job) {
  if (!job?.id || watched.has(job.id)) return;
  watched.add(job.id);
  const tick = async () => {
    try {
      const j = await api.job(job.id);
      if (JOB_FINAL.includes(j.state)) {
        watched.delete(job.id);
        if (root && !root.hidden) load();
        return;
      }
    } catch (e) {
      if (e?.status === 404) { watched.delete(job.id); return; } // задание удалено
    }
    setTimeout(tick, WATCH_MS);
  };
  setTimeout(tick, WATCH_MS);
}

function choice(name, label, options) {
  const sel = h('select', { name, 'aria-label': label },
    options.map(([value, text]) => h('option', { value }, text)));
  sel.addEventListener('change', () => setFilter({ [name]: sel.value }));
  ctl[name] = sel;
  return h('label', { class: 'songs-filter' }, h('span', {}, label), sel);
}

const resetFilters = () => setFilter({ ...DEFAULT_FILTER, sort: filter.sort });

export function mount(section) {
  root = section;
  targetSel = h('select', { 'aria-label': 'Хранилище' });
  targetSel.addEventListener('change', () => {
    target = targetSel.value;
    remember(target);
    syncHash();
    load();
  });
  rescanBtn = h('button', { type: 'button', onclick: rescan }, 'Обновить');
  ctl.q = h('input', { type: 'search', placeholder: 'Поиск по исполнителю или названию', 'aria-label': 'Поиск песен' });
  ctl.q.addEventListener('input', debounce(() => setFilter({ q: ctl.q.value }), 250));
  ctl.artist = h('select', { name: 'artist', 'aria-label': 'Исполнитель' });
  ctl.artist.addEventListener('change', () => setFilter({ artist: ctl.artist.value }));
  const yesNo = [['all', 'все'], ['yes', 'есть'], ['no', 'нет']];
  resetBtn = h('button', { type: 'button', onclick: resetFilters }, 'Сбросить фильтры');
  copyAllBtn = h('button', { type: 'button', onclick: () => openCopyDialog(shown, { bulk: true }) });
  infoEl = h('div', { class: 'small muted' });
  bannerEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  errEl = h('div', { class: 'banner err', hidden: true });
  emptyEl = h('div', { class: 'card empty', hidden: true });
  listEl = h('div', { class: 'songs' });
  root.append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Песни')),
    h('div', { class: 'songs-tools' },
      h('label', { class: 'songs-filter songs-target' }, h('span', {}, 'Хранилище'), targetSel), rescanBtn),
    bannerEl, errEl,
    h('div', { class: 'songs-filters' },
      h('div', { class: 'songs-search' }, ctl.q),
      h('label', { class: 'songs-filter' }, h('span', {}, 'Исполнитель'), ctl.artist),
      choice('instrumental', 'Минусовка', yesNo),
      choice('video', 'Видео', yesNo),
      choice('duet', 'Дуэт', [['all', 'все'], ['duet', 'дуэт'], ['solo', 'соло']]),
      choice('cover', 'Обложка', yesNo),
      choice('origin', 'Происхождение',
        [['all', 'все'], ['generated', 'сгенерирована здесь'], ['import', 'импорт'], ['foreign', 'чужая']]),
      choice('sort', 'Сортировка', SORTS.map((x) => [x.id, x.label])),
      resetBtn),
    h('div', { class: 'songs-summary' }, infoEl, copyAllBtn),
    emptyEl, listEl);
  onEditorsChanged(() => data && render());
}

export function show(params) {
  const p = params || new URLSearchParams();
  target = p.get('target') || stored();
  filter = parseFilter(p);
  syncControls();
  syncHash();
  load();
  getDefaults().then((d) => { trashDays = d.trash_days; }).catch(() => {});
}

export function hide() {
  clearTimeout(scanTimer);
}

/** Фильтры и хранилище — в адрес (#songs?…) без перехода (replaceState не будит роутер). */
function syncHash() {
  const p = new URLSearchParams(filterParams(filter));
  if (target) p.set('target', target);
  const qs = p.toString();
  const hash = `#songs${qs ? `?${qs}` : ''}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

function syncControls() {
  if (document.activeElement !== ctl.q) ctl.q.value = filter.q;
  for (const k of ['instrumental', 'video', 'duet', 'cover', 'origin', 'sort']) ctl[k].value = filter[k];
}

function setFilter(patch) {
  filter = { ...filter, ...patch };
  syncControls();
  syncHash();
  if (data) render();
}

export async function load() {
  const my = ++seq;
  try {
    let res;
    try {
      res = await api.targetSongs(target);
    } catch (e) {
      if (e?.status !== 400 || e.data?.field !== 'target' || !target) throw e;
      target = ''; // хранилище удалено из настроек — показать основную цель
      remember('');
      syncHash();
      res = await api.targetSongs('');
    }
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
  await runAction(rescanBtn, () => api.rescanTarget(data?.target?.id || target));
  clearTimeout(scanTimer);
  scanTimer = setTimeout(load, 500);
}

function outputOk() {
  return !data || !data.output || data.output.ok !== false;
}

function targetName(t) {
  return t?.name || t?.label || '';
}

function otherTargets() {
  return (data?.targets || []).filter((t) => t.id !== data?.target?.id);
}

function renderTargets() {
  clear(targetSel).append(...(data.targets || []).map((t) => h('option', { value: t.id }, targetName(t))));
  targetSel.value = data.target?.id || '';
}

function renderArtists() {
  const counts = artistCounts(data.items);
  const opts = [h('option', { value: '' }, `все (${counts.length})`),
    ...counts.map((a) => h('option', { value: a.artist }, `${a.artist} (${a.count})`))];
  if (filter.artist && !counts.some((a) => a.artist === filter.artist)) {
    opts.push(h('option', { value: filter.artist }, `${filter.artist} (0)`));
  }
  clear(ctl.artist).append(...opts);
  ctl.artist.value = filter.artist;
}

function render() {
  const out = data.output || {};
  const name = targetName(data.target);
  const label = data.target?.label || name;
  renderTargets();
  renderArtists();
  bannerEl.hidden = outputOk();
  // out.error начинается с «Папка результата недоступна: …» (сервер) — причина после двоеточия
  const reason = String(out.error || '').replace(/^Папка результата недоступна:\s*/, '') || 'нет связи';
  bannerEl.textContent = `Хранилище «${name}» недоступно: ${reason}. Показан последний индекс, действия с файлами отключены.`;

  shown = filterSongs(data.items, filter);
  const total = data.items.length;
  const parts = [label];
  parts.push(data.scanned_at ? `просканировано ${fmtDate(data.scanned_at)}` : 'ещё не сканировалось');
  if (data.scanning) parts.push('идёт сканирование…');
  parts.push(`показано ${shown.length} из ${total}`);
  infoEl.textContent = parts.join(' · ');
  rescanBtn.disabled = !!data.scanning;
  resetBtn.hidden = isDefaultFilter(filter);
  copyAllBtn.textContent = `Копировать показанные (${shown.length}) в…`;
  copyAllBtn.disabled = !shown.length || !otherTargets().length || !outputOk();

  clear(emptyEl);
  if (!total) {
    emptyEl.append(
      h('p', {}, 'В хранилище пока нет песен'),
      h('p', { class: 'small muted' }, label),
      h('a', { class: 'btn primary', href: '#new' }, 'Добавить песню'));
  } else if (!shown.length) {
    emptyEl.append(h('p', {}, 'Ничего не найдено по фильтрам'),
      h('button', { type: 'button', onclick: resetFilters }, 'Сбросить'));
  }
  emptyEl.hidden = shown.length > 0;
  clear(listEl).append(...shown.map(card));
}

function tag(text, on, extra = '') {
  return h('span', { class: `tag${on ? ' on' : ''}${extra ? ` ${extra}` : ''}` }, text);
}

/** «Скачать .zip»: сначала `?check=1` (503/404 — тост вместо битого архива), потом одно скачивание. */
async function downloadZip(e, song) {
  e.preventDefault();
  const link = e.currentTarget;
  if (link.getAttribute('aria-busy') === 'true') return;
  link.setAttribute('aria-busy', 'true');
  try {
    await probeDownload(`${link.href}?check=1`); // лёгкая проверка: файлы не читаются, поток один
    const a = h('a', { href: link.href, download: '' });
    document.body.append(a);
    a.click();
    a.remove();
  } catch (err) {
    toast(`Не удалось скачать «${songName(song.artist, song.title)}»: ${err.detail || err.message}`, 'err');
  } finally {
    link.removeAttribute('aria-busy');
  }
}

function card(song) {
  const enabled = outputOk();
  const cover = song.cover
    ? h('img', { class: 'cover', src: api.coverUrl(song.song_id), alt: '', loading: 'lazy', onerror: (e) => e.target.replaceWith(noCover()) })
    : noCover();
  const tags = [];
  if (song.instrumental) tags.push(tag('есть минусовка', true));
  if (IMPORT_SOURCES.includes(song.source)) tags.push(tag('импорт', true));
  else if (song.source === 'generated' || song.own) tags.push(tag('создана сервисом', true));
  if (song.source === 'usdb') tags.push(tag('из usdb', true));
  if (song.is_duet) tags.push(tag('дуэт', true));
  if (song.video) tags.push(tag('видео', true));
  for (const c of song.pending_copies || []) tags.push(tag(`ждёт копирования в «${c.name}»`, false, 'wait'));

  const others = otherTargets();
  const actions = h('div', { class: 'actions' });
  actions.append(
    h('a', { class: 'btn', href: `#new?song=${encodeURIComponent(song.song_id)}`, 'aria-disabled': String(!enabled),
      onclick: (e) => { if (!enabled) e.preventDefault(); } }, 'Перегенерировать'),
    h('button', { type: 'button', disabled: !enabled || !song.audio, title: song.audio ? null : 'У песни нет аудиофайла',
      onclick: (e) => instrumental(e.target, song) }, song.instrumental ? 'Пересоздать минусовку' : 'Минусовка'),
    h('button', { type: 'button', disabled: !enabled, onclick: () => openVideoDialog(song) }, 'Видео…'),
    h('a', { class: 'btn', href: api.zipUrl(song.song_id), download: '', 'aria-disabled': String(!enabled),
      onclick: (e) => (enabled ? downloadZip(e, song) : e.preventDefault()) }, 'Скачать .zip'),
    h('button', { type: 'button', disabled: !enabled || !others.length,
      title: others.length ? null : 'Других хранилищ нет — добавьте их в «Настройках»',
      onclick: () => openCopyDialog([song]) }, 'Копировать в…'),
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

/** Диалог «Копировать в…»: хранилище (кроме текущего), «если уже есть», у «показанных» — «только недостающие». */
function openCopyDialog(songs, { bulk = false } = {}) {
  const others = otherTargets();
  if (!songs.length || !others.length) return;
  const title = bulk ? `Копировать показанные (${songs.length}) в…`
    : `Копировать «${songName(songs[0].artist, songs[0].title)}» в…`;
  const radios = others.map((t, i) => h('label', { class: 'check' },
    h('input', { type: 'radio', name: 'copy-target', value: t.id, checked: i === 0 }), targetName(t)));
  const repl = h('input', { type: 'radio', name: 'copy-exists', value: 'replace' });
  const onlyMissing = bulk ? h('input', { type: 'checkbox', name: 'only-missing', checked: true }) : null;
  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const submit = h('button', { type: 'button', class: 'primary' }, 'Копировать');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  const existsBox = h('fieldset', {}, h('legend', {}, 'Если песня там уже есть'),
    h('label', { class: 'check' }, h('input', { type: 'radio', name: 'copy-exists', value: 'skip', checked: true }), 'пропустить'),
    h('label', { class: 'check' }, repl, 'заменить (прежняя версия уйдёт в корзину)'));
  const el = h('dialog', { class: 'copy-dlg', 'aria-labelledby': 'copy-dlg-title' },
    h('h3', { id: 'copy-dlg-title' }, title),
    h('fieldset', {}, h('legend', {}, 'Хранилище'), radios),
    bulk ? h('label', { class: 'check' }, onlyMissing, 'только недостающие') : null,
    existsBox, errEl,
    h('div', { class: 'actions' }, cancel, submit));
  // «только недостающие» — уже имеющиеся пропускаются, выбор «заменить» не нужен
  const syncExists = () => { existsBox.disabled = !!onlyMissing?.checked; };
  onlyMissing?.addEventListener('change', syncExists);
  syncExists();
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');

  submit.addEventListener('click', async () => {
    const to = el.querySelector('input[name="copy-target"]:checked')?.value;
    const toName = targetName(others.find((t) => t.id === to));
    const replace = !onlyMissing?.checked && repl.checked;
    const body = { song_ids: songs.map((s) => s.song_id), target_id: to, replace,
      only_missing: bulk ? onlyMissing.checked : !replace };
    errEl.hidden = true;
    submit.disabled = true;
    try {
      const res = await api.copySongs(body);
      el.close();
      const n = res.queued.length;
      const errs = res.errors?.length ? `; не скопировано ${res.errors.length}: ${res.errors[0].detail}` : '';
      if (bulk) toast(`В «${toName}»: поставлено ${n}, пропущено ${res.skipped} (уже есть)${errs}`, errs ? 'err' : '');
      else if (n) toast(`Копирование в «${toName}» поставлено в очередь`);
      else if (res.skipped) toast(`Уже есть в «${toName}» — пропущено`);
      else toast(`Не скопировано${errs}`, 'err');
      load(); // пометка «ждёт копирования»
    } catch (e) {
      errEl.textContent = errorText(e);
      errEl.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
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
  watchJob(await runAction(btn, () => api.instrumental(song.song_id, !!song.instrumental), 'Минусовка поставлена в очередь'));
}

/** Текущее #VIDEOGAP песни (из заголовков GET /notes); нет или ошибка — ''. */
async function currentVideoGap(song) {
  try {
    const { headers = [] } = await api.notes(song.song_id);
    const hit = headers.find(([k]) => String(k).toUpperCase() === 'VIDEOGAP');
    return hit ? String(hit[1]).trim().replace(',', '.') : '0';
  } catch {
    return null; // не узнали — смещение не отправляется, чтобы не стереть #VIDEOGAP
  }
}

/** Диалог «Видео…»: своя ссылка с качеством или файл, смещение; у песни с видео — «Убрать видео». */
async function openVideoDialog(song) {
  const name = songName(song.artist, song.title);
  let d = {};
  try { d = await getDefaults(); } catch { /* умолчания блока */ }
  const block = createVideoBlock({ modes: ['url', 'file'], mode: 'url', gap: '0', maxMb: d.max_video_mb,
    heights: d.video_heights, defaultHeight: d.default_video_height, exts: d.video_exts });
  let gapKnown = false; // текущее смещение песни прочитано (иначе без правки videogap не уходит)
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
  currentVideoGap(song).then((gap) => {
    if (gap === null) return;
    gapKnown = true;
    if (!block.state().gapTouched) block.setGap(gap);
  });

  async function send(form, okText) {
    errEl.hidden = true;
    for (const b of [submit, removeBtn]) if (b) b.disabled = true;
    try {
      const job = await api.video(song.song_id, form);
      el.close();
      watchJob(job); // метка «видео» на карточке обновится сама
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
    if (!block.validate()) return;
    const fields = block.fields();
    if (!gapKnown && !block.state().gapTouched) delete fields.videogap;
    send(fields, 'Видео поставлено в очередь');
  });

  async function removeVideo() {
    if (!(await confirmDialog(`Убрать видео у "${name}"? Файл видео удалится, а #VIDEO и #VIDEOGAP уйдут из .txt.`,
      'Убрать', { danger: true }))) return;
    send({ remove: true }, 'Удаление видео поставлено в очередь');
  }
}
