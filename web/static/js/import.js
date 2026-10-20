// Раздел «Импорт»: готовые UltraStar-песни из usdb, из файлов (zip или .txt + аудио + обложка)
// и по ссылке (zip или GitHub). Сначала разбор (inspect), затем по заданию на отмеченную песню.

import { api, getDefaults, inspectForm, importForm, errorText } from './api.js';
import { h, clear, toast, field, debounce, songName } from './ui.js';
import {
  pickAudioSource, importWarnings, initialCardState, importFields, importBlocker, importOutcome,
  expiredMessage, DUP_TEXT,
} from './import-logic.js';

const TABS = [['usdb', 'usdb'], ['files', 'Файлы'], ['url', 'Ссылка']];
const USDB_LANGUAGES = [['Russian', 'русский'], ['English', 'английский'], ['Ukrainian', 'украинский'], ['', 'любой']];
const FILE_ACCEPT = '.zip,.txt,.mp3,.ogg,.m4a,.opus,.wav,.flac,.jpg,.jpeg,.png,.webp';
const SOURCE_LABEL = { usdb: 'из usdb', files: 'из файлов', url: 'по ссылке' };

let root, built = false;
let tab = 'usdb';
const view = {}; // элементы раздела: вкладки, формы, пак
const usdbState = { start: 0, query: null, seq: 0 }; // поиск usdb: запрос, смещение, номер ответа
let pack = null; // {token, source, items: [{song, state, card}]} — token разбора из inspect
let importing = false;

export function mount(section) {
  root = section;
}

export function show() {
  if (!built) build();
  checkUsdbAccount();
  getDefaults().then((d) => {
    if (d.max_import_mb) view.filesHint.textContent = `zip-архив или файлы песни (.txt, аудио, обложка), до ${d.max_import_mb} МБ`;
  }).catch(() => {});
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
  for (const [id] of TABS) {
    Object.assign(view.panels[id], { id: `import-panel-${id}`, role: 'tabpanel' });
    view.panels[id].setAttribute('aria-labelledby', `import-tab-${id}`);
  }

  view.packBox = h('div', { class: 'import-pack', hidden: true });
  clear(root).append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Импорт')),
    buildTips(), tabs, view.panels.usdb, view.panels.files, view.panels.url, view.packBox);
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
    if (isNoAccount(e)) view.noAccount.hidden = false;
    showError(errEl, errorText(e));
    markInvalid(fields[e.data?.field]);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

function showPack(res) {
  const { token } = res;
  pack = { token, source: res.source, items: res.songs.map((song) => ({ song, state: initialCardState(song) })) };
  view.packErr = errorBanner();
  view.importBtn = h('button', { type: 'button', class: 'primary', onclick: runImport }, 'Импортировать выбранные');
  view.blocker = h('div', { class: 'small muted' });
  const n = pack.items.length;
  clear(view.packBox).append(
    h('h3', {}, n === 1 ? `Найдена песня ${SOURCE_LABEL[res.source] || ''}` : `Найдено песен: ${n} ${SOURCE_LABEL[res.source] || ''}`),
    ...pack.items.map(buildCard),
    view.packErr,
    h('div', { class: 'card import-submit' }, h('div', { class: 'actions' }, view.importBtn), view.blocker));
  view.packBox.hidden = false;
  updateSubmit();
  view.packBox.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function closePack(text) {
  pack = null;
  clear(view.packBox).append(h('div', { class: 'banner err', role: 'alert' }, text));
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
  if (!failed) {
    toast(ok === 1 ? 'Песня поставлена в очередь' : `В очереди песен: ${ok}`);
    location.hash = '#queue';
  } else {
    showError(view.packErr, ok ? `Поставлено ${ok}, не получилось ${failed} — см. карточки выше` : 'Не получилось — см. карточки выше');
  }
}
