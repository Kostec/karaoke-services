// Теги mp3 (G07): разбор ID3v1 и ID3v2.2–2.4 в браузере, без отправки на сервер.
//
// Чистые функции (тесты — tests/frontend/id3.test.mjs):
//   id3v2Size(head10) → полный размер тега ID3v2 в байтах (0 — тега нет);
//   parseId3(head, tail) → {artist, title, cover: {mime, data}|null} (пустые строки, если нет);
//   planAutofill(current, tags, prevAuto) → какие поля формы заполнить.
// readId3(file) — обёртка для File/Blob.

const MAX_TAG_BYTES = 16 * 1024 * 1024;

function syncsafe(b, i) {
  return ((b[i] & 0x7f) << 21) | ((b[i + 1] & 0x7f) << 14) | ((b[i + 2] & 0x7f) << 7) | (b[i + 3] & 0x7f);
}

function be32(b, i) {
  return ((b[i] << 24) >>> 0) + (b[i + 1] << 16) + (b[i + 2] << 8) + b[i + 3];
}

function ascii(b, from, to) {
  let s = '';
  for (let i = from; i < to; i++) s += String.fromCharCode(b[i]);
  return s;
}

/** Размер тега ID3v2 вместе с заголовком (и футером v2.4); 0 — тега нет. */
export function id3v2Size(head) {
  if (!head || head.length < 10 || ascii(head, 0, 3) !== 'ID3' || head[3] < 2 || head[3] > 4) return 0;
  return 10 + syncsafe(head, 6) + (head[3] === 4 && head[5] & 0x10 ? 10 : 0);
}

// ---------------------------------------------------------------- кодировки

const isHighLetter = (x) => x >= 0xc0 || x === 0xa8 || x === 0xb8;
const isAsciiLetter = (x) => (x >= 0x41 && x <= 0x5a) || (x >= 0x61 && x <= 0x7a);

/** Однобайтовый текст: latin-1, но кириллица в cp1251 (частый случай тегов «latin-1»). */
function looksCp1251(b) {
  let high = 0, letters = 0;
  let wordHigh = 0, wordAscii = 0;
  let wholeWord = false;
  const endWord = () => {
    if (wordHigh >= 2 && wordAscii === 0) wholeWord = true;
    wordHigh = 0; wordAscii = 0;
  };
  for (const x of b) {
    if (isHighLetter(x)) { high++; letters++; wordHigh++; }
    else if (isAsciiLetter(x)) { letters++; wordAscii++; }
    else endWord();
  }
  endWord();
  return high > 0 && (wholeWord || high * 2 >= letters);
}

function decodeSingleByte(b) {
  if (looksCp1251(b)) {
    try { return new TextDecoder('windows-1251').decode(b); } catch { /* нет декодера — как latin-1 */ }
  }
  let s = '';
  for (const x of b) s += String.fromCharCode(x);
  return s;
}

/** Конец строки с терминатором: индекс терминатора (или длина) и длина терминатора. */
function findTerminator(b, from, enc) {
  if (enc === 1 || enc === 2) {
    for (let i = from; i + 1 < b.length; i += 2) if (b[i] === 0 && b[i + 1] === 0) return [i, 2];
    return [b.length, 0];
  }
  for (let i = from; i < b.length; i++) if (b[i] === 0) return [i, 1];
  return [b.length, 0];
}

function decodeText(b, enc) {
  try {
    if (enc === 0) return decodeSingleByte(b);
    if (enc === 3) return new TextDecoder('utf-8').decode(b);
    if (enc === 2) return new TextDecoder('utf-16be').decode(b);
    if (enc === 1) {
      if (b[0] === 0xfe && b[1] === 0xff) return new TextDecoder('utf-16be').decode(b.subarray(2));
      if (b[0] === 0xff && b[1] === 0xfe) return new TextDecoder('utf-16le').decode(b.subarray(2));
      return new TextDecoder('utf-16le').decode(b);
    }
  } catch { /* битая строка — как пустая */ }
  return '';
}

const clean = (s) => s.replace(/\0+$/g, '').trim();

/** Текстовый кадр: байт кодировки + строка (берётся первое значение из нескольких). */
function textFrame(b) {
  if (!b.length) return '';
  const enc = b[0];
  const [end] = findTerminator(b, 1, enc);
  return clean(decodeText(b.subarray(1, end), enc));
}

function sniffMime(data, declared) {
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return 'image/jpeg';
  if (data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47) return 'image/png';
  if (ascii(data, 0, 4) === 'RIFF' && ascii(data, 8, 12) === 'WEBP') return 'image/webp';
  const m = (declared || '').toLowerCase();
  if (m === 'jpg' || m === 'image/jpg') return 'image/jpeg';
  if (m === 'png') return 'image/png';
  return m.includes('/') ? m : '';
}

/** Кадр APIC (v2.3/2.4) или PIC (v2.2) → {type, mime, data} | null. */
function pictureFrame(b, v22) {
  if (b.length < 4) return null;
  const enc = b[0];
  let pos, declared;
  if (v22) {
    declared = ascii(b, 1, 4);
    pos = 4;
  } else {
    const [end, tl] = findTerminator(b, 1, 0);
    declared = ascii(b, 1, end);
    pos = end + tl;
  }
  const type = b[pos];
  const [dEnd, dl] = findTerminator(b, pos + 1, enc);
  const data = b.slice(dEnd + dl);
  if (!data.length) return null;
  const mime = sniffMime(data, declared);
  return mime ? { type, mime, data } : null;
}

function deunsync(b) {
  const out = [];
  for (let i = 0; i < b.length; i++) {
    out.push(b[i]);
    if (b[i] === 0xff && b[i + 1] === 0x00) i++;
  }
  return Uint8Array.from(out);
}

function parseV2(head) {
  const res = { artist: '', title: '', cover: null };
  const total = id3v2Size(head);
  if (!total) return res;
  const ver = head[3], flags = head[5];
  let b = head.subarray(10, Math.min(head.length, 10 + syncsafe(head, 6)));
  if (flags & 0x80 && ver < 4) b = deunsync(b);
  let pos = 0;
  if (flags & 0x40 && ver >= 3 && b.length >= 4) pos = ver === 3 ? 4 + be32(b, 0) : syncsafe(b, 0);
  const idLen = ver === 2 ? 3 : 4, hdr = ver === 2 ? 6 : 10;
  const pictures = [];
  while (pos + hdr <= b.length && b[pos] !== 0) {
    const id = ascii(b, pos, pos + idLen);
    if (!/^[A-Z0-9]+$/.test(id)) break;
    const size = ver === 2 ? (b[pos + 3] << 16) | (b[pos + 4] << 8) | b[pos + 5]
      : ver === 4 ? syncsafe(b, pos + 4) : be32(b, pos + 4);
    const fmt = ver === 2 ? 0 : b[pos + 9];
    const start = pos + hdr, end = start + size;
    if (size <= 0 || end > b.length) break;
    pos = end;
    let body = b.subarray(start, end);
    if (ver === 4) {
      if (fmt & 0x0c) continue; // сжатие/шифрование не поддерживаем
      if (fmt & 0x01) body = body.subarray(4);
      if (fmt & 0x02) body = deunsync(body);
    } else if (ver === 3 && fmt & 0xc0) {
      continue;
    }
    if (id === 'TPE1' || id === 'TP1') res.artist = res.artist || textFrame(body);
    else if (id === 'TIT2' || id === 'TT2') res.title = res.title || textFrame(body);
    else if (id === 'APIC' || id === 'PIC') {
      const p = pictureFrame(body, ver === 2);
      if (p) pictures.push(p);
    }
  }
  const pic = pictures.find((p) => p.type === 3) || pictures[0];
  if (pic) res.cover = { mime: pic.mime, data: pic.data };
  return res;
}

function parseV1(tail) {
  if (!tail || tail.length < 128) return { artist: '', title: '' };
  const b = tail.subarray(tail.length - 128);
  if (ascii(b, 0, 3) !== 'TAG') return { artist: '', title: '' };
  const field = (from) => {
    const raw = b.subarray(from, from + 30);
    const z = raw.indexOf(0);
    return clean(decodeSingleByte(z >= 0 ? raw.subarray(0, z) : raw));
  };
  return { title: field(3), artist: field(33) };
}

/** Теги файла: head — начало файла (весь тег ID3v2), tail — последние 128 байт. */
export function parseId3(head, tail) {
  let v2 = { artist: '', title: '', cover: null };
  let v1 = { artist: '', title: '' };
  try { v2 = parseV2(head || new Uint8Array()); } catch { /* битый тег — как без тега */ }
  try { v1 = parseV1(tail); } catch { /* то же */ }
  return { artist: v2.artist || v1.artist, title: v2.title || v1.title, cover: v2.cover };
}

/**
 * Что заполнить в форме: только пустые поля (или ещё не тронутые значения из тегов прошлого mp3 — prevAuto).
 * current, prevAuto: {artist, title}; результат — {artist?, title?}.
 */
export function planAutofill(current, tags, prevAuto = {}) {
  const out = {};
  for (const k of ['artist', 'title']) {
    const val = (tags?.[k] || '').trim();
    if (!val) continue;
    const cur = (current?.[k] || '').trim();
    if (cur === '' || (prevAuto?.[k] && cur === prevAuto[k])) out[k] = val;
  }
  return out;
}

/** Прочитать теги из File/Blob. */
export async function readId3(file) {
  const read = async (a, b) => new Uint8Array(await file.slice(a, b).arrayBuffer());
  let head = await read(0, 10);
  const size = id3v2Size(head);
  if (size > 10) head = await read(0, Math.min(size, MAX_TAG_BYTES));
  const tail = file.size >= 128 ? await read(file.size - 128, file.size) : new Uint8Array();
  return parseId3(head, tail);
}
