// Редактор исходного текста (G05): чистые функции web/static/js/editors/lyrics-text.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeLyrics, regenFields } from '../../web/static/js/editors/lyrics-text.js';

test('строки нумеруются, метки [..] помечаются, счётчики', () => {
  const r = analyzeLyrics('[Куплет 1]\nПервая строка\n\n  [Припев]  \nНе [метка] внутри\n[незакрытая\n');
  assert.deepEqual(r.lines.map((l) => [l.n, l.marker]), [
    [1, true], [2, false], [3, false], [4, true], [5, false], [6, false], [7, false],
  ]);
  assert.equal(r.lines[1].text, 'Первая строка');
  assert.equal(r.total, 7);
  assert.equal(r.markers, 2);
  assert.equal(r.sung, 3, 'непустые строки без меток');
});

test('CRLF и пустой текст', () => {
  assert.deepEqual(analyzeLyrics('a\r\nb').lines.map((l) => l.text), ['a', 'b']);
  const e = analyzeLyrics('');
  assert.equal(e.total, 1);
  assert.equal(e.sung, 0);
});

test('поля задания generate: replace, song_id, параметры песни поверх умолчаний', () => {
  const song = { song_id: 's1', artist: 'A', title: 'T', own: true, params: { whisper_model: 'large-v2', rel_dir: 'x' } };
  const f = regenFields(song, 'текст\r\nстрока', { whisper_model: 'medium', language: 'ru' });
  assert.equal(f.artist, 'A');
  assert.equal(f.title, 'T');
  assert.equal(f.song_id, 's1');
  assert.equal(f.replace, 'true');
  assert.equal(f.lyrics, 'текст\nстрока');
  assert.deepEqual(JSON.parse(f.params), { whisper_model: 'large-v2', language: 'ru' });
  const foreign = regenFields({ song_id: 's2', artist: 'B', title: 'U', own: false }, 'x', { language: 'en' });
  assert.deepEqual(JSON.parse(foreign.params), { language: 'en' });
});
