// Раздел «Импорт»: готовые UltraStar-песни из usdb, из файлов (zip или .txt + аудио + обложка),
// по ссылке (zip или GitHub) и из папки с компьютера. Сначала разбор (inspect), затем по заданию
// на отмеченную песню. Папка (G08): готовые песни — тем же разбором, прочие mp3 — на генерацию
// (по строке на трек, текст ищется сам по одному треку).

import { api, getDefaults, inspectForm, importForm, generateForm, errorText } from './api.js';
import { h, clear, toast, field, debounce, songName } from './ui.js';
import { readId3 } from './id3.js';
import { usableHits, LRC_TIMING_LABEL } from './lyrics-search.js';
import { openLyricsDialog } from './lyrics-dialog.js';
import {
  splitFolder, trackMeta, initialTrack, withExisting, withHit, withDuration, generateBlocker, trackFields,
  lyricsLabel, folderNotice, queuedText, nextLyricsRow, NO_FOLDER_PICKER,
} from './folder-logic.js';
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
  getDefaults().then((d) => {
    if (d.max_import_mb) view.filesHint.textContent = `zip-архив или файлы песни (.txt, аудио, обложка), до ${d.max_import_mb} МБ`;
  }).catch(() => {});
  shown = true;
  if (tab === 'folder') runLyricsQueue();
}

export function hide() {
  shown = false;
  stopLyrics(); // уход из раздела — поиск текстов на паузе, продолжится при возврате
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
  clear(root).append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Импорт')),
    buildTips(), tabs, view.panels.usdb, view.panels.files, view.panels.url, view.panels.folder, view.packBox);
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
  if (id === 'folder') runLyricsQueue(); else stopLyrics();
}

function errorBanner() {
  return h('div', { class: 'banner err', hidden: true, role: 'alert' });
}

function showError(el, text) {
  el.textContent = text;
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
    placeholder: 'https://…/songs.zip или https://github.com/<владелец>/<репозиторий>' });
  view.urlBtn = h('button', { type: 'submit', class: 'primary' }, 'Разобрать');
  view.urlErr = errorBanner();
  const form = h('form', { class: 'card', novalidate: true },
    field('Ссылка на zip или GitHub', view.url, 'можно на папку: …/tree/<ветка>/<папка>'),
    view.urlErr,
    h('div', { class: 'actions' }, view.urlBtn));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!view.url.value.trim()) { showError(view.urlErr, 'Вставьте ссылку на zip или GitHub'); markInvalid(view.url); return; }
    inspect({ source: 'url', url: view.url.value }, view.urlBtn, view.urlErr, { url: view.url });
  });
  return form;
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
    showError(errEl, errorText(e));
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

  card.el = h('article', { class: 'card import-song' },
    h('label', { class: 'check import-song-head' }, card.select,
      h('span', { class: 'song-title' }, songName(song.artist, song.title))),
    h('div', { class: 'small muted' }, facts.join(' · ')),
    h('div', { class: 'row2' }, field('Исполнитель', card.artist), field('Название', card.title)),
    card.audioInfo,
    card.youtubeBox,
    field('Свой mp3', card.file, 'необязательно — важнее архива и ссылки'),
    h('label', { class: 'check' }, card.instrumental, 'Сделать минусовку'),
    song.has_instrumental ? h('div', { class: 'small muted' }, 'В архиве уже есть своя минусовка — новая её заменит.') : null,
    card.dup, card.warnings, card.status);

  const recheck = debounce(() => checkExists(item), 400);
  card.select.addEventListener('change', () => { state.selected = card.select.checked; refreshCard(item); });
  card.artist.addEventListener('input', () => { state.artist = card.artist.value; refreshCard(item); recheck(); });
  card.title.addEventListener('input', () => { state.title = card.title.value; refreshCard(item); recheck(); });
  card.youtube.addEventListener('input', () => { state.youtube = card.youtube.value; refreshCard(item); });
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
          markInvalid(el);
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

// ---------------------------------------------------------------- папка (G08)

// rows: [{state, file, card}] — mp3 на генерацию; lyricsSeq — номер прохода поиска текстов
// (стоп/новая папка — +1, ответ старого прохода игнорируется).
const folder = { seq: 0, rows: [], lyricsSeq: 0, searching: false, generating: false, defaults: null };

function canPickFolder(input) {
  return 'webkitdirectory' in input && !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '');
}

function buildFolder() {
  view.folder = h('input', { type: 'file', name: 'folder', multiple: true, webkitdirectory: '', directory: '' });
  view.folderErr = errorBanner();
  view.folderInfo = h('div', { class: 'small', role: 'status' });
  view.folderWarn = h('div', { class: 'banner warn', hidden: true });
  view.folderPack = h('div', { class: 'import-pack', hidden: true });
  view.musicBox = h('div', { class: 'folder-music', hidden: true });
  const supported = canPickFolder(view.folder);
  const card = h('div', { class: 'card' },
    supported
      ? h('label', { class: 'field' }, h('span', {}, 'Папка с музыкой'), view.folder,
        h('div', { class: 'small muted' }, 'готовые песни UltraStar (.txt с аудио) импортируются, остальные mp3 — на генерацию'))
      : h('div', { class: 'banner warn' }, NO_FOLDER_PICKER),
    view.folderWarn, view.folderErr, view.folderInfo);
  view.folder.addEventListener('change', () => onFolderChosen([...view.folder.files]));
  return h('div', {}, card, view.folderPack, view.musicBox);
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
  const my = ++folder.seq;
  stopLyrics();
  folder.rows = [];
  if (pack?.folder) pack = null;
  clear(view.folderPack); view.folderPack.hidden = true;
  clear(view.musicBox); view.musicBox.hidden = true;
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

// ---------------------------------------------------------------- группа «Музыка для генерации»

async function showMusic(my, files) {
  let d = {};
  try { d = await getDefaults(); } catch (e) { showError(view.folderErr, errorText(e)); }
  if (my !== folder.seq) return;
  folder.defaults = d;
  const max = d.max_upload_mb || 0;
  view.gModel = h('select', { name: 'folder-whisper-model' }, (d.whisper_models || []).map((m) => h('option', { value: m }, m)));
  view.gLang = h('select', { name: 'folder-language' }, (d.languages || []).map((l) => h('option', { value: l.code }, `${l.name} (${l.code})`)));
  view.gModel.value = d.defaults?.whisper_model || '';
  view.gLang.value = d.defaults?.language || '';
  view.genBtn = h('button', { type: 'button', class: 'primary', onclick: runGenerate }, 'Сгенерировать выбранные');
  view.genBlocker = h('div', { class: 'small muted', role: 'status' });
  view.genList = h('div', {});
  clear(view.musicBox).append(
    h('h3', {}, `Музыка для генерации: ${files.length}`),
    h('div', { class: 'card' },
      h('div', { class: 'row2' }, field('Модель распознавания', view.gModel), field('Язык', view.gLang)),
      h('div', { class: 'small muted' }, 'одни на все треки; прочие параметры — по умолчанию, как в «Новой песне»')),
    view.genList,
    h('div', { class: 'card import-submit' }, h('div', { class: 'actions' }, view.genBtn), view.genBlocker));
  view.musicBox.hidden = false;

  for (const file of files) {
    let tags = null;
    try { tags = await readId3(file); } catch { /* без тегов — из имени файла */ }
    if (my !== folder.seq) return;
    const row = { file, state: initialTrack(relPath(file), file.size, trackMeta(tags, relPath(file)), max) };
    folder.rows.push(row);
    view.genList.append(buildTrack(row));
    refreshTrack(row);
  }
  for (const row of folder.rows) {
    await checkTrackExists(row);
    if (my !== folder.seq) return;
  }
  runLyricsQueue();
}

function groupParams() {
  const d = folder.defaults || {};
  const language = view.gLang.value;
  return { ...(d.defaults || {}), whisper_model: view.gModel.value, language,
    align_model: (d.align_models || {})[language] || '' };
}

function buildTrack(row) {
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
  card.pick = h('button', { type: 'button', onclick: () => pickTrackLyrics(row) }, 'Выбрать текст');
  card.lrc = h('input', { type: 'checkbox' });
  card.lrcHint = h('div', { class: 'small muted' });
  card.lrcBox = h('div', { hidden: true }, h('label', { class: 'check' }, card.lrc, LRC_TIMING_LABEL), card.lrcHint);
  card.status = h('div', { class: 'small', role: 'status' });
  const mb = (state.size / 1024 / 1024).toFixed(1);
  card.el = h('article', { class: 'card import-song folder-track' },
    h('label', { class: 'check import-song-head' }, card.select, h('span', { class: 'song-title' }, state.path.split('/').pop())),
    h('div', { class: 'small muted' }, `${state.path} · ${mb} МБ`),
    h('div', { class: 'row2' }, field('Исполнитель', card.artist), field('Название', card.title)),
    h('div', { class: 'folder-lyrics small' }, card.lyrics, card.pick),
    card.lrcBox, card.big, card.dup, card.status);

  const changed = debounce(() => {
    if (!state.lyricsManual) { Object.assign(state, { lyrics: 'queued', hit: null, hits: [] }); runLyricsQueue(); }
    checkTrackExists(row);
  }, 600);
  card.select.addEventListener('change', () => { Object.assign(state, { selected: card.select.checked, touched: true }); refreshTrack(row); });
  card.artist.addEventListener('input', () => { state.artist = card.artist.value; refreshTrack(row); changed(); });
  card.title.addEventListener('input', () => { state.title = card.title.value; refreshTrack(row); changed(); });
  card.replace.addEventListener('change', () => { state.replace = card.replace.checked; });
  card.lrc.addEventListener('change', () => { state.lrcTiming = card.lrc.checked; });
  return card.el;
}

function refreshTrack(row) {
  const { state, card } = row;
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
  for (const el of [card.select, card.artist, card.title, card.replace, card.lrc, card.pick]) el.disabled = locked || folder.generating;
  updateGenerate();
}

function setTrack(row, patch) {
  Object.assign(row.state, patch);
  refreshTrack(row);
}

async function checkTrackExists(row) {
  const artist = row.state.artist.trim(), title = row.state.title.trim();
  if (!artist || !title) return;
  const my = (row.existsSeq = (row.existsSeq || 0) + 1);
  try {
    const r = await api.exists(artist, title);
    if (my === row.existsSeq) setTrack(row, withExisting(row.state, r.exists ? r.song_id : null));
  } catch { /* дубль проверит сервер при постановке */ }
}

function pickTrackLyrics(row) {
  const { state } = row;
  openLyricsDialog({
    artist: state.artist.trim(), title: state.title.trim(),
    hits: state.lyrics === 'found' && state.hits.length ? state.hits : undefined,
    hint: 'Выберите вариант текста для этого трека.',
    onPick: (hit) => { setTrack(row, { ...withHit(state, hit), lyricsManual: true }); return true; },
  });
}

function updateGenerate() {
  if (!view.genBtn) return;
  const blocker = generateBlocker(folder.rows);
  view.genBtn.disabled = folder.generating || !!blocker;
  if (!folder.generating) view.genBlocker.textContent = blocker || '';
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

function stopLyrics() {
  folder.lyricsSeq++;
  folder.searching = false;
  for (const row of folder.rows) if (row.state.lyrics === 'searching') setTrack(row, { lyrics: 'queued' });
}

async function runLyricsQueue() {
  if (folder.searching || !shown || tab !== 'folder') return;
  folder.searching = true;
  const my = folder.lyricsSeq;
  try {
    // следующая строка выбирается заново после каждого трека: правка во время поиска
    // (вписали исполнителя, сменили название) возвращает строку в очередь, и проход её возьмёт
    for (let i = nextLyricsRow(folder.rows.map((r) => r.state)); i >= 0; i = nextLyricsRow(folder.rows.map((r) => r.state))) {
      const row = folder.rows[i];
      const { state } = row;
      const artist = state.artist.trim(), title = state.title.trim();
      setTrack(row, { lyrics: 'searching' });
      if (state.duration == null) {
        const sec = await readDuration(row.file);
        if (my !== folder.lyricsSeq) return;
        Object.assign(state, withDuration(state, sec));
      }
      let hits = null;
      try {
        hits = usableHits((await api.lyricsSearch(artist, title)).items);
      } catch { /* сервис текстов недоступен — без текста */ }
      if (my !== folder.lyricsSeq) return;
      if (state.lyrics !== 'searching') continue; // правка вернула строку в очередь или выбрали вручную
      if (state.artist.trim() !== artist || state.title.trim() !== title) { state.lyrics = 'queued'; continue; }
      if (hits === null) setTrack(row, { lyrics: 'failed', hits: [] });
      else setTrack(row, { hits, ...withHit(state, hits[0] || null) });
    }
  } finally {
    if (my === folder.lyricsSeq) folder.searching = false;
  }
}

// ---------------------------------------------------------------- постановка генерации

async function runGenerate() {
  if (folder.generating) return;
  const chosen = folder.rows.filter((r) => r.state.selected && !r.state.done);
  if (generateBlocker(chosen)) return;
  folder.generating = true;
  const params = groupParams();
  let ok = 0, failed = 0;
  for (const row of folder.rows) refreshTrack(row);
  view.genBtn.textContent = 'Отправка…';
  try {
    for (const row of chosen) {
      view.genBlocker.textContent = queuedText(ok, chosen.length);
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
          card.status.textContent = errorText(e);
        }
      }
      refreshTrack(row);
    }
  } finally {
    folder.generating = false;
    view.genBtn.textContent = 'Сгенерировать выбранные';
    for (const row of folder.rows) refreshTrack(row);
  }
  view.genBlocker.replaceChildren(queuedText(ok, chosen.length), failed ? ' — ошибки в строках выше. ' : '. ',
    h('a', { href: '#queue' }, 'Открыть очередь'));
  if (ok) toast(ok === 1 ? 'Трек поставлен на генерацию' : `На генерацию поставлено: ${ok}`);
}
