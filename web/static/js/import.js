// Раздел «Импорт»: готовые UltraStar-песни из usdb, из файлов (zip или .txt + аудио + обложка)
// и по ссылке (zip или GitHub). Сначала разбор (inspect), затем по заданию на отмеченную песню.

import { api, getDefaults, inspectForm, importForm, errorText } from './api.js';
import { h, clear, toast, field, debounce, songName } from './ui.js';
import {
  pickAudioSource, importWarnings, initialCardState, importFields, importBlocker, importOutcome, EXPIRED,
} from './import-logic.js';

const TABS = [['usdb', 'usdb'], ['files', 'Файлы'], ['url', 'Ссылка']];
const USDB_LANGUAGES = [['Russian', 'русский'], ['English', 'английский'], ['Ukrainian', 'украинский'], ['', 'любой']];
const FILE_ACCEPT = '.zip,.txt,.mp3,.ogg,.m4a,.opus,.wav,.flac,.jpg,.jpeg,.png,.webp';
const SOURCE_LABEL = { usdb: 'из usdb', files: 'из файлов', url: 'по ссылке' };

let root, built = false;
let tab = 'usdb';
const t = {}; // элементы вкладок
const u = { start: 0, query: null, seq: 0 }; // поиск usdb
let pack = null; // {token, source, items: [{song, state, el}]}
let importing = false;

export function mount(section) {
  root = section;
}

export function show() {
  if (!built) build();
  checkUsdbAccount();
  getDefaults().then((d) => {
    if (d.max_import_mb) t.filesHint.textContent = `zip-архив или файлы песни (.txt, аудио, обложка), до ${d.max_import_mb} МБ`;
  }).catch(() => {});
}

// ---------------------------------------------------------------- построение

function build() {
  built = true;
  t.tabBtns = {};
  t.panels = {};
  const tabs = h('div', { class: 'subtabs', role: 'tablist', 'aria-label': 'Источник' },
    TABS.map(([id, label]) => (t.tabBtns[id] = h('button', {
      type: 'button', role: 'tab', id: `import-tab-${id}`, 'aria-controls': `import-panel-${id}`,
      onclick: () => selectTab(id),
    }, label))));
  t.panels.usdb = buildUsdb();
  t.panels.files = buildFiles();
  t.panels.url = buildUrl();
  for (const [id] of TABS) {
    Object.assign(t.panels[id], { id: `import-panel-${id}`, role: 'tabpanel' });
    t.panels[id].setAttribute('aria-labelledby', `import-tab-${id}`);
  }

  t.packBox = h('div', { class: 'import-pack', hidden: true });
  clear(root).append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Импорт')),
    buildTips(), tabs, t.panels.usdb, t.panels.files, t.panels.url, t.packBox);
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
    t.tabBtns[k].setAttribute('aria-selected', String(k === id));
    t.panels[k].hidden = k !== id;
  }
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
  t.noAccount = h('div', { class: 'banner warn', hidden: true },
    'Впишите логин и пароль usdb в ', h('a', { href: '#settings' }, 'Настройках'), '.');
  t.uArtist = h('input', { type: 'text', name: 'usdb-artist', autocomplete: 'off', maxlength: '200' });
  t.uTitle = h('input', { type: 'text', name: 'usdb-title', autocomplete: 'off', maxlength: '200' });
  t.uLang = h('select', { name: 'usdb-language' }, USDB_LANGUAGES.map(([v, l]) => h('option', { value: v }, l)));
  t.uSearch = h('button', { type: 'submit', class: 'primary' }, 'Найти');
  t.uErr = errorBanner();
  t.uInfo = h('div', { class: 'small muted', role: 'status' });
  t.uList = h('div', { class: 'usdb-list' });
  t.uMore = h('button', { type: 'button', hidden: true, onclick: () => usdbSearch(true) }, 'Показать ещё');
  const form = h('form', { class: 'card', novalidate: true },
    t.noAccount,
    h('div', { class: 'row2' }, field('Исполнитель', t.uArtist), field('Название', t.uTitle)),
    field('Язык', t.uLang),
    h('div', { class: 'actions' }, t.uSearch),
    t.uErr, t.uInfo, t.uList,
    h('div', { class: 'actions' }, t.uMore));
  form.addEventListener('submit', (e) => { e.preventDefault(); usdbSearch(false); });
  return form;
}

async function checkUsdbAccount() {
  try {
    const acc = await api.usdbAccount();
    t.noAccount.hidden = !!(acc.user && acc.has_password);
  } catch {
    t.noAccount.hidden = true; // поиск сам скажет, если учётки нет
  }
}

function isNoAccount(e) {
  return e?.data?.code === 'usdb_no_account';
}

async function usdbSearch(more) {
  if (!more) {
    u.query = { artist: t.uArtist.value.trim(), title: t.uTitle.value.trim(), language: t.uLang.value };
    u.start = 0;
  }
  const my = ++u.seq;
  t.uSearch.disabled = t.uMore.disabled = true;
  showError(t.uErr, '');
  if (!more) { clear(t.uList); t.uInfo.textContent = 'Поиск…'; }
  try {
    const page = await api.usdbSearch({ ...u.query, start: u.start });
    if (my !== u.seq) return;
    t.noAccount.hidden = true;
    u.start += page.items.length;
    t.uList.append(...page.items.map(usdbRow));
    t.uMore.hidden = !page.has_more;
    t.uInfo.textContent = t.uList.children.length ? `Найдено: ${t.uList.children.length}${page.has_more ? '+' : ''}` : 'В usdb ничего не нашлось';
  } catch (e) {
    if (my !== u.seq) return;
    t.uInfo.textContent = '';
    if (isNoAccount(e)) t.noAccount.hidden = false;
    else showError(t.uErr, errorText(e));
  } finally {
    if (my === u.seq) t.uSearch.disabled = t.uMore.disabled = false;
  }
}

function usdbRow(hit) {
  const take = h('button', { type: 'button', onclick: () => inspect({ source: 'usdb', usdb_id: hit.id }, take, t.uErr) }, 'Взять');
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
  t.files = h('input', { type: 'file', name: 'files', multiple: true, accept: FILE_ACCEPT });
  t.filesHint = h('span', {}, 'zip-архив или файлы песни (.txt, аудио, обложка)');
  t.filesBtn = h('button', { type: 'submit', class: 'primary' }, 'Разобрать');
  t.filesErr = errorBanner();
  const form = h('form', { class: 'card', novalidate: true },
    h('label', { class: 'field' }, h('span', {}, 'Файлы'), t.files, h('div', { class: 'small muted' }, t.filesHint)),
    t.filesErr,
    h('div', { class: 'actions' }, t.filesBtn));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!t.files.files.length) { showError(t.filesErr, 'Выберите zip или файлы песни'); markInvalid(t.files); return; }
    inspect({ source: 'files', files: [...t.files.files] }, t.filesBtn, t.filesErr, { files: t.files });
  });
  return form;
}

function buildUrl() {
  t.url = h('input', { type: 'text', name: 'url', inputmode: 'url', autocomplete: 'off',
    placeholder: 'https://…/songs.zip или https://github.com/<владелец>/<репозиторий>' });
  t.urlBtn = h('button', { type: 'submit', class: 'primary' }, 'Разобрать');
  t.urlErr = errorBanner();
  const form = h('form', { class: 'card', novalidate: true },
    field('Ссылка на zip или GitHub', t.url, 'можно на папку: …/tree/<ветка>/<папка>'),
    t.urlErr,
    h('div', { class: 'actions' }, t.urlBtn));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!t.url.value.trim()) { showError(t.urlErr, 'Вставьте ссылку на zip или GitHub'); markInvalid(t.url); return; }
    inspect({ source: 'url', url: t.url.value }, t.urlBtn, t.urlErr, { url: t.url });
  });
  return form;
}

// ---------------------------------------------------------------- разбор

async function inspect(src, btn, errEl, fields = {}) {
  if (importing) return;
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = 'Разбор…';
  showError(errEl, '');
  try {
    const res = await api.importInspect(inspectForm(src));
    showPack(res);
  } catch (e) {
    if (isNoAccount(e)) t.noAccount.hidden = false;
    showError(errEl, errorText(e));
    markInvalid(fields[e.data?.field]);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

function showPack(res) {
  pack = { id: res.token, source: res.source, items: res.songs.map((song) => ({ song, state: initialCardState(song) })) };
  t.packErr = errorBanner();
  t.importBtn = h('button', { type: 'button', class: 'primary', onclick: runImport }, 'Импортировать выбранные');
  t.blocker = h('div', { class: 'small muted' });
  const n = pack.items.length;
  clear(t.packBox).append(
    h('h3', {}, n === 1 ? `Найдена песня ${SOURCE_LABEL[res.source] || ''}` : `Найдено песен: ${n} ${SOURCE_LABEL[res.source] || ''}`),
    ...pack.items.map(buildCard),
    t.packErr,
    h('div', { class: 'card import-submit' }, h('div', { class: 'actions' }, t.importBtn), t.blocker));
  t.packBox.hidden = false;
  updateSubmit();
  t.packBox.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function closePack(text) {
  pack = null;
  clear(t.packBox).append(h('div', { class: 'banner err', role: 'alert' }, text));
}

// ---------------------------------------------------------------- карточка песни

function buildCard(item) {
  const { song, state } = item;
  const c = {};
  item.c = c;
  c.select = h('input', { type: 'checkbox', checked: state.selected });
  c.artist = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.artist });
  c.title = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', value: state.title });
  c.youtube = h('input', { type: 'text', inputmode: 'url', autocomplete: 'off', value: state.youtube,
    placeholder: 'https://www.youtube.com/watch?v=…' });
  c.file = h('input', { type: 'file', accept: '.mp3,audio/mpeg' });
  c.instrumental = h('input', { type: 'checkbox', checked: state.instrumental });
  c.replace = h('input', { type: 'checkbox', checked: state.replace });
  c.audioInfo = h('div', { class: 'small' });
  c.warnings = h('div', { class: 'banner warn', hidden: true });
  c.dup = h('div', { class: 'banner warn', hidden: true },
    h('div', {}, 'Уже есть в папке результата'),
    h('label', { class: 'check' }, c.replace, 'Заменить (старая уйдёт в корзину)'));
  c.status = h('div', { class: 'small', role: 'status' });

  const facts = [song.language, song.duet ? 'дуэт' : null, song.cover ? 'есть обложка' : 'без обложки',
    song.has_instrumental ? 'есть своя минусовка' : null].filter(Boolean);
  c.youtubeBox = field('Ссылка на YouTube', c.youtube, song.youtube?.length ? 'найдена в песне, можно заменить' : 'звук скачается оттуда');
  c.youtubeBox.hidden = !!song.audio; // аудио из архива важнее ссылки

  c.el = h('article', { class: 'card import-song' },
    h('label', { class: 'check import-song-head' }, c.select,
      h('span', { class: 'song-title' }, songName(song.artist, song.title))),
    h('div', { class: 'small muted' }, facts.join(' · ')),
    h('div', { class: 'row2' }, field('Исполнитель', c.artist), field('Название', c.title)),
    c.audioInfo,
    c.youtubeBox,
    field('Свой mp3', c.file, 'необязательно — важнее архива и ссылки'),
    h('label', { class: 'check' }, c.instrumental, 'Сделать минусовку'),
    song.has_instrumental ? h('div', { class: 'small muted' }, 'В архиве уже есть своя минусовка — новая её заменит.') : null,
    c.dup, c.warnings, c.status);

  const recheck = debounce(() => checkExists(item), 400);
  c.select.addEventListener('change', () => { state.selected = c.select.checked; refreshCard(item); });
  c.artist.addEventListener('input', () => { state.artist = c.artist.value; refreshCard(item); recheck(); });
  c.title.addEventListener('input', () => { state.title = c.title.value; refreshCard(item); recheck(); });
  c.youtube.addEventListener('input', () => { state.youtube = c.youtube.value; refreshCard(item); });
  c.file.addEventListener('change', () => { state.file = c.file.files[0] || null; refreshCard(item); });
  c.instrumental.addEventListener('change', () => { state.instrumental = c.instrumental.checked; });
  c.replace.addEventListener('change', () => { state.replace = c.replace.checked; });
  refreshCard(item);
  return c.el;
}

function refreshCard(item) {
  const { song, state, c } = item;
  const audio = pickAudioSource(song, state);
  c.audioInfo.textContent = {
    upload: `Звук: свой файл ${audio.name}`,
    archive: `Звук: из архива (${audio.name})`,
    youtube: `Звук: с YouTube${state.youtube.trim() ? '' : ` — ${audio.url}`}`,
    none: 'Звука нет',
  }[audio.kind];
  const warns = importWarnings(song, audio);
  c.warnings.textContent = warns.join('\n');
  c.warnings.hidden = !warns.length;
  c.dup.hidden = !state.existing;
  c.el.classList.toggle('off', !state.selected);
  for (const el of [c.select, c.artist, c.title, c.youtube, c.file, c.instrumental, c.replace]) el.disabled = !!state.done;
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
  if (!pack || !t.importBtn) return;
  const pending = pack.items.filter((i) => !i.state.done);
  const blocker = importBlocker(pending);
  t.importBtn.disabled = importing || !!blocker;
  t.blocker.textContent = importing ? '' : (blocker || '');
}

// ---------------------------------------------------------------- постановка

async function runImport() {
  if (!pack || importing) return;
  const chosen = pack.items.filter((i) => i.state.selected && !i.state.done);
  if (importBlocker(chosen)) return;
  importing = true;
  updateSubmit();
  showError(t.packErr, '');
  const label = t.importBtn.textContent;
  t.importBtn.textContent = 'Отправка…';
  let ok = 0, failed = 0;
  try {
    for (const item of chosen) {
      const { song, state, c } = item;
      c.status.className = 'small';
      c.status.textContent = 'Отправка…';
      try {
        await api.importJob(importForm(importFields(pack.id, song, state)));
        state.done = true;
        ok += 1;
        c.status.className = 'small ok-text';
        c.status.textContent = 'Поставлено в очередь';
        refreshCard(item);
      } catch (e) {
        const out = importOutcome(e);
        if (out.kind === 'expired') { closePack(EXPIRED); return; }
        failed += 1;
        if (out.kind === 'duplicate') {
          state.existing = out.songId;
          c.status.textContent = '';
          refreshCard(item);
          c.replace.focus();
        } else {
          c.status.className = 'small err-text';
          c.status.textContent = out.text;
          const el = { artist: c.artist, title: c.title, audio: c.file, youtube_url: c.youtube }[out.field];
          markInvalid(el);
        }
      }
    }
  } finally {
    importing = false;
    if (t.importBtn) t.importBtn.textContent = label;
    updateSubmit();
  }
  if (!failed) {
    toast(ok === 1 ? 'Песня поставлена в очередь' : `В очереди песен: ${ok}`);
    location.hash = '#queue';
  } else {
    showError(t.packErr, ok ? `Поставлено ${ok}, не получилось ${failed} — см. карточки выше` : 'Не получилось — см. карточки выше');
  }
}
