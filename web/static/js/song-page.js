// Страница песни (#song?id=<song_id>): шапка с обложкой и фоном, теги, действия, плееры,
// текст, сведения, хранилища, файлы.

import { api, getDefaults } from './api.js';
import { h, clear, fmtDate } from './ui.js';
import { menuButton, closeMenu } from './menu.js';
import { soloPlayback, pausePlayers } from './player.js';
import {
  songMenuItems, editorItems, makeInstrumental, openVideoDialog, openSongTagsDialog, downloadZip,
} from './song-actions.js';
import { tagChip } from './tags-ui.js';
import { tagsById, songTagList } from './tags-logic.js';
import { mediaRows, infoRows, fmtSize, lyricsPreview } from './song-page-logic.js';
import { builtinTags, songHref } from './songs.js';

let root;
let songId = '';
let seq = 0;
let fromList = false; // пришли на страницу из списка «Песен» — «← Песни» делает history.back()
let lastFrom = '';
let trashDays = null;

// Слушатель ставится при загрузке модуля — раньше роутера app.js, поэтому к show() адрес уже известен.
window.addEventListener('hashchange', (e) => {
  try { lastFrom = new URL(e.oldURL).hash; } catch { lastFrom = ''; }
});

export function mount(section) {
  root = section;
}

export function show(params) {
  const id = params?.get('id') || '';
  if (id !== songId) fromList = /^#songs(\?|$)/.test(lastFrom);
  songId = id;
  load();
  getDefaults().then((d) => { trashDays = d.trash_days; }).catch(() => {});
}

export function hide() {
  pausePlayers();
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
  if (!quiet) clear(root).append(backLink(), h('p', { class: 'muted' }, 'Загрузка…'));
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
    if (quiet && e.status !== 404) return; // фоновое перечитывание — прежний вид остаётся
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

function render(details, tags, targetsRes) {
  const song = details.song;
  const media = details.media || {};
  const fileUrl = (name, o) => api.fileUrl(song.song_id, name, o);
  const env = {
    targets: (targetsRes?.targets || details.copies?.map((c) => ({ id: c.target_id, name: c.target_name })) || []),
    currentTargetId: song.target_id, outputOk: true, trashDays, reload,
    afterRemove: () => { location.hash = '#songs'; },
  };

  // ---- шапка
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
  const hero = h('div', { class: 'song-hero' }, heroBg,
    h('div', { class: 'song-hero-in' }, big,
      h('div', { class: 'song-hero-text' },
        h('div', { class: 'song-hero-artist' }, song.artist || 'Исполнитель не указан'),
        h('h2', {}, song.title || song.txt_name),
        h('div', { class: 'tags' }, builtinTags(song), userTags, addTag),
        h('div', { class: 'song-hero-acts' }, edBtn('notes', true), edBtn('lyrics', false),
          menuButton(() => songMenuItems(song, env, { editors: false }))))));

  // ---- слушать и смотреть
  const mediaCard = h('div', { class: 'card song-sec' }, h('h3', {}, 'Слушать и смотреть'));
  for (const row of mediaRows(details)) mediaCard.append(mediaRow(row, song, details, env, fileUrl));
  if (media.background) {
    mediaCard.append(h('div', { class: 'media-row' }, h('b', {}, 'Фон'),
      h('a', { href: fileUrl(media.background), target: '_blank', rel: 'noopener', title: 'Открыть изображение целиком' },
        h('img', { class: 'song-bg-thumb', src: fileUrl(media.background), alt: 'Фоновое изображение', loading: 'lazy' }))));
  }

  // ---- текст
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

  // ---- сведения
  const dl = h('dl', { class: 'song-info-list' });
  for (const [label, value, href] of infoRows(details, { date: fmtDate })) {
    dl.append(h('dt', {}, label),
      h('dd', {}, href ? h('a', { href, target: '_blank', rel: 'noopener' }, value) : value));
  }
  const infoCard = h('div', { class: 'card song-sec' }, h('h3', {}, 'Сведения'), dl);

  // ---- хранилища и файлы
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
  const storeCard = h('div', { class: 'card song-sec' },
    h('h3', {}, 'Хранилища'), stores,
    h('h3', { class: 'song-sec-next' }, 'Файлы'), files,
    h('button', { type: 'button', class: 'song-zip', onclick: () => downloadZip(song) }, 'Скачать всё (.zip)'));

  pausePlayers();
  clear(root).append(backLink(), hero,
    h('div', { class: 'song-grid' }, mediaCard, lyricsCard, infoCard, storeCard));
  document.title = `${song.artist ? `${song.artist} — ` : ''}${song.title || song.txt_name} · Караоке`;
}

function targetLabel(targets, id) {
  const t = targets.find((x) => x.id === id);
  return t?.name || t?.label || id;
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
  const el = h(isVideo ? 'video' : 'audio', { controls: true, preload: 'none', src: fileUrl(name) });
  if (isVideo && song.cover) el.setAttribute('poster', api.coverUrl(song.song_id));
  const fail = h('div', { class: 'field-error', hidden: true }, 'Файл недоступен');
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
