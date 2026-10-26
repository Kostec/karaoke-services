// Страница песни (song-page-logic.js): плееры, сведения, размеры, текст.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mediaRows, infoRows, fmtSize, originLabel, lyricsPreview, mediaMime, browserCanPlay,
} from '../../web/static/js/song-page-logic.js';

const details = (o = {}) => ({
  song: { song_id: 's1', artist: 'Градусы', title: 'Режиссер', rel_dir: 'Градусы/Градусы - Режиссер',
    source: 'generated', own: true, updated_at: '2026-10-26T11:05:00+00:00', is_duet: false, ...o.song },
  headers: { bpm: '312.5', gap: '14230', language: 'Russian', year: '2010', ...o.headers },
  singers: o.singers ?? null,
  media: { audio: 'a.mp3', instrumental: null, vocals: 'a [Vocals].mp3', video: null, cover: null,
    background: null, midi: null, ...o.media },
  usdb_url: o.usdb_url ?? null,
});

test('mediaRows: песня, минусовка, вокал, видео — по порядку, чего нет — null', () => {
  assert.deepEqual(mediaRows(details()), [
    { kind: 'audio', label: 'Песня', name: 'a.mp3' },
    { kind: 'instrumental', label: 'Минусовка', name: null },
    { kind: 'vocals', label: 'Вокал', name: 'a [Vocals].mp3' },
    { kind: 'video', label: 'Видео', name: null },
  ]);
});

test('infoRows: подписи по порядку, пустые пропущены, числа по-русски', () => {
  const rows = infoRows(details(), { date: () => '26 окт, 14:05' });
  assert.deepEqual(rows.map((r) => r.slice(0, 2)), [
    ['Темп (BPM)', '312,5'],
    ['GAP', '14 230 мс'],
    ['Язык', 'Russian'],
    ['Год', '2010'],
    ['Происхождение', 'создана сервисом'],
    ['Обновлена', '26 окт, 14:05'],
    ['Папка', 'Градусы/Градусы - Режиссер'],
  ]);
});

test('infoRows: автор, жанр, издание, автор разметки, дуэт с певцами, usdb со ссылкой', () => {
  const d = details({
    song: { is_duet: true, source: 'usdb', own: true, updated_at: null },
    headers: { author: 'Иванов', genre: 'Поп', edition: 'SingStar', creator: 'Петров', bpm: '', gap: '' },
    singers: { p1: 'Маша', p2: '' },
    usdb_url: 'https://usdb.animux.de/index.php?link=detail&id=7',
  });
  const rows = infoRows(d);
  const map = Object.fromEntries(rows.map((r) => [r[0], r]));
  assert.equal(rows[0][0], 'Автор');
  assert.equal(map['Автор'][1], 'Иванов');
  assert.equal(map['Жанр'][1], 'Поп');
  assert.equal(map['Издание'][1], 'SingStar');
  assert.equal(map['Автор разметки'][1], 'Петров');
  assert.equal(map['Дуэт'][1], 'Певец 1: Маша · Певец 2: без имени');
  assert.deepEqual(map['Происхождение'].slice(1), ['из usdb', 'https://usdb.animux.de/index.php?link=detail&id=7']);
  assert.equal(map['Обновлена'], undefined);
  assert.equal(map['Темп (BPM)'], undefined);
  assert.equal(map['GAP'], undefined);
});

test('fmtSize: Б, КБ, МБ (до 10 — с десятой), ГБ', () => {
  assert.equal(fmtSize(0), '0 Б');
  assert.equal(fmtSize(512), '512 Б');
  assert.equal(fmtSize(6 * 1024 + 100), '6 КБ');
  assert.equal(fmtSize(120 * 1024), '120 КБ');
  assert.equal(fmtSize(8.4 * 1024 * 1024), '8,4 МБ');
  assert.equal(fmtSize(48 * 1024 * 1024 + 5), '48 МБ');
  assert.equal(fmtSize(1.5 * 1024 ** 3), '1,5 ГБ');
  assert.equal(fmtSize(null), '');
});

test('originLabel: создана сервисом / из usdb / импорт из файлов / по ссылке / чужая', () => {
  assert.equal(originLabel({ source: 'generated' }), 'создана сервисом');
  assert.equal(originLabel({ source: null, own: true }), 'создана сервисом');
  assert.equal(originLabel({ source: 'usdb', own: true }), 'из usdb');
  assert.equal(originLabel({ source: 'files' }), 'импорт из файлов');
  assert.equal(originLabel({ source: 'url' }), 'импорт по ссылке');
  assert.equal(originLabel({ source: null, own: false }), 'чужая');
});

test('lyricsPreview: первые 12 строк и признак «есть ещё»', () => {
  const text = Array.from({ length: 15 }, (_, i) => `строка ${i + 1}`).join('\n');
  const p = lyricsPreview(text);
  assert.equal(p.head.split('\n').length, 12);
  assert.equal(p.head.split('\n')[11], 'строка 12');
  assert.equal(p.more, true);
  assert.deepEqual(lyricsPreview('а\nб\n\n'), { head: 'а\nб', more: false });
  assert.deepEqual(lyricsPreview('а\r\nб\r\nв', 2), { head: 'а\nб', more: true });
  assert.deepEqual(lyricsPreview(''), { head: '', more: false });
  assert.deepEqual(lyricsPreview(null), { head: '', more: false });
});

test('mediaMime: тип по расширению без учёта регистра, неизвестное — null', () => {
  assert.equal(mediaMime('A - T.AVI'), 'video/x-msvideo');
  assert.equal(mediaMime('a [Instrumental].mp3'), 'audio/mpeg');
  assert.equal(mediaMime('clip.webm'), 'video/webm');
  assert.equal(mediaMime('noext'), null);
  assert.equal(mediaMime('x.xyz'), null);
});

test('browserCanPlay: пустой ответ canPlayType — не играет, неизвестный тип пробуем', () => {
  const chrome = (mime) => (['video/mp4', 'audio/mpeg', 'video/webm'].includes(mime) ? 'maybe' : '');
  assert.equal(browserCanPlay('a.mp4', chrome), true);
  assert.equal(browserCanPlay('a.avi', chrome), false);
  assert.equal(browserCanPlay('a.mpg', chrome), false);
  assert.equal(browserCanPlay('a.xyz', chrome), true);
});
