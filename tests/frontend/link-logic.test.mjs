// Ссылки на музыку: вид ссылки во вкладке «Импорт → Ссылка», ответ link/inspect для формы,
// строки треков по ссылке (folder-logic.js) и поля generate с audio_url.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  linkSource, linkOutcome, linkCoverUrl, isYandexNoToken, yandexSaveAction, NO_YM_CODE, NO_TRACKS,
} from '../../web/static/js/link-logic.js';
import { initialLinkTrack, generateBlocker, trackFields, withHit, nextLyricsRow } from '../../web/static/js/folder-logic.js';
import { generateForm, ApiError } from '../../web/static/js/api.js';

test('linkSource: zip, codeload и GitHub — архив песен; прочее — музыка на генерацию', () => {
  for (const url of [
    'https://github.com/Vasil-Pahomov/UltraStarSongs',
    'https://github.com/Vasil-Pahomov/UltraStarSongs/tree/master/Кино',
    'github.com/a/b',
    'https://www.github.com/a/b',
    'https://codeload.github.com/a/b/zip/refs/heads/main',
    'https://example.com/files/songs.ZIP',
    'https://example.com/files/songs.zip?dl=1',
    'https://example.com/%D0%BF%D0%B5%D1%81%D0%BD%D0%B8.zip',
  ]) assert.equal(linkSource(url), 'pack', url);
  for (const url of [
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://youtu.be/dQw4w9WgXcQ',
    'https://music.yandex.ru/album/40620828/track/148124289',
    'https://music.yandex.ru/users/someone/playlists/3',
    'https://vk.com/video-123_456',
    'https://rutube.ru/video/abc/',
    'https://soundcloud.com/a/b',
    'https://example.com/zip/track',
    'не ссылка',
    '',
  ]) assert.equal(linkSource(url), 'music', url);
});

test('linkOutcome: один трек — берётся, список — подсказка про «Импорт → Ссылка», пусто — текст', () => {
  const t = { url: 'https://music.yandex.ru/track/1', artist: 'Кино', title: 'Кукушка', duration: 400 };
  assert.deepEqual(linkOutcome({ kind: 'yandex_track', tracks: [t] }), { kind: 'track', track: t });
  assert.deepEqual(linkOutcome({ kind: 'yandex_album', tracks: [t] }), { kind: 'track', track: t });
  const two = linkOutcome({ kind: 'yandex_album', tracks: [t, t] });
  assert.equal(two.kind, 'list');
  assert.equal(two.text, 'Это список из 2 треков — откройте Импорт → Ссылка');
  assert.equal(linkOutcome({ tracks: Array(21).fill(t) }).text, 'Это список из 21 трека — откройте Импорт → Ссылка');
  assert.equal(linkOutcome({ tracks: Array(11).fill(t) }).text, 'Это список из 11 треков — откройте Импорт → Ссылка');
  assert.deepEqual(linkOutcome({ tracks: [] }), { kind: 'empty', text: NO_TRACKS });
  assert.deepEqual(linkOutcome(null), { kind: 'empty', text: NO_TRACKS });
});

test('isYandexNoToken: по code из ответа сервера', () => {
  assert.equal(NO_YM_CODE, 'yandex_no_token');
  assert.equal(isYandexNoToken(new ApiError(400, 'Впишите…', { code: 'yandex_no_token' })), true);
  assert.equal(isYandexNoToken(new ApiError(400, 'Плохо', { field: 'url' })), false);
  assert.equal(isYandexNoToken(null), false);
});

test('initialLinkTrack: длительность и «уже есть» из ответа, лимита размера нет, исполнитель может быть пуст', () => {
  const s = initialLinkTrack({ url: 'https://youtu.be/x', artist: ' Сплин ', title: 'Романс', duration: 215.4,
    thumbnail: 'https://i.ytimg.com/x.jpg', existing_song_id: null });
  assert.equal(s.url, 'https://youtu.be/x');
  assert.equal(s.artist, 'Сплин');
  assert.equal(s.duration, 215.4);
  assert.equal(s.thumbnail, 'https://i.ytimg.com/x.jpg');
  assert.equal(s.tooBig, '');
  assert.equal(s.selected, true);
  assert.equal(s.lyrics, 'queued');
  const dup = initialLinkTrack({ url: 'u', artist: 'A', title: 'T', duration: null, existing_song_id: 'sid' });
  assert.equal(dup.existing, 'sid');
  assert.equal(dup.selected, false);
  assert.equal(dup.duration, null);
  const noArtist = initialLinkTrack({ url: 'u', artist: '', title: 'Видео' });
  assert.equal(noArtist.needArtist, true);
  assert.equal(nextLyricsRow([noArtist, s]), 1);
  assert.equal(generateBlocker([{ state: { ...noArtist, lyrics: 'none' } }]), 'Укажите исполнителя и название');
  assert.equal(generateBlocker([{ state: { ...s, lyrics: 'none' } }]), null);
});

test('трек по ссылке: правило 3 с по длительности из ответа, поля generate — audio_url вместо файла', () => {
  const s0 = initialLinkTrack({ url: 'https://music.yandex.ru/album/1/track/2', artist: 'Кино', title: 'Кукушка', duration: 200 });
  const synced = { id: 2, text: 'Раз\nДва', synced: '[00:01.00] Раз\n[00:05.00] Два', duration: 202 };
  const s = { ...s0, ...withHit(s0, synced) };
  assert.equal(s.lrcTiming, true);
  const f = trackFields(s, null, { language: 'ru' });
  assert.equal(f.audio, undefined);
  assert.equal(f.audio_url, 'https://music.yandex.ru/album/1/track/2');
  assert.equal(f.params.lrc_timing, true);
  const fd = generateForm(f);
  assert.equal(fd.get('audio_url'), 'https://music.yandex.ru/album/1/track/2');
  assert.equal(fd.has('audio'), false);
  const far = { ...s0, ...withHit({ ...s0, duration: 240 }, synced) };
  assert.equal(far.lrcTiming, false);
});

test('linkSource: никогда не бросает (битый %, не строка)', () => {
  for (const raw of ['https://example.com/%E0%A4%A.zip', 'https://example.com/100%.zip', '%', 'https://ex.com/%zz',
    'http://[bad', 'https://', null, undefined, 42, {}, Symbol('x')]) {
    assert.doesNotThrow(() => linkSource(raw), String(typeof raw === 'symbol' ? 'symbol' : raw));
  }
  assert.equal(linkSource('https://example.com/100%.zip'), 'pack');
  assert.equal(linkSource('https://ex.com/%zz'), 'music');
  assert.equal(linkSource(Symbol('x')), 'music');
});

test('linkCoverUrl: обложка со ссылки уходит, только если своей нет и «Получить» был для этой ссылки', () => {
  const link = { input: 'https://youtu.be/x', url: 'https://youtu.be/x', list: '' };
  const thumb = 'https://i.ytimg.com/x.jpg';
  assert.equal(linkCoverUrl({ link, input: ' https://youtu.be/x ', thumb }), thumb);
  assert.equal(linkCoverUrl({ link, input: 'https://youtu.be/x', thumb, ownCover: new Blob(['c']) }), null);
  assert.equal(linkCoverUrl({ link, input: 'https://youtu.be/x', thumb, audioFile: new Blob(['a']) }), null);
  assert.equal(linkCoverUrl({ link, input: 'https://youtu.be/other', thumb }), null);
  assert.equal(linkCoverUrl({ link, input: '', thumb }), null);
  assert.equal(linkCoverUrl({ link, input: 'https://youtu.be/x', thumb: null }), null);
  assert.equal(linkCoverUrl({ link: { input: 'https://y/a', url: '', list: 'Это список' }, input: 'https://y/a', thumb }), null);
  assert.equal(linkCoverUrl(), null);
});

test('generateForm: cover_url — только без своей обложки', () => {
  const fd = generateForm({ artist: 'A', title: 'T', audio_url: 'https://youtu.be/x', cover_url: ' https://i/x.jpg ', params: {} });
  assert.equal(fd.get('cover_url'), 'https://i/x.jpg');
  const own = generateForm({ artist: 'A', title: 'T', audio_url: 'https://youtu.be/x', cover: new Blob(['c']),
    cover_url: 'https://i/x.jpg', params: {} });
  assert.equal(own.has('cover_url'), false);
  assert.ok(own.get('cover') instanceof Blob);
  assert.equal(generateForm({ artist: 'A', title: 'T', cover_url: '  ', params: {} }).has('cover_url'), false);
});

test('trackFields: трек по ссылке передаёт миниатюру как cover_url, файл из папки — нет', () => {
  const s = initialLinkTrack({ url: 'https://youtu.be/x', artist: 'A', title: 'T', thumbnail: 'https://i.ytimg.com/x.jpg' });
  assert.equal(trackFields(s, null, {}).cover_url, 'https://i.ytimg.com/x.jpg');
  assert.equal(generateForm(trackFields(s, null, {})).get('cover_url'), 'https://i.ytimg.com/x.jpg');
  assert.equal(trackFields({ ...s, thumbnail: null }, null, {}).cover_url, undefined);
  assert.equal(trackFields(s, new Blob(['a']), {}).cover_url, undefined);
  assert.equal(trackFields({ ...s, url: '' }, null, {}).cover_url, undefined);
});

test('yandexSaveAction: пустое поле удаляет сохранённый токен только с подтверждением', () => {
  assert.equal(yandexSaveAction(' abc ', false), 'save');
  assert.equal(yandexSaveAction('abc', true), 'save');
  assert.equal(yandexSaveAction('  ', true), 'confirm-remove');
  assert.equal(yandexSaveAction('', false), 'empty');
  assert.equal(yandexSaveAction(undefined, undefined), 'empty');
});
