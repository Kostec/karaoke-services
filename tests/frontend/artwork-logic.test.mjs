// Обложка и фон (artwork-logic.js): проверка файла и ссылки, подписи вариантов, поля формы.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  imageError, urlError, hitLabel, hitSize, SOURCE_LABELS, searchNote, artworkFields, isListLink,
} from '../../web/static/js/artwork-logic.js';

const MB = 1024 * 1024;

test('imageError: jpg/png/webp до лимита — без ошибки, остальное — текст как у сервера', () => {
  assert.equal(imageError({ name: 'a.JPG', type: 'image/jpeg', size: 5 * MB }, 10), null);
  assert.equal(imageError({ name: 'a.webp', type: '', size: 1 }, 10), null);
  assert.equal(imageError({ name: 'cover.png', type: 'image/png', size: 1 }, 10), null);
  assert.equal(imageError({ name: 'a.gif', type: 'image/gif', size: 1 }, 10), 'Это не картинка (нужны jpg, png или webp)');
  assert.equal(imageError({ name: 'a.jpg', type: 'image/jpeg', size: 10 * MB + 1 }, 10), 'Файл больше 10 МБ');
  assert.equal(imageError(null, 10), 'Выберите файл');
});

test('urlError: только http(s) с адресом', () => {
  assert.equal(urlError('https://img.example/a.jpg'), null);
  assert.equal(urlError(' http://x.ru/a '), null);
  assert.equal(urlError(''), 'Вставьте ссылку на картинку');
  assert.equal(urlError('ftp://x/a.jpg'), 'Нужна ссылка http(s) на картинку');
  assert.equal(urlError('картинка'), 'Нужна ссылка http(s) на картинку');
});

test('hitLabel и hitSize: источник, альбом, размер', () => {
  const hit = { source: 'musicbrainz', album: 'A Night at the Opera', artist: 'Queen', title: 'x', width: 500, height: 500 };
  assert.equal(SOURCE_LABELS.itunes, 'iTunes');
  assert.equal(hitSize(hit), '500×500');
  assert.equal(hitSize({ source: 'deezer' }), '');
  assert.equal(hitLabel(hit), 'MusicBrainz · A Night at the Opera · 500×500');
  assert.equal(hitLabel({ source: 'deezer', album: '', artist: 'Queen', title: 'Bohemian Rhapsody' }),
    'Deezer · Queen — Bohemian Rhapsody');
});

test('searchNote: пусто, упавшие сервисы, итог', () => {
  assert.equal(searchNote({ items: [], failed: [] }), 'Обложек не нашлось — уточните название или загрузите свой файл');
  assert.equal(searchNote({ items: [{}, {}], failed: ['musicbrainz'] }),
    'Найдено вариантов: 2 · MusicBrainz не ответил');
  assert.equal(searchNote({ items: [{}], failed: ['deezer', 'itunes'] }),
    'Найдено вариантов: 1 · Deezer, iTunes не ответили');
  assert.equal(searchNote({ items: [{}, {}, {}] }), 'Найдено вариантов: 3');
});

test('artworkFields: ровно один источник', () => {
  const file = { name: 'a.png' };
  assert.deepEqual(artworkFields({ kind: 'background', mode: 'file', file }), { kind: 'background', image: file });
  assert.deepEqual(artworkFields({ kind: 'cover', mode: 'url', url: ' https://a/b.jpg ' }), { kind: 'cover', url: 'https://a/b.jpg' });
  assert.deepEqual(artworkFields({ kind: 'cover', mode: 'search', hit: { url: 'https://a/1000.jpg' } }),
    { kind: 'cover', url: 'https://a/1000.jpg' });
  assert.deepEqual(artworkFields({ kind: 'background', mode: 'remove', file }), { kind: 'background', remove: 'true' });
});

test('isListLink: альбом и плейлист — да, трек — нет', () => {
  assert.equal(isListLink({ kind: 'list' }), true);
  assert.equal(isListLink({ kind: 'track' }), false);
  assert.equal(isListLink({ kind: 'empty' }), false);
  assert.equal(isListLink(null), false);
});
