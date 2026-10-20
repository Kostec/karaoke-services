import { test } from 'node:test';
import assert from 'node:assert/strict';

const logic = await import('../../web/static/js/folder-logic.js');

const NOTES = '#BPM:300\n#GAP:0\n: 0 4 5 Раз\nE\n';
const song = (head) => `${head}\n${NOTES}`;

test('splitFolder: смешанная папка — готовые песни, музыка для генерации, пропущенные', () => {
  const entries = [
    { path: 'Музыка/Кино - Группа крови/song.txt',
      text: song('#TITLE:Группа крови\n#ARTIST:Кино\n#MP3:SONG.MP3\n#COVER:cover.JPG\n#INSTRUMENTAL:minus.mp3') },
    { path: 'Музыка/Кино - Группа крови/song.mp3' },
    { path: 'Музыка/Кино - Группа крови/cover.jpg' },
    { path: 'Музыка/Кино - Группа крови/minus.mp3' },
    // mp3 в папке песни, на который .txt не ссылается, — тоже не генерация
    { path: 'Музыка/Кино - Группа крови/demo.mp3' },
    { path: 'Музыка/Кино - Группа крови/song.lyrics.txt', text: 'Раз два' },
    // ссылка в подпапку и ссылка с #AUDIO
    { path: 'Музыка/Ария/ария.txt', text: song('#TITLE:Ангел\n#ARTIST:Ария\n#AUDIO:audio/Ангел.ogg') },
    { path: 'Музыка/Ария/audio/ангел.OGG' },
    // обычные mp3 — на генерацию
    { path: 'Музыка/Сплин - Романс.mp3' },
    { path: 'Музыка/Разное/Земфира - Ромашки.MP3' },
    // лишнее
    { path: 'Музыка/readme.txt', text: 'просто текст' },
    { path: 'Музыка/Разное/clip.ogg' },
    { path: 'Музыка/Разное/folder.jpg' },
    { path: 'Музыка/.git/x.mp3' },
    { path: 'Музыка/notes.docx' },
  ];
  const r = logic.splitFolder(entries);
  assert.deepEqual(r.songs.slice().sort(), [
    'Музыка/Ария/audio/ангел.OGG',
    'Музыка/Ария/ария.txt',
    'Музыка/Кино - Группа крови/cover.jpg',
    'Музыка/Кино - Группа крови/demo.mp3',
    'Музыка/Кино - Группа крови/minus.mp3',
    'Музыка/Кино - Группа крови/song.mp3',
    'Музыка/Кино - Группа крови/song.txt',
  ].sort());
  assert.deepEqual(r.music, ['Музыка/Разное/Земфира - Ромашки.MP3', 'Музыка/Сплин - Романс.mp3']);
  assert.equal(r.skipped, 6);
  assert.equal(r.songCount, 2);
});

test('splitFolder: песня, сославшаяся на mp3 в соседней папке, забирает его из генерации', () => {
  const r = logic.splitFolder([
    { path: 'a/song.txt', text: song('#TITLE:T\n#ARTIST:A\n#MP3:sub/x.mp3') },
    { path: 'a/sub/x.mp3' },
    { path: 'a/sub/y.mp3' },
  ]);
  assert.deepEqual(r.songs.slice().sort(), ['a/song.txt', 'a/sub/x.mp3']);
  assert.deepEqual(r.music, ['a/sub/y.mp3']);
  assert.equal(r.skipped, 0);
});

test('splitFolder: без песен — всё mp3 в генерацию', () => {
  const r = logic.splitFolder([{ path: 'x/1.mp3' }, { path: 'x/2.mp3' }, { path: 'x/cover.png' }]);
  assert.deepEqual(r.songs, []);
  assert.deepEqual(r.music, ['x/1.mp3', 'x/2.mp3']);
  assert.equal(r.skipped, 1);
  assert.equal(r.songCount, 0);
});

test('trackMeta: ID3 → имя файла «Исполнитель - Название» → только название, исполнитель пуст', () => {
  assert.deepEqual(logic.trackMeta({ artist: 'Кино', title: 'Кукушка' }, 'Музыка/01 трек.mp3'),
    { artist: 'Кино', title: 'Кукушка', needArtist: false });
  assert.deepEqual(logic.trackMeta({ artist: '', title: '' }, 'Музыка/Сплин - Романс.mp3'),
    { artist: 'Сплин', title: 'Романс', needArtist: false });
  assert.deepEqual(logic.trackMeta(null, 'Земфира  -  Ромашки.MP3'),
    { artist: 'Земфира', title: 'Ромашки', needArtist: false });
  assert.deepEqual(logic.trackMeta({}, '07 - ДДТ - Осень.mp3'), { artist: 'ДДТ', title: 'Осень', needArtist: false });
  assert.deepEqual(logic.trackMeta({ title: 'Только тег' }, 'Ария - Ангел.mp3'),
    { artist: 'Ария', title: 'Только тег', needArtist: false });
  assert.deepEqual(logic.trackMeta({}, 'a/track01.mp3'), { artist: '', title: 'track01', needArtist: true });
});

test('initialTrack / ограничения: трек больше max_upload_mb помечен и не выбирается; дубль снимает галочку', () => {
  const MB = 1024 * 1024;
  const meta = { artist: 'Сплин', title: 'Романс', needArtist: false };
  const ok = logic.initialTrack('Сплин - Романс.mp3', 5 * MB, meta, 10);
  assert.equal(ok.selected, true);
  assert.equal(ok.tooBig, '');
  assert.equal(ok.lyrics, 'queued');
  const big = logic.initialTrack('big.mp3', 10 * MB + 1, meta, 10);
  assert.equal(big.selected, false);
  assert.equal(big.tooBig, 'Больше 10 МБ — такой mp3 не загрузится');
  assert.equal(logic.generateBlocker([{ state: big }]), 'Отметьте треки для генерации');
  assert.equal(logic.generateBlocker([{ state: { ...big, selected: true } }]), 'Больше 10 МБ — такой mp3 не загрузится');
  assert.equal(logic.generateBlocker([{ state: { ...ok, lyrics: 'none' } }, { state: { ...ok, artist: ' ' } }]), 'Укажите исполнителя и название');
  assert.equal(logic.generateBlocker([{ state: ok }]), 'Тексты ещё ищутся — подождите');
  assert.equal(logic.generateBlocker([{ state: { ...ok, lyrics: 'searching' } }]), 'Тексты ещё ищутся — подождите');
  assert.equal(logic.generateBlocker([{ state: { ...ok, lyrics: 'found' } }, { state: { ...ok, lyrics: 'none' } }]), null);
  assert.equal(logic.generateBlocker([{ state: { ...ok, lyrics: 'failed' } }, { state: { ...big, lyrics: 'queued' } }]), null);

  assert.deepEqual(logic.withExisting(ok, 'id1'), { existing: 'id1', selected: false });
  assert.deepEqual(logic.withExisting({ ...ok, touched: true }, 'id1'), { existing: 'id1' });
  assert.deepEqual(logic.withExisting({ ...ok, existing: 'id1', selected: false }, null), { existing: null, selected: true });

  assert.equal(logic.folderNotice(300), '');
  assert.equal(logic.folderNotice(301), 'В папке 301 файл — разбор и загрузка займут время');
  assert.equal(logic.queuedText(2, 5), 'Поставлено 2 из 5');
});

test('текст трека: подпись, LRC и галочка таймингов по правилу 3 с, поля generate', () => {
  const base = logic.initialTrack('a.mp3', 100, { artist: 'Кино', title: 'Кукушка', needArtist: false }, 10);
  assert.equal(logic.lyricsLabel(base), 'текст будет найден автоматически');
  assert.equal(logic.lyricsLabel({ ...base, lyrics: 'searching' }), 'ищу текст…');
  assert.equal(logic.lyricsLabel({ ...base, lyrics: 'none' }), 'текст не найден — слова распознаются автоматически');

  const plain = { id: 1, text: 'Песен ещё не написанных', synced: null, duration: 200 };
  const synced = { id: 2, text: 'Раз\nДва', synced: '[00:01.00] Раз\n[00:05.00][00:09.00] Два', duration: 200 };

  // вариант без LRC
  let s = { ...base, duration: 201, ...logic.withHit({ ...base, duration: 201 }, plain) };
  assert.equal(s.lyrics, 'found');
  assert.equal(logic.lyricsLabel(s), 'текст найден');
  assert.equal(s.lrcTiming, false);
  let f = logic.trackFields(s, 'FILE', { language: 'ru', lrc_timing: true });
  assert.deepEqual(f, { artist: 'Кино', title: 'Кукушка', lyrics: 'Песен ещё не написанных', audio: 'FILE',
    audio_url: undefined, cover_url: undefined, params: { language: 'ru', lrc_timing: false }, replace: false, song_id: undefined, lyrics_lrc: undefined });

  // синхронизированный: текст из LRC в развёрнутом порядке, длительность близка → тайминги включены
  s = { ...base, duration: 202.5, ...logic.withHit({ ...base, duration: 202.5 }, synced) };
  assert.equal(logic.lyricsLabel(s), 'текст найден · есть синхронизация');
  assert.equal(s.lrcTiming, true);
  assert.equal(s.lrcHint, '');
  f = logic.trackFields(s, 'FILE', { language: 'ru' });
  assert.equal(f.lyrics, 'Раз\nДва\nДва');
  assert.equal(f.lyrics_lrc, synced.synced);
  assert.equal(f.params.lrc_timing, true);

  // длительность разнится > 3 с → выключено с подсказкой; длительность пришла позже — пересчёт
  s = { ...base, ...logic.withHit(base, synced) };
  assert.equal(s.lrcTiming, false);
  s = { ...s, ...logic.withDuration(s, 230) };
  assert.equal(s.lrcTiming, false);
  assert.equal(s.lrcHint, 'Длительность не совпадает с mp3 — тайминги, скорее всего, от другой версии');
  s = { ...s, ...logic.withDuration(s, 199) };
  assert.equal(s.lrcTiming, true);

  // текста нет — пустой текст, слова распознаются; дубль с «Заменить»
  s = { ...base, ...logic.withHit(base, null), existing: 'sid', replace: true };
  assert.equal(s.lyrics, 'none');
  f = logic.trackFields(s, 'FILE', {});
  assert.equal(f.lyrics, '');
  assert.equal(f.lyrics_lrc, undefined);
  assert.equal(f.replace, true);
  assert.equal(f.song_id, undefined);
});

test('inspectForm: файлы папки уходят с относительными путями, обычные — по имени', async () => {
  const { inspectForm } = await import('../../web/static/js/api.js');
  const inFolder = new File(['x'], 'song.txt');
  Object.defineProperty(inFolder, 'webkitRelativePath', { value: 'Музыка/Кино - Группа крови/song.txt' });
  const fd = inspectForm({ source: 'files', files: [inFolder, new File(['y'], 'a.mp3')] });
  assert.deepEqual(fd.getAll('files').map((f) => f.name), ['Музыка/Кино - Группа крови/song.txt', 'a.mp3']);
});

test('nextLyricsRow: следующий трек для поиска — первый в очереди с исполнителем и названием, правка возвращает строку', () => {
  const t = (over) => ({ ...logic.initialTrack('a.mp3', 1, { artist: 'A', title: 'T', needArtist: false }, 10), ...over });
  const rows = [t({ lyrics: 'found' }), t({ artist: '' }), t({ lyrics: 'searching' }), t({ tooBig: 'big' }), t({})];
  assert.equal(logic.nextLyricsRow(rows), 4);
  rows[4].lyrics = 'found';
  assert.equal(logic.nextLyricsRow(rows), -1);
  // пока шёл поиск, у строки без исполнителя его вписали — проход должен её взять
  rows[1].artist = 'Кино';
  assert.equal(logic.nextLyricsRow(rows), 1);
  // строку, которую уже искали, правка вернула в очередь — её снова берут
  rows[1].lyrics = 'none'; rows[0].lyrics = 'queued';
  assert.equal(logic.nextLyricsRow(rows), 0);
});
