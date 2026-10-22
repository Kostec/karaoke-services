// Модель редактора нот (спека §2–§5, §14, §15): чистые операции без DOM.

import { toSyllables } from './syllables.js';
//
// State: {editable, reason, bpm, gap, headers, notes, nextId, created, duet, singers: {p1, p2}, p1Break}.
// notes — плоский список нот; порядок важен внутри партии (подпоследовательности нот одного певца):
//   {id, src, type, start, length, pitch, text, ls, brk, voice, src2, brk2}
//   id   — ключ ноты в редакторе (уникален, не меняется при правках);
//   src  — номер ноты в файле (`id` из GET /notes), у новых нот null;
//   ls   — нота начинает строку (у первой ноты песни всегда true);
//   brk  — прежний бит разрыва перед этой строкой (только у нот с ls, иначе null);
//   voice — певец строки: 1 | 2 | 'both' (одинаков у всех нот строки; у соло всегда 1);
//   src2, brk2 — у нот «оба»: номер копии в блоке P2 и разрыв перед строкой в P2.
// Партия певца v — ноты с voice v и 'both': соседи, перекрытия и строки считаются внутри партии.
// created — id нот, созданных последней операцией (addNote, splitNote, addNotesToLine).
// Все операции возвращают новое состояние и не меняют входное; ошибка — Error с русским текстом.

const TYPES = [':', '*', 'F', 'R', 'G'];
const PITCH_MIN = -40;
const PITCH_MAX = 100;
export const GAP_ERROR = 'Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0';
export const PITCH_ERROR = 'Высота ноты — от −40 до 100';
export const START_ERROR = 'Начало ноты раньше бита 0';
export const LENGTH_ERROR = 'Длина ноты — не меньше 1 бита';
export const NEWLINE_ERROR = 'В слоге не может быть перевода строки';
export const NO_NOTE_ERROR = 'Нет такой ноты';
export const LAST_NOTE_ERROR = 'В песне должна остаться хотя бы одна нота';

/** Время бита в мс: GAP_ms + beat * 60000 / (BPM * 4). */
export function beatToMs(beat, gap, bpm) {
  return (Number(gap) || 0) + (beat * 60000) / (Number(bpm) * 4);
}

/** Бит (дробный) по времени в мс — обратное к beatToMs. */
export function msToBeat(ms, gap, bpm) {
  return ((ms - (Number(gap) || 0)) * Number(bpm) * 4) / 60000;
}

/** Слог свободен: пустой или «~» (тянет гласную). */
export function isFree(text) {
  const t = String(text ?? '').trim();
  return t === '' || t === '~';
}

// ---------- голоса и партии ----------

export const VOICES = [1, 2, 'both'];
export const NOT_DUET_ERROR = 'Песня не дуэт — сначала «Сделать дуэтом»';
export const VOICE_ERROR = 'Певец строки — 1, 2 или «оба»';
export const OTHER_VOICE_ERROR = 'Строки разных певцов — склеивать нельзя';

const voiceOf = (x) => x?.voice ?? 1;

/** Нота входит в партию певца v (1 | 2): своя нота певца или «оба». */
export function inVoice(x, v) {
  const w = voiceOf(x);
  return w === 'both' || w === v;
}

/** Подписи певца строки: кнопка (short), «отдать кому» (to), «уже у кого» (at), «кто» (who). */
export const VOICE_LABELS = {
  1: { short: '1', to: 'певцу 1', at: 'певца 1', who: 'певец 1' },
  2: { short: '2', to: 'певцу 2', at: 'певца 2', who: 'певец 2' },
  both: { short: 'оба', to: 'обоим', at: 'обоих', who: 'оба' },
};

/** Все партии дуэта; обход партий в операциях — только по этому списку. */
const PARTS = [1, 2];

/** Партии песни для обхода на экране: у дуэта [1, 2], у соло [1]. */
export function parts(state) {
  return state.duet ? PARTS : [1];
}

/** Партия, в которой правится нота: у певца 2 — вторая, у певца 1 и «оба» (и без певца) — первая. */
export function partOf(x) {
  return voiceOf(x) === 2 ? 2 : 1;
}

/** Ноты партии певца v (1 | 2) в её порядке, вместе с нотами «оба». */
export function voiceNotes(state, v) {
  return state.notes.filter((x) => inVoice(x, v));
}

/** Ноты партии ноты id (Tab, правка слогов, перетаскивание); у соло — все ноты. */
export function partNotes(state, id) {
  const x = state.notes[indexOf(state, id)];
  return state.duet ? voiceNotes(state, partOf(x)) : state.notes;
}

/** Все ноты ids есть и уже у певца v (1 | 2 | 'both'); пустой выбор — false. */
export function allVoice(state, ids, v) {
  const list = [...ids];
  if (!list.length) return false;
  const byId = new Map(state.notes.map((x) => [x.id, x]));
  return list.every((id) => byId.has(id) && voiceOf(byId.get(id)) === v);
}

/** Нота j подпоследовательности партии начинает строку: первая, флаг `ls` или смена певца. */
function startsLine(sub, j) {
  return j === 0 || sub[j].ls || voiceOf(sub[j]) !== voiceOf(sub[j - 1]);
}

/** Строки одной партии (подпоследовательности нот). */
function partLines(sub) {
  const out = [];
  sub.forEach((x, j) => {
    if (startsLine(sub, j)) out.push([]);
    out[out.length - 1].push(x);
  });
  return out;
}

/** Слить две последовательности по `start`, сохраняя порядок внутри каждой (при равенстве — первая). */
function mergeByStart(a, b) {
  const out = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) out.push(b[j].start < a[i].start ? b[j++] : a[i++]);
  return out.concat(a.slice(i), b.slice(j));
}

/** Каждое начало строки в каждой партии помечено `ls` (первая нота, смена певца). */
function markLineStarts(notes) {
  const heads = new Set();
  for (const v of PARTS) {
    const sub = notes.filter((x) => inVoice(x, v));
    sub.forEach((x, j) => { if (!x.ls && startsLine(sub, j)) heads.add(x.id); });
  }
  return heads.size ? notes.map((x) => (heads.has(x.id) ? { ...x, ls: true, brk: null, brk2: null } : x)) : notes;
}

// ---------- загрузка и выгрузка ----------

const sameNote = (x, y) => x.type === y.type && x.start === y.start && x.length === y.length
  && x.pitch === y.pitch && (x.text ?? '') === (y.text ?? '');
const sameLine = (a, b) => a.notes.length === b.notes.length && a.notes.every((x, i) => sameNote(x, b.notes[i]));
const srcOf = (x) => (Number.isInteger(x.id) ? x.id : null);

/**
 * Ответ GET /api/songs/{id}/notes → состояние редактора. У дуэта строка P1 и строка P2 с одинаковыми
 * нотами (тип, начало, длина, высота, текст) склеиваются в одну строку «оба» (`src` — P1, `src2` — P2).
 */
export function fromPayload(data) {
  const all = data.lines;
  const duet = data.duet === true || all.some((l) => l.player === 2);
  // ключи нот без номера в файле (старый ответ сервера) — после самого большого номера
  let next = all.reduce((m, line) => line.notes.reduce((k, x) => (Number.isInteger(x.id) ? Math.max(k, x.id + 1) : k), m), 0);
  const mk = (x, extra) => {
    const src = srcOf(x);
    return {
      id: src ?? next++, src, type: x.type, start: x.start, length: x.length, pitch: x.pitch, text: x.text ?? '',
      ls: false, brk: null, voice: 1, src2: null, brk2: null, ...extra,
    };
  };
  const prevBrk = (block, i) => (i > 0 ? block[i - 1].break_beat ?? null : null);
  const b1 = duet ? all.filter((l) => l.player !== 2) : all;
  const b2 = duet ? all.filter((l) => l.player === 2) : [];
  const pair = new Map(); // строка P1 → её копия в P2
  const used = new Set();
  b1.forEach((l, i) => {
    const j = b2.findIndex((m, k) => !used.has(k) && sameLine(l, m));
    if (j >= 0) { used.add(j); pair.set(i, j); }
  });
  const n1 = [];
  b1.forEach((l, i) => {
    const j = pair.get(i);
    l.notes.forEach((x, k) => n1.push(mk(x, {
      ls: k === 0, brk: k === 0 ? prevBrk(b1, i) : null,
      ...(j === undefined ? {} : { voice: 'both', src2: srcOf(b2[j].notes[k]), brk2: k === 0 ? prevBrk(b2, j) : null }),
    })));
  });
  const n2 = [];
  b2.forEach((l, j) => {
    if (used.has(j)) return;
    l.notes.forEach((x, k) => n2.push(mk(x, { voice: 2, ls: k === 0, brk: k === 0 ? prevBrk(b2, j) : null })));
  });
  const s = data.singers ?? {};
  return {
    editable: data.editable !== false, reason: data.reason ?? null, bpm: data.bpm, gap: data.gap ?? null,
    headers: data.headers ?? [], notes: markLineStarts(mergeByStart(n1, n2)), nextId: next, created: [],
    duet, singers: { p1: s.p1 ?? '', p2: s.p2 ?? '' },
    // разрыв «- N» после последней строки певца 1 (перед P2); null — разрыва нет
    p1Break: duet && b1.length ? b1[b1.length - 1].break_beat ?? null : null,
  };
}

/**
 * Строки песни: ноты, сгруппированные по началам строк (`ls`, смена певца) внутри партии.
 * У дуэта — строки обеих партий (строка «оба» — один раз) в порядке списка нот.
 */
export function lines(state) {
  if (!state.duet) return partLines(state.notes);
  const pos = new Map(state.notes.map((x, i) => [x.id, i]));
  const own2 = partLines(voiceNotes(state, 2)).filter((l) => voiceOf(l[0]) !== 'both');
  return [...partLines(voiceNotes(state, 1)), ...own2].sort((a, b) => pos.get(a[0].id) - pos.get(b[0].id));
}

/** Строки партии певца v (1 | 2) по порядку, со строками «оба» — как в блоке P1/P2 файла. */
export function voiceLines(state, v) {
  return partLines(voiceNotes(state, v));
}

/** Бит разрыва между строками (§4): прежний, если он ещё между нотами, иначе конец предыдущей ноты. */
function breakBeat(prev, next, brk = next.brk) {
  const end = prev.start + prev.length;
  return brk != null && brk >= end && brk <= next.start ? brk : end;
}

const noteOut = (x, id) => ({ id, type: x.type, start: x.start, length: x.length, pitch: x.pitch, text: x.text });

/**
 * Состояние → тело PUT /api/songs/{id}/notes. У дуэта: строки певца 1 (и «оба»), затем певца 2
 * (и копии «оба» с `id: src2`), `player` у каждой строки, разрывы внутри партии, `singers`.
 */
export function toPayload(state) {
  if (!state.duet) {
    const ls = lines(state);
    return {
      gap: state.gap,
      lines: ls.map((line, li) => ({
        break_beat: li < ls.length - 1 ? breakBeat(line[line.length - 1], ls[li + 1][0]) : null,
        notes: line.map((x) => noteOut(x, x.src)),
      })),
    };
  }
  const block = (v) => {
    const ls = voiceLines(state, v);
    const copy = (x) => v === 2 && voiceOf(x) === 'both';
    return ls.map((line, li) => {
      const nx = ls[li + 1];
      const last = line[line.length - 1];
      let tail = null; // у последней строки певца 1 — прежний разрыв перед P2, не раньше конца её ноты
      if (v === 1 && state.p1Break != null) tail = Math.max(state.p1Break, last.start + last.length);
      return {
        break_beat: nx ? breakBeat(last, nx[0], copy(nx[0]) ? nx[0].brk2 : nx[0].brk) : tail,
        player: v,
        notes: line.map((x) => noteOut(x, copy(x) ? x.src2 ?? null : x.src)),
      };
    });
  };
  return { gap: state.gap, singers: { p1: state.singers?.p1 ?? '', p2: state.singers?.p2 ?? '' }, lines: [...block(1), ...block(2)] };
}

/** Есть ли несохранённые правки относительно исходного состояния (ноты, певцы строк, имена). */
export function isDirty(state, original) {
  return JSON.stringify(toPayload(state)) !== JSON.stringify(toPayload(original));
}

// ---------- внутренние помощники ----------

function msPerBeat(state) {
  if (!(Number(state.bpm) > 0)) throw new Error('В песне нет #BPM — редактор только для просмотра');
  return 60000 / (Number(state.bpm) * 4);
}

function indexOf(state, id) {
  const i = state.notes.findIndex((x) => x.id === id);
  if (i < 0) throw new Error(NO_NOTE_ERROR);
  return i;
}

/** Нота id в своей партии: {x, sub — ноты партии, i — номер в ней}. */
function inPart(state, id) {
  const x = state.notes[indexOf(state, id)];
  const sub = voiceNotes(state, partOf(x));
  return { x, sub, i: sub.indexOf(x) };
}

/** Все ли id есть в песне — иначе ошибка «Нет такой ноты». */
function checkIds(state, ids) {
  const known = new Set(state.notes.map((x) => x.id));
  for (const id of ids) if (!known.has(id)) throw new Error(NO_NOTE_ERROR);
}

const shiftBeat = (b, d) => (b != null ? b + d : null);

/**
 * Новое состояние из списка нот: ноты `moved` (их id) переставляются по `start` среди остальных нот
 * своей партии (обгон соседей, §3), остальные сохраняют порядок; ноты левее бита 0 сдвигают всю песню
 * (обе партии) вправо, а `gap` уменьшается на столько же мс (§5).
 */
function settle(state, notes, moved = [], extra = {}) {
  const movedSet = new Set(moved);
  let list = placeByTime(notes, notes.filter((x) => movedSet.has(x.id)).map((x) => [x]), (sub) => sub.map((x) => [x]));
  let gap = state.gap;
  const min = Math.min(...list.map((x) => x.start));
  if (min < 0) {
    const g = (Number(gap) || 0) + min * msPerBeat(state);
    if (g < -1e-6) throw new Error(GAP_ERROR);
    gap = Math.max(0, g);
    list = list.map((x) => ({ ...x, start: x.start - min, brk: shiftBeat(x.brk, -min), brk2: shiftBeat(x.brk2, -min) }));
  }
  const p1Break = min < 0 ? shiftBeat(state.p1Break ?? null, -min) : state.p1Break ?? null;
  return { ...state, gap, p1Break, notes: markLineStarts(list.slice()), created: [], ...extra };
}

/**
 * Строки `moved` (массивы id, целиком сменившие певца) встают по времени начала среди строк своей
 * новой партии, не разрезая чужие строки (при равном начале — после прежних); дальше — как settle.
 */
function settleLines(state, notes, moved, extra = {}) {
  const byId = new Map(notes.map((x) => [x.id, x]));
  return settle(state, placeByTime(notes, moved.map((ids) => ids.map((id) => byId.get(id))), partLines), [], extra);
}

/**
 * Общая вставка по времени внутри партии: в каждой партии группы `groups` (массивы нот: одна нота
 * или строка; партия — по первой ноте) встают по началу среди прочих групп партии — `split(ноты)`
 * режет остальные ноты партии на группы, чтобы не разрезать их; при равном начале — после прежних.
 * Ноты других певцов сохраняют порядок; партии сливаются обратно по времени.
 */
function placeByTime(notes, groups, split) {
  let list = notes;
  for (const p of PARTS) {
    const mv = groups.filter((g) => partOf(g[0]) === p).sort((a, b) => a[0].start - b[0].start);
    if (!mv.length) continue;
    const mvSet = new Set(mv.flat().map((x) => x.id));
    const rest = split(list.filter((x) => inVoice(x, p) && !mvSet.has(x.id)));
    for (const g of mv) {
      let at = rest.length;
      while (at > 0 && rest[at - 1][0].start > g[0].start) at -= 1;
      rest.splice(at, 0, g);
    }
    list = mergeByStart(rest.flat(), list.filter((x) => !inVoice(x, p)));
  }
  return list;
}

function checkPitch(pitch) {
  if (!Number.isInteger(pitch) || pitch < PITCH_MIN || pitch > PITCH_MAX) throw new Error(PITCH_ERROR);
}

// ---------- операции ----------

/** Сдвинуть ноты `ids` на dBeat битов и dPitch полутонов (стрелки, мышь, «выделить всё»). */
export function move(state, ids, dBeat, dPitch = 0) {
  checkIds(state, ids);
  const set = new Set(ids);
  const db = Math.round(dBeat);
  const dp = Math.round(dPitch);
  const notes = state.notes.map((x) => {
    if (!set.has(x.id)) return x;
    checkPitch(x.pitch + dp);
    return { ...x, start: x.start + db, pitch: x.pitch + dp, brk: shiftBeat(x.brk, db), brk2: shiftBeat(x.brk2, db) };
  });
  return settle(state, notes, db ? [...set] : []);
}

/** Растянуть/сжать ноту за край: edge 'left' | 'right'; длина не меньше 1 бита. */
export function resize(state, id, edge, dBeat) {
  if (edge !== 'left' && edge !== 'right') throw new Error('Неизвестный край ноты');
  const i = indexOf(state, id);
  const x = state.notes[i];
  const d = Math.round(dBeat);
  let patch;
  if (edge === 'right') {
    patch = { length: Math.max(1, x.length + d) };
  } else {
    const end = x.start + x.length;
    const start = Math.min(end - 1, x.start + d);
    patch = { start, length: end - start };
  }
  const notes = state.notes.slice();
  notes[i] = { ...x, ...patch };
  return settle(state, notes, edge === 'left' ? [id] : []);
}

function checkVoice(state, voice) {
  if (!VOICES.includes(voice)) throw new Error(VOICE_ERROR);
  if (voice !== 1 && !state.duet) throw new Error(NOT_DUET_ERROR);
}

/** Добавить ноту (двойной клик, `N`): по умолчанию 4 бита, без текста, обычная, певца `voice` (1). */
export function addNote(state, { start, pitch, length = 4, text = '', type = ':', voice = 1 }) {
  checkPitch(pitch);
  checkVoice(state, voice);
  const id = state.nextId;
  const note = {
    id, src: null, type, start: Math.round(start), length: Math.max(1, Math.round(length)), pitch, text,
    ls: false, brk: null, voice, src2: null, brk2: null,
  };
  return settle({ ...state, nextId: id + 1 }, [...state.notes, note], [id], { created: [id] });
}

/**
 * Удалить ноты; начало строки переходит к следующей уцелевшей ноте той же строки (в партии ноты).
 * Последнюю ноту песни не удалить; партию певца 2 можно опустошить целиком.
 */
export function deleteNotes(state, ids) {
  checkIds(state, ids);
  const set = new Set(ids);
  if (state.notes.every((x) => set.has(x.id))) throw new Error(LAST_NOTE_ERROR);
  const heads = new Map(); // id уцелевшей ноты → унаследованные разрывы
  for (const p of PARTS) {
    let carry = null; // начало строки удалённой ноты: {voice, brk, brk2}
    for (const x of voiceNotes(state, p)) {
      if (set.has(x.id)) {
        if (x.ls && !carry && partOf(x) === p) carry = { voice: voiceOf(x), brk: x.brk, brk2: x.brk2 ?? null };
        continue;
      }
      if (carry && !x.ls && voiceOf(x) === carry.voice) heads.set(x.id, { ls: true, brk: carry.brk, brk2: carry.brk2 });
      carry = null;
    }
  }
  const out = state.notes.filter((x) => !set.has(x.id)).map((x) => (heads.has(x.id) ? { ...x, ...heads.get(x.id) } : x));
  return settle(state, out);
}

/** Текст слога (поле ввода, `Tab` по нотам). */
export function setText(state, id, text) {
  const t = String(text ?? '');
  if (/[\r\n]/.test(t)) throw new Error(NEWLINE_ERROR);
  const i = indexOf(state, id);
  const notes = state.notes.slice();
  notes[i] = { ...notes[i], text: t };
  return { ...state, notes, created: [] };
}

/**
 * Текст строки для панели: слоги подряд, «~» убраны (и свободные ноты «~ », и склейки «~w »);
 * пробелы слогов — в начале или в конце, как у UltraSinger, — остаются границами слов.
 */
export function lineText(line) {
  return line.map((x) => String(x.text).replace(/~/g, '')).join('').replace(/\s+/g, ' ').trim();
}

/**
 * Строка li (номер в lines(state)) целиком из текста панели: слоги (toSyllables) по нотам строки
 * по порядку; лишние ноты получают «~», лишние слоги склеиваются в последней ноте.
 */
export function setLineText(state, li, text) {
  const line = lines(state)[li];
  if (!line) throw new Error('Нет такой строки');
  const syl = toSyllables(String(text ?? '').replace(/[\r\n]+/g, ' ').replace(/~/g, ''));
  const byId = new Map(line.map((x, i) => {
    let t = '~';
    if (i < syl.length) t = i === line.length - 1 ? syl.slice(i).join('') : syl[i];
    return [x.id, t];
  }));
  const notes = state.notes.map((x) => (byId.has(x.id) ? { ...x, text: byId.get(x.id) } : x));
  return { ...state, notes, created: [] };
}

/** «+ K нот»: k нот по 3 бита подряд за последней нотой строки li, с её высотой и певцом (остаются в строке). */
export function addNotesToLine(state, li, k) {
  const line = lines(state)[li];
  if (!line) throw new Error('Нет такой строки');
  const last = line[line.length - 1];
  const added = [];
  let start = last.start + last.length;
  let id = state.nextId;
  for (let j = 0; j < k; j += 1) {
    added.push({
      id, src: null, type: ':', start, length: 3, pitch: last.pitch, text: '', ls: false, brk: null,
      voice: voiceOf(last), src2: null, brk2: null,
    });
    start += 3;
    id += 1;
  }
  const at = indexOf(state, last.id) + 1;
  const notes = [...state.notes.slice(0, at), ...added, ...state.notes.slice(at)];
  return settle({ ...state, nextId: id }, notes, [], { created: added.map((x) => x.id) });
}

/**
 * Ноты, перекрывающие предыдущую в своей партии (и сама предыдущая) — для красной подсветки.
 * Ноты «оба» проверяются в обеих партиях; ноты разных певцов друг другу не мешают.
 */
export function overlaps(state) {
  const out = new Set();
  for (const v of PARTS) {
    const sub = voiceNotes(state, v);
    sub.forEach((x, i) => {
      const prev = sub[i - 1];
      if (prev && x.start < prev.start + prev.length) {
        out.add(prev.id);
        out.add(x.id);
      }
    });
  }
  return out;
}

export const SHIFT_SCOPES = ['word', 'line', 'song'];
const LEFT_NONE = { word: 'Левее в этом слове нот нет', line: 'Левее в этой строке нот нет', song: 'Левее нот нет' };
const RIGHT_NONE = { word: 'Правее в этом слове нот нет', line: 'Правее в этой строке нот нет', song: 'Правее нот нет' };

/**
 * Нота j начинает слово: начало строки; иначе свободная нота («~» с любыми пробелами) — продолжение
 * предыдущего слова; нота с текстом — если её слог начинается с пробела или пробелом кончается
 * предыдущий слог (через «~»-ноты — до последнего слога с текстом).
 */
function wordStart(notes, j) {
  if (startsLine(notes, j)) return true;
  if (isFree(notes[j].text)) return false;
  if (/^\s/.test(String(notes[j].text))) return true;
  for (let k = j - 1; k >= 0; k -= 1) {
    const t = String(notes[k].text);
    if (/\s$/.test(t)) return true;
    if (!isFree(t) || startsLine(notes, k)) return false;
  }
  return false;
}

/** Склеить слоги в один (перелив при сдвиге): «~» отбрасываются, пробелы-границы слов остаются. */
function glue(texts) {
  if (texts.every(isFree)) return texts[0];
  return texts.map((t) => (isFree(t) ? String(t).replace('~', '') : String(t))).join('');
}

/**
 * Область сдвига текста для ноты id: номера первой и последней ноты её слова/строки/партии —
 * в списке нот партии ноты (voiceNotes; у соло — это state.notes).
 */
export function shiftRange(state, id, scope = 'line') {
  if (!SHIFT_SCOPES.includes(scope)) throw new Error('Неизвестная область сдвига текста');
  const { sub: ns, i } = inPart(state, id);
  if (scope === 'song') return { first: 0, last: ns.length - 1 };
  const isStart = scope === 'word' ? (j) => wordStart(ns, j) : (j) => startsLine(ns, j);
  let s = i;
  let e = i;
  while (!isStart(s)) s -= 1;
  while (e + 1 < ns.length && !isStart(e + 1)) e += 1;
  return { first: s, last: e };
}

/**
 * На сколько нот на деле сдвинется текст при запросе k (знак — направление): не дальше границ
 * области; у первой ноты области влево и у последней вправо — ошибка «Левее/Правее … нот нет».
 */
export function shiftAmount(state, id, k, scope = 'line') {
  const { first, last } = shiftRange(state, id, scope);
  const { i } = inPart(state, id);
  if (k > 0) {
    if (i === last) throw new Error(RIGHT_NONE[scope]);
    return Math.min(k, last - i);
  }
  if (k < 0) {
    if (i === first) throw new Error(LEFT_NONE[scope]);
    return -Math.min(-k, i - first);
  }
  return 0;
}

/**
 * Сдвиг текста по нотам (G03): слог ноты id и все следующие в пределах области `scope`
 * ('word' — слово, 'line' — строка, 'song' — до конца партии ноты) уезжают на |k| нот (k > 0 — вправо).
 * Вправо: освободившиеся ноты получают «~», слоги, которым не хватило нот, приклеиваются к последней
 * ноте области. Влево: слог приклеивается к ноте на k левее (вместе со слогами между ними; «~»
 * заменяется), хвост области получает «~»; дальше начала области не уходит. Ноты и строки не двигаются.
 */
export function shiftTextBy(state, id, k, scope = 'line') {
  const { last: e } = shiftRange(state, id, scope);
  const { sub: ns, i } = inPart(state, id);
  const t = ns.map((x) => x.text);
  const next = t.slice();
  const amount = shiftAmount(state, id, k, scope);
  if (amount > 0) {
    const d = amount;
    for (let j = i; j < i + d; j += 1) next[j] = '~';
    for (let j = i + d; j < e; j += 1) next[j] = t[j - d];
    next[e] = glue(t.slice(e - d, e + 1));
  } else if (amount < 0) {
    const d = -amount;
    next[i - d] = glue(t.slice(i - d, i + 1));
    for (let j = i - d + 1; j <= e; j += 1) next[j] = j + d <= e ? t[j + d] : '~';
  }
  if (next.every((v, j) => v === t[j])) return state; // текст не изменился — шага отмены нет
  const byId = new Map(ns.map((x, j) => [x.id, next[j]]));
  return { ...state, notes: state.notes.map((x) => (byId.has(x.id) && byId.get(x.id) !== x.text ? { ...x, text: byId.get(x.id) } : x)), created: [] };
}

/** «⇠ текст / текст ⇢» в пределах строки: shiftTextBy(state, id, dir, 'line'). */
export function shiftText(state, id, dir) {
  return shiftTextBy(state, id, dir, 'line');
}

/** Разрезать ноту пополам (`S`): вторая половина — новая нота с «~» (того же певца). */
export function splitNote(state, id) {
  const i = indexOf(state, id);
  const x = state.notes[i];
  if (x.length < 2) throw new Error('Нота в 1 бит — резать нечего');
  const a = Math.ceil(x.length / 2);
  const nid = state.nextId;
  const tail = {
    ...x, id: nid, src: null, src2: null, start: x.start + a, length: x.length - a, text: '~', ls: false, brk: null, brk2: null,
  };
  const notes = [...state.notes.slice(0, i), { ...x, length: a }, tail, ...state.notes.slice(i + 1)];
  return { ...state, notes, nextId: nid + 1, created: [nid] };
}

/** Слить ноту со следующей в её партии (`Shift+J`): длина — до конца следующей, текст склеен; не через строку. */
export function joinNext(state, id) {
  const { x, sub, i } = inPart(state, id);
  const nx = sub[i + 1];
  if (!nx) throw new Error('Это последняя нота — сливать не с чем');
  if (startsLine(sub, i + 1)) throw new Error('Следующая нота в другой строке — сливать нельзя');
  // «~» (с любыми пробелами) при слиянии отбрасывается с любой стороны, пробелы-границы слов остаются
  const drop = (t) => (String(t).trim() === '~' ? String(t).replace('~', '') : String(t));
  const both = drop(x.text) + drop(nx.text);
  const text = both.trim() ? both : x.text;
  const notes = state.notes
    .filter((y) => y.id !== nx.id)
    .map((y) => (y.id === x.id ? { ...x, length: nx.start + nx.length - x.start, text } : y));
  return { ...state, notes, created: [] };
}

/** «↵ Строка»: начать новую строку с ноты id (в её партии). */
export function startLine(state, id) {
  const { x, sub, i } = inPart(state, id);
  if (startsLine(sub, i)) throw new Error('Эта нота уже начинает строку');
  return { ...state, notes: state.notes.map((y) => (y.id === x.id ? { ...y, ls: true, brk: null, brk2: null } : y)), created: [] };
}

/**
 * Склеить строку ноты id с предыдущей строкой партии voice (значок ↵ на полосе этой партии; по умолчанию —
 * партия ноты). Строка «оба» есть в обеих партиях: склеивается, только если предыдущая строка — та же
 * строка «оба» и у второго певца, иначе отказ.
 */
export function mergeLineAt(state, id, voice = null) {
  const { x } = inPart(state, id);
  const own = voice ?? partOf(x);
  if (!inVoice(x, own)) throw new Error(NO_NOTE_ERROR);
  let head = null;
  for (const p of voiceOf(x) === 'both' ? [own, 3 - own] : [own]) {
    const pl = voiceLines(state, p);
    const li = pl.findIndex((line) => line.some((y) => y.id === id));
    if (p === own && li <= 0) throw new Error('Это первая строка — склеивать не с чем');
    const prev = li > 0 ? voiceOf(pl[li - 1][0]) : null;
    if (p === own && prev !== voiceOf(pl[li][0])) throw new Error(OTHER_VOICE_ERROR);
    if (p !== own && prev !== 'both') throw new Error(`Строки «оба» не соседние: у певца ${p} между ними своя строка — склеивать нельзя`);
    head ??= pl[li][0].id;
  }
  return { ...state, notes: state.notes.map((y) => (y.id === head ? { ...y, ls: false, brk: null, brk2: null } : y)), created: [] };
}

/**
 * Перетащить разрыв перед строкой, которая начинается нотой id (в партии voice; по умолчанию — партии ноты),
 * в бит beat (§14). Новая первая нота строки — первая нота партии с `start >= beat` среди нот этой строки
 * и предыдущей; граница не уходит за соседние разрывы (в каждой строке остаётся ≥1 нота). Бит разрыва —
 * beat, если он в паузе перед новой первой нотой, иначе конец предыдущей ноты. Строки другой партии не
 * меняются; нота «оба» переходит, только если граница проходит у обоих певцов одинаково.
 */
export function moveBreak(state, id, beat, voice = null) {
  const { x } = inPart(state, id);
  const own = voice ?? partOf(x);
  if (!inVoice(x, own)) throw new Error(NO_NOTE_ERROR);
  const pl = voiceLines(state, own);
  const li = pl.findIndex((line) => line[0].id === id);
  if (li < 0) throw new Error('Эта нота не начинает строку — разрыва перед ней нет');
  if (li === 0) throw new Error('Это первая строка — разрыва перед ней нет');
  const all = [...pl[li - 1], ...pl[li]];
  const b = Math.round(Number(beat));
  let h = all.findIndex((y, k) => k > 0 && y.start >= b);
  if (h < 0) h = all.length - 1;
  h = Math.min(Math.max(h, 1), all.length - 1);
  const head = all[h];
  const prevEnd = all[h - 1].start + all[h - 1].length;
  const brk = b >= prevEnd && b <= head.start ? b : null;
  const field = own === 2 && voiceOf(head) === 'both' ? 'brk2' : 'brk';
  if (head.id === id && (head[field] ?? null) === brk) return state;
  const notes = state.notes.map((y) => {
    if (y.id === head.id) {
      if (head.id === id) return { ...y, [field]: brk };
      return { ...y, ls: true, brk, brk2: voiceOf(y) === 'both' ? brk : null };
    }
    if (y.id === id) return { ...y, ls: false, brk: null, brk2: null };
    return y;
  });
  const out = { ...state, notes, created: [] };
  checkBreakMove(state, out, own, [pl[li - 1], pl[li]], [all.slice(0, h), all.slice(h)]);
  return out;
}

/**
 * Строки после moveBreak: в партии own пара строк `before` стала парой `after`, прочие строки те же;
 * в другой партии — без изменений или то же самое (граница по нотам «оба» у обоих певцов одинакова).
 */
function checkBreakMove(state, out, own, before, after) {
  const ids = (ls) => JSON.stringify(ls.map((l) => l.map((y) => y.id)));
  const want = (ls) => {
    const s = ids(ls);
    const pair = ids(before).slice(1, -1);
    return s.includes(pair) ? s.replace(pair, ids(after).slice(1, -1)) : null;
  };
  for (const p of [own, ...parts(state).filter((q) => q !== own)]) {
    const was = voiceLines(state, p);
    const now = ids(voiceLines(out, p));
    if (p === own) {
      if (now !== want(was)) throw new Error(OTHER_VOICE_ERROR);
    } else if (now !== ids(was) && now !== want(was)) {
      throw new Error('Граница по нотам «оба» у певцов проходит по-разному — так разрыв не двигается');
    }
  }
}

// ---------- «Строки как в тексте» (POST /api/songs/{id}/notes/lines) ----------

export const LINES_DUET_ERROR = 'У дуэта строки по тексту не расставляются — только у соло';
export const LINE_STARTS_ERROR = 'Неверные номера нот начал строк';

/** Тело запроса «Строки как в тексте»: тексты нот соло по порядку и индексы нот — начал строк. */
export function lineStartsRequest(state) {
  if (state.duet) throw new Error(LINES_DUET_ERROR);
  return {
    texts: state.notes.map((x) => x.text),
    starts: state.notes.flatMap((x, i) => (i === 0 || x.ls ? [i] : [])),
  };
}

/**
 * Строки соло начинаются с нот с индексами `indices` (в `state.notes`, по возрастанию); первая нота — всегда
 * начало строки. У ноты, которая уже начинала строку, прежний разрыв сохраняется; у новых начал разрыв
 * сбрасывается (станет концом предыдущей ноты). Без изменений — то же состояние.
 */
export function setLineStarts(state, indices) {
  if (state.duet) throw new Error(LINES_DUET_ERROR);
  const n = state.notes.length;
  if (!Array.isArray(indices)) throw new Error(LINE_STARTS_ERROR);
  indices.forEach((k, j) => {
    if (!Number.isInteger(k) || k < 0 || k >= n || (j > 0 && k <= indices[j - 1])) throw new Error(LINE_STARTS_ERROR);
  });
  const heads = new Set(indices);
  let changed = false;
  const notes = state.notes.map((x, i) => {
    const want = i === 0 || heads.has(i);
    const was = i === 0 || x.ls;
    if (want === was && x.ls === want) return x;
    changed = true;
    return { ...x, ls: want, brk: want && was ? x.brk : null, brk2: null };
  });
  return changed ? { ...state, notes, created: [] } : state;
}

/** Золотые (`G`, ★): если не все выбранные «:»/«*» золотые — все «*», иначе все «:». */
export function toggleGold(state, ids) {
  checkIds(state, ids);
  const set = new Set(ids);
  // freestyle/rap (F, R, G) не трогаются — их тип не теряется
  const hit = (x) => set.has(x.id) && (x.type === ':' || x.type === '*');
  const sel = state.notes.filter(hit);
  const type = sel.every((x) => x.type === '*') ? ':' : '*';
  return { ...state, notes: state.notes.map((x) => (hit(x) ? { ...x, type } : x)), created: [] };
}

/** Отстукивание: ноте id новое начало и длина (≥ 1 бита); текст и высота сохраняются. */
export function retime(state, id, start, length) {
  const i = indexOf(state, id);
  const x = state.notes[i];
  const s = Math.round(start);
  const notes = state.notes.slice();
  notes[i] = { ...x, start: s, length: Math.max(1, Math.round(length)), brk: shiftBeat(x.brk, s - x.start), brk2: shiftBeat(x.brk2, s - x.start) };
  return settle(state, notes, [id]);
}

// ---------- дуэт ----------

/**
 * Отдать строки выбранных нот певцу voice (1 | 2 | 'both'): переводятся строки целиком и встают
 * по времени в партию нового певца. «оба» → один певец: остаётся копия этого певца.
 */
export function setVoice(state, ids, voice) {
  if (!state.duet) throw new Error(NOT_DUET_ERROR);
  checkVoice(state, voice);
  checkIds(state, ids);
  const set = new Set(ids);
  const hit = new Set();
  const heads = new Set();
  const moved = [];
  for (const line of lines(state)) {
    if (!line.some((x) => set.has(x.id)) || voiceOf(line[0]) === voice) continue;
    line.forEach((x) => hit.add(x.id));
    heads.add(line[0].id);
    moved.push(line.map((x) => x.id));
  }
  if (!hit.size) return state; // певец уже тот — шага отмены нет
  const notes = state.notes.map((x) => {
    if (!hit.has(x.id)) return x;
    const from = voiceOf(x);
    let { src, brk } = x;
    let src2 = null;
    let brk2 = null;
    if (from === 'both' && voice === 2) { src = x.src2 ?? null; brk = x.brk2 ?? null; }
    if (from === 2 && voice === 'both') { src2 = src; brk2 = brk; src = null; brk = null; }
    if (from === 1 && voice === 'both') brk2 = null;
    if ((from === 1 && voice === 2) || (from === 2 && voice === 1)) brk = null;
    return { ...x, voice, src, src2, brk, brk2, ...(heads.has(x.id) ? { ls: true } : {}) };
  });
  return settleLines(state, notes, moved);
}

/** «Сделать дуэтом»: все строки — певца 1, появляются певцы и имена. */
export function makeDuet(state) {
  if (state.duet) throw new Error('Песня уже дуэт');
  return {
    ...state, duet: true, singers: { p1: state.singers?.p1 ?? '', p2: state.singers?.p2 ?? '' },
    notes: state.notes.map((x) => (x.voice === 1 ? x : { ...x, voice: 1, src2: null, brk2: null })),
    created: [],
  };
}

/** «Сделать соло»: всё — певцу 1, строки «оба» — одна копия (P1), строки певца 2 встают по времени. */
export function makeSolo(state) {
  if (!state.duet) throw new Error('Песня и так не дуэт');
  const ls = lines(state);
  const heads = new Set(ls.map((line) => line[0].id));
  const moved = ls.filter((line) => voiceOf(line[0]) === 2).map((line) => line.map((x) => x.id));
  const notes = state.notes.map((x) => ({
    ...x, voice: 1, src2: null, brk2: null, ...(heads.has(x.id) ? { ls: true } : {}),
  }));
  return settleLines(state, notes, moved, { duet: false });
}

/** Имена певцов дуэта (пустое — заголовок имени удаляется при сохранении). */
export function setSingers(state, p1, p2) {
  if (!state.duet) throw new Error(NOT_DUET_ERROR);
  const name = (v) => {
    const t = String(v ?? '');
    if (/[\r\n]/.test(t)) throw new Error('В имени певца не может быть перевода строки');
    return t.trim();
  };
  return { ...state, singers: { p1: name(p1), p2: name(p2) }, created: [] };
}

/**
 * Проверка перед сохранением — то же, что PUT на сервере (§14), по партиям.
 * null — всё в порядке, иначе {message, id} первой ноты с ошибкой (id null — ошибка не ноты).
 * У дуэта место называет певца: «Певец 2, строка 3: ноты перекрываются».
 */
export function validate(state) {
  if (!state.notes.length) return { message: LAST_NOTE_ERROR, id: null };
  const blocks = state.duet ? PARTS.map((v) => ({ v, ls: voiceLines(state, v) })) : [{ v: null, ls: lines(state) }];
  // место — как _where в web/app/notes.py: соло «Что: строка K, слог «x»», дуэт «Певец N, строка K: что, слог «x»»
  const place = (v, li, what, x) => {
    const syl = x ? `, слог «${String(x.text).trim()}»` : '';
    return v ? `Певец ${v}, строка ${li + 1}: ${what[0].toLowerCase()}${what.slice(1)}${syl}` : `${what}: строка ${li + 1}${syl}`;
  };
  for (const { v, ls } of blocks) {
    for (let li = 0; li < ls.length; li += 1) {
      for (const x of ls[li]) {
        // тексты — дословно как 400 сервера (web/app/notes.py)
        const fail = (what, withSyl = true) => ({ message: place(v, li, what, withSyl ? x : null), id: x.id });
        if (!TYPES.includes(x.type)) return fail(`Неизвестный тип ноты «${x.type}»`);
        if (!Number.isInteger(x.start) || x.start < 0) return fail(START_ERROR);
        if (!Number.isInteger(x.length) || x.length < 1) return fail(LENGTH_ERROR);
        if (!Number.isInteger(x.pitch) || x.pitch < PITCH_MIN || x.pitch > PITCH_MAX) return fail(PITCH_ERROR);
        if (/[\r\n]/.test(String(x.text))) return fail(NEWLINE_ERROR, false);
      }
    }
  }
  for (const { v, ls } of blocks) {
    const flat = ls.flat();
    for (let li = 0, k = 0; li < ls.length; li += 1) {
      for (const x of ls[li]) {
        const prev = flat[k - 1];
        k += 1;
        if (prev && x.start < prev.start + prev.length) {
          return { message: place(v, li, 'Ноты перекрываются', x), id: x.id };
        }
      }
    }
  }
  if (state.gap != null && Number(state.gap) < 0) return { message: GAP_ERROR, id: null };
  return null;
}

/** История отмены: снимки состояний (до 200 шагов). push(до правки), undo(текущее), redo(текущее). */
export function history(limit = 200) {
  const past = [];
  let future = [];
  return {
    push(state) {
      past.push(state);
      if (past.length > limit) past.shift();
      future = [];
    },
    undo(current) {
      if (!past.length) return null;
      future.push(current);
      return past.pop();
    },
    redo(current) {
      if (!future.length) return null;
      past.push(current);
      return future.pop();
    },
    canUndo: () => past.length > 0,
    canRedo: () => future.length > 0,
  };
}
