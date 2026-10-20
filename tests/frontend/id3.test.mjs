// Теги mp3 (G07): чистый разбор ID3 web/static/js/id3.js на фикстурах, собранных байтами.
import test from 'node:test';
import assert from 'node:assert/strict';
import { id3v2Size, parseId3, planAutofill } from '../../web/static/js/id3.js';

const JPEG = [0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9];
const MPEG_FRAME = [0xff, 0xfb, 0x90, 0x64, 0, 0, 0, 0];

const ascii = (s) => [...s].map((c) => c.charCodeAt(0));
const utf8 = (s) => [...new TextEncoder().encode(s)];
const utf16bom = (s) => { const o = [0xff, 0xfe]; for (const c of s) { const x = c.charCodeAt(0); o.push(x & 0xff, x >> 8); } return o; };
const cp1251 = (s) => [...s].map((c) => {
  const x = c.charCodeAt(0);
  if (x >= 0x410 && x <= 0x44f) return x - 0x410 + 0xc0;
  if (c === 'ё') return 0xb8;
  if (c === 'Ё') return 0xa8;
  return x;
});
const be32 = (n) => [(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff];
const syncsafe = (n) => [(n >> 21) & 0x7f, (n >> 14) & 0x7f, (n >> 7) & 0x7f, n & 0x7f];

function frame(ver, id, body) {
  if (ver === 2) return [...ascii(id), (body.length >> 16) & 0xff, (body.length >> 8) & 0xff, body.length & 0xff, ...body];
  return [...ascii(id), ...(ver === 4 ? syncsafe(body.length) : be32(body.length)), 0, 0, ...body];
}
function tag(ver, frames, padding = 16) {
  const body = [...frames.flat(), ...new Array(padding).fill(0)];
  return [...ascii('ID3'), ver, 0, 0, ...syncsafe(body.length), ...body];
}
function v1(title, artist) {
  const pad = (b) => [...b, ...new Array(30 - b.length).fill(0)].slice(0, 30);
  return [...ascii('TAG'), ...pad(title), ...pad(artist), ...new Array(30 + 4 + 30).fill(0), 12];
}
// mp3: тег ID3v2 в начале, аудиокадры, ID3v1 в последних 128 байтах
const mp3 = (v2 = [], v1tag = []) => new Uint8Array([...v2, ...MPEG_FRAME, ...MPEG_FRAME, ...v1tag]);
const tail = (u8) => u8.slice(Math.max(0, u8.length - 128));

test('ID3v2.3: UTF-16 с BOM, APIC — обложка', () => {
  const file = mp3(tag(3, [
    frame(3, 'TPE1', [1, ...utf16bom('Кино'), 0, 0]),
    frame(3, 'TIT2', [1, ...utf16bom('Группа крови')]),
    frame(3, 'APIC', [1, ...ascii('image/jpeg'), 0, 3, ...utf16bom('обл'), 0, 0, ...JPEG]),
  ]));
  assert.equal(id3v2Size(file.slice(0, 10)), file.length - 16);
  const t = parseId3(file, tail(file));
  assert.equal(t.artist, 'Кино');
  assert.equal(t.title, 'Группа крови');
  assert.equal(t.cover.mime, 'image/jpeg');
  assert.deepEqual([...t.cover.data], JPEG);
});

test('ID3v2.4: UTF-8, размеры кадров syncsafe; без APIC — обложки нет', () => {
  const long = 'Очень длинное название песни, '.repeat(6); // > 127 байт: проверка syncsafe
  const file = mp3(tag(4, [frame(4, 'TIT2', [3, ...utf8(long), 0]), frame(4, 'TPE1', [3, ...utf8('Сплин')])]));
  const t = parseId3(file, tail(file));
  assert.equal(t.title, long.trim());
  assert.equal(t.artist, 'Сплин');
  assert.equal(t.cover, null);
});

test('ID3v1 в cp1251', () => {
  const file = mp3([], v1(cp1251('Звезда по имени Солнце'), cp1251('Кино')));
  const t = parseId3(file.slice(0, 10), tail(file));
  assert.equal(t.title, 'Звезда по имени Солнце');
  assert.equal(t.artist, 'Кино');
  assert.equal(t.cover, null);
});

test('latin-1 в ID3v2: кириллица в cp1251 распознаётся, латиница с диакритикой — нет', () => {
  const file = mp3(tag(3, [frame(3, 'TPE1', [0, ...cp1251('Ария')]), frame(3, 'TIT2', [0, ...ascii('Caf'), 0xe9])]));
  const t = parseId3(file, tail(file));
  assert.equal(t.artist, 'Ария');
  assert.equal(t.title, 'Café');
});

test('ID3v2.2 (TP1/TT2/PIC) и v2 приоритетнее v1', () => {
  const file = mp3(tag(2, [
    frame(2, 'TT2', [0, ...ascii('Title22')]),
    frame(2, 'PIC', [0, ...ascii('JPG'), 3, 0, ...JPEG]),
  ]), v1(ascii('Old'), ascii('Artist v1')));
  const t = parseId3(file, tail(file));
  assert.equal(t.title, 'Title22');
  assert.equal(t.artist, 'Artist v1', 'нет TP1 → берётся из v1');
  assert.equal(t.cover.mime, 'image/jpeg');
});

test('mp3 без тегов и мусор — пустые поля без ошибок', () => {
  const file = mp3();
  assert.equal(id3v2Size(file.slice(0, 10)), 0);
  assert.deepEqual(parseId3(file, tail(file)), { artist: '', title: '', cover: null });
  const broken = new Uint8Array([...ascii('ID3'), 3, 0, 0, 0, 0, 0x7f, 0x7f, ...ascii('TPE1'), 0xff, 0xff, 0xff, 0xff]);
  assert.deepEqual(parseId3(broken, new Uint8Array()), { artist: '', title: '', cover: null });
});

test('автозаполнение: только пустые поля; значения из прошлого mp3 заменяются', () => {
  const tags = { artist: 'Кино', title: 'Кукушка', cover: null };
  assert.deepEqual(planAutofill({ artist: '', title: '  ' }, tags), { artist: 'Кино', title: 'Кукушка' });
  assert.deepEqual(planAutofill({ artist: 'Свой', title: '' }, tags), { title: 'Кукушка' });
  assert.deepEqual(planAutofill({ artist: 'Свой', title: 'Своё' }, tags), {});
  assert.deepEqual(planAutofill({ artist: '', title: '' }, { artist: '', title: '', cover: null }), {});
  // поле заполнено тегами прошлого файла и не тронуто — новый mp3 его обновляет
  assert.deepEqual(planAutofill({ artist: 'Старый', title: 'Своё' }, tags, { artist: 'Старый', title: 'Чужое' }),
    { artist: 'Кино' });
});

// ---------------------------------------------------------------- дозапрос: обложка и ветки parseV2

const deunsyncable = (b) => { const o = []; for (const x of b) { o.push(x); if (x === 0xff) o.push(0); } return o; };
const t = (u8) => parseId3(u8, tail(u8));

test('обложка из тегов без распознанной сигнатуры jpg/png/webp — игнорируется молча', () => {
  const gif = [...ascii('GIF89a'), 1, 0, 1, 0];
  for (const [mime, data] of [['image/jpeg', [1, 2, 3, 4, 5]], ['image/gif', gif], ['image/png', ascii('not a png')]]) {
    const file = mp3(tag(3, [frame(3, 'TPE1', [0, ...ascii('A')]),
      frame(3, 'APIC', [0, ...ascii(mime), 0, 3, 0, ...data])]));
    const r = t(file);
    assert.equal(r.cover, null, mime);
    assert.equal(r.artist, 'A');
  }
  const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0];
  const ok = t(mp3(tag(3, [frame(3, 'APIC', [0, ...ascii('image/jpeg'), 0, 3, 0, ...PNG])])));
  assert.equal(ok.cover.mime, 'image/png', 'тип — по сигнатуре, а не по заявленному');
});

test('флаг группировки: v2.3 0x20 и v2.4 0x40 — байт group id пропускается', () => {
  const v3 = [...ascii('TPE1'), ...be32(1 + 1 + 4), 0, 0x20, 7, 0, ...ascii('Grp3')];
  const v4 = [...ascii('TIT2'), ...syncsafe(1 + 1 + 4), 0, 0x40, 9, 3, ...utf8('Grp4')];
  assert.equal(t(mp3(tag(3, [v3]))).artist, 'Grp3');
  assert.equal(t(mp3(tag(4, [v4]))).title, 'Grp4');
});

test('v2.3: unsynchronisation на весь тег', () => {
  const frames = [...frame(3, 'TIT2', [0, ...ascii('Uns')]), ...frame(3, 'APIC', [0, ...ascii('image/jpeg'), 0, 3, 0, ...JPEG])];
  const body = [...deunsyncable(frames), ...new Array(8).fill(0)];
  const file = new Uint8Array([...ascii('ID3'), 3, 0, 0x80, ...syncsafe(body.length), ...body, ...MPEG_FRAME]);
  const r = t(file);
  assert.equal(r.title, 'Uns');
  assert.deepEqual([...r.cover.data], JPEG);
});

test('v2.4: unsynchronisation и data length indicator на кадре', () => {
  const pic = [0, ...ascii('image/jpeg'), 0, 3, 0, ...JPEG];
  const unsBody = [...syncsafe(pic.length), ...deunsyncable(pic)];
  const apic = [...ascii('APIC'), ...syncsafe(unsBody.length), 0, 0x03, ...unsBody];
  const dliBody = [...syncsafe(5), 3, ...utf8('Dli!')];
  const tit = [...ascii('TIT2'), ...syncsafe(dliBody.length), 0, 0x01, ...dliBody];
  const r = t(mp3(tag(4, [apic, tit])));
  assert.deepEqual([...r.cover.data], JPEG);
  assert.equal(r.title, 'Dli!');
});

test('extended header v2.3 и v2.4', () => {
  const fr3 = frame(3, 'TPE1', [0, ...ascii('Ext3')]);
  const ext3 = [...be32(6), 0, 0, ...be32(0)];
  const b3 = [...ext3, ...fr3, 0, 0, 0, 0];
  assert.equal(t(new Uint8Array([...ascii('ID3'), 3, 0, 0x40, ...syncsafe(b3.length), ...b3, ...MPEG_FRAME])).artist, 'Ext3');
  const fr4 = frame(4, 'TPE1', [3, ...utf8('Ext4')]);
  const ext4 = [...syncsafe(6), 1, 0];
  const b4 = [...ext4, ...fr4, 0, 0, 0, 0];
  assert.equal(t(new Uint8Array([...ascii('ID3'), 4, 0, 0x40, ...syncsafe(b4.length), ...b4, ...MPEG_FRAME])).artist, 'Ext4');
});

test('UTF-16 без BOM (как LE) и enc=2 (UTF-16BE)', () => {
  const le = []; for (const c of 'Без') { const x = c.charCodeAt(0); le.push(x & 0xff, x >> 8); }
  const be = []; for (const c of 'Би') { const x = c.charCodeAt(0); be.push(x >> 8, x & 0xff); }
  const r = t(mp3(tag(4, [frame(4, 'TPE1', [1, ...le, 0, 0]), frame(4, 'TIT2', [2, ...be])])));
  assert.equal(r.artist, 'Без');
  assert.equal(r.title, 'Би');
});

test('кадр длиннее тега и обрезанный файл — без исключений, прочитанное сохраняется', () => {
  const good = frame(3, 'TPE1', [0, ...ascii('Ok')]);
  const huge = [...ascii('TIT2'), ...be32(100000), 0, 0, 0, ...ascii('x')];
  const file = mp3(tag(3, [good, huge], 0));
  assert.deepEqual(t(file), { artist: 'Ok', title: '', cover: null });
  const cut = file.slice(0, 14);
  assert.deepEqual(parseId3(cut, new Uint8Array()), { artist: '', title: '', cover: null });
});
