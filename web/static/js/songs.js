// Раздел «Песни»: хранилище, поиск, свёрнутые «Фильтры (N)», «…» раздела (Обновить, Копировать
// показанные, Мои теги), список из индекса; у песни — ссылка на её страницу, «▶» и «…» с действиями.
// Режим «Выбрать»: чекбоксы на карточках, «Все показанные», нижняя панель .bulk-bar с действиями
// над отмеченными (выбор — по song_id, переживает смену фильтра, сбрасывается сменой хранилища).

import { api, getDefaults } from './api.js';
import { h, clear, runAction, toast, fmtDate, debounce } from './ui.js';
import { onEditorsChanged } from './extensions.js';
import { menuButton, closeMenu } from './menu.js';
import { playToggle, adoptPlayButton } from './player.js';
import {
  songMenuItems, openCopyDialog, openBulkTagsDialog, bulkDelete, bulkInstrumental, bulkZip, showBulkResult,
} from './song-actions.js';
import { createSelection, selectionLabel, bulkButtons } from './select-logic.js';
import { tagChip, openTagsManager } from './tags-ui.js';
import { tagsById, songTagList } from './tags-logic.js';
import {
  filterSongs, artistCounts, parseFilter, filterParams, isDefaultFilter, activeFilterCount, originOf,
  SORTS, DEFAULT_FILTER, NO_TAG,
} from './songs-filter.js';

let trashDays = null; // из /api/defaults (TRASH_DAYS)

const TARGET_KEY = 'songs.target';
const FILTERS_OPEN_KEY = 'songs.filtersOpen';

let root, listEl, infoEl, bannerEl, emptyEl, errEl, targetSel, resetBtn, filtersBtn, filtersEl;
const ctl = {}; // элементы фильтров: q, artist, instrumental, video, duet, cover, origin, tag, sort
let data = null;
let tags = []; // свои теги: [{id, name, color, count}]
let byId = new Map();
let target = ''; // выбранное хранилище ('' — основная цель)
let filter = { ...DEFAULT_FILTER };
let shown = []; // песни под фильтром (для «Копировать показанные»)
let scanTimer = null;
let seq = 0;
let waits = 0; // повторные запросы, пока идёт (или ещё не прошло) сканирование
const sel = createSelection(); // отмеченные песни (song_id)
let selecting = false; // режим «Выбрать»
let selTarget = null; // хранилище, к которому относится выбор
let selectBtn, allEl, allBox, allText, barEl, barCount, barSub;
const barBtns = {}; // кнопки панели: tags, copy, zip, instrumental, delete

function stored(key) {
  try { return localStorage.getItem(key) || ''; } catch { return ''; }
}

function store(key, value) {
  try {
    if (value) localStorage.setItem(key, value); else localStorage.removeItem(key);
  } catch { /* приватное окно */ }
}

function choice(name, label, options) {
  const sel = h('select', { name, 'aria-label': label },
    options.map(([value, text]) => h('option', { value }, text)));
  sel.addEventListener('change', () => setFilter({ [name]: sel.value }));
  ctl[name] = sel;
  return h('label', { class: 'songs-filter' }, h('span', {}, label), sel);
}

const resetFilters = () => setFilter({ ...DEFAULT_FILTER, q: filter.q, sort: filter.sort });

function setFiltersOpen(open) {
  filtersEl.hidden = !open;
  filtersBtn.setAttribute('aria-expanded', String(open));
  store(FILTERS_OPEN_KEY, open ? '1' : '');
}

export function mount(section) {
  root = section;
  targetSel = h('select', { 'aria-label': 'Хранилище', class: 'songs-target' });
  targetSel.addEventListener('change', () => {
    target = targetSel.value;
    store(TARGET_KEY, target);
    syncHash();
    load();
  });
  ctl.q = h('input', { type: 'search', placeholder: 'Поиск по исполнителю или названию', 'aria-label': 'Поиск песен' });
  ctl.q.addEventListener('input', debounce(() => setFilter({ q: ctl.q.value }), 250));
  ctl.artist = h('select', { name: 'artist', 'aria-label': 'Исполнитель' });
  ctl.artist.addEventListener('change', () => setFilter({ artist: ctl.artist.value }));
  const yesNo = [['all', 'все'], ['yes', 'есть'], ['no', 'нет']];
  resetBtn = h('button', { type: 'button', onclick: resetFilters }, 'Сбросить фильтры');
  filtersBtn = h('button', { type: 'button', class: 'filters-btn', 'aria-controls': 'songs-filters',
    onclick: () => setFiltersOpen(filtersEl.hidden) }, 'Фильтры');
  const sectionMenu = menuButton(sectionMenuItems, { title: 'Ещё действия раздела' });
  selectBtn = h('button', { type: 'button', class: 'select-btn', 'aria-pressed': 'false',
    title: 'Отметить несколько песен', onclick: () => setSelecting(!selecting) }, 'Выбрать');
  allBox = h('input', { type: 'checkbox' });
  allBox.addEventListener('change', () => {
    sel.setAll(shown.map((s) => s.song_id), allBox.checked);
    syncSelection();
  });
  allText = h('span', {}, 'Все показанные');
  allEl = h('label', { class: 'check select-all', hidden: true }, allBox, allText);
  barEl = buildBar();
  infoEl = h('div', { class: 'small muted' });
  bannerEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  errEl = h('div', { class: 'banner err', hidden: true });
  emptyEl = h('div', { class: 'card empty', hidden: true });
  listEl = h('div', { class: 'songs' });
  filtersEl = h('div', { class: 'songs-filters', id: 'songs-filters', hidden: true },
    h('label', { class: 'songs-filter' }, h('span', {}, 'Исполнитель'), ctl.artist),
    choice('instrumental', 'Минусовка', yesNo),
    choice('video', 'Видео', yesNo),
    choice('duet', 'Дуэт', [['all', 'все'], ['duet', 'дуэт'], ['solo', 'соло']]),
    choice('cover', 'Обложка', yesNo),
    choice('origin', 'Происхождение',
      [['all', 'все'], ['generated', 'сгенерирована здесь'], ['import', 'импорт'], ['foreign', 'чужая']]),
    choice('tag', 'Мой тег', [['', 'все']]),
    choice('sort', 'Сортировка', SORTS.map((x) => [x.id, x.label])),
    h('div', { class: 'songs-filter songs-reset' }, resetBtn));
  root.append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Песни')),
    h('div', { class: 'songs-tools with-select' }, targetSel, ctl.q, filtersBtn, selectBtn, sectionMenu),
    filtersEl,
    bannerEl, errEl,
    h('div', { class: 'songs-summary' }, infoEl, allEl),
    emptyEl, listEl, barEl);
  setFiltersOpen(stored(FILTERS_OPEN_KEY) === '1');
  onEditorsChanged(() => data && render());
}

export function show(params) {
  const p = params || new URLSearchParams();
  target = p.get('target') || stored(TARGET_KEY);
  filter = parseFilter(p);
  syncControls();
  syncHash();
  load();
  loadTags();
  getDefaults().then((d) => { trashDays = d.trash_days; }).catch(() => {});
}

export function hide() {
  clearTimeout(scanTimer);
  closeMenu();
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
  renderTagChoice();
  const n = activeFilterCount(filter);
  clear(filtersBtn).append('Фильтры');
  if (n) filtersBtn.append(h('span', { class: 'badge' }, String(n)));
  filtersBtn.setAttribute('aria-label', n ? `Фильтры, включено ${n}` : 'Фильтры');
}

function setFilter(patch) {
  filter = { ...filter, ...patch };
  syncControls();
  syncHash();
  if (data) render();
}

async function loadTags() {
  try {
    tags = (await api.tags()).tags || [];
  } catch {
    tags = []; // без своих тегов список всё равно работает
  }
  byId = tagsById(tags);
  renderTagChoice();
  if (data) render();
}

function renderTagChoice() {
  const opts = [['', 'все'], ...tags.map((t) => [t.id, t.name]), [NO_TAG, 'без своих тегов']];
  if (filter.tag && filter.tag !== NO_TAG && !byId.has(filter.tag)) opts.push([filter.tag, 'тег удалён']);
  clear(ctl.tag).append(...opts.map(([value, text]) => h('option', { value }, text)));
  ctl.tag.value = filter.tag;
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
      store(TARGET_KEY, '');
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

/** Перечитать список и свои теги, если раздел на экране (после заданий и правок). */
function reloadVisible() {
  if (root && !root.hidden) { load(); loadTags(); }
}

async function rescan() {
  await runAction(null, () => api.rescanTarget(data?.target?.id || target));
  clearTimeout(scanTimer);
  scanTimer = setTimeout(load, 500);
}

function outputOk() {
  return !data || !data.output || data.output.ok !== false;
}

function targetName(t) {
  return t?.name || t?.label || '';
}

function env() {
  return { targets: data?.targets || [], currentTargetId: data?.target?.id, outputOk: outputOk(), trashDays,
    reload: reloadVisible };
}

function sectionMenuItems() {
  const others = (data?.targets || []).filter((t) => t.id !== data?.target?.id);
  const copyOff = !outputOk() ? 'Хранилище недоступно'
    : !shown.length ? 'Нет показанных песен'
      : !others.length ? 'Других хранилищ нет — добавьте их в «Настройках»' : false;
  return [
    { label: 'Обновить', disabled: data?.scanning ? 'Идёт сканирование…' : false, onSelect: rescan },
    { label: `Копировать показанные (${shown.length})…`, disabled: copyOff,
      onSelect: () => openCopyDialog(shown, env(), { bulk: true }) },
    { label: 'Мои теги…', onSelect: () => openTagsManager({ onChanged: reloadVisible }) },
    { label: 'Проверить библиотеку', href: '#check' },
  ];
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
  // выбор — внутри одного хранилища: сменилось — сброс; пропавшие из индекса песни — снять
  if (selTarget !== (data.target?.id ?? null)) { sel.clear(); selTarget = data.target?.id ?? null; }
  const present = new Set(data.items.map((s) => s.song_id));
  sel.setAll(sel.ids().filter((id) => !present.has(id)), false);
  const parts = [label];
  parts.push(data.scanned_at ? `просканировано ${fmtDate(data.scanned_at)}` : 'ещё не сканировалось');
  if (data.scanning) parts.push('идёт сканирование…');
  parts.push(`показано ${shown.length} из ${total}`);
  infoEl.textContent = parts.join(' · ');
  resetBtn.hidden = isDefaultFilter({ ...filter, q: '' });

  clear(emptyEl);
  if (!total) {
    emptyEl.append(
      h('p', {}, 'В хранилище пока нет песен'),
      h('p', { class: 'small muted' }, label),
      h('a', { class: 'btn primary', href: '#new' }, 'Добавить песню'));
  } else if (!shown.length) {
    emptyEl.append(h('p', {}, 'Ничего не найдено по фильтрам'),
      h('button', { type: 'button', onclick: () => setFilter({ ...DEFAULT_FILTER, sort: filter.sort }) }, 'Сбросить'));
  }
  emptyEl.hidden = shown.length > 0;
  clear(listEl).append(...shown.map(card));
  syncSelection();
}

// ---------------------------------------------------------------- режим «Выбрать»

function setSelecting(on) {
  selecting = on;
  if (!on) sel.clear();
  if (data) render(); else syncSelection();
}

function chosenSongs() {
  const items = new Map((data?.items || []).map((s) => [s.song_id, s]));
  return sel.ids().map((id) => items.get(id)).filter(Boolean);
}

function bulkEnv() {
  return { ...env(), afterBulk: (res) => {
    if (res?.removed) sel.setAll(res.removed, false);
    syncSelection();
    reloadVisible();
  } };
}

function barButton(key, label, run, cls = '') {
  const b = h('button', { type: 'button', class: cls || null }, label);
  b.addEventListener('click', () => {
    if (b.getAttribute('aria-disabled') === 'true') { toast(b.title, 'err'); return; }
    run(chosenSongs());
  });
  barBtns[key] = b;
  return b;
}

function buildBar() {
  barCount = h('span', {});
  barSub = h('small', {});
  const copy = (songs) => openCopyDialog(songs, bulkEnv(), { bulk: true, what: 'выбранные',
    onResult: (res, toName) => showBulkResult(`Копирование в «${toName}»`, res, songs, { queue: true }) });
  return h('div', { class: 'bulk-bar', hidden: true, role: 'region', 'aria-label': 'Действия с отмеченными' },
    h('div', { class: 'bulk-in' },
      h('div', { class: 'cnt', 'aria-live': 'polite' }, barCount, barSub),
      barButton('tags', 'Теги…', (songs) => openBulkTagsDialog(songs, bulkEnv())),
      barButton('copy', 'Копировать…', copy),
      barButton('zip', 'Скачать zip', (songs) => bulkZip(songs)),
      barButton('instrumental', 'Минусовка', (songs) => bulkInstrumental(songs, bulkEnv())),
      barButton('delete', 'Удалить', (songs) => bulkDelete(songs, bulkEnv()), 'danger'),
      h('span', { class: 'sp' }),
      h('button', { type: 'button', title: 'Снять выбор и выйти из режима выбора', 'aria-label': 'Снять выбор',
        onclick: () => setSelecting(false) }, '✕')));
}

/** Шапка, «Все показанные», карточки и панель — по текущему выбору (без пересборки списка). */
function syncSelection() {
  if (!selectBtn) return;
  selectBtn.classList.toggle('primary', selecting);
  selectBtn.setAttribute('aria-pressed', String(selecting));
  selectBtn.textContent = selecting ? 'Выбрать ✓' : 'Выбрать';
  const shownIds = shown.map((s) => s.song_id);
  allEl.hidden = !selecting || !shown.length;
  allBox.checked = sel.allIn(shownIds);
  allText.textContent = `Все показанные (${shown.length})`;
  for (const el of listEl.children) {
    const on = sel.has(el.dataset.id);
    el.classList.toggle('sel', selecting && on);
    const box = el.querySelector('input.pick');
    if (box) box.checked = on;
  }
  barEl.hidden = !selecting;
  const label = selectionLabel(sel.size, sel.hiddenCount(shownIds));
  barCount.textContent = label.main;
  barSub.textContent = label.sub;
  barSub.hidden = !label.sub;
  const others = (data?.targets || []).filter((t) => t.id !== data?.target?.id).length;
  const state = bulkButtons({ count: sel.size, outputOk: outputOk(), others });
  for (const [key, b] of Object.entries(barBtns)) {
    const off = state[key];
    b.setAttribute('aria-disabled', String(!!off));
    b.classList.toggle('off', !!off);
    b.title = off || '';
  }
}

function tag(text, on, extra = '') {
  return h('span', { class: `tag${on ? ' on' : ''}${extra ? ` ${extra}` : ''}` }, text);
}

/** Встроенные метки песни (как были) — общие для списка и страницы песни. */
export function builtinTags(song) {
  const tags = [];
  if (song.instrumental) tags.push(tag('есть минусовка', true));
  const origin = originOf(song);
  if (origin === 'import') tags.push(tag('импорт', true));
  else if (origin === 'generated') tags.push(tag('создана сервисом', true));
  if (song.source === 'usdb') tags.push(tag('из usdb', true));
  if (song.is_duet) tags.push(tag('дуэт', true));
  if (song.video) tags.push(tag('видео', true));
  for (const c of song.pending_copies || []) tags.push(tag(`ждёт копирования в «${c.name}»`, false, 'wait'));
  return tags;
}

export function songHref(song) {
  return `#song?id=${encodeURIComponent(song.song_id)}`;
}

function card(song) {
  const href = songHref(song);
  const cover = song.cover
    ? h('img', { class: 'cover', src: api.coverUrl(song.song_id), alt: '', loading: 'lazy', onerror: (e) => e.target.replaceWith(noCover()) })
    : noCover();
  const userTags = songTagList(song, byId).map((t) => tagChip(t, {
    title: 'Показать песни с этим тегом',
    onClick: () => { setFilter({ tag: t.id }); toast(`Фильтр: тег «${t.name}»`); },
  }));
  const play = h('button', { type: 'button', class: 'play', disabled: !song.audio,
    title: song.audio ? 'Послушать' : 'У песни нет аудиофайла' }, '▶');
  if (song.audio) {
    const url = api.audioUrl(song.song_id);
    adoptPlayButton(play, url);
    play.addEventListener('click', () => playToggle(play, url));
  } else {
    play.setAttribute('aria-label', 'У песни нет аудиофайла');
  }
  const more = menuButton(() => songMenuItems(song, env()));

  const pick = selecting ? h('input', { type: 'checkbox', class: 'pick',
    'aria-label': `Отметить «${song.title || song.txt_name}»` }) : null;
  pick?.addEventListener('change', () => {
    if (pick.checked !== sel.has(song.song_id)) sel.toggle(song.song_id);
    syncSelection();
  });
  const el = h('article', { class: `card song${selecting ? ' picking' : ''}`, dataset: { id: song.song_id } },
    pick,
    h('a', { class: 'song-cover', href, tabindex: '-1', 'aria-hidden': 'true' }, cover),
    h('div', { class: 'song-info' },
      h('a', { class: 'song-link', href },
        h('span', { class: 'song-title' }, song.title || song.txt_name),
        h('span', { class: 'song-artist' }, song.artist || 'Исполнитель не указан')),
      h('div', { class: 'tags' }, builtinTags(song), userTags)),
    h('div', { class: 'song-quick' }, play, more));
  // клик по пустому месту карточки — тоже открыть страницу песни
  el.addEventListener('click', (e) => {
    if (e.target.closest('a, button, input, select, label')) return;
    if (window.getSelection?.().toString()) return;
    if (selecting) { sel.toggle(song.song_id); syncSelection(); return; } // в режиме выбора — отметить
    location.hash = href;
  });
  return el;
}

function noCover() {
  return h('div', { class: 'cover', 'aria-hidden': 'true' }, '♪');
}
