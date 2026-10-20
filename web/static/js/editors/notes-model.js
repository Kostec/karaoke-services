// Модель редактора нот (спека §2–§5, §14, §15): чистые операции без DOM.

import { toSyllables } from './syllables.js';
//
// State: {editable, reason, bpm, gap, headers, notes, nextId, created}.
// notes — плоский список нот в порядке песни:
//   {id, src, type, start, length, pitch, text, ls, brk}
//   id   — ключ ноты в редакторе (уникален, не меняется при правках);
//   src  — номер ноты в файле (`id` из GET /notes), у новых нот null;
//   ls   — нота начинает строку (у первой ноты песни всегда true);
//   brk  — прежний бит разрыва перед этой строкой (только у нот с ls, иначе null).
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

/** Ответ GET /api/songs/{id}/notes → состояние редактора. */
export function fromPayload(data) {
  const notes = [];
  // ключи нот без номера в файле (старый ответ сервера) — после самого большого номера
  let next = data.lines.reduce((m, line) => line.notes.reduce((k, x) => (Number.isInteger(x.id) ? Math.max(k, x.id + 1) : k), m), 0);
  data.lines.forEach((line, li) => {
    line.notes.forEach((x, ni) => {
      const src = Number.isInteger(x.id) ? x.id : null;
      const id = src ?? next++;
      notes.push({
        id, src, type: x.type, start: x.start, length: x.length, pitch: x.pitch, text: x.text ?? '',
        ls: ni === 0, brk: ni === 0 && li > 0 ? data.lines[li - 1].break_beat ?? null : null,
      });
    });
  });
  return {
    editable: data.editable !== false, reason: data.reason ?? null, bpm: data.bpm, gap: data.gap ?? null,
    headers: data.headers ?? [], notes: withFirstLine(notes), nextId: next, created: [],
  };
}

/** Строки песни: ноты, сгруппированные по началам строк (`ls`). */
export function lines(state) {
  const out = [];
  for (const x of state.notes) {
    if (x.ls || !out.length) out.push([]);
    out[out.length - 1].push(x);
  }
  return out;
}

/** Бит разрыва между строками (§4): прежний, если он ещё между нотами, иначе конец предыдущей ноты. */
function breakBeat(prev, next) {
  const end = prev.start + prev.length;
  return next.brk != null && next.brk >= end && next.brk <= next.start ? next.brk : end;
}

/** Состояние → тело PUT /api/songs/{id}/notes. */
export function toPayload(state) {
  const ls = lines(state);
  return {
    gap: state.gap,
    lines: ls.map((line, li) => ({
      break_beat: li < ls.length - 1 ? breakBeat(line[line.length - 1], ls[li + 1][0]) : null,
      notes: line.map((x) => ({ id: x.src, type: x.type, start: x.start, length: x.length, pitch: x.pitch, text: x.text })),
    })),
  };
}

/** Есть ли несохранённые правки относительно исходного состояния. */
export function isDirty(state, original) {
  return JSON.stringify(toPayload(state)) !== JSON.stringify(toPayload(original));
}

// ---------- внутренние помощники ----------

/** Первая нота песни всегда начинает строку. */
function withFirstLine(notes) {
  if (notes.length && !notes[0].ls) notes[0] = { ...notes[0], ls: true, brk: null };
  return notes;
}

function msPerBeat(state) {
  if (!(Number(state.bpm) > 0)) throw new Error('В песне нет #BPM — редактор только для просмотра');
  return 60000 / (Number(state.bpm) * 4);
}

function indexOf(state, id) {
  const i = state.notes.findIndex((x) => x.id === id);
  if (i < 0) throw new Error(NO_NOTE_ERROR);
  return i;
}

function lineIndexOf(state, id) {
  const li = lines(state).findIndex((line) => line.some((x) => x.id === id));
  if (li < 0) throw new Error(NO_NOTE_ERROR);
  return li;
}

/** Все ли id есть в песне — иначе ошибка «Нет такой ноты». */
function checkIds(state, ids) {
  const known = new Set(state.notes.map((x) => x.id));
  for (const id of ids) if (!known.has(id)) throw new Error(NO_NOTE_ERROR);
}

/**
 * Новое состояние из списка нот: ноты `moved` (их id) переставляются по `start` среди остальных
 * (обгон соседей, §3), остальные сохраняют порядок; ноты левее бита 0 сдвигают всю песню
 * вправо, а `gap` уменьшается на столько же мс (§5).
 */
function settle(state, notes, moved = [], extra = {}) {
  const movedSet = new Set(moved);
  let list = notes;
  if (movedSet.size) {
    const rest = notes.filter((x) => !movedSet.has(x.id));
    const mv = notes.filter((x) => movedSet.has(x.id)).sort((a, b) => a.start - b.start);
    for (const x of mv) {
      let at = rest.length;
      while (at > 0 && rest[at - 1].start > x.start) at -= 1;
      rest.splice(at, 0, x);
    }
    list = rest;
  }
  let gap = state.gap;
  const min = Math.min(...list.map((x) => x.start));
  if (min < 0) {
    const g = (Number(gap) || 0) + min * msPerBeat(state);
    if (g < -1e-6) throw new Error(GAP_ERROR);
    gap = Math.max(0, g);
    list = list.map((x) => ({ ...x, start: x.start - min, brk: x.brk != null ? x.brk - min : null }));
  }
  return { ...state, gap, notes: withFirstLine(list.slice()), created: [], ...extra };
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
    return { ...x, start: x.start + db, pitch: x.pitch + dp, brk: x.brk != null ? x.brk + db : null };
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

/** Добавить ноту (двойной клик, `N`): по умолчанию 4 бита, без текста, обычная. */
export function addNote(state, { start, pitch, length = 4, text = '', type = ':' }) {
  checkPitch(pitch);
  const id = state.nextId;
  const note = {
    id, src: null, type, start: Math.round(start), length: Math.max(1, Math.round(length)), pitch, text, ls: false, brk: null,
  };
  return settle({ ...state, nextId: id + 1 }, [...state.notes, note], [id], { created: [id] });
}

/** Удалить ноты; начало строки переходит к следующей уцелевшей ноте. Последнюю ноту не удалить. */
export function deleteNotes(state, ids) {
  checkIds(state, ids);
  const set = new Set(ids);
  if (state.notes.every((x) => set.has(x.id))) throw new Error(LAST_NOTE_ERROR);
  const out = [];
  let carry = null; // начало строки удалённой ноты: {brk}
  for (const x of state.notes) {
    if (set.has(x.id)) {
      if (x.ls && !carry) carry = { brk: x.brk };
      continue;
    }
    if (carry && !x.ls) out.push({ ...x, ls: true, brk: carry.brk });
    else out.push(x);
    carry = null;
  }
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
 * Строка li целиком из текста панели: слоги (toSyllables) по нотам строки по порядку;
 * лишние ноты получают «~», лишние слоги склеиваются в последней ноте.
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

/** «+ K нот»: k нот по 3 бита подряд за последней нотой строки li, с её высотой (остаются в строке). */
export function addNotesToLine(state, li, k) {
  const line = lines(state)[li];
  if (!line) throw new Error('Нет такой строки');
  const last = line[line.length - 1];
  const added = [];
  let start = last.start + last.length;
  let id = state.nextId;
  for (let j = 0; j < k; j += 1) {
    added.push({ id, src: null, type: ':', start, length: 3, pitch: last.pitch, text: '', ls: false, brk: null });
    start += 3;
    id += 1;
  }
  const at = indexOf(state, last.id) + 1;
  const notes = [...state.notes.slice(0, at), ...added, ...state.notes.slice(at)];
  return settle({ ...state, nextId: id }, notes, [], { created: added.map((x) => x.id) });
}

/** Ноты, перекрывающие предыдущую по порядку песни (и сама предыдущая) — для красной подсветки. */
export function overlaps(state) {
  const out = new Set();
  state.notes.forEach((x, i) => {
    const prev = state.notes[i - 1];
    if (prev && x.start < prev.start + prev.length) {
      out.add(prev.id);
      out.add(x.id);
    }
  });
  return out;
}

/**
 * «⇠ текст / текст ⇢»: сдвинуть слоги строки на одну ноту, начиная с ноты id (dir 1 — вправо,
 * −1 — влево). Освободившаяся нота получает «~»; занятая крайняя нота — ошибка.
 */
export function shiftText(state, id, dir) {
  const line = lines(state)[lineIndexOf(state, id)];
  const i = line.findIndex((x) => x.id === id);
  const t = line.map((x) => x.text);
  const next = t.slice();
  if (dir > 0) {
    if (!isFree(t[t.length - 1])) throw new Error('Справа нет свободной ноты — добавь ноту в конец строки');
    for (let k = line.length - 1; k > i; k -= 1) next[k] = t[k - 1];
    next[i] = '~';
  } else {
    if (i === 0) throw new Error('Слева нет ноты в этой строке — текст некуда сдвинуть');
    if (!isFree(t[i - 1])) throw new Error('Слева занятая нота — текст некуда сдвинуть');
    for (let k = i - 1; k < line.length - 1; k += 1) next[k] = t[k + 1];
    next[line.length - 1] = '~';
  }
  const byId = new Map(line.map((x, k) => [x.id, next[k]]));
  return { ...state, notes: state.notes.map((x) => (byId.has(x.id) ? { ...x, text: byId.get(x.id) } : x)), created: [] };
}

/** Разрезать ноту пополам (`S`): вторая половина — новая нота с «~». */
export function splitNote(state, id) {
  const i = indexOf(state, id);
  const x = state.notes[i];
  if (x.length < 2) throw new Error('Нота в 1 бит — резать нечего');
  const a = Math.ceil(x.length / 2);
  const nid = state.nextId;
  const tail = { ...x, id: nid, src: null, start: x.start + a, length: x.length - a, text: '~', ls: false, brk: null };
  const notes = [...state.notes.slice(0, i), { ...x, length: a }, tail, ...state.notes.slice(i + 1)];
  return { ...state, notes, nextId: nid + 1, created: [nid] };
}

/** Слить ноту со следующей (`Shift+J`): длина — до конца следующей, текст склеен; не через строку. */
export function joinNext(state, id) {
  const i = indexOf(state, id);
  const x = state.notes[i];
  const nx = state.notes[i + 1];
  if (!nx) throw new Error('Это последняя нота — сливать не с чем');
  if (nx.ls) throw new Error('Следующая нота в другой строке — сливать нельзя');
  // «~» (с любыми пробелами) при слиянии отбрасывается с любой стороны, пробелы-границы слов остаются
  const drop = (t) => (String(t).trim() === '~' ? String(t).replace('~', '') : String(t));
  const both = drop(x.text) + drop(nx.text);
  const text = both.trim() ? both : x.text;
  const notes = [...state.notes.slice(0, i), { ...x, length: nx.start + nx.length - x.start, text }, ...state.notes.slice(i + 2)];
  return { ...state, notes, created: [] };
}

/** «↵ Строка»: начать новую строку с ноты id. */
export function startLine(state, id) {
  const i = indexOf(state, id);
  if (state.notes[i].ls) throw new Error('Эта нота уже начинает строку');
  const notes = state.notes.slice();
  notes[i] = { ...notes[i], ls: true, brk: null };
  return { ...state, notes, created: [] };
}

/** Склеить строку ноты id с предыдущей (значок ↵ на границе строк). */
export function mergeLineAt(state, id) {
  const li = lineIndexOf(state, id);
  if (li <= 0) throw new Error('Это первая строка — склеивать не с чем');
  const head = lines(state)[li][0].id;
  return { ...state, notes: state.notes.map((x) => (x.id === head ? { ...x, ls: false, brk: null } : x)), created: [] };
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
  notes[i] = { ...x, start: s, length: Math.max(1, Math.round(length)), brk: x.brk != null ? x.brk + s - x.start : null };
  return settle(state, notes, [id]);
}

/**
 * Проверка перед сохранением — то же, что PUT на сервере (§14).
 * null — всё в порядке, иначе {message, id} первой ноты с ошибкой (id null — ошибка не ноты).
 */
export function validate(state) {
  if (!state.notes.length) return { message: LAST_NOTE_ERROR, id: null };
  const ls = lines(state);
  for (let li = 0; li < ls.length; li += 1) {
    for (const x of ls[li]) {
      // тексты — дословно как 400 сервера (web/app/notes.py)
      const where = `строка ${li + 1}, слог «${String(x.text).trim()}»`;
      const fail = (message, at = where) => ({ message: `${message}: ${at}`, id: x.id });
      if (!TYPES.includes(x.type)) return fail(`Неизвестный тип ноты «${x.type}»`);
      if (!Number.isInteger(x.start) || x.start < 0) return fail(START_ERROR);
      if (!Number.isInteger(x.length) || x.length < 1) return fail(LENGTH_ERROR);
      if (!Number.isInteger(x.pitch) || x.pitch < PITCH_MIN || x.pitch > PITCH_MAX) return fail(PITCH_ERROR);
      if (/[\r\n]/.test(String(x.text))) return fail(NEWLINE_ERROR, `строка ${li + 1}`);
    }
  }
  const prevOf = new Map(state.notes.map((x, i) => [x.id, state.notes[i - 1]]));
  for (let li = 0; li < ls.length; li += 1) {
    for (const x of ls[li]) {
      const prev = prevOf.get(x.id);
      if (prev && x.start < prev.start + prev.length) {
        return { message: `Ноты перекрываются: строка ${li + 1}, слог «${String(x.text).trim()}»`, id: x.id };
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
