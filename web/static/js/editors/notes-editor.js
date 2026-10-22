// Экран «Редактор нот» (спека: истории 1–15, 17–20, 27–30, 32–34; решения §1, §3, §7–§11):
// таймлайн (линейка, волна, ноты по высоте, дорожка слогов, границы строк, курсор), звук из /audio,
// правка мышью и клавишами через notes-model.js, сохранение PUT /notes.
//
// Дуэт (таск 03 «дуэты»): цвет нот по певцу (1 / 2 / «оба»), две полосы слогов, живые ноты каждой партии,
// Tab, новая нота и границы строк — внутри партии выбранной ноты.
//
// Точки расширения (панель текста, отстукивание, перенос текста, справка — таск 04):
// addNotesEditorPlugin(fn) — fn(ctx) вызывается при каждом открытии редактора, ctx описан у makeContext().

import { api, errorText } from '../api.js';
import { h, songName } from '../ui.js';
import { openShell, fmtTime } from './shell.js';
import * as M from './notes-model.js';
import {
  octaveLabel, clampZoom, zoomScroll, hitZone, noteAt, rulerStep, pitchRange, ensureVisible, rebaseBeat,
} from './timeline-math.js';
import { loadPeaks, drawWave } from './waveform.js';
import { liveNotes } from './notes-panel-logic.js';

const RULER_H = 24;
const WAVE_H = 44;
const WAVE_OFF_H = 20;
const ZOOM_KEY = 'notesEditor.ppb';
const VIEW_BPM = 300;
const NO_BPM_PLAY = 'В песне нет #BPM — время нот неизвестно'; // без #BPM ноты всё равно рисуются (только просмотр)

const plugins = [];

/** Подключить расширение редактора: fn(ctx) при каждом открытии (см. makeContext). */
export function addNotesEditorPlugin(fn) {
  plugins.push(fn);
}

function loadZoom() {
  try {
    const v = Number(localStorage.getItem(ZOOM_KEY));
    if (v > 0) return clampZoom(v);
  } catch { /* хранилище недоступно */ }
  return 16;
}

function saveZoom(v) {
  try { localStorage.setItem(ZOOM_KEY, String(v)); } catch { /* хранилище недоступно */ }
}

const isRap = (t) => t === 'R' || t === 'G';
const VOICE_CLASS = { 1: 'p1', 2: 'p2', both: 'both' };
/** Подписи певца строки — один словарь модели (кнопка, «кому», «у кого», «кто»). */
const voiceLabel = (v) => M.VOICE_LABELS[v] ?? M.VOICE_LABELS[1];

export async function openNotesEditor(song, { reload } = {}) {
  let state = null;
  let original = null;
  let hist = M.history();
  let sel = new Set();
  let lastSel = null;
  let busy = false;
  let ppb = loadZoom();
  let row = 12;
  let pr = { min: 0, max: 12 };
  let origin = 0; // бит у левого края таймлайна (≤ 0: до первой ноты видно вступление)
  let wave = null;
  let waveState = song.audio ? 'loading' : 'off';
  let duration = 0; // с
  let posMs = 0;
  let playing = false;
  let stopAt = null;
  let raf = 0;
  let liveIds = new Set();
  let drag = null;
  let dirtyMemo = { s: null, v: false };
  const els = new Map(); // id → {note, chip}
  let noteMap = new Map(); // id → нота текущего состояния (строится в render)
  let endMs = 0; // конец песни, мс (считается в render)
  let endLabel = '0:00';
  const hooks = { render: [], select: [], tick: [] };
  const extraKeys = [];
  const waveAbort = new AbortController();

  // ------------------------------------------------------------ разметка

  const btn = (label, title, attrs = {}) => h('button', { type: 'button', title, 'aria-label': attrs.aria || title, ...attrs, aria: undefined }, label);
  const undoBtn = btn('↶', 'Отменить (Ctrl+Z)', { class: 'icon', disabled: true, aria: 'Отменить' });
  const redoBtn = btn('↷', 'Повторить (Ctrl+Shift+Z)', { class: 'icon', disabled: true, aria: 'Повторить' });
  const status = h('span', { class: 'ne-status', role: 'status' });
  const saveBtn = btn('Сохранить', 'Сохранить (Ctrl+S)', { class: 'primary', disabled: true });

  const playBtn = btn('▶', 'Играть / пауза (Пробел)', { class: 'icon', aria: 'Играть' });
  const lineBtn = btn('▶ строка', 'Проиграть строку выбранной ноты (L)');
  const timeEl = h('span', { class: 'ne-time' }, '0:00.0');
  const rateSel = h('select', { title: 'Скорость проигрывания — медленнее удобнее расставлять', 'aria-label': 'Скорость' },
    h('option', { value: '0.5' }, '0.5×'), h('option', { value: '0.75' }, '0.75×'), h('option', { value: '1', selected: true }, '1×'));
  const followBtn = btn('Следовать', 'Таймлайн едет за курсором', { class: 'on', 'aria-pressed': 'true' });
  const zoutBtn = btn('−', 'Отдалить (−, Ctrl+колесо)', { class: 'icon', aria: 'Отдалить' });
  const zinBtn = btn('+', 'Приблизить (+, Ctrl+колесо)', { class: 'icon', aria: 'Приблизить' });
  const selAllBtn = btn('Выделить всё', 'Выделить все ноты (Ctrl+A) — сдвинуть песню по времени или тональность');
  const selInfo = h('span', { class: 'small muted ne-selinfo' }, 'Ничего не выбрано');
  const textBtn = btn('Текст', 'Править слог выбранной ноты (F2, Enter, двойной клик по слогу)', { disabled: true });
  const goldBtn = btn('★', 'Золотая нота (G)', { class: 'icon', disabled: true, aria: 'Золотая нота' });
  const delBtn = btn('Удалить', 'Удалить выбранные ноты (Delete)', { disabled: true });
  // слоты для расширений (таск 04)
  const slotPlay = h('span', { class: 'ne-slot' });
  const slotTools = h('span', { class: 'ne-slot' });
  const slotEnd = h('span', { class: 'ne-slot' });
  const sep = () => h('span', { class: 'ne-sep' });

  const bar = h('div', { class: 'ne-bar', role: 'toolbar', 'aria-label': 'Проигрывание и правка' },
    playBtn, lineBtn, timeEl, rateSel, followBtn, sep(), zoutBtn, zinBtn, sep(), slotPlay,
    h('span', { class: 'ne-grow' }), selAllBtn, selInfo, textBtn, slotTools, goldBtn, delBtn, slotEnd);

  const keysIn = h('div', { class: 'ne-keys-in' });
  const keys = h('div', { class: 'ne-keys', 'aria-hidden': 'true' }, keysIn);
  const ruler = h('div', { class: 'ne-ruler', title: 'Клик — перейти сюда' });
  const canvas = h('canvas', { class: 'ne-wave-cv' });
  const waveLabel = h('span', { class: 'ne-wave-label small muted' });
  const waveBox = h('div', { class: 'ne-wave', title: 'Громкость трека — клик перемещает курсор' }, canvas, waveLabel);
  const roll = h('div', { class: 'ne-roll' });
  const lane = h('div', { class: 'ne-lane' });
  const brkLayer = h('div', { class: 'ne-brks' });
  const playhead = h('div', { class: 'ne-playhead' });
  const inner = h('div', { class: 'ne-inner' }, ruler, waveBox, roll, lane, brkLayer, playhead);
  const scroll = h('div', { class: 'ne-scroll', tabindex: '0', 'aria-label': 'Таймлайн нот' }, inner);
  const legend = h('div', { class: 'ne-legend small', hidden: true, 'aria-label': 'Цвета певцов' });
  const centerTop = h('div', { class: 'ne-center-top' }, legend);
  const hint = h('div', { class: 'ne-hint' },
    h('span', {}, h('b', {}, 'Двойной клик'), ' по пустому месту — новая нота'),
    h('span', {}, h('b', {}, 'Тяни ноту'), ' — время и высота'),
    h('span', {}, h('b', {}, 'Тяни край'), ' — длительность'),
    h('span', {}, h('b', {}, 'Двойной клик по слогу'), ' — правка, ', h('kbd', {}, 'Tab'), ' — к следующему'),
    h('span', {}, h('kbd', {}, 'Delete'), ' — удалить'),
    h('span', {}, 'рамка мышью — выделить несколько'));
  const center = h('div', { class: 'ne-center' }, centerTop, h('div', { class: 'ne-tl' }, keys, scroll), hint);
  const panel = h('aside', { class: 'ne-panel', hidden: true, 'aria-label': 'Текст песни' });
  const main = h('div', { class: 'ne-main' }, center, panel);
  const toastEl = h('div', { class: 'ne-toast', role: 'status' });

  const shell = openShell({
    title: 'Редактор нот',
    subtitle: songName(song.artist, song.title),
    isDirty: () => dirty(),
    wide: true,
  });
  for (const el of [undoBtn, redoBtn, status, saveBtn]) shell.head.insertBefore(el, shell.closeBtn);
  shell.body.classList.add('ne');
  shell.body.append(bar, main, toastEl);
  const dlg = shell.dlg;
  shell.message('Загрузка…', 'warn');

  // ------------------------------------------------------------ координаты

  const bpm = () => (Number(state?.bpm) > 0 ? Number(state.bpm) : VIEW_BPM);
  const msOf = (beat) => M.beatToMs(beat, state.gap, bpm());
  const beatOf = (ms) => M.msToBeat(ms, state.gap, bpm());
  const bx = (beat) => (beat - origin) * ppb;
  const xBeat = (x) => x / ppb + origin;
  const py = (pitch) => (pr.max - pitch) * row;
  const waveH = () => (waveState === 'off' || waveState === 'error' ? WAVE_OFF_H : WAVE_H);
  const editable = () => !!state?.editable;
  const byId = (id) => noteMap.get(id);
  const songEndMs = () => endMs;
  function calcEnd() {
    const last = state.notes.reduce((m, x) => Math.max(m, x.start + x.length), 0);
    endMs = Math.max(duration * 1000, msOf(last));
    endLabel = fmtTime(endMs).replace(/\.\d$/, '');
  }

  function dirty() {
    if (!editable() || !original) return false;
    if (dirtyMemo.s !== state) dirtyMemo = { s: state, v: M.isDirty(state, original) };
    return dirtyMemo.v;
  }

  // ------------------------------------------------------------ сообщения

  let toastTimer = 0;
  function toast(text, kind = '') {
    toastEl.textContent = text;
    toastEl.className = `ne-toast show ${kind}`;
    toastEl.setAttribute('role', kind === 'err' ? 'alert' : 'status');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), kind === 'err' ? 4000 : 2000);
  }

  // ------------------------------------------------------------ отрисовка

  function noteTitle(x, bad) {
    const t = String(x.text).trim() || '∅';
    const who = state.duet ? ` · ${voiceLabel(x.voice).who}` : '';
    return `«${t}» · ${fmtTime(msOf(x.start))} · ${x.length} бит${who}${bad ? ' · перекрывается с соседней!' : ''}`;
  }

  /** Подпись певца: «Певец 2 (Анна)». */
  const singerLabel = (v) => {
    const name = state?.singers?.[`p${v}`];
    return `Певец ${v}${name ? ` (${name})` : ''}`;
  };

  function renderLegend() {
    legend.hidden = !state.duet;
    legend.textContent = '';
    if (!state.duet) return;
    for (const [cls, label] of [['p1', singerLabel(1)], ['p2', singerLabel(2)], ['both', 'Оба']]) {
      legend.append(h('span', { class: `ne-lg ${cls}` }, h('i', { 'aria-hidden': 'true' }), label));
    }
  }

  function place(e, x) {
    e.note.style.left = `${bx(x.start)}px`;
    e.note.style.width = `${Math.max(4, x.length * ppb - 2)}px`;
    e.note.style.top = `${py(x.pitch) + 1}px`;
    e.chip.style.left = `${bx(x.start)}px`;
    e.chip.style.width = `${Math.max(8, x.length * ppb)}px`;
  }

  function renderKeys() {
    keysIn.textContent = '';
    const top = RULER_H + waveH();
    const frag = document.createDocumentFragment();
    for (let p = pr.max; p >= pr.min; p -= 1) {
      const d = document.createElement('div');
      d.style.top = `${top + (pr.max - p) * row}px`;
      d.style.height = `${row}px`;
      if ([1, 3, 6, 8, 10].includes(((p % 12) + 12) % 12)) d.className = 'blk';
      const lbl = octaveLabel(p);
      if (lbl) d.textContent = lbl;
      frag.append(d);
    }
    keysIn.append(frag);
  }

  function renderRuler() {
    ruler.textContent = '';
    const pxPerSec = (ppb * 1000) / (60000 / (bpm() * 4));
    const step = rulerStep(pxPerSec);
    const frag = document.createDocumentFragment();
    const end = songEndMs() + 5000;
    for (let ms = 0; ms < end; ms += step) {
      const x = bx(beatOf(ms));
      if (x < 0) continue;
      const i = document.createElement('i');
      i.style.left = `${x}px`;
      const s = document.createElement('span');
      s.style.left = `${x}px`;
      const sec = Math.round(ms / 1000);
      s.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
      frag.append(i, s);
    }
    ruler.append(frag);
  }

  function renderNotes() {
    roll.textContent = '';
    lane.textContent = '';
    brkLayer.textContent = '';
    els.clear();
    liveIds = new Set();
    const bad = M.overlaps(state);
    const duet = !!state.duet;
    lane.classList.toggle('duet', duet);
    const fn = document.createDocumentFragment();
    const fc = document.createDocumentFragment();
    const fb = document.createDocumentFragment();
    state.notes.forEach((x, i) => {
      const note = document.createElement('div');
      const vc = duet ? ` ${VOICE_CLASS[x.voice] || 'p1'}` : '';
      note.className = `ne-note${vc}${x.type === '*' || x.type === 'G' ? ' gold' : ''}${x.type === 'F' ? ' free' : ''}`
        + `${isRap(x.type) ? ' rap' : ''}${bad.has(x.id) ? ' bad' : ''}${sel.has(x.id) ? ' sel' : ''}`;
      note.dataset.id = x.id;
      note.title = noteTitle(x, bad.has(x.id));
      const chip = document.createElement('div');
      const empty = !String(x.text).trim();
      chip.className = `ne-chip${vc}${empty ? ' empty' : ''}${isRap(x.type) ? ' rap' : ''}${sel.has(x.id) ? ' sel' : ''}`;
      chip.dataset.id = x.id;
      chip.textContent = empty ? '∅' : String(x.text).trim();
      chip.title = editable() ? 'Двойной клик — править слог' : String(x.text);
      const e = { note, chip };
      place(e, x);
      els.set(x.id, e);
      fn.append(note);
      fc.append(chip);
    });
    // границы строк — внутри каждой партии (у дуэта ↵ певца 1 — на верхней полосе слогов, певца 2 — на нижней)
    for (const v of M.parts(state)) {
      const ls = M.voiceLines(state, v);
      for (let j = 1; j < ls.length; j += 1) {
        const pv = ls[j - 1][ls[j - 1].length - 1];
        const x = ls[j][0];
        const b = document.createElement('div');
        b.className = `ne-brk${duet ? ` p${v}` : ''}`;
        // линия — на бите разрыва «- N», если он задан и стоит в паузе; иначе посередине паузы
        const end = pv.start + pv.length;
        const brk = v === 2 && x.voice === 'both' ? x.brk2 : x.brk;
        b.style.left = `${bx(brk != null && brk >= end && brk <= x.start ? brk : (end + x.start) / 2)}px`;
        if (editable()) {
          // зона захвата 8 px: тяга двигает разрыв (M.moveBreak)
          const g = document.createElement('i');
          g.className = 'ne-brk-grip';
          g.dataset.id = x.id;
          g.dataset.voice = String(v);
          g.title = 'Тяни — граница строки: поверх нот переносит их, в паузе ставит бит разрыва';
          b.append(g);
        }
        const k = document.createElement('b');
        k.textContent = '↵';
        k.dataset.id = x.id;
        k.dataset.voice = String(v); // партия полосы: ↵ у строки «оба» склеивает в ней
        k.title = duet ? `Граница строки (певец ${v})` : 'Граница строки';
        b.append(k);
        fb.append(b);
      }
    }
    roll.append(fn);
    lane.append(fc);
    brkLayer.append(fb);
  }

  function render() {
    if (!state) return;
    noteMap = new Map(state.notes.map((x) => [x.id, x]));
    calcEnd();
    pr = pitchRange(state.notes, 4);
    const avail = scroll.clientHeight - RULER_H - waveH() - 44;
    row = Math.max(8, Math.min(22, Math.floor(avail / (pr.max - pr.min + 1)) || 8));
    origin = Math.min(0, Math.floor(beatOf(0)));
    const endBeat = Math.ceil(beatOf(songEndMs())) + 48;
    inner.style.width = `${(endBeat - origin) * ppb}px`;
    waveBox.style.height = `${waveH()}px`;
    waveBox.classList.toggle('off', waveH() !== WAVE_H);
    roll.style.height = `${(pr.max - pr.min + 1) * row}px`;
    roll.style.setProperty('--nh', `${row - 2}px`);
    roll.style.setProperty('--row', `${row}px`);
    roll.style.setProperty('--beat4', `${ppb * 4}px`);
    roll.style.setProperty('--beat16', `${ppb * 16}px`);
    roll.style.backgroundPosition = `${bx(0)}px 0`;
    brkLayer.style.top = `${RULER_H + waveH()}px`;
    renderLegend();
    renderKeys();
    renderRuler();
    renderNotes();
    drawVisible();
    updatePlayhead();
    updateTools();
    hooks.render.forEach((f) => f());
  }

  function renderSel() {
    for (const [id, e] of els) {
      const on = sel.has(id);
      e.note.classList.toggle('sel', on);
      e.chip.classList.toggle('sel', on);
    }
    updateTools();
    hooks.select.forEach((f) => f());
  }

  function drawVisible() {
    if (!state) return;
    const sl = scroll.scrollLeft;
    canvas.style.left = `${sl}px`;
    waveLabel.style.left = `${sl + 8}px`;
    keysIn.style.transform = `translateY(${-scroll.scrollTop}px)`;
    if (waveState !== 'ready') {
      canvas.hidden = true;
      return;
    }
    canvas.hidden = false;
    drawWave(canvas, wave, {
      scrollLeft: sl, width: scroll.clientWidth, height: WAVE_H,
      xToMs: (x) => msOf(xBeat(x)), color: getComputedStyle(dlg).getPropertyValue('--ne-wave').trim() || '#9aa6bd',
    });
  }

  function updateTools() {
    const n = sel.size;
    const one = n === 1 ? byId([...sel][0]) : null;
    const total = state?.notes.length ?? 0;
    selInfo.textContent = n === 0 ? 'Ничего не выбрано'
      : n === total && n > 1 ? `Выбраны все ноты (${n})`
        : one ? `«${String(one.text).trim() || '∅'}» · ${one.length} бит · ${fmtTime(msOf(one.start))}`
            + `${state.duet ? ` · ${voiceLabel(one.voice).who}` : ''}`
          : `Выбрано нот: ${n}`;
    const ro = !editable();
    textBtn.disabled = ro || n !== 1;
    goldBtn.disabled = ro || n === 0;
    delBtn.disabled = ro || n === 0;
    selAllBtn.disabled = !state;
    undoBtn.disabled = ro || !hist.canUndo();
    redoBtn.disabled = ro || !hist.canRedo();
    const d = dirty();
    saveBtn.hidden = !!state && ro;
    saveBtn.disabled = busy || !d;
    saveBtn.textContent = busy ? 'Сохраняю…' : 'Сохранить';
    undoBtn.hidden = redoBtn.hidden = !!state && ro;
    status.textContent = !state ? '' : ro ? 'Только просмотр' : d ? 'Есть несохранённые правки' : 'Правок нет';
    status.classList.toggle('dirty', d);
    const reason = playReason();
    for (const b of [playBtn, lineBtn]) {
      b.disabled = !!reason;
      b.title = reason || (b === playBtn ? 'Играть / пауза (Пробел)' : 'Проиграть строку выбранной ноты (L)');
    }
  }

  // ------------------------------------------------------------ звук

  const audio = new Audio();
  audio.preload = 'auto';
  audio.preservesPitch = true;
  audio.mozPreservesPitch = true;
  audio.webkitPreservesPitch = true;
  let audioError = song.audio ? '' : 'У песни нет аудиофайла — правка работает без звука';
  if (song.audio) audio.src = api.audioUrl(song.song_id);
  audio.addEventListener('error', () => {
    if (!song.audio) return;
    audioError = 'Аудио не загрузилось — правка работает без звука';
    stopPlay();
    updateTools();
  });
  audio.addEventListener('loadedmetadata', () => {
    if (Number.isFinite(audio.duration)) duration = audio.duration;
    render();
  });
  audio.addEventListener('pause', () => stopPlay());

  function playReason() {
    if (audioError) return audioError;
    if (state && !(Number(state.bpm) > 0)) return NO_BPM_PLAY;
    return '';
  }

  function stopPlay() {
    if (!playing) return;
    playing = false;
    stopAt = null;
    cancelAnimationFrame(raf);
    if (!audio.paused) audio.pause();
    playBtn.textContent = '▶';
    playBtn.setAttribute('aria-label', 'Играть');
    updatePlayhead();
  }

  async function play(fromMs, untilMs) {
    if (playReason()) return;
    if (playing && fromMs === undefined) { stopPlay(); return; }
    stopPlay();
    if (fromMs !== undefined) posMs = Math.max(0, fromMs);
    audio.playbackRate = Number(rateSel.value);
    try {
      audio.currentTime = posMs / 1000;
      await audio.play();
    } catch (e) {
      if (e?.name !== 'AbortError') shell.message(`Не удалось проиграть: ${e?.message || 'аудио недоступно'}`, 'err');
      return;
    }
    stopAt = untilMs ?? null;
    playing = true;
    playBtn.textContent = '❚❚';
    playBtn.setAttribute('aria-label', 'Пауза');
    const loop = () => {
      if (!playing) return;
      posMs = audio.currentTime * 1000;
      if (stopAt !== null && posMs >= stopAt) { stopPlay(); return; }
      updatePlayhead();
      if (followBtn.classList.contains('on')) {
        const sl = ensureVisible(bx(beatOf(posMs)), scroll.scrollLeft, scroll.clientWidth);
        if (sl !== scroll.scrollLeft) scroll.scrollLeft = sl;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
  }

  function seekMs(ms, reveal = false) {
    posMs = Math.max(0, ms);
    if (!audioError) {
      try { audio.currentTime = posMs / 1000; } catch { /* метаданные ещё не пришли */ }
    }
    updatePlayhead();
    if (reveal) scroll.scrollLeft = Math.max(0, bx(beatOf(posMs)) - scroll.clientWidth / 4);
  }

  function updatePlayhead() {
    if (!state) return;
    const beat = beatOf(posMs);
    playhead.style.transform = `translateX(${bx(beat)}px)`;
    timeEl.textContent = `${fmtTime(posMs)} / ${endLabel}`;
    // живая нота — в каждой партии своя (у соло партия одна — все ноты)
    const now = playing ? liveNotes(state, beat) : new Set();
    if (now.size !== liveIds.size || [...now].some((id) => !liveIds.has(id))) {
      for (const id of liveIds) {
        const was = els.get(id);
        if (was && !now.has(id)) { was.note.classList.remove('live'); was.chip.classList.remove('live'); }
      }
      for (const id of now) {
        const e = els.get(id);
        if (e) { e.note.classList.add('live'); e.chip.classList.add('live'); }
      }
      liveIds = now;
    }
    hooks.tick.forEach((f) => f(posMs, playing));
  }

  function playLine() {
    const id = sel.has(lastSel) ? lastSel : state.notes[Math.max(0, noteAt(state.notes, beatOf(posMs)))].id;
    const line = M.lines(state).find((l) => l.some((x) => x.id === id));
    if (!line) return;
    const last = line[line.length - 1];
    play(msOf(line[0].start) - 200, msOf(last.start + last.length) + 300);
  }

  // ------------------------------------------------------------ правка

  /**
   * Применить операцию модели: история, выделение созданных нот, перерисовка; ошибка — сообщение.
   * amend — дописать в последний шаг отмены (правка строки в панели, сессия отстукивания).
   */
  function apply(fn, okText, { amend = false } = {}) {
    if (!editable()) return false;
    let next;
    try {
      next = fn(state);
    } catch (e) {
      toast(e.message, 'err');
      return false;
    }
    if (!next || next === state) return false;
    if (!amend) hist.push(state);
    state = next;
    if (state.created.length) {
      sel = new Set(state.created);
      lastSel = state.created[state.created.length - 1];
    }
    pruneSel();
    render();
    if (okText) toast(okText);
    return true;
  }

  function pruneSel() {
    const ids = new Set(state.notes.map((x) => x.id));
    sel = new Set([...sel].filter((id) => ids.has(id)));
    if (!ids.has(lastSel)) lastSel = sel.size ? [...sel][sel.size - 1] : null;
  }

  function select(ids, { reveal = false, add = false } = {}) {
    const list = [...ids];
    sel = add ? new Set([...sel, ...list]) : new Set(list);
    if (list.length) lastSel = list[list.length - 1];
    renderSel();
    if (reveal && list.length) revealNote(list[list.length - 1]);
  }

  function revealNote(id) {
    const x = byId(id);
    if (!x) return;
    const sl = ensureVisible(bx(x.start), scroll.scrollLeft, scroll.clientWidth);
    if (sl !== scroll.scrollLeft) scroll.scrollLeft = sl;
    const y = RULER_H + waveH() + py(x.pitch);
    if (y < scroll.scrollTop + RULER_H || y > scroll.scrollTop + scroll.clientHeight - 60) {
      scroll.scrollTop = Math.max(0, y - scroll.clientHeight / 2);
    }
  }

  function undo() {
    if (!editable()) return;
    const prev = hist.undo(state);
    if (!prev) return;
    state = prev;
    pruneSel();
    render();
    toast('Отменено');
  }

  function redo() {
    if (!editable()) return;
    const next = hist.redo(state);
    if (!next) return;
    state = next;
    pruneSel();
    render();
  }

  function deleteSel() {
    if (!sel.size) return;
    const k = sel.size;
    apply((s) => M.deleteNotes(s, [...sel]), `Удалено нот: ${k} — Ctrl+Z вернёт`);
  }

  function selectAll() {
    if (!state) return;
    select(state.notes.map((x) => x.id));
    lastSel = state.notes[0].id;
    toast('Выделены все ноты: ←/→ сдвигают песню по времени, ↑/↓ меняют тональность');
  }

  /** Ноты партии ноты id (у соло — все ноты): по ним ходят Tab и правка слогов. */
  function partNotes(id) {
    return byId(id) ? M.partNotes(state, id) : M.voiceNotes(state, 1); // нет выбора — партия певца 1
  }

  /** Певец новой ноты: певец выбранной ноты (у соло — 1). */
  const newVoice = () => (state.duet && sel.has(lastSel) ? (byId(lastSel)?.voice ?? 1) : 1);

  /** Tab по нотам (у дуэта — по партии выбранной ноты); на крайней ноте — false: фокус уходит дальше. */
  function stepSel(dir) {
    const list = partNotes(lastSel);
    const i = list.findIndex((x) => x.id === lastSel);
    if (i >= 0 && (i + dir < 0 || i + dir >= list.length)) return false;
    const j = Math.max(0, Math.min(list.length - 1, i < 0 ? 0 : i + dir));
    select([list[j].id], { reveal: true });
    return true;
  }

  function newAfter() {
    const one = sel.size === 1 ? byId(lastSel) : null;
    if (!one) return;
    if (apply((s) => M.addNote(s, { start: one.start + one.length, pitch: one.pitch, length: 3, voice: one.voice ?? 1 }))) editChip(lastSel);
  }

  /** Поле ввода слога на дорожке: Tab/Shift+Tab — к соседней ноте, Enter — готово, Esc — отмена. */
  function editChip(id) {
    if (!editable()) return;
    const e = els.get(id);
    const x = byId(id);
    if (!e || !x) return;
    select([id], { reveal: true });
    const inp = h('input', { type: 'text', value: x.text, spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Текст слога' });
    e.chip.textContent = '';
    e.chip.classList.add('editing');
    e.chip.append(inp);
    inp.focus();
    inp.select();
    let done = false;
    const finish = (move, cancel = false) => {
      if (done) return;
      done = true;
      const changed = !cancel && inp.value !== x.text;
      if (!changed || !apply((s) => M.setText(s, id, inp.value))) render();
      if (move) {
        const list = partNotes(id);
        const i = list.findIndex((n) => n.id === id) + move;
        if (list[i]) editChip(list[i].id);
      } else {
        scroll.focus({ preventScroll: true });
      }
    };
    inp.addEventListener('keydown', (ev) => {
      ev.stopPropagation();
      if (ev.key === 'Tab') { ev.preventDefault(); finish(ev.shiftKey ? -1 : 1); } else if (ev.key === 'Enter') { ev.preventDefault(); finish(0); } else if (ev.key === 'Escape') { ev.preventDefault(); finish(0, true); }
    });
    inp.addEventListener('blur', () => finish(0));
  }

  async function save() {
    if (!editable() || busy || !dirty()) return;
    const bad = M.validate(state);
    if (bad) {
      if (bad.id != null) {
        select([bad.id], { reveal: true });
        seekMs(msOf(byId(bad.id).start) - 300);
      }
      shell.message(bad.message.startsWith('Ноты перекрываются')
        ? `${bad.message}. Перекрытые ноты подсвечены красным.` : bad.message, 'err');
      return;
    }
    busy = true;
    updateTools();
    try {
      await api.saveNotes(song.song_id, M.toPayload(state));
      setData(await api.notes(song.song_id));
      shell.message('Сохранено. Прежняя версия .txt — в корзине.', 'ok');
      reload?.();
    } catch (e) {
      shell.message(errorText(e, 'Не удалось сохранить'), 'err');
    } finally {
      busy = false;
      updateTools();
    }
  }

  // ------------------------------------------------------------ мышь и касание

  function seekFromEvent(e) {
    if (!state) return;
    const x = e.clientX - inner.getBoundingClientRect().left;
    seekMs(msOf(xBeat(x)));
  }
  ruler.addEventListener('click', seekFromEvent);
  waveBox.addEventListener('click', seekFromEvent);

  roll.addEventListener('pointerdown', (e) => {
    if (!state || e.button !== 0) return;
    const el = e.target.closest('.ne-note');
    const r = roll.getBoundingClientRect();
    if (!el) {
      if (!e.shiftKey && sel.size) select([]);
      const box = h('div', { class: 'ne-marquee' });
      drag = { kind: 'marquee', x0: e.clientX - r.left, y0: e.clientY - r.top, box, add: e.shiftKey };
      roll.setPointerCapture(e.pointerId);
      return;
    }
    const id = Number(el.dataset.id);
    if (e.shiftKey) {
      if (sel.has(id)) { sel.delete(id); renderSel(); } else select([id], { add: true });
      return;
    }
    const already = sel.has(id);
    if (!already) select([id]);
    lastSel = id;
    if (!editable()) return;
    const bxr = el.getBoundingClientRect();
    const kind = hitZone(e.clientX - bxr.left, bxr.width);
    const ids = kind === 'move' ? [...sel] : [id];
    drag = {
      kind, id, x0: e.clientX, y0: e.clientY, ids, idSet: new Set(ids), db: 0, dp: 0, moved: false, already, preview: null,
    };
    roll.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  roll.addEventListener('pointermove', (e) => {
    if (!drag) {
      const el = e.target.closest?.('.ne-note');
      if (el && editable()) {
        const bxr = el.getBoundingClientRect();
        el.style.cursor = hitZone(e.clientX - bxr.left, bxr.width) === 'move' ? 'grab' : 'ew-resize';
      }
      return;
    }
    if (drag.kind === 'marquee') {
      const r = roll.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (!drag.box.isConnected) roll.append(drag.box);
      drag.rect = { L: Math.min(x, drag.x0), T: Math.min(y, drag.y0), R: Math.max(x, drag.x0), B: Math.max(y, drag.y0) };
      Object.assign(drag.box.style, {
        left: `${drag.rect.L}px`, top: `${drag.rect.T}px`, width: `${drag.rect.R - drag.rect.L}px`, height: `${drag.rect.B - drag.rect.T}px`,
      });
      return;
    }
    const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
    if (!drag.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
    drag.moved = true;
    const db = Math.round(dx / ppb);
    const dp = drag.kind === 'move' ? -Math.round(dy / row) : 0;
    if (db === drag.db && dp === drag.dp) return;
    drag.db = db;
    drag.dp = dp;
    // предпросмотр — та же операция модели, что и на отпускании; двигаются только затронутые элементы
    try {
      drag.preview = drag.kind === 'move' ? M.move(state, drag.ids, db, dp) : M.resize(state, drag.id, drag.kind, db);
    } catch {
      return; // за пределом (высота, #GAP < 0) — предпросмотр стоит на последнем допустимом месте
    }
    const P = drag.preview;
    const b = bpm();
    for (const x of P.notes) {
      if (!drag.idSet.has(x.id)) continue;
      const ne = els.get(x.id);
      if (ne) place(ne, { ...x, start: rebaseBeat(x.start, P.gap ?? 0, state.gap ?? 0, b) });
    }
  });

  function endDrag(e, cancel = false) {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.kind === 'marquee') {
      d.box.remove();
      if (!cancel && d.rect) {
        const hit = state.notes.filter((x) => {
          const x1 = bx(x.start), x2 = bx(x.start + x.length), y1 = py(x.pitch), y2 = y1 + row;
          return x2 > d.rect.L && x1 < d.rect.R && y2 > d.rect.T && y1 < d.rect.B;
        }).map((x) => x.id);
        if (hit.length) select(hit, { add: d.add });
      }
      return;
    }
    if (cancel || !d.moved || (!d.db && !d.dp)) {
      if (d.moved) render(); // вернуть предпросмотр на место
      else if (d.already && sel.size > 1 && !cancel) select([d.id]);
      return;
    }
    const ok = d.preview && apply(() => d.preview);
    if (!ok) render();
  }
  roll.addEventListener('pointerup', (e) => endDrag(e));

  // перетаскивание разрыва строки (история 1–6, §14): призрак во время тяги, на отпускании — один шаг истории
  let brkDrag = null;
  brkLayer.addEventListener('pointerdown', (e) => {
    const g = e.target.closest('.ne-brk-grip');
    if (!g || e.button !== 0 || !editable()) return;
    e.preventDefault();
    e.stopPropagation();
    g.setPointerCapture(e.pointerId);
    const ghost = h('div', { class: `ne-brk ghost${state.duet ? ` p${g.dataset.voice}` : ''}` });
    ghost.style.left = g.parentElement.style.left;
    brkLayer.append(ghost);
    g.parentElement.classList.add('dragging');
    brkDrag = { g, id: Number(g.dataset.id), voice: Number(g.dataset.voice) || null, x0: e.clientX, ghost, beat: null };
    inner.classList.add('brk-dragging');
  });
  brkLayer.addEventListener('pointermove', (e) => {
    if (!brkDrag) return;
    if (brkDrag.beat == null && Math.abs(e.clientX - brkDrag.x0) < 3) return;
    const r = inner.getBoundingClientRect();
    brkDrag.beat = Math.round(xBeat(e.clientX - r.left));
    brkDrag.ghost.style.left = `${bx(brkDrag.beat)}px`;
  });
  function endBrkDrag(cancel) {
    if (!brkDrag) return;
    const d = brkDrag;
    brkDrag = null;
    d.ghost.remove();
    d.g.parentElement?.classList.remove('dragging');
    inner.classList.remove('brk-dragging');
    if (cancel || d.beat == null) return;
    apply((s) => M.moveBreak(s, d.id, d.beat, state.duet ? d.voice : null), 'Граница строки сдвинута');
  }
  brkLayer.addEventListener('pointerup', () => endBrkDrag(false));
  brkLayer.addEventListener('pointercancel', () => endBrkDrag(true));
  brkLayer.addEventListener('lostpointercapture', () => endBrkDrag(true));
  roll.addEventListener('pointercancel', (e) => endDrag(e, true));

  roll.addEventListener('dblclick', (e) => {
    if (!editable()) return;
    const el = e.target.closest('.ne-note');
    if (el) { editChip(Number(el.dataset.id)); return; }
    const r = roll.getBoundingClientRect();
    const start = Math.floor(xBeat(e.clientX - r.left));
    const pitch = pr.max - Math.floor((e.clientY - r.top) / row);
    const voice = newVoice();
    if (apply((s) => M.addNote(s, { start, pitch, length: 4, voice }))) editChip(lastSel);
  });

  lane.addEventListener('click', (e) => {
    const c = e.target.closest('.ne-chip');
    if (!c || c.classList.contains('editing')) return;
    const id = Number(c.dataset.id);
    if (e.shiftKey) select([id], { add: true }); else select([id]);
  });
  lane.addEventListener('dblclick', (e) => {
    const c = e.target.closest('.ne-chip');
    if (c && !c.classList.contains('editing')) editChip(Number(c.dataset.id));
  });

  let scrollRaf = 0;
  scroll.addEventListener('scroll', () => {
    cancelAnimationFrame(scrollRaf);
    scrollRaf = requestAnimationFrame(drawVisible);
  });
  scroll.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });

  function zoom(f) {
    const next = clampZoom(ppb * f);
    if (!state || next === ppb) return;
    const sl = zoomScroll({ scrollLeft: scroll.scrollLeft, width: scroll.clientWidth, ppb }, next);
    ppb = next;
    saveZoom(ppb);
    render();
    scroll.scrollLeft = sl;
    drawVisible();
  }

  // ------------------------------------------------------------ кнопки

  playBtn.addEventListener('click', () => play());
  lineBtn.addEventListener('click', () => playLine());
  rateSel.addEventListener('change', () => { audio.playbackRate = Number(rateSel.value); });
  followBtn.addEventListener('click', () => {
    const on = followBtn.classList.toggle('on');
    followBtn.setAttribute('aria-pressed', String(on));
  });
  zinBtn.addEventListener('click', () => zoom(1.25));
  zoutBtn.addEventListener('click', () => zoom(0.8));
  selAllBtn.addEventListener('click', selectAll);
  goldBtn.addEventListener('click', () => sel.size && apply((s) => M.toggleGold(s, [...sel])));
  delBtn.addEventListener('click', deleteSel);
  textBtn.addEventListener('click', () => sel.size === 1 && editChip(lastSel));
  undoBtn.addEventListener('click', undo);
  redoBtn.addEventListener('click', redo);
  saveBtn.addEventListener('click', save);

  // ------------------------------------------------------------ клавиатура (по code — работает в русской раскладке)

  function arrows(e) {
    if (!sel.size || e.altKey) return false;
    const ids = [...sel];
    const st = e.shiftKey ? 4 : 1;
    if (e.ctrlKey || e.metaKey) {
      if (e.code !== 'ArrowLeft' && e.code !== 'ArrowRight') return false;
      const d = e.code === 'ArrowRight' ? 1 : -1;
      apply((s) => ids.reduce((acc, id) => M.resize(acc, id, 'right', d), s));
      return true;
    }
    if (e.code === 'ArrowLeft') apply((s) => M.move(s, ids, -st, 0));
    else if (e.code === 'ArrowRight') apply((s) => M.move(s, ids, st, 0));
    else if (e.code === 'ArrowUp') apply((s) => M.move(s, ids, 0, 1));
    else if (e.code === 'ArrowDown') apply((s) => M.move(s, ids, 0, -1));
    if (sel.size === 1) revealNote(lastSel);
    return true;
  }

  const KEYS = [
    { code: 'Space', fn: () => play() },
    { code: 'KeyZ', ctrl: true, shift: false, fn: undo },
    { code: 'KeyZ', ctrl: true, shift: true, fn: redo },
    { code: 'KeyY', ctrl: true, fn: redo },
    { code: 'KeyS', ctrl: true, fn: save },
    { code: 'KeyA', ctrl: true, fn: selectAll },
    { code: 'Delete', fn: deleteSel },
    { code: 'Backspace', fn: deleteSel },
    { code: 'Tab', ctrl: false, shift: false, fn: () => stepSel(1) },
    { code: 'Tab', ctrl: false, shift: true, fn: () => stepSel(-1) },
    { code: 'F2', fn: () => sel.size === 1 && editChip(lastSel) },
    { code: 'Enter', ctrl: false, shift: false, fn: () => sel.size === 1 && editChip(lastSel) },
    { code: 'NumpadEnter', fn: () => sel.size === 1 && editChip(lastSel) },
    { code: 'KeyL', ctrl: false, fn: () => !playReason() && playLine() },
    { code: 'KeyN', ctrl: false, fn: newAfter },
    { code: 'KeyG', ctrl: false, fn: () => sel.size && apply((s) => M.toggleGold(s, [...sel])) },
    { code: 'Equal', ctrl: false, fn: () => zoom(1.25) },
    { code: 'NumpadAdd', ctrl: false, fn: () => zoom(1.25) },
    { code: 'Minus', ctrl: false, fn: () => zoom(0.8) },
    { code: 'NumpadSubtract', ctrl: false, fn: () => zoom(0.8) },
  ];

  const matches = (k, e) => k.code === e.code
    && (k.ctrl === undefined || k.ctrl === (e.ctrlKey || e.metaKey))
    && (k.shift === undefined || k.shift === e.shiftKey)
    && (k.alt === undefined ? !e.altKey : k.alt === e.altKey);

  dlg.addEventListener('keydown', (e) => {
    if (!state) return;
    if (e.target.closest?.('input, select, textarea, [contenteditable]')) return;
    if (e.code === 'Escape') {
      const k = extraKeys.find((x) => matches(x, e));
      if (k && k.fn(e) !== false) { e.preventDefault(); return; }
      if (sel.size) { e.preventDefault(); select([]); }
      return; // иначе — закрытие окна (cancel у dialog)
    }
    const onControl = !!e.target.closest?.('button, a, select, summary');
    const onTimeline = scroll.contains(e.target);
    for (const k of [...extraKeys, ...KEYS]) {
      if (!matches(k, e)) continue;
      if (k.code === 'Tab' && !onTimeline) continue; // с кнопок — обычный порядок фокуса
      if (['Space', 'Enter', 'NumpadEnter'].includes(k.code) && onControl) continue; // нажать кнопку
      if (k.fn(e) !== false) { e.preventDefault(); return; }
    }
    if (e.code.startsWith('Arrow') && arrows(e)) e.preventDefault();
  });

  // ------------------------------------------------------------ загрузка, жизненный цикл

  function setData(data) {
    state = M.fromPayload(data);
    original = state;
    hist = M.history();
    sel = new Set();
    lastSel = null;
    dirtyMemo = { s: null, v: false };
    shell.message(state.editable ? '' : (state.reason || 'Эту песню можно только просмотреть'), state.editable ? 'ok' : 'warn');
    render();
  }

  function startWave() {
    if (!song.audio) {
      waveLabel.textContent = 'Волна недоступна: у песни нет аудиофайла';
      return;
    }
    waveLabel.textContent = 'Строю волну…';
    loadPeaks(api.audioUrl(song.song_id), { signal: waveAbort.signal }).then((w) => {
      wave = w;
      waveState = 'ready';
      waveLabel.textContent = '';
      render();
    }, (e) => {
      if (e?.name === 'AbortError') return;
      waveState = 'error';
      waveLabel.textContent = `Волна недоступна: ${e?.message || 'ошибка разбора аудио'}`;
      render();
    });
  }

  let resizeTimer = 0;
  const ro = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 100);
  });
  ro.observe(scroll);

  dlg.addEventListener('editor-close', () => {
    stopPlay();
    audio.removeAttribute('src');
    audio.load();
    waveAbort.abort();
    ro.disconnect();
    clearTimeout(resizeTimer);
    cancelAnimationFrame(scrollRaf);
    clearTimeout(toastTimer);
  });

  // контекст для расширений (таск 04)
  const ctx = {
    song, shell, dlg, M,
    els: { bar, slotPlay, slotTools, slotEnd, centerTop, panel, hint, main, scroll, inner, roll, lane, brkLayer },
    get state() { return state; },
    get selection() { return new Set(sel); },
    get lastSel() { return lastSel; },
    get posMs() { return posMs; },
    get playing() { return playing; },
    /** Причина, по которой нельзя играть (нет звука, нет #BPM), иначе ''. */
    playReason,
    editable, apply, select, revealNote, editChip, render, renderSel, toast, play, stopPlay, seekMs, playLine,
    msOf, beatOf, bx, xBeat, py,
    /**
     * Ноты партии ноты id (у соло — все); подпись певца v: «Певец 2 (имя)»;
     * voiceLabel(v) — подписи певца строки (1 | 2 | 'both'): {short, to, at, who} из M.VOICE_LABELS.
     */
    partNotes, singerLabel, voiceLabel,
    onRender: (f) => hooks.render.push(f),
    onSelect: (f) => hooks.select.push(f),
    onTick: (f) => hooks.tick.push(f),
    /** Клавиша по code: {code, ctrl?, shift?, alt?, fn(e)}; fn → false — не обработано. Проверяются раньше встроенных. */
    addKey: (k) => extraKeys.push(k),
  };
  for (const p of plugins) {
    try { p(ctx); } catch (e) { console.error('Расширение редактора нот:', e); }
  }

  try {
    setData(await api.notes(song.song_id));
    scroll.focus({ preventScroll: true });
    startWave();
  } catch (e) {
    main.hidden = true;
    bar.hidden = true;
    shell.message(`Не удалось открыть песню: ${errorText(e)}`, 'err');
  }
}
