// Импорт (R07i, R06i.1, G05): чистые функции web/static/js/import-logic.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  pickAudioSource, importWarnings, NEED_AUDIO, WARN_SYNC,
  initialCardState, importFields, importBlocker, importOutcome, EXPIRED, DUP_TEXT, expiredMessage,
} from '../../web/static/js/import-logic.js';

const song = (o = {}) => ({
  index: 0, artist: 'Кино', title: 'Звезда', language: 'Russian', duet: false,
  audio: null, cover: false, has_instrumental: false, youtube: [], existing_song_id: null, warnings: [], ...o,
});

test('pickAudioSource: свой mp3 важнее всего', () => {
  const s = song({ audio: 'Кино - Звезда.mp3', youtube: ['https://www.youtube.com/watch?v=a'] });
  assert.deepEqual(pickAudioSource(s, { file: { name: 'my.mp3' }, youtube: 'https://youtu.be/x' }),
    { kind: 'upload', name: 'my.mp3' });
});

test('pickAudioSource: затем аудио из архива, ссылка тогда не нужна', () => {
  const s = song({ audio: 'song.ogg', youtube: ['https://www.youtube.com/watch?v=a'] });
  assert.deepEqual(pickAudioSource(s, { youtube: 'https://youtu.be/x' }), { kind: 'archive', name: 'song.ogg' });
});

test('pickAudioSource: затем своя ссылка, затем ссылка из песни', () => {
  const s = song({ youtube: ['https://www.youtube.com/watch?v=a', 'https://www.youtube.com/watch?v=b'] });
  assert.deepEqual(pickAudioSource(s, { youtube: '  https://youtu.be/x ' }), { kind: 'youtube', url: 'https://youtu.be/x' });
  assert.deepEqual(pickAudioSource(s, { youtube: '' }), { kind: 'youtube', url: 'https://www.youtube.com/watch?v=a' });
  assert.deepEqual(pickAudioSource(s, {}), { kind: 'youtube', url: 'https://www.youtube.com/watch?v=a' });
});

test('pickAudioSource: без файла, архива и ссылок — звука нет', () => {
  assert.deepEqual(pickAudioSource(song(), { youtube: '   ' }), { kind: 'none' });
});

test('importWarnings: нет звука — «Нужен звук…» приходит от сервера и показывается как есть', () => {
  assert.equal(NEED_AUDIO, 'Нужен звук: загрузите mp3 или вставьте ссылку на YouTube');
  assert.deepEqual(importWarnings(song({ warnings: [NEED_AUDIO] }), { kind: 'none' }), [NEED_AUDIO]);
});

test('importWarnings: звук не из архива — предупреждение о рассинхроне', () => {
  assert.equal(WARN_SYNC, 'Ноты сделаны под конкретную запись — с другой версией слова могут разъехаться');
  assert.deepEqual(importWarnings(song(), { kind: 'youtube', url: 'u' }), [WARN_SYNC]);
  assert.deepEqual(importWarnings(song({ audio: 'a.mp3' }), { kind: 'upload', name: 'b.mp3' }), [WARN_SYNC]);
  assert.deepEqual(importWarnings(song({ audio: 'a.mp3' }), { kind: 'archive', name: 'a.mp3' }), []);
});

test('importWarnings: звук песни как в разборе — предупреждения сервера как есть, без фильтра', () => {
  const other = 'Любое предупреждение сервера';
  const yt = song({ youtube: ['https://www.youtube.com/watch?v=a'], warnings: ['про ссылку — от сервера', other] });
  assert.deepEqual(importWarnings(yt, pickAudioSource(yt, { youtube: '' })), ['про ссылку — от сервера', other]);
  assert.deepEqual(importWarnings(yt, pickAudioSource(yt, { youtube: ' https://www.youtube.com/watch?v=a ' })),
    ['про ссылку — от сервера', other]);
  const mute = song({ warnings: ['нет звука — от сервера'] });
  assert.deepEqual(importWarnings(mute, pickAudioSource(mute, {})), ['нет звука — от сервера']);
  const arch = song({ audio: 'a.mp3', warnings: [other] });
  assert.deepEqual(importWarnings(arch, pickAudioSource(arch, {})), [other]);
});

test('importWarnings: свой звук сервер не видел — только своё предупреждение о рассинхроне', () => {
  const mute = song({ warnings: ['нет звука — от сервера'] });
  assert.deepEqual(importWarnings(mute, pickAudioSource(mute, { youtube: 'https://youtu.be/x' })), [WARN_SYNC]);
  assert.deepEqual(importWarnings(mute, pickAudioSource(mute, { file: { name: 'my.mp3' } })), [WARN_SYNC]);
});

test('initialCardState: дубли не отмечены, минусовка выключена при своём [Instrumental]', () => {
  assert.deepEqual(initialCardState(song({ youtube: ['https://www.youtube.com/watch?v=a'] })), {
    selected: true, artist: 'Кино', title: 'Звезда', youtube: 'https://www.youtube.com/watch?v=a',
    instrumental: true, replace: false, existing: null,
  });
  const dup = initialCardState(song({ existing_song_id: 'sid', has_instrumental: true }));
  assert.equal(dup.selected, false);
  assert.equal(dup.existing, 'sid');
  assert.equal(dup.instrumental, false);
  assert.equal(dup.youtube, '');
  // ссылка в поле — по тому же правилу, что pickAudioSource: первая непустая после trim
  const links = song({ youtube: ['  ', ' https://www.youtube.com/watch?v=b ', 'https://www.youtube.com/watch?v=c'] });
  assert.equal(initialCardState(links).youtube, 'https://www.youtube.com/watch?v=b');
  assert.deepEqual(pickAudioSource(links, {}), { kind: 'youtube', url: initialCardState(links).youtube });
});

test('importFields: что уходит в POST /api/jobs/import', () => {
  const file = { name: 'my.mp3' };
  const base = { token: 't1', index: 2, artist: ' Кино ', title: 'Звезда ', instrumental: true, replace: false };
  assert.deepEqual(importFields('t1', song({ index: 2 }), { ...base, file, youtube: 'https://youtu.be/x' }),
    { token: 't1', index: 2, artist: 'Кино', title: 'Звезда', audio: file, instrumental: true, replace: false });
  assert.deepEqual(importFields('t1', song({ index: 2, youtube: ['https://www.youtube.com/watch?v=a'] }), { ...base, youtube: '' }),
    { token: 't1', index: 2, artist: 'Кино', title: 'Звезда', youtube_url: 'https://www.youtube.com/watch?v=a',
      instrumental: true, replace: false });
  assert.deepEqual(importFields('t1', song({ index: 2, audio: 'a.mp3' }), { ...base, youtube: 'https://youtu.be/x', replace: true }),
    { token: 't1', index: 2, artist: 'Кино', title: 'Звезда', instrumental: true, replace: true });
});

test('importBlocker: нужна хотя бы одна песня и звук у каждой отмеченной', () => {
  const ok = { song: song({ audio: 'a.mp3' }), state: { ...initialCardState(song({ audio: 'a.mp3' })) } };
  const mute = { song: song(), state: initialCardState(song()) };
  assert.equal(importBlocker([]), 'Отметьте песни для импорта');
  assert.equal(importBlocker([{ ...ok, state: { ...ok.state, selected: false } }]), 'Отметьте песни для импорта');
  assert.equal(importBlocker([ok, mute]), NEED_AUDIO);
  assert.equal(importBlocker([ok, { ...mute, state: { ...mute.state, selected: false } }]), null);
  assert.equal(importBlocker([{ ...ok, state: { ...ok.state, artist: ' ' } }]), 'Укажите исполнителя и название');
});

test('importOutcome: 409 с song_id — дубль, 410 — загрузка устарела, прочее — текст и поле', () => {
  assert.equal(DUP_TEXT, 'Уже есть в папке результата');
  assert.deepEqual(importOutcome({ status: 409, detail: 'Такая песня уже есть в папке результата', data: { song_id: 'x' } }),
    { kind: 'duplicate', songId: 'x', text: DUP_TEXT });
  assert.deepEqual(importOutcome({ status: 410, detail: 'Текст сервера', data: {} }), { kind: 'expired', text: 'Текст сервера' });
  assert.deepEqual(importOutcome({ status: 410, data: {} }), { kind: 'expired', text: EXPIRED });
  assert.deepEqual(importOutcome({ status: 409, detail: 'Эта песня уже в очереди', data: {} }),
    { kind: 'error', text: 'Эта песня уже в очереди', field: null });
  assert.deepEqual(importOutcome({ status: 400, detail: 'Это не mp3-файл', data: { field: 'audio' } }),
    { kind: 'error', text: 'Это не mp3-файл', field: 'audio' });
});

test('expiredMessage: прерванный импорт пака называет, сколько песен уже в очереди', () => {
  assert.equal(expiredMessage('Загрузка устарела, загрузите заново', 0), 'Загрузка устарела, загрузите заново');
  assert.equal(expiredMessage('Загрузка устарела, загрузите заново', 2),
    'Загрузка устарела, загрузите заново. Уже поставлено в очередь: 2 — их загружать заново не нужно');
  assert.equal(expiredMessage('Загрузка устарела.', 1),
    'Загрузка устарела. Уже поставлено в очередь: 1 — их загружать заново не нужно');
});

test('importForm / inspectForm: multipart как ждёт сервер', async () => {
  const { importForm, inspectForm } = await import('../../web/static/js/api.js');
  const file = new Blob(['ID3'], { type: 'audio/mpeg' });
  const fd = importForm({ token: 't', index: 3, artist: 'A', title: 'T', audio: file, instrumental: true, replace: false });
  assert.deepEqual([...fd.keys()], ['token', 'index', 'artist', 'title', 'audio', 'instrumental', 'replace']);
  assert.equal(fd.get('index'), '3');
  assert.equal(fd.get('instrumental'), 'true');
  assert.equal(fd.get('replace'), 'false');
  const yt = importForm({ token: 't', index: 0, artist: 'A', title: 'T', youtube_url: 'https://youtu.be/x', instrumental: false, replace: true });
  assert.equal(yt.get('youtube_url'), 'https://youtu.be/x');
  assert.equal(yt.has('audio'), false);

  assert.deepEqual([...inspectForm({ source: 'usdb', usdb_id: 42 }).entries()], [['source', 'usdb'], ['usdb_id', '42']]);
  assert.deepEqual([...inspectForm({ source: 'url', url: ' https://github.com/a/b ' }).entries()],
    [['source', 'url'], ['url', 'https://github.com/a/b']]);
  const files = inspectForm({ source: 'files', files: [new File(['x'], 'a.txt'), new File(['y'], 'a.mp3')] });
  assert.deepEqual(files.getAll('files').map((f) => f.name), ['a.txt', 'a.mp3']);
});
