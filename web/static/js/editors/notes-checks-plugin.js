// Расширение «Редактора нот»: подсветка подозрительных нот, счётчик с переходом (!) и проигрывание
// выбранной ноты её высотой («♪», P). Логика проверок — notes-checks.js, звук — tone.js.

import { h } from '../ui.js';
import { api } from '../api.js';
import { suspects, nextSuspect } from './notes-checks.js';
import { playTone, toneSupported } from '../tone.js';

const HILITE_KEY = 'notesEditor.suspectsOn';
const RECHECK_MS = 900;
const DEFAULT_TONE_MS = 600;

const loadOn = () => {
  try { return localStorage.getItem(HILITE_KEY) !== '0'; } catch { return true; }
};
const saveOn = (v) => {
  try { localStorage.setItem(HILITE_KEY, v ? '1' : '0'); } catch { /* хранилище недоступно */ }
};

export function notesChecksPlugin(ctx) {
  const { els, M } = ctx;
  let on = loadOn();
  let found = new Map();
  let unmatchedLines = [];
  let textNote = ''; // почему строки текста не проверяются
  let sig = null; // подпись нот, по которой запрошено выравнивание
  let timer = 0;
  let seq = 0;

  // ------------------------------------------------------------ звук ноты («♪», P)

  let stopTone = () => {};
  const tonBtn = h('button', { type: 'button', 'aria-label': 'Сыграть выбранную ноту её высотой (P)', title: 'Сыграть выбранную ноту (P)' }, '♪');
  els.slotPlay.append(tonBtn);

  const target = () => {
    const id = ctx.lastSel;
    return id == null ? null : ctx.state?.notes.find((x) => x.id === id) || null;
  };
  function playNote() {
    if (!toneSupported()) { ctx.toast('Браузер не умеет синтезировать звук', 'err'); return true; }
    const x = target();
    if (!x) { ctx.toast('Выбери ноту — она сыграет своей высотой', 'err'); return true; }
    ctx.stopPlay();
    stopTone();
    const ms = Number(ctx.state.bpm) > 0 ? (x.length * 60000) / (Number(ctx.state.bpm) * 4) : DEFAULT_TONE_MS;
    stopTone = playTone(x.pitch, ms);
    return true;
  }
  tonBtn.addEventListener('click', () => { playNote(); els.scroll.focus({ preventScroll: true }); });
  ctx.addKey({ code: 'KeyP', ctrl: false, shift: false, fn: playNote });
  const updateTone = () => {
    const x = target();
    tonBtn.disabled = !x;
    tonBtn.title = x ? 'Сыграть выбранную ноту (P)' : 'Выбери ноту, чтобы сыграть её высотой (P)';
  };
  ctx.onSelect(updateTone);

  // ------------------------------------------------------------ счётчик и подсветка

  const counter = h('button', { type: 'button', class: 'ne-sus' });
  const toggle = h('input', { type: 'checkbox' });
  toggle.checked = on;
  const toggleLabel = h('label', { class: 'check ne-sus-toggle', title: 'Подсвечивать подозрительные ноты' }, toggle, ' подсветка');
  const note = h('span', { class: 'small muted ne-sus-note', hidden: true });
  els.slotTools.append(counter, toggleLabel, note);

  function gotoNext() {
    const id = nextSuspect(ctx.state, found, ctx.lastSel);
    if (id == null) { ctx.toast('Подозрительных мест нет'); return true; }
    ctx.select([id], { reveal: true });
    const reasons = found.get(id) || [];
    ctx.toast(reasons.join('; '));
    return true;
  }
  counter.addEventListener('click', () => { gotoNext(); els.scroll.focus({ preventScroll: true }); });
  toggle.addEventListener('change', () => { on = toggle.checked; saveOn(on); paint(); });
  ctx.addKey({ code: 'Digit1', shift: true, ctrl: false, fn: () => gotoNext() });

  function paint() {
    for (const el of els.lane.querySelectorAll('.ne-note')) {
      const reasons = found.get(Number(el.dataset.id));
      if (el.dataset.baseTitle === undefined) el.dataset.baseTitle = el.title;
      el.classList.toggle('suspect', on && !!reasons);
      el.title = reasons && on ? `${el.dataset.baseTitle}\n⚠ ${reasons.join('\n⚠ ')}` : el.dataset.baseTitle;
    }
    counter.textContent = `Подозрительных: ${found.size} ▸`;
    counter.classList.toggle('has', found.size > 0);
    counter.disabled = !found.size;
    counter.title = found.size ? 'К следующей подозрительной ноте (!)' : 'Подозрительных мест нет';
    note.hidden = !textNote;
    note.textContent = textNote;
  }

  function recompute() {
    found = suspects(ctx.state, { unmatchedLines });
    paint();
  }

  // ------------------------------------------------------------ сверка строк с исходным текстом

  async function checkLines() {
    const st = ctx.state;
    if (!st) return;
    if (st.duet) { textNote = 'У дуэта строки с текстом не сверяются'; unmatchedLines = []; sig = null; return; }
    const req = M.lineStartsRequest(st);
    const now = JSON.stringify(req);
    if (now === sig) return;
    sig = now;
    const mine = ++seq;
    try {
      const res = await api.alignLines(ctx.song.song_id, req.texts, req.starts);
      if (mine !== seq) return;
      unmatchedLines = Array.isArray(res?.unmatched_lines) ? res.unmatched_lines : [];
      textNote = '';
    } catch (e) {
      if (mine !== seq) return;
      unmatchedLines = [];
      textNote = e?.status === 409 ? 'Нет исходного текста — строки с ним не сверяются' : 'Строки с текстом не сверены';
    }
    recompute();
  }

  ctx.onRender(() => {
    recompute();
    updateTone();
    if (ctx.state?.duet) { textNote = 'У дуэта строки с текстом не сверяются'; unmatchedLines = []; paint(); return; }
    clearTimeout(timer);
    timer = setTimeout(() => { if (ctx.dlg.isConnected) checkLines(); }, RECHECK_MS);
  });
}
