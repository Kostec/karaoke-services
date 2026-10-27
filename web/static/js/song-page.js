// Страница песни (#song?id=<song_id>): шапка с обложкой и фоном, теги, действия, плееры,
// текст, сведения, хранилища, файлы.

import { api, getDefaults } from './api.js';
import { h, clear, fmtDate, toast } from './ui.js';
import { menuButton, closeMenu } from './menu.js';
import { soloPlayback, releasePlayers } from './player.js';
import {
  songMenuItems, editorItems, makeInstrumental, openVideoDialog, openSongTagsDialog, downloadZip,
} from './song-actions.js';
import { tagChip } from './tags-ui.js';
import { openCoverDialog, openBackgroundDialog } from './artwork.js';
import { tagsById, songTagList } from './tags-logic.js';
import { mediaRows, infoRows, fmtSize, lyricsPreview, browserCanPlay, blockSigs } from './song-page-logic.js';
import { builtinTags, songHref } from './songs.js';

let root;
let songId = '';
let seq = 0;
let fromList = false; // пришли на страницу из списка «Песен» — «← Песни» делает history.back()
let lastFrom = '';
let trashDays = null;
let renamed = false; // переход на новый id после переименования — «← Песни» ведёт туда же, что и раньше

// Слушатель ставится при загрузке модуля — раньше роутера app.js, поэтому к show() адрес уже известен.
window.addEventListener('hashchange', (e) => {
  try { lastFrom = new URL(e.oldURL).hash; } catch { lastFrom = ''; }
});

export function mount(section) {
  root = section;
}

export function show(params) {
  const id = params?.get('id') || '';
  if (id !== songId && !renamed) fromList = /^#songs(\?|$)/.test(lastFrom);
  renamed = false;
  songId = id;
  load();
  getDefaults().then((d) => { trashDays = d.trash_days; }).catch(() => {});
}

export function hide() {
  stopPolling();
  releasePlayers();
  page = null;
  closeMenu();
  songId = '';
  document.title = 'Караоке';
}

function backLink() {
  return h('a', { class: 'back', href: '#songs', onclick: (e) => {
    if (fromList && history.length > 1) { e.preventDefault(); history.back(); }
  } }, '← Песни');
}

/** Перечитать страницу (после задания, тегов, копирования); тихо — без «Загрузка…». */
async function load({ quiet = false } = {}) {
  const my = ++seq;
  const id = songId;
  if (!id) {
    clear(root).append(backLink(), notFound());
    return;
  }
  if (!quiet) {
    stopPolling();
    releasePlayers();
    page = null;
    clear(root).append(backLink(), h('p', { class: 'muted' }, 'Загрузка…'));
  }
  try {
    const [details, tagsRes, targetsRes] = await Promise.all([
      api.songDetails(id),
      api.tags().catch(() => ({ tags: [] })),
      api.targets().catch(() => null),
    ]);
    if (my !== seq || id !== songId) return;
    render(details, tagsRes.tags || [], targetsRes);
  } catch (e) {
    if (my !== seq || id !== songId) return;
    if (quiet && e.status !== 404) { // фоновое перечитывание — прежний вид остаётся
      if (e.status === 503 && page?.id === id) setStorageOk(false);
      return;
    }
    clear(root).append(backLink(), e.status === 404 ? notFound() : unavailable(e));
  }
}

function notFound() {
  return h('div', { class: 'card empty' },
    h('p', {}, 'Песня не найдена'),
    h('p', { class: 'small muted' }, 'Её могли удалить или переименовать, либо хранилище пересканировано.'),
    h('a', { class: 'btn primary', href: '#songs' }, 'К списку песен'));
}

function unavailable(e) {
  return h('div', { class: 'banner err', role: 'alert' },
    h('p', { class: 'banner-text' }, e.status === 503 ? e.detail : `Не удалось открыть песню: ${e.detail}`),
    h('button', { type: 'button', onclick: () => load() }, 'Повторить'));
}

function reload() {
  if (root && !root.hidden && songId) load({ quiet: true });
}

// ---- состояние показанной страницы: блоки обновляются по подписям, плееры живут между обновлениями
let page = null; // {id, env, sigs, slots, banner, details, tags}
let pollTimer = null;
const POLL_MS = 15000;
const BLOCKS = ['hero', 'media', 'lyrics', 'info', 'store'];

function makeEnv(details, targetsRes) {
  const song = details.song;
  return {
    targets: (targetsRes?.targets || details.copies?.map((c) => ({ id: c.target_id, name: c.target_name })) || []),
    currentTargetId: song.target_id, outputOk: page?.id === song.song_id ? page.env.outputOk : true, trashDays, reload,
    afterRemove: () => { location.hash = '#songs'; },
    // прежний id исчез — заменить адрес, чтобы «Назад» не вёл на него
    afterRename: (newId) => {
      if (songId !== song.song_id) return; // пользователь уже ушёл со страницы
      renamed = true;
      location.replace(`#song?id=${encodeURIComponent(newId)}`);
    },
  };
}

function render(details, tags, targetsRes) {
  const song = details.song;
  const sigs = blockSigs(details, tags);
  // library-tools 07: строки «Обложка»/«Фон» в «Медиа» — по именам файлов
  sigs.media = `${sigs.media}|${details.media?.cover || ''}|${details.media?.background || ''}`;
  if (page && page.id === song.song_id && root.contains(page.slots.hero)) {
    // та же песня: пересобираем только блоки со сменившейся подписью
    page.env = makeEnv(details, targetsRes);
    page.details = details;
    page.tags = tags;
    for (const name of BLOCKS) {
      if (sigs[name] === page.sigs[name]) continue;
      if (name === 'media') releasePlayers(page.slots.media);
      const el = BUILDERS[name](details, tags, page.env);
      page.slots[name].replaceWith(el);
      page.slots[name] = el;
    }
    page.sigs = sigs;
    setTitle(song);
    return;
  }
  releasePlayers();
  const env = makeEnv(details, targetsRes);
  const slots = {};
  for (const name of BLOCKS) slots[name] = BUILDERS[name](details, tags, env);
  const banner = h('div', { class: 'song-banner', hidden: true });
  page = { id: song.song_id, env, sigs, slots, banner, details, tags };
  clear(root).append(backLink(), banner, slots.hero,
    h('div', { class: 'song-grid' }, slots.media, slots.lyrics, slots.info, slots.store));
  setTitle(song);
  startPolling();
}

function setTitle(song) {
  document.title = `${song.artist ? `${song.artist} — ` : ''}${song.title || song.txt_name} · Караоке`;
}

// ---- доступность хранилища песни

function storageName(p) {
  const t = p.env.targets.find((x) => x.id === p.env.currentTargetId);
  return t?.name || t?.label || p.details.copies?.find((c) => c.current)?.target_name || p.env.currentTargetId;
}

function setStorageOk(ok, label) {
  if (!page) return;
  if (page.env.outputOk !== ok) {
    page.env.outputOk = ok;
    // кнопки редакторов в шапке гаснут/оживают; меню «…» считает пункты при открытии
    const el = BUILDERS.hero(page.details, page.tags, page.env);
    page.slots.hero.replaceWith(el);
    page.slots.hero = el;
  }
  const b = page.banner;
  b.hidden = ok;
  clear(b);
  if (!ok) {
    b.append(h('div', { class: 'banner warn', role: 'status' },
      h('b', {}, `Хранилище «${storageName(page) || label || ''}» недоступно — действия с файлами отключены.`),
      ' ', h('span', { class: 'small' }, 'Проверка раз в 15 с; когда оно вернётся, всё включится само.')));
  }
}

function pollStatus() {
  const p = page;
  if (!p || !songId || root.hidden) return;
  api.targetStatus(p.env.currentTargetId).then((st) => {
    if (page === p) setStorageOk(st.ok !== false, st.label);
  }).catch((e) => {
    if (page === p && e.status === 503) setStorageOk(false);
  });
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, POLL_MS);
  pollStatus();
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

// ---- блоки

function buildHero(details, tags, env) {
  const song = details.song;
  const media = details.media || {};
  const fileUrl = (name, o) => api.fileUrl(song.song_id, name, o);
  const bg = media.background ? fileUrl(media.background) : (song.cover ? api.coverUrl(song.song_id) : null);
  const heroBg = h('div', { class: `song-hero-bg${bg ? '' : ' plain'}` });
  if (bg) heroBg.style.backgroundImage = `url("${bg}")`;
  const big = song.cover
    ? h('img', { class: 'song-hero-cover', src: api.coverUrl(song.song_id), alt: 'Обложка',
      onerror: (e) => e.target.replaceWith(h('div', { class: 'song-hero-cover none', 'aria-hidden': 'true' }, '♪')) })
    : h('div', { class: 'song-hero-cover none', 'aria-hidden': 'true' }, '♪');
  const userTags = songTagList(song, tagsById(tags)).map((t) => tagChip(t, {
    title: 'Показать песни с этим тегом',
    onClick: () => { location.hash = `#songs?tag=${encodeURIComponent(t.id)}`; },
  }));
  const addTag = h('button', { type: 'button', class: 'addtag', onclick: () => openSongTagsDialog(song, env) }, '+ тег');
  const eds = editorItems(song, env);
  const edBtn = (kind, primary) => {
    const ed = eds.find((e) => e.kind === kind);
    if (!ed) return null;
    return h('button', { type: 'button', class: primary ? 'primary' : null, dataset: { editor: kind },
      disabled: !!ed.disabled, title: ed.disabled || null, onclick: ed.open }, ed.label);
  };
  // library-tools 11: «▶ Прогон» читает файлы песни — гаснет вместе с хранилищем
  const playBtn = h('button', { type: 'button', dataset: { action: 'play' }, disabled: env.outputOk === false,
    title: env.outputOk === false ? STORAGE_OFF : 'Проиграть песню с бегущим текстом и нотами',
    onclick: () => { location.hash = `#play?id=${encodeURIComponent(song.song_id)}`; } }, '▶ Прогон');
  return h('div', { class: 'song-hero' }, heroBg,
    h('div', { class: 'song-hero-in' }, big,
      h('div', { class: 'song-hero-text' },
        h('div', { class: 'song-hero-artist' }, song.artist || 'Исполнитель не указан'),
        h('h2', {}, song.title || song.txt_name),
        h('div', { class: 'tags' }, builtinTags(song), userTags, addTag),
        h('div', { class: 'song-hero-acts' }, edBtn('notes', true), playBtn, edBtn('lyrics', false),
          menuButton(() => songMenuItems(song, env, { editors: false }))))));
}

function buildMedia(details, tags, env) {
  const song = details.song;
  const media = details.media || {};
  const fileUrl = (name, o) => api.fileUrl(song.song_id, name, o);
  const mediaCard = h('div', { class: 'card song-sec' }, h('h3', {}, 'Слушать и смотреть'));
  for (const row of mediaRows(details)) mediaCard.append(mediaRow(row, song, details, env, fileUrl));
  // library-tools 07: обложка и фон — миниатюра, имя файла и «Заменить…/Поставить…»
  mediaCard.append(artworkRow('cover', media.cover, song, env, fileUrl),
    artworkRow('background', media.background, song, env, fileUrl));
  return mediaCard;
}

function buildLyrics(details) {
  const song = details.song;
  const lyricsBody = h('div', { class: 'song-lyrics muted' }, 'Загрузка…');
  const lyricsCard = h('div', { class: 'card song-sec' }, h('h3', {}, 'Текст'), lyricsBody);
  api.lyrics(song.song_id).then(({ text }) => {
    const { head, more } = lyricsPreview(text);
    lyricsBody.classList.remove('muted');
    if (!head) { lyricsBody.textContent = 'Текста нет'; lyricsBody.classList.add('muted'); return; }
    const full = String(text).replace(/\r\n?/g, '\n').replace(/\s+$/, '');
    let open = false;
    lyricsBody.textContent = head;
    if (more) {
      const toggle = h('button', { type: 'button', class: 'link song-lyrics-toggle' }, 'Показать весь текст');
      toggle.addEventListener('click', () => {
        open = !open;
        lyricsBody.textContent = open ? full : head;
        toggle.textContent = open ? 'Свернуть' : 'Показать весь текст';
      });
      lyricsCard.append(toggle);
    }
  }).catch((e) => { lyricsBody.textContent = `Текст недоступен: ${e.detail || e.message}`; });
  return lyricsCard;
}

function buildInfo(details) {
  const dl = h('dl', { class: 'song-info-list' });
  for (const [label, value, href] of infoRows(details, { date: fmtDate })) {
    dl.append(h('dt', {}, label),
      h('dd', {}, href ? h('a', { href, target: '_blank', rel: 'noopener' }, value) : value));
  }
  return h('div', { class: 'card song-sec' }, h('h3', {}, 'Сведения'), dl);
}

function buildStore(details, tags, env) {
  const song = details.song;
  const fileUrl = (name, o) => api.fileUrl(song.song_id, name, o);
  const stores = h('div', { class: 'song-list-rows' });
  const pending = song.pending_copies || [];
  const copies = details.copies?.length ? details.copies
    : [{ song_id: song.song_id, target_id: song.target_id, target_name: '', current: true }];
  for (const c of copies) {
    const name = c.target_name || targetLabel(env.targets, c.target_id);
    stores.append(c.current
      ? h('div', {}, h('span', {}, name, ' ', h('span', { class: 'tag on' }, 'открыто')), h('span'))
      : h('div', {}, h('a', { href: songHref(c) }, name), h('span', { class: 'muted small' }, 'есть')));
  }
  for (const p of pending) {
    if (copies.some((c) => c.target_id === p.target_id)) continue;
    stores.append(h('div', {}, h('span', {}, p.name || targetLabel(env.targets, p.target_id)),
      h('span', { class: 'tag wait' }, 'ждёт копирования')));
  }
  const files = h('div', { class: 'song-list-rows' });
  for (const f of details.files || []) {
    files.append(h('div', {},
      h('a', { href: fileUrl(f.name, { download: true }), download: f.name }, f.name),
      h('span', { class: 'muted small nowrap' }, fmtSize(f.size))));
  }
  if (!details.files?.length) files.append(h('p', { class: 'muted' }, 'Файлов нет'));
  return h('div', { class: 'card song-sec' },
    h('h3', {}, 'Хранилища'), stores,
    h('h3', { class: 'song-sec-next' }, 'Файлы'), files,
    h('button', { type: 'button', class: 'song-zip', onclick: () => downloadZip(song) }, 'Скачать всё (.zip)'));
}

const BUILDERS = { hero: buildHero, media: buildMedia, lyrics: buildLyrics, info: buildInfo, store: buildStore };

function targetLabel(targets, id) {
  const t = targets.find((x) => x.id === id);
  return t?.name || t?.label || id;
}

const STORAGE_OFF = 'Хранилище недоступно — действия с файлами отключены';

/** Строка «Обложка»/«Фон» блока «Медиа»: миниатюра (ссылка на картинку целиком) и кнопка диалога. */
function artworkRow(kind, name, song, env, fileUrl) {
  const isCover = kind === 'cover';
  const open = () => {
    if (env.outputOk === false) { toast(STORAGE_OFF, 'err'); return; }
    (isCover ? openCoverDialog : openBackgroundDialog)(song, env);
  };
  const btn = h('button', { type: 'button', class: 'sm', disabled: env.outputOk === false,
    title: env.outputOk === false ? STORAGE_OFF : null, onclick: open }, name ? 'Заменить…' : 'Поставить…');
  const body = name
    ? [h('a', { href: fileUrl(name), target: '_blank', rel: 'noopener', title: 'Открыть изображение целиком' },
      h('img', { class: isCover ? 'song-cover-thumb' : 'song-bg-thumb', src: fileUrl(name),
        alt: isCover ? 'Обложка' : 'Фоновое изображение', loading: 'lazy' })),
    h('span', { class: 'small muted artwork-name' }, name)]
    : [h('span', { class: 'muted' }, isCover ? 'нет' : 'не задан')];
  return h('div', { class: 'media-row artwork-row' }, h('b', {}, isCover ? 'Обложка' : 'Фон'),
    h('div', { class: 'mrow' }, ...body, btn));
}

function mediaRow({ kind, label, name }, song, details, env, fileUrl) {
  const row = h('div', { class: 'media-row' }, h('b', {}, label));
  if (!name) {
    const none = h('div', { class: 'media-none' }, 'нет');
    if (kind === 'instrumental') {
      none.append(h('button', { type: 'button', disabled: !song.audio, title: song.audio ? null : 'У песни нет аудиофайла',
        onclick: (e) => makeInstrumental(e.currentTarget, song, env) }, 'Сделать минусовку'));
    } else if (kind === 'video') {
      none.append(h('button', { type: 'button', onclick: () => openVideoDialog(song, env) }, 'Прикрепить видео…'));
    }
    row.append(none);
    return row;
  }
  const isVideo = kind === 'video';
  const download = () => h('a', { href: fileUrl(name, { download: true }), download: name }, 'Скачать');
  const el = h(isVideo ? 'video' : 'audio');
  if (!browserCanPlay(name, (mime) => el.canPlayType(mime))) {
    // .avi, .mpg и т. п.: браузер такое не играет — сразу говорим об этом, без пустого плеера.
    const ext = (/\.([^.]+)$/.exec(name)?.[1] || '').toLowerCase();
    row.append(h('div', { class: 'media-none' },
      `Браузер не умеет воспроизводить ${ext ? `формат .${ext}` : 'этот формат'} — откройте файл в плеере.`, download()));
    if (isVideo) row.classList.add('tall');
    return row;
  }
  Object.assign(el, { controls: true, preload: 'none', src: fileUrl(name) });
  if (isVideo && song.cover) el.setAttribute('poster', api.coverUrl(song.song_id));
  // Ошибка — либо файл не отдался, либо браузер не справился с кодеком внутри; различить нельзя.
  const fail = h('div', { class: 'media-none', hidden: true },
    'Не удалось воспроизвести: файл недоступен или его формат не поддерживается браузером.', download());
  el.addEventListener('error', () => { fail.hidden = false; });
  el.addEventListener('playing', () => { fail.hidden = true; });
  soloPlayback(el);
  const cell = h('div', { class: 'media-cell' }, el, fail);
  if (isVideo) {
    const gap = details.headers?.videogap;
    if (gap && Number(String(gap).replace(',', '.')) !== 0) {
      cell.append(h('div', { class: 'small muted' }, `смещение видео ${String(gap).replace('.', ',')} с`));
    }
  }
  if (isVideo) row.classList.add('tall');
  row.append(cell);
  return row;
}
