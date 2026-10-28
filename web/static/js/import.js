// Раздел «Импорт»: готовые UltraStar-песни из usdb, из файлов (zip или .txt + аудио + обложка),
// по ссылке (zip или GitHub) и из папки с компьютера. Сначала разбор (inspect), затем по заданию
// на отмеченную песню. Папка (G08): готовые песни — тем же разбором, прочие mp3 — на генерацию
// (по строке на трек, текст ищется сам по одному треку). «Ссылка» на музыку (YouTube, VK-видео,
// Яндекс Музыка…) — /api/link/inspect и та же группа генерации, только звук — audio_url.

import { api, getDefaults, inspectForm, importForm, generateForm, errorText } from './api.js';
import { createVideoBlock, videoChoices } from './video-block.js';

let videoDefaults = {}; // max_video_mb, video_heights, default_video_height, video_exts из /api/defaults

/** Блок «Видео» карточки: source — ссылка для «из ссылки…» ('' — варианта нет), pack — видео в архиве. */
function videoBlock({ source = '', pack = false, label, gap, onChange }) {
  return createVideoBlock({ ...videoChoices({ source: !!source, pack }), sourceUrl: source,
    labels: label ? { source: label } : undefined, gap: gap ?? '', maxMb: videoDefaults.max_video_mb,
    heights: videoDefaults.video_heights, defaultHeight: videoDefaults.default_video_height,
    exts: videoDefaults.video_exts, onChange });
}
import { h, clear, toast, field, debounce, songName } from './ui.js';
import { readId3 } from './id3.js';
import { usableHits, mergeHits, isLinkHit, fmtSeconds, LRC_TIMING_LABEL } from './lyrics-search.js';
import { openLyricsDialog } from './lyrics-dialog.js';
import { publishLine } from './songs-filter.js';
import {
  splitFolder, trackMeta, initialTrack, withExisting, withHit, withDuration, generateBlocker, trackFields,
  lyricsLabel, folderNotice, queuedText, nextLyricsRow, initialLinkTrack, NO_FOLDER_PICKER,
} from './folder-logic.js';
import { linkSource, isYandexNoToken, LINK_SERVICES, NEED_LINK, NO_TRACKS, SETTINGS_LINK_TEXT } from './link-logic.js';
import { IMPORT_URL_KEY } from './artwork-logic.js'; // library-tools 07: ссылка из «Новой песни»
import {
  pickAudioSource, importWarnings, initialCardState, importFields, importBlocker, importOutcome,
  expiredMessage, DUP_TEXT,
} from './import-logic.js';

const TABS = [['usdb', 'usdb'], ['files', 'Файлы'], ['url', 'Ссылка'], ['folder', 'Папка']];
const USDB_LANGUAGES = [['Russian', 'русский'], ['English', 'английский'], ['Ukrainian', 'украинский'], ['', 'любой']];
const FILE_ACCEPT = '.zip,.txt,.mp3,.ogg,.m4a,.opus,.wav,.flac,.jpg,.jpeg,.png,.webp';
const SOURCE_LABEL = { usdb: 'из usdb', files: 'из файлов', url: 'по ссылке' };

let root, built = false;
let tab = 'usdb';
const view = {}; // элементы раздела: вкладки, формы, пак
const usdbState = { start: 0, query: null, seq: 0 }; // поиск usdb: запрос, смещение, номер ответа
let pack = null; // {token, source, items: [{song, state, card}]} — token разбора из inspect
let importing = false;
let shown = false; // раздел на экране (hide — поиск текстов на паузе)

export function mount(section) {
  root = section;
}

export function show() {
  if (!built) build();
  checkUsdbAccount();
  api.targets().then((r) => { view.publishLine.textContent = publishLine(r); view.publishLine.hidden = false; })
    .catch(() => { view.publishLine.hidden = true; });
  getDefaults().then((d) => {
    videoDefaults = d;
    if (d.max_import_mb) view.filesHint.textContent = `zip-архив или файлы песни (.txt, аудио, обложка), до ${d.max_import_mb} МБ`;
  }).catch(() => {});
  shown = true;
  if (takeHandedUrl()) return;
  const g = groupOf(tab);
  if (g) runLyricsQueue(g);
}

/** library-tools 07: альбом/плейлист из «Новой песни» — вкладка «Ссылка» и сразу разбор. */
function takeHandedUrl() {
  let url = '';
  try {
    url = sessionStorage.getItem(IMPORT_URL_KEY) || '';
    sessionStorage.removeItem(IMPORT_URL_KEY);
  } catch { return false; }
  url = url.trim();
  if (!url) return false;
  selectTab('url');
  view.url.value = url;
  if (linkSource(url) === 'music') inspectLink(url);
  else {
    resetGroup(linkGroup);
    inspect({ source: 'url', url }, view.urlBtn, view.urlErr, { url: view.url });
  }
  return true;
}

export function hide() {
  shown = false;
  for (const g of GROUPS) stopLyrics(g); // уход из раздела — поиск текстов на паузе, продолжится при возврате
}

// ---------------------------------------------------------------- построение

function build() {
  built = true;
  view.tabBtns = {};
  view.panels = {};
  const tabs = h('div', { class: 'subtabs', role: 'tablist', 'aria-label': 'Источник' },
    TABS.map(([id, label]) => (view.tabBtns[id] = h('button', {
      type: 'button', role: 'tab', id: `import-tab-${id}`, 'aria-controls': `import-panel-${id}`,
      onclick: () => selectTab(id),
    }, label))));
  view.panels.usdb = buildUsdb();
  view.panels.files = buildFiles();
  view.panels.url = buildUrl();
  view.panels.folder = buildFolder();
  for (const [id] of TABS) {
    Object.assign(view.panels[id], { id: `import-panel-${id}`, role: 'tabpanel' });
    view.panels[id].setAttribute('aria-labelledby', `import-tab-${id}`);
  }

  view.packBox = h('div', { class: 'import-pack', hidden: true });
  view.publishLine = h('div', { class: 'small muted publish-line', hidden: true });
  clear(root).append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Импорт')),
    buildTips(), view.publishLine, tabs, view.panels.usdb, view.panels.files, view.panels.url, view.panels.folder, view.packBox);
  selectTab(tab);
}

function buildTips() {
  const link = (href, text) => h('a', { href, target: '_blank', rel: 'noopener' }, text);
  return h('details', { class: 'more import-tips' },
    h('summary', {}, 'Где брать русские песни'),
    h('ul', { class: 'small' },
      h('li', {}, link('https://usdb.animux.de/', 'usdb.animux.de'),
        ' — вкладка «usdb», язык «русский» (нужна учётка в ', h('a', { href: '#settings' }, 'Настройках'), ').'),
      h('li', {}, link('https://ultrastar-es.org/ru', 'ultrastar-es.org/ru'),
        ' — скачайте песню на сайте и загрузите архив во вкладке «Файлы» (сервису сайт не отвечает).'),
      h('li', {}, link('https://github.com/Vasil-Pahomov/UltraStarSongs', 'github.com/Vasil-Pahomov/UltraStarSongs'),
        ' — вставьте ссылку на репозиторий или его папку во вкладке «Ссылка».')));
}

function selectTab(id) {
  tab = id;
  for (const [k] of TABS) {
    view.tabBtns[k].setAttribute('aria-selected', String(k === id));
    view.panels[k].hidden = k !== id;
  }
  for (const g of GROUPS) {
    if (g.tab === id) runLyricsQueue(g); else stopLyrics(g);
  }
}

function errorBanner() {
  return h('div', { class: 'banner err', hidden: true, role: 'alert' });
}

/** Текст ошибки в баннер; e — ошибка API: нет токена Яндекс Музыки → ссылка на «Настройки». */
function showError(el, text, e) {
  el.textContent = text;
  if (text && isYandexNoToken(e)) el.append(' ', h('a', { href: '#settings' }, SETTINGS_LINK_TEXT));
  el.hidden = !text;
}

function markInvalid(el) {
  if (!el) return;
  el.classList.add('invalid');
  const off = () => el.classList.remove('invalid');
  el.addEventListener('input', off, { once: true });
  el.addEventListener('change', off, { once: true });
  el.focus();
}

// ---------------------------------------------------------------- usdb

function buildUsdb() {
  view.noAccount = h('div', { class: 'banner warn', hidden: true },
    'Впишите логин и пароль usdb в ', h('a', { href: '#settings' }, 'Настройках'), '.');
  view.uArtist = h('input', { type: 'text', name: 'usdb-artist', autocomplete: 'off', maxlength: '200' });
  view.uTitle = h('input', { type: 'text', name: 'usdb-title', autocomplete: 'off', maxlength: '200' });
  view.uLang = h('select', { name: 'usdb-language' }, USDB_LANGUAGES.map(([v, l]) => h('option', { value: v }, l)));
  view.uSearch = h('button', { type: 'submit', class: 'primary' }, 'Найти');
  view.uErr = errorBanner();
  view.uInfo = h('div', { class: 'small muted', role: 'status' });
  view.uList = h('div', { class: 'usdb-list' });
  view.uMore = h('button', { type: 'button', hidden: true, onclick: () => usdbSearch(true) }, 'Показать ещё');
  const form = h('form', { class: 'card', novalidate: true },
    view.noAccount,
    h('div', { class: 'row2' }, field('Исполнитель', view.uArtist), field('Название', view.uTitle)),
    field('Язык', view.uLang),
    h('div', { class: 'actions' }, view.uSearch),
    view.uErr, view.uInfo, view.uList,
    h('div', { class: 'actions' }, view.uMore));
  form.addEventListener('submit', (e) => { e.preventDefault(); usdbSearch(false); });
  return form;
}

async function checkUsdbAccount() {
  try {
    const acc = await api.usdbAccount();
    view.noAccount.hidden = !!(acc.user && acc.has_password);
  } catch {
    view.noAccount.hidden = true; // поиск сам скажет, если учётки нет
  }
}

function isNoAccount(e) {
  return e?.data?.code === 'usdb_no_account';
}

async function usdbSearch(more) {
  if (!more) {
    usdbState.query = { artist: view.uArtist.value.trim(), title: view.uTitle.value.trim(), language: view.uLang.value };
    usdbState.start = 0;
  }
  const my = ++usdbState.seq;
  view.uSearch.disabled = view.uMore.disabled = true;
  showError(view.uErr, '');
  if (!more) { clear(view.uList); view.uInfo.textContent = 'Поиск…'; }
  try {
    const page = await api.usdbSearch({ ...usdbState.query, start: usdbState.start });
    if (my !== usdbState.seq) return;
    view.noAccount.hidden = true;
    usdbState.start += page.items.length;
    view.uList.append(...page.items.map(usdbRow));
    view.uMore.hidden = !page.has_more;
    view.uInfo.textContent = view.uList.children.length ? `Найдено: ${view.uList.children.length}${page.has_more ? '+' : ''}` : 'В usdb ничего не нашлось';
  } catch (e) {
    if (my !== usdbState.seq) return;
    view.uInfo.textContent = '';
    if (isNoAccount(e)) view.noAccount.hidden = false;
    else showError(view.uErr, errorText(e));
  } finally {
    if (my === usdbState.seq) view.uSearch.disabled = view.uMore.disabled = false;
  }
}

function usdbRow(hit) {
  const take = h('button', { type: 'button', onclick: () => inspect({ source: 'usdb', usdb_id: hit.id }, take, view.uErr) }, 'Взять');
  const meta = [hit.language, hit.rating ? `рейтинг ${Number(hit.rating).toFixed(1)}` : null].filter(Boolean).join(' · ');
  return h('div', { class: 'usdb-hit' },
    h('div', { class: 'usdb-hit-info' },
      h('div', { class: 'song-title' }, hit.title),
      h('div', { class: 'song-artist' }, hit.artist),
      h('div', { class: 'tags' }, meta ? h('span', { class: 'small muted' }, meta) : null,
        hit.existing_song_id ? h('span', { class: 'tag on' }, 'уже есть') : null)),
    take);
}

// ---------------------------------------------------------------- файлы и ссылка

function buildFiles() {
  view.files = h('input', { type: 'file', name: 'files', multiple: true, accept: FILE_ACCEPT });
  view.filesHint = h('span', {}, 'zip-архив или файлы песни (.txt, аудио, обложка)');
  view.filesBtn = h('button', { type: 'submit', class: 'primary' }, 'Разобрать');
  view.filesErr = errorBanner();
  const form = h('form', { class: 'card', novalidate: true },
    h('label', { class: 'field' }, h('span', {}, 'Файлы'), view.files, h('div', { class: 'small muted' }, view.filesHint)),
    view.filesErr,
    h('div', { class: 'actions' }, view.filesBtn));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!view.files.files.length) { showError(view.filesErr, 'Выберите zip или файлы песни'); markInvalid(view.files); return; }
    inspect({ source: 'files', files: [...view.files.files] }, view.filesBtn, view.filesErr, { files: view.files });
  });
  return form;
}

function buildUrl() {
  view.url = h('input', { type: 'text', name: 'url', inputmode: 'url', autocomplete: 'off',
    placeholder: 'https://github.com/<владелец>/<репозиторий>, …/songs.zip или ссылка на трек, альбом, плейлист' });
  view.urlBtn = h('button', { type: 'submit', class: 'primary' }, 'Разобрать');
  view.urlErr = errorBanner();
  linkGroup.box = h('div', { class: 'folder-music', hidden: true });
  linkGroup.errEl = view.urlErr;
  const form = h('form', { class: 'card', novalidate: true },
    field('Ссылка', view.url, 'zip или GitHub (можно на папку: …/tree/<ветка>/<папка>) — готовые песни'),
    h('div', { class: 'small muted' }, `Ссылка на музыку (${LINK_SERVICES}) — трек, альбом или плейлист на генерацию.`),
    view.urlErr,
    h('div', { class: 'actions' }, view.urlBtn));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const url = view.url.value.trim();
    if (!url) { showError(view.urlErr, NEED_LINK); markInvalid(view.url); return; }
    if (linkSource(url) === 'music') { inspectLink(url); return; }
    resetGroup(linkGroup);
    inspect({ source: 'url', url }, view.urlBtn, view.urlErr, { url: view.url });
  });
  return h('div', {}, form, linkGroup.box);
}

// ---------------------------------------------------------------- разбор

/** Разбор источника; box — куда показать пак (у папки свой блок, без перехода в очередь). */
async function inspect(src, btn, errEl, fields = {}, box = view.packBox) {
  if (importing) return;
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = 'Разбор…'; }
  showError(errEl, '');
  try {
    const res = await api.importInspect(inspectForm(src));
    showPack(res, box);
  } catch (e) {
    if (isNoAccount(e)) view.noAccount.hidden = false;
    showError(errEl, errorText(e), e);
    markInvalid(fields[e.data?.field]);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

function showPack(res, box = view.packBox) {
  const { token } = res;
  if (pack && pack.box !== box) { clear(pack.box); pack.box.hidden = true; } // пак один на раздел
  const folder = box !== view.packBox;
  pack = { token, source: res.source, box, folder, items: res.songs.map((song) => ({ song, state: initialCardState(song) })) };
  view.packErr = errorBanner();
  view.importBtn = h('button', { type: 'button', class: 'primary', onclick: runImport }, 'Импортировать выбранные');
  view.blocker = h('div', { class: 'small muted', role: 'status' });
  const n = pack.items.length;
  const from = SOURCE_LABEL[res.source] || '';
  clear(box).append(
    h('h3', {}, folder ? `Готовые песни UltraStar: ${n}` : n === 1 ? `Найдена песня ${from}` : `Найдено песен: ${n} ${from}`),
    ...pack.items.map(buildCard),
    view.packErr,
    h('div', { class: 'card import-submit' }, h('div', { class: 'actions' }, view.importBtn), view.blocker));
  box.hidden = false;
  updateSubmit();
  if (!folder) box.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function closePack(text) {
  const box = pack?.box || view.packBox;
  pack = null;
  clear(box).append(h('div', { class: 'banner err', role: 'alert' }, text));
}

// ---------------------------------------------------------------- карточка песни

function buildCard(item) {
  const { song, state } = item;
  const card = {};
  item.card = card;
  card.select = h('input', { type: 'checkbox', checked: state.selected });
  card.artist = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.artist });
  card.title = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.title });
  card.youtube = h('input', { type: 'text', inputmode: 'url', autocomplete: 'off', value: state.youtube,
    placeholder: 'https://www.youtube.com/watch?v=…' });
  card.file = h('input', { type: 'file', accept: '.mp3,audio/mpeg' });
  card.instrumental = h('input', { type: 'checkbox', checked: state.instrumental });
  card.replace = h('input', { type: 'checkbox', checked: state.replace });
  card.audioInfo = h('div', { class: 'small' });
  card.warnings = h('div', { class: 'banner warn', hidden: true });
  card.dup = h('div', { class: 'banner warn', hidden: true },
    h('div', {}, DUP_TEXT),
    h('label', { class: 'check' }, card.replace, 'Заменить (старая уйдёт в корзину)'));
  card.status = h('div', { class: 'small', role: 'status' });

  const facts = [song.language, song.duet ? 'дуэт' : null, song.cover ? 'есть обложка' : 'без обложки',
    song.has_instrumental ? 'есть своя минусовка' : null].filter(Boolean);
  card.youtubeBox = field('Ссылка на YouTube', card.youtube, song.youtube?.length ? 'найдена в песне, можно заменить' : 'звук скачается оттуда');
  card.youtubeBox.hidden = !!song.audio; // аудио из архива важнее ссылки
  // видео (истории 25, 26): «из ссылки» — v= из #VIDEO, иначе ссылка звука; «из архива» — файл по #VIDEO
  const vlinks = song.video_links || [];
  const videoSource = () => vlinks[0] || state.youtube.trim() || song.youtube?.[0] || '';
  card.video = videoBlock({ source: videoSource(), pack: !!song.video_file,
    label: vlinks.length && pack?.source === 'usdb' ? 'Из ссылки usdb' : null,
    gap: song.videogap ?? '', onChange: () => { state.video = card.video.fields(); } });
  if (song.video_file) card.video.el.prepend(h('div', { class: 'small muted' }, `Видео в архиве: ${song.video_file}`));
  state.video = card.video.fields();

  card.el = h('article', { class: 'card import-song' },
    h('label', { class: 'check import-song-head' }, card.select,
      h('span', { class: 'song-title' }, songName(song.artist, song.title))),
    h('div', { class: 'small muted' }, facts.join(' · ')),
    h('div', { class: 'row2' }, field('Исполнитель', card.artist), field('Название', card.title)),
    card.audioInfo,
    card.youtubeBox,
    field('Свой mp3', card.file, 'необязательно — важнее архива и ссылки'),
    card.video.el,
    h('label', { class: 'check' }, card.instrumental, 'Сделать минусовку'),
    song.has_instrumental ? h('div', { class: 'small muted' }, 'В архиве уже есть своя минусовка — новая её заменит.') : null,
    card.dup, card.warnings, card.status);

  const recheck = debounce(() => checkExists(item), 400);
  card.select.addEventListener('change', () => { state.selected = card.select.checked; refreshCard(item); });
  card.artist.addEventListener('input', () => { state.artist = card.artist.value; refreshCard(item); recheck(); });
  card.title.addEventListener('input', () => { state.title = card.title.value; refreshCard(item); recheck(); });
  card.youtube.addEventListener('input', () => {
    state.youtube = card.youtube.value;
    if (!vlinks.length) {
      const src = videoSource(); // годится ли ссылка для видео — решает сервер (400 у поля video_mode)
      card.video.setModes(videoChoices({ source: !!src, pack: !!song.video_file }).modes);
      card.video.setSource(src);
      state.video = card.video.fields();
    }
    refreshCard(item);
  });
  card.file.addEventListener('change', () => { state.file = card.file.files[0] || null; refreshCard(item); });
  card.instrumental.addEventListener('change', () => { state.instrumental = card.instrumental.checked; });
  card.replace.addEventListener('change', () => { state.replace = card.replace.checked; });
  refreshCard(item);
  return card.el;
}

function refreshCard(item) {
  const { song, state, card } = item;
  const audio = pickAudioSource(song, state);
  card.audioInfo.textContent = {
    upload: `Звук: свой файл ${audio.name}`,
    archive: `Звук: из архива (${audio.name})`,
    youtube: `Звук: с YouTube${state.youtube.trim() ? '' : ` — ${audio.url}`}`,
    none: 'Звука нет',
  }[audio.kind];
  const warns = importWarnings(song, audio);
  card.warnings.textContent = warns.join('\n');
  card.warnings.hidden = !warns.length;
  card.dup.hidden = !state.existing;
  card.el.classList.toggle('off', !state.selected);
  for (const el of [card.select, card.artist, card.title, card.youtube, card.file, card.instrumental, card.replace]) el.disabled = !!state.done;
  updateSubmit();
}

async function checkExists(item) {
  const { state } = item;
  const artist = state.artist.trim(), title = state.title.trim();
  if (!artist || !title) return;
  const my = (item.existsSeq = (item.existsSeq || 0) + 1);
  try {
    const r = await api.exists(artist, title);
    if (my !== item.existsSeq) return;
    state.existing = r.exists ? r.song_id : null;
    refreshCard(item);
  } catch { /* не мешаем: дубль проверит сервер при постановке */ }
}

function updateSubmit() {
  if (!pack || !view.importBtn) return;
  const pending = pack.items.filter((i) => !i.state.done);
  const blocker = importBlocker(pending);
  view.importBtn.disabled = importing || !!blocker;
  view.blocker.textContent = importing ? '' : (blocker || '');
}

// ---------------------------------------------------------------- постановка

async function runImport() {
  if (!pack || importing) return;
  const chosen = pack.items.filter((i) => i.state.selected && !i.state.done);
  if (importBlocker(chosen)) return;
  importing = true;
  updateSubmit();
  showError(view.packErr, '');
  const label = view.importBtn.textContent;
  view.importBtn.textContent = 'Отправка…';
  let ok = 0, failed = 0;
  try {
    for (const item of chosen) {
      const { song, state, card } = item;
      view.blocker.textContent = queuedText(ok, chosen.length);
      card.status.className = 'small';
      card.status.textContent = 'Отправка…';
      try {
        await api.importJob(importForm(importFields(pack.token, song, state)));
        state.done = true;
        ok += 1;
        card.status.className = 'small ok-text';
        card.status.textContent = 'Поставлено в очередь';
        refreshCard(item);
      } catch (e) {
        const out = importOutcome(e);
        if (out.kind === 'expired') { closePack(expiredMessage(out.text, pack.items.filter((i) => i.state.done).length)); return; }
        failed += 1;
        if (out.kind === 'duplicate') {
          state.existing = out.songId;
          card.status.textContent = '';
          refreshCard(item);
          card.replace.focus();
        } else {
          card.status.className = 'small err-text';
          card.status.textContent = out.text;
          const el = { artist: card.artist, title: card.title, audio: card.file, youtube_url: card.youtube }[out.field];
          if (!card.video.showApiError(e)) markInvalid(el);
        }
      }
    }
  } finally {
    importing = false;
    if (view.importBtn) view.importBtn.textContent = label;
    updateSubmit();
  }
  if (pack?.folder) { // на экране остаётся группа генерации — не уходим, а даём ссылку в очередь
    view.blocker.replaceChildren(queuedText(ok, chosen.length), failed ? ' — ошибки в карточках выше. ' : '. ',
      h('a', { href: '#queue' }, 'Открыть очередь'));
    return;
  }
  if (!failed) {
    toast(ok === 1 ? 'Песня поставлена в очередь' : `В очереди песен: ${ok}`);
    location.hash = '#queue';
  } else {
    showError(view.packErr, ok ? `Поставлено ${ok}, не получилось ${failed} — см. карточки выше` : 'Не получилось — см. карточки выше');
  }
}

// ---------------------------------------------------------------- группы генерации: папка и ссылка

// Группа «Музыка для генерации»: rows — [{state, file, card}] (file — mp3 из папки, у трека по
// ссылке null — звук уйдёт audio_url); seq — номер разбора (новая папка/ссылка — +1);
// lyricsSeq — номер прохода поиска текстов (стоп — +1, ответ старого прохода игнорируется).
function makeGroup(tabId) {
  return { tab: tabId, seq: 0, rows: [], lyricsSeq: 0, searching: false, generating: false,
    defaults: null, box: null, errEl: null, v: {} };
}
const folder = makeGroup('folder');
const linkGroup = makeGroup('url');
const GROUPS = [folder, linkGroup];
function groupOf(id) { return GROUPS.find((g) => g.tab === id) || null; }

/** Сбросить группу: поиск текстов — стоп, строки и блок — убрать; ответы старого разбора — мимо. */
function resetGroup(g) {
  g.seq++;
  stopLyrics(g);
  g.rows = [];
  g.v = {};
  if (g.box) { clear(g.box); g.box.hidden = true; }
}

// ---------------------------------------------------------------- папка (G08)

function canPickFolder(input) {
  return 'webkitdirectory' in input && !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '');
}

function buildFolder() {
  view.folder = h('input', { type: 'file', name: 'folder', multiple: true, webkitdirectory: '', directory: '' });
  view.folderErr = errorBanner();
  view.folderInfo = h('div', { class: 'small', role: 'status' });
  view.folderWarn = h('div', { class: 'banner warn', hidden: true });
  view.folderPack = h('div', { class: 'import-pack', hidden: true });
  folder.box = h('div', { class: 'folder-music', hidden: true });
  folder.errEl = view.folderErr;
  const supported = canPickFolder(view.folder);
  const card = h('div', { class: 'card' },
    supported
      ? h('label', { class: 'field' }, h('span', {}, 'Папка с музыкой'), view.folder,
        h('div', { class: 'small muted' }, 'готовые песни UltraStar (.txt с аудио) импортируются, остальные mp3 — на генерацию'))
      : h('div', { class: 'banner warn' }, NO_FOLDER_PICKER),
    view.folderWarn, view.folderErr, view.folderInfo);
  view.folder.addEventListener('change', () => onFolderChosen([...view.folder.files]));
  return h('div', {}, card, view.folderPack, folder.box);
}

/** Текст .txt: UTF-8, иначе cp1251 (старые песни UltraStar). */
async function readText(file) {
  if (file.size > 2 * 1024 * 1024) return '';
  const bytes = await file.arrayBuffer();
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { /* не UTF-8 */ }
  try { return new TextDecoder('windows-1251').decode(bytes); } catch { return ''; }
}

const relPath = (file) => file.webkitRelativePath || file.name;

async function onFolderChosen(files) {
  resetGroup(folder);
  const my = folder.seq;
  if (pack?.folder) pack = null;
  clear(view.folderPack); view.folderPack.hidden = true;
  showError(view.folderErr, '');
  const notice = folderNotice(files.length);
  view.folderWarn.textContent = notice;
  view.folderWarn.hidden = !notice;
  if (!files.length) { view.folderInfo.textContent = 'Папка пуста'; return; }
  view.folderInfo.textContent = 'Разбираю папку…';

  const byPath = new Map(files.map((f) => [relPath(f), f]));
  const entries = [];
  for (const f of files) {
    const path = relPath(f);
    entries.push(/\.txt$/i.test(path) ? { path, text: await readText(f) } : { path });
    if (my !== folder.seq) return;
  }
  const split = splitFolder(entries);
  view.folderInfo.textContent = `Готовых песен: ${split.songCount} · mp3 на генерацию: ${split.music.length} · пропущено файлов: ${split.skipped}`;

  if (split.songs.length) {
    inspect({ source: 'files', files: split.songs.map((p) => byPath.get(p)) }, null, view.folderErr, {}, view.folderPack);
  }
  if (split.music.length) await showMusic(my, split.music.map((p) => byPath.get(p)));
}

async function showMusic(my, files) {
  if (!(await openGroup(folder, my, `Музыка для генерации: ${files.length}`))) return;
  const max = folder.defaults.max_upload_mb || 0;
  for (const file of files) {
    let tags = null;
    try { tags = await readId3(file); } catch { /* без тегов — из имени файла */ }
    if (my !== folder.seq) return;
    addTrack(folder, { file, state: initialTrack(relPath(file), file.size, trackMeta(tags, relPath(file)), max) });
  }
  for (const row of folder.rows) {
    await checkTrackExists(folder, row);
    if (my !== folder.seq) return;
  }
  runLyricsQueue(folder);
}

// ---------------------------------------------------------------- ссылка на музыку

/** Музыкальная ссылка → link/inspect → строки треков (звук — audio_url, «уже есть» — от сервера). */
async function inspectLink(url) {
  const g = linkGroup;
  resetGroup(g);
  const my = g.seq;
  if (pack && !pack.folder) { clear(pack.box); pack.box.hidden = true; pack = null; } // прежний пак zip/GitHub
  showError(view.urlErr, '');
  view.urlBtn.disabled = true;
  view.urlBtn.textContent = 'Получаю…';
  try {
    const info = await api.linkInspect(url);
    if (my !== g.seq) return;
    const tracks = info?.tracks || [];
    if (!tracks.length) { showError(view.urlErr, NO_TRACKS); return; }
    const heading = tracks.length === 1 ? 'Трек на генерацию' : `Треки на генерацию: ${tracks.length}`;
    const note = tracks.length > 1 && info.title ? info.title : null;
    if (!(await openGroup(g, my, heading, note))) return;
    for (const t of tracks) addTrack(g, { file: null, state: { ...initialLinkTrack(t), videoOk: t.video } });
    g.box.scrollIntoView({ block: 'start', behavior: 'smooth' });
    runLyricsQueue(g);
  } catch (e) {
    if (my !== g.seq) return;
    showError(view.urlErr, errorText(e), e);
    if (e?.data?.field === 'url') markInvalid(view.url);
  } finally {
    if (my === g.seq) { view.urlBtn.disabled = false; view.urlBtn.textContent = 'Разобрать'; }
  }
}

// ---------------------------------------------------------------- группа «Музыка для генерации»

/** Шапка группы: параметры на все треки, место под строки, кнопка. false — разбор устарел. */
async function openGroup(g, my, heading, note) {
  let d = {};
  try { d = await getDefaults(); } catch (e) { showError(g.errEl, errorText(e)); }
  if (my !== g.seq) return false;
  g.defaults = d;
  const v = (g.v = {});
  v.model = h('select', { name: `${g.tab}-whisper-model` }, (d.whisper_models || []).map((m) => h('option', { value: m }, m)));
  v.lang = h('select', { name: `${g.tab}-language` }, (d.languages || []).map((l) => h('option', { value: l.code }, `${l.name} (${l.code})`)));
  v.model.value = d.defaults?.whisper_model || '';
  v.lang.value = d.defaults?.language || '';
  v.genBtn = h('button', { type: 'button', class: 'primary', onclick: () => runGenerate(g) }, 'Сгенерировать выбранные');
  v.genBlocker = h('div', { class: 'small muted', role: 'status' });
  v.list = h('div', {});
  clear(g.box).append(
    h('h3', {}, heading),
    ...(note ? [h('div', { class: 'small muted' }, note)] : []),
    h('div', { class: 'card' },
      h('div', { class: 'row2' }, field('Модель распознавания', v.model), field('Язык', v.lang)),
      h('div', { class: 'small muted' }, 'одни на все треки; прочие параметры — по умолчанию, как в «Новой песне»')),
    v.list,
    h('div', { class: 'card import-submit' }, h('div', { class: 'actions' }, v.genBtn), v.genBlocker));
  g.box.hidden = false;
  return true;
}

function addTrack(g, row) {
  g.rows.push(row);
  g.v.list.append(buildTrack(g, row));
  refreshTrack(g, row);
}

function groupParams(g) {
  const d = g.defaults || {};
  const language = g.v.lang.value;
  return { ...(d.defaults || {}), whisper_model: g.v.model.value, language,
    align_model: (d.align_models || {})[language] || '' };
}

/** Заголовок строки: mp3 — имя файла, путь и размер; трек по ссылке — название, ссылка, длительность. */
function trackHead(row) {
  const { state } = row;
  if (row.file) {
    const mb = (state.size / 1024 / 1024).toFixed(1);
    return [state.path.split('/').pop(), h('div', { class: 'small muted' }, `${state.path} · ${mb} МБ`)];
  }
  const thumb = state.thumbnail
    ? h('img', { src: state.thumbnail, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer',
      style: 'width:40px;height:40px;object-fit:cover;border-radius:4px;vertical-align:middle;margin-right:8px' })
    : null;
  const len = fmtSeconds(state.duration);
  return [state.title ? songName(state.artist, state.title) : state.url,
    h('div', { class: 'small muted' }, thumb,
      h('a', { href: state.url, target: '_blank', rel: 'noopener' }, state.url), len ? ` · ${len}` : null)];
}

function buildTrack(g, row) {
  const { state } = row;
  const card = {};
  row.card = card;
  card.select = h('input', { type: 'checkbox', checked: state.selected });
  card.artist = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.artist, placeholder: 'не определился — впишите' });
  card.title = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.title });
  card.replace = h('input', { type: 'checkbox' });
  card.big = h('div', { class: 'banner err', hidden: true }, state.tooBig);
  card.dup = h('div', { class: 'banner warn', hidden: true },
    h('div', {}, DUP_TEXT), h('label', { class: 'check' }, card.replace, 'Заменить (старая уйдёт в корзину)'));
  card.lyrics = h('span', {});
  card.pick = h('button', { type: 'button', onclick: () => pickTrackLyrics(g, row) }, 'Выбрать текст');
  card.lrc = h('input', { type: 'checkbox' });
  card.lrcHint = h('div', { class: 'small muted' });
  card.lrcBox = h('div', { hidden: true }, h('label', { class: 'check' }, card.lrc, LRC_TIMING_LABEL), card.lrcHint);
  card.status = h('div', { class: 'small', role: 'status' });
  if (!row.file) { // трек по ссылке; mp3 из папки видео не выбирает (история 31)
    const src = state.videoOk === false ? '' : state.url; // признак video трека из link/inspect
    card.video = videoBlock({ source: src, onChange: () => { state.video = card.video.fields(); } });
    state.video = card.video.fields();
  }
  const [name, sub] = trackHead(row);
  card.el = h('article', { class: 'card import-song folder-track' },
    h('label', { class: 'check import-song-head' }, card.select, h('span', { class: 'song-title' }, name)),
    sub,
    h('div', { class: 'row2' }, field('Исполнитель', card.artist), field('Название', card.title)),
    h('div', { class: 'folder-lyrics small' }, card.lyrics, card.pick),
    card.lrcBox, card.video?.el || null, card.big, card.dup, card.status);

  const changed = debounce(() => {
    if (!state.lyricsManual) { Object.assign(state, { lyrics: 'queued', hit: null, hits: [] }); runLyricsQueue(g); }
    checkTrackExists(g, row);
  }, 600);
  card.select.addEventListener('change', () => { Object.assign(state, { selected: card.select.checked, touched: true }); refreshTrack(g, row); });
  card.artist.addEventListener('input', () => { state.artist = card.artist.value; refreshTrack(g, row); changed(); });
  card.title.addEventListener('input', () => { state.title = card.title.value; refreshTrack(g, row); changed(); });
  card.replace.addEventListener('change', () => { state.replace = card.replace.checked; });
  card.lrc.addEventListener('change', () => { state.lrcTiming = card.lrc.checked; });
  return card.el;
}

function refreshTrack(g, row) {
  const { state, card } = row;
  if (!card) return;
  card.select.checked = state.selected;
  card.artist.classList.toggle('invalid', !state.artist.trim());
  card.lyrics.textContent = lyricsLabel(state);
  card.lyrics.className = state.lyrics === 'found' ? 'ok-text' : '';
  card.pick.hidden = !state.artist.trim() || !state.title.trim();
  card.lrcBox.hidden = !state.hit?.synced;
  card.lrc.checked = state.lrcTiming;
  card.lrcHint.textContent = state.lrcHint;
  card.big.hidden = !state.tooBig;
  card.dup.hidden = !state.existing;
  card.replace.checked = state.replace;
  card.el.classList.toggle('off', !state.selected);
  const locked = !!state.done || !!state.tooBig;
  for (const el of [card.select, card.artist, card.title, card.replace, card.lrc, card.pick]) el.disabled = locked || g.generating;
  updateGenerate(g);
}

function setTrack(g, row, patch) {
  Object.assign(row.state, patch);
  refreshTrack(g, row);
}

async function checkTrackExists(g, row) {
  const artist = row.state.artist.trim(), title = row.state.title.trim();
  if (!artist || !title) return;
  const my = (row.existsSeq = (row.existsSeq || 0) + 1);
  try {
    const r = await api.exists(artist, title);
    if (my === row.existsSeq) setTrack(g, row, withExisting(row.state, r.exists ? r.song_id : null));
  } catch { /* дубль проверит сервер при постановке */ }
}

function pickTrackLyrics(g, row) {
  const { state } = row;
  openLyricsDialog({
    artist: state.artist.trim(), title: state.title.trim(),
    hits: state.lyrics === 'found' && state.hits.length ? state.hits : undefined,
    hint: 'Выберите вариант текста для этого трека.',
    onPick: (hit) => { setTrack(g, row, { ...withHit(state, hit), lyricsManual: true }); return true; },
  });
}

function updateGenerate(g) {
  if (!g.v.genBtn) return;
  const blocker = generateBlocker(g.rows);
  g.v.genBtn.disabled = g.generating || !!blocker;
  if (!g.generating) g.v.genBlocker.textContent = blocker || '';
}

// ---------------------------------------------------------------- авто-поиск текста: по одному треку

/** Длительность mp3 по метаданным <audio>; не вышло за 5 с — null. */
function readDuration(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const el = new Audio();
    let timer = null;
    const done = (sec) => { clearTimeout(timer); URL.revokeObjectURL(url); el.removeAttribute('src'); resolve(sec); };
    timer = setTimeout(() => done(null), 5000);
    el.preload = 'metadata';
    el.addEventListener('loadedmetadata', () => done(el.duration), { once: true });
    el.addEventListener('error', () => done(null), { once: true });
    el.src = url;
  });
}

function stopLyrics(g) {
  g.lyricsSeq++;
  g.searching = false;
  for (const row of g.rows) if (row.state.lyrics === 'searching') setTrack(g, row, { lyrics: 'queued' });
}

const AUTO_LYRICS_SOURCES = ['lrclib', 'netease']; // авто-поиск «Папки»: без Genius (только ссылки)

async function runLyricsQueue(g) {
  if (g.searching || !shown || tab !== g.tab) return;
  g.searching = true;
  const my = g.lyricsSeq;
  try {
    // следующая строка выбирается заново после каждого трека: правка во время поиска
    // (вписали исполнителя, сменили название) возвращает строку в очередь, и проход её возьмёт
    for (let i = nextLyricsRow(g.rows.map((r) => r.state)); i >= 0; i = nextLyricsRow(g.rows.map((r) => r.state))) {
      const row = g.rows[i];
      const { state } = row;
      const artist = state.artist.trim(), title = state.title.trim();
      setTrack(g, row, { lyrics: 'searching' });
      if (state.duration == null && row.file) { // у трека по ссылке длительность — из ответа сервера
        const sec = await readDuration(row.file);
        if (my !== g.lyricsSeq) return;
        Object.assign(state, withDuration(state, sec));
      }
      // только источники с текстом (LRCLIB и NetEase) — параллельно; Genius даёт лишь ссылки и отвечает до 15 с
      const answers = await Promise.allSettled(AUTO_LYRICS_SOURCES.map((id) => api.lyricsSearch(artist, title, id)));
      let hits = null; // null — ни один источник не ответил
      for (const a of answers) {
        if (a.status === 'fulfilled') hits = mergeHits(hits || [], usableHits(a.value?.items).filter((x) => !isLinkHit(x)));
      }
      if (my !== g.lyricsSeq) return;
      if (state.lyrics !== 'searching') continue; // правка вернула строку в очередь или выбрали вручную
      if (state.artist.trim() !== artist || state.title.trim() !== title) { state.lyrics = 'queued'; continue; }
      if (hits === null) setTrack(g, row, { lyrics: 'failed', hits: [] });
      else setTrack(g, row, { hits, ...withHit(state, hits[0] || null) });
    }
  } finally {
    if (my === g.lyricsSeq) g.searching = false;
  }
}

// ---------------------------------------------------------------- постановка генерации

async function runGenerate(g) {
  if (g.generating) return;
  const chosen = g.rows.filter((r) => r.state.selected && !r.state.done);
  if (generateBlocker(chosen)) return;
  g.generating = true;
  const params = groupParams(g);
  let ok = 0, failed = 0;
  for (const row of g.rows) refreshTrack(g, row);
  g.v.genBtn.textContent = 'Отправка…';
  try {
    for (const row of chosen) {
      g.v.genBlocker.textContent = queuedText(ok, chosen.length);
      const { state, card } = row;
      card.status.className = 'small';
      card.status.textContent = 'Отправка…';
      try {
        await api.generate(generateForm(trackFields(state, row.file, params)));
        state.done = true;
        ok += 1;
        card.status.className = 'small ok-text';
        card.status.textContent = 'Поставлено в очередь';
      } catch (e) {
        failed += 1;
        if (e.status === 409 && e.data?.song_id) {
          state.existing = e.data.song_id;
          card.status.textContent = '';
        } else {
          card.status.className = 'small err-text';
          showError(card.status, errorText(e), e); // нет токена Яндекс Музыки — со ссылкой на «Настройки»
          card.video?.showApiError(e);
        }
      }
      refreshTrack(g, row);
    }
  } finally {
    g.generating = false;
    g.v.genBtn.textContent = 'Сгенерировать выбранные';
    for (const row of g.rows) refreshTrack(g, row);
  }
  g.v.genBlocker.replaceChildren(queuedText(ok, chosen.length), failed ? ' — ошибки в строках выше. ' : '. ',
    h('a', { href: '#queue' }, 'Открыть очередь'));
  if (ok) toast(ok === 1 ? 'Трек поставлен на генерацию' : `На генерацию поставлено: ${ok}`);
}
