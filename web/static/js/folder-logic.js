// Папка с музыкой (G08): чистая логика без DOM — раскладка файлов на группы, исполнитель/название
// трека, ограничения и подписи строк. DOM и сеть — в import.js.
//
// Раскладка повторяет правила разбора сборника на сервере (core/karaoke_core/songpack.py):
// песня — .txt с #TITLE и нотами (кроме *.lyrics.txt), её файлы — по заголовкам без учёта регистра,
// путь от папки .txt без «..»; скрытые файлы и папки пропускаются. Сервер всё равно разбирает .txt сам.

import { lrcPlainText, lrcForNewText, lrcFormPart, lrcTimingDefault, SYNCED_LABEL } from './lyrics-search.js';

export const AUDIO_EXTS = ['.mp3', '.ogg', '.m4a', '.opus', '.wav', '.flac'];
export const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp'];
export const REF_HEADERS = ['AUDIO', 'MP3', 'COVER', 'INSTRUMENTAL', 'VOCALS', 'BACKGROUND'];
export const MAX_FOLDER_FILES = 300;
export const NO_FOLDER_PICKER = 'Выбор папки поддерживается в браузере на компьютере';
export const LYRICS_FOUND = 'текст найден';
export const LYRICS_NONE = 'текст не найден — слова распознаются автоматически';
export const LYRICS_WAIT = 'ищу текст…';
export const LYRICS_QUEUED = 'текст будет найден автоматически';
export const LYRICS_PENDING = 'Тексты ещё ищутся — подождите';
export const LYRICS_FAILED ='поиск текста не удался — слова распознаются автоматически';

const ext = (path) => {
  const name = path.slice(path.lastIndexOf('/') + 1);
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot).toLowerCase() : '';
};
const dirOf = (path) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '');
const hidden = (path) => path.split('/').some((p) => p.startsWith('.'));
const fold = (s) => s.toLocaleLowerCase('ru');

/** Текст .txt — песня UltraStar: #TITLE и хотя бы одна нота. */
export function isSongText(text) {
  const t = String(text ?? '');
  return /^﻿?#TITLE:/im.test(t) && /^[:*FRG]\s/m.test(t);
}

/** Значения заголовков-ссылок на файлы (#AUDIO, #MP3, #COVER, …). */
function refValues(text) {
  const out = [];
  for (const line of String(text ?? '').replace(/^﻿/, '').split(/\r\n|\r|\n/)) {
    const m = /^#([A-Z0-9]+):(.*)$/i.exec(line.trim());
    if (m && REF_HEADERS.includes(m[1].toUpperCase()) && m[2].trim()) out.push(m[2].trim());
  }
  return out;
}

/** Путь из заголовка от папки песни; «..» и абсолютные — null (как songpack.resolve_file). */
function joinRef(dir, value) {
  const parts = value.replace(/\\/g, '/').split('/').filter((p) => p && p !== '.');
  if (!parts.length || parts.includes('..') || /^[A-Za-z]:/.test(parts[0])) return null;
  return [dir, ...parts].filter(Boolean).join('/');
}

/**
 * Разложить папку. entries: [{path, text?}] — path как webkitRelativePath, text — содержимое .txt.
 * → {songs: [path] — уходят одним inspect, music: [path] — mp3 на генерацию (по пути),
 *    skipped: число прочих файлов, songCount: число .txt-песен}
 * Файлы песни: .txt, файлы по её заголовкам и все аудио/картинки в папке .txt.
 */
export function splitFolder(entries) {
  const visible = entries.filter((e) => !hidden(e.path));
  const byFold = new Map(visible.map((e) => [fold(e.path), e.path]));
  const songTxt = visible.filter((e) => ext(e.path) === '.txt' && !/\.lyrics\.txt$/i.test(e.path) && isSongText(e.text));
  const songDirs = new Set(songTxt.map((e) => dirOf(e.path)));
  const songs = new Set(songTxt.map((e) => e.path));
  for (const e of songTxt) {
    for (const value of refValues(e.text)) {
      const ref = joinRef(dirOf(e.path), value);
      const found = ref && byFold.get(fold(ref));
      if (found && ext(found) !== '.txt') songs.add(found);
    }
  }
  const music = [];
  for (const e of visible) {
    if (songs.has(e.path)) continue;
    const x = ext(e.path);
    if (songDirs.has(dirOf(e.path)) && (AUDIO_EXTS.includes(x) || IMAGE_EXTS.includes(x))) songs.add(e.path);
    else if (x === '.mp3') music.push(e.path);
  }
  music.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return {
    songs: entries.map((e) => e.path).filter((p) => songs.has(p)),
    music,
    skipped: entries.length - songs.size - music.length,
    songCount: songTxt.length,
  };
}

/**
 * Исполнитель и название трека: теги ID3 → имя файла «Исполнитель - Название» (номер дорожки
 * в начале отбрасывается) → имя файла как название, исполнитель пуст (needArtist — подсветить).
 */
export function trackMeta(tags, path) {
  const name = String(path ?? '').split('/').pop().replace(/\.[^.]+$/, '').trim();
  let parts = name.split(/\s+-\s+/).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 2 && /^\d{1,3}\.?$/.test(parts[0])) parts = parts.slice(1);
  const fromName = parts.length >= 2
    ? { artist: parts[0], title: parts.slice(1).join(' - ') }
    : { artist: '', title: name };
  const artist = (tags?.artist || '').trim() || fromName.artist;
  const title = (tags?.title || '').trim() || fromName.title;
  return { artist, title, needArtist: !artist };
}

const MB = 1024 * 1024;

function plural(n, one, few, many) {
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return one;
  if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
  return many;
}

/** Предупреждение о большой папке (больше MAX_FOLDER_FILES файлов); пусто — не нужно. */
export function folderNotice(total) {
  if (total <= MAX_FOLDER_FILES) return '';
  return `В папке ${total} ${plural(total, 'файл', 'файла', 'файлов')} — разбор и загрузка займут время`;
}

/** Ход постановки. */
export function queuedText(n, m) {
  return `Поставлено ${n} из ${m}`;
}

/**
 * Состояние строки трека. lyrics: 'queued' | 'searching' | 'found' | 'none' | 'failed';
 * hit — выбранный вариант текста (usableHits), lrcTiming/lrcHint — галочка таймингов (правило 3 с).
 */
export function initialTrack(path, size, meta, maxUploadMb) {
  const tooBig = maxUploadMb > 0 && size > maxUploadMb * MB ? `Больше ${maxUploadMb} МБ — такой mp3 не загрузится` : '';
  return {
    path, size, tooBig,
    artist: meta.artist, title: meta.title, needArtist: meta.needArtist,
    selected: !tooBig, touched: false, existing: null, replace: false, done: false,
    lyrics: 'queued', hits: [], hit: null, duration: null, lrcTiming: false, lrcHint: '',
  };
}

/** Ответ /api/songs/exists → правка состояния: дубль снимает галочку, пока пользователь её не трогал. */
export function withExisting(state, songId) {
  const existing = songId || null;
  if (state.touched) return { existing };
  if (existing) return { existing, selected: false };
  return state.existing && !state.tooBig ? { existing: null, selected: true } : { existing: null };
}

/** Почему «Сгенерировать выбранные» недоступна; null — можно. items: [{state}]. */
export function generateBlocker(items) {
  const chosen = items.filter((i) => i.state.selected && !i.state.done);
  if (!chosen.length) return 'Отметьте треки для генерации';
  const big = chosen.find((i) => i.state.tooBig);
  if (big) return big.state.tooBig;
  if (chosen.some((i) => !i.state.artist?.trim() || !i.state.title?.trim())) return 'Укажите исполнителя и название';
  // иначе трек уйдёт без найденного текста; ждать — недолго, поиск идёт по одному треку
  if (chosen.some((i) => i.state.lyrics === 'queued' || i.state.lyrics === 'searching')) return LYRICS_PENDING;
  return null;
}

/** Подпись текста в строке трека. */
export function lyricsLabel(state) {
  if (state.lyrics === 'found') return state.hit?.synced ? `${LYRICS_FOUND} · ${SYNCED_LABEL}` : LYRICS_FOUND;
  return { searching: LYRICS_WAIT, none: LYRICS_NONE, failed: LYRICS_FAILED }[state.lyrics] || LYRICS_QUEUED;
}

/** Галочка таймингов: только у варианта с LRC, по правилу 3 с (lrcTimingDefault). */
function timing(hit, duration) {
  if (!hit?.synced) return { lrcTiming: false, lrcHint: '' };
  const { checked, hint } = lrcTimingDefault(hit.duration, duration);
  return { lrcTiming: checked, lrcHint: hint };
}

/** Выбран вариант текста (или null — не найден) → правка состояния. */
export function withHit(state, hit) {
  return { hit: hit || null, lyrics: hit ? 'found' : 'none', ...timing(hit, state.duration) };
}

/** Пришла длительность mp3 → правка состояния (галочка заново по правилу 3 с). */
export function withDuration(state, duration) {
  const sec = Number.isFinite(duration) && duration > 0 ? duration : null;
  return { duration: sec, ...timing(state.hit, sec) };
}

/** Поля generateForm для трека: params — общие на группу, lrc_timing — свой у трека. */
export function trackFields(state, file, params) {
  const hit = state.hit;
  const fromLrc = hit?.synced ? lrcPlainText(hit.synced) : '';
  const held = lrcForNewText(fromLrc ? hit : null);
  return {
    artist: state.artist.trim(), title: state.title.trim(),
    lyrics: fromLrc || hit?.text || '',
    audio: file,
    params: { ...params, lrc_timing: !!held && !!state.lrcTiming },
    replace: !!state.replace,
    song_id: undefined,
    lyrics_lrc: lrcFormPart(held),
  };
}

/**
 * Индекс следующего трека для авто-поиска текста (states — состояния строк по порядку) или -1.
 * Берётся первая строка 'queued' с исполнителем и названием, не слишком большая; проход
 * спрашивает заново после каждого трека — строки, вернувшиеся в очередь (правка), не теряются.
 */
export function nextLyricsRow(states) {
  return states.findIndex((s) => s.lyrics === 'queued' && !s.tooBig && s.artist?.trim() && s.title?.trim());
}
