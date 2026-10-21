// Панель «Текст» справа в редакторе нот (таск 04; спека: истории 21–23, 34; решение §6):
// строки песни как обычный текст — правка раскладывает слоги по нотам строки (модель setLineText),
// счётчик слогов/нот и «+ K нот», клик по строке — переход к её первой ноте, подсветка выбранной
// и звучащей строки, сворачивание в узкую полоску (запоминается; на телефоне — свёрнута по умолчанию).
// Дуэт (таск 03 «дуэты»): строки по группам «Певец 1» / «Певец 2» (строка «оба» — в обеих),
// у строки переключатель «1 / 2 / оба», над строками — имена певцов; звучащая строка — в каждой партии.

import { h } from '../ui.js';
import { toSyllables } from './syllables.js';
import {
  lineStatus, plural, liveLines, panelRows,
} from './notes-panel-logic.js';

const CLOSED_KEY = 'notesEditor.textPanelClosed';
const PHONE = '(max-width: 639px)';

function loadClosed() {
  try {
    const v = localStorage.getItem(CLOSED_KEY);
    if (v === '1' || v === '0') return v === '1';
  } catch { /* хранилище недоступно */ }
  try { return window.matchMedia(PHONE).matches; } catch { return false; }
}

function saveClosed(v) {
  try { localStorage.setItem(CLOSED_KEY, v ? '1' : '0'); } catch { /* хранилище недоступно */ }
}

const sylCount = (text) => toSyllables(String(text).replace(/~/g, '')).length;
/** Отпечаток строки: ноты и их слоги — набранный текст помнится, пока строка не изменилась иначе. */
const sigOf = (line) => line.map((x) => `${x.id}:${x.text}`).join('\u0001');
const voiceOfLine = (line) => line?.[0]?.voice ?? 1;

export function textPanelPlugin(ctx) {
  const { M, els } = ctx;
  const panel = els.panel;
  let closed = loadClosed();
  let lines = [];
  let rows = []; // строки в порядке на экране: {key, li, g, item, num, inp, st, vbtns}
  const byKey = new Map(); // `${группа}:${li}` → строка панели (у дуэта строка «оба» — в обеих группах)
  let orderKey = '';
  let liveLis = new Set();
  let editLi = -1; // строка, которую сейчас правят в поле
  let editBase = null; // состояние до правки строки (первая буква — шаг отмены, дальше — дописываем)
  const TYPE_DELAY = 250;
  let typeTimer = 0;
  let blurTimer = 0;
  let pending = null; // строка, набор в которой ещё не применён
  let gone = false; // окно закрыто — отложенное не выполнять
  ctx.dlg.addEventListener('editor-close', () => {
    gone = true;
    pending = null;
    clearTimeout(typeTimer);
    clearTimeout(blurTimer);
  });
  const typed = new Map(); // li → {text, sig}: набранное в поле (с «|»), пока строка та же

  const toggle = h('button', { type: 'button', class: 'icon ne-ptoggle' });
  const vlabel = h('button', { type: 'button', class: 'ne-vlabel', title: 'Развернуть текст песни' }, 'Текст песни');
  const list = h('ol', { class: 'ne-plist', 'aria-label': 'Строки песни' });
  const groupHead = [1, 2].map(() => h('li', { class: 'ne-pgroup' }));
  // имена певцов дуэта: пусто — подсказка «Певец 1/2», при сохранении пустое имя удаляет заголовок
  const nameInp = [1, 2].map((v) => h('input', {
    type: 'text', spellcheck: 'false', autocomplete: 'off', placeholder: `Певец ${v}`,
    'aria-label': `Имя певца ${v}`, title: `Имя певца ${v} (#P${v}); пусто — без имени`,
  }));
  const names = h('div', { class: 'ne-singers', hidden: true },
    h('label', {}, h('span', { class: 'ne-lg p1' }, h('i', {})), nameInp[0]),
    h('label', {}, h('span', { class: 'ne-lg p2' }, h('i', {})), nameInp[1]));
  const foot = h('div', { class: 'ne-pfoot' },
    'Правь строку как обычный текст — слоги сами разложатся по нотам строки. Принудительный перенос слога — ',
    h('kbd', {}, '|'), '. Клик по строке — переход к её первой ноте.');
  panel.append(h('div', { class: 'ne-ph' }, h('h4', {}, 'Текст'), toggle, vlabel), names, list, foot);
  panel.hidden = false;

  for (const inp of nameInp) {
    inp.addEventListener('change', () => {
      const st = ctx.state;
      if (!st?.duet) return;
      if (nameInp[0].value.trim() === (st.singers?.p1 ?? '') && nameInp[1].value.trim() === (st.singers?.p2 ?? '')) return;
      ctx.apply((s) => M.setSingers(s, nameInp[0].value, nameInp[1].value), 'Имена певцов изменены');
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); els.scroll.focus({ preventScroll: true }); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); refreshNames(true); inp.blur(); }
    });
  }

  function setClosed(v, remember = true) {
    closed = v;
    panel.classList.toggle('closed', v);
    toggle.textContent = v ? '⟨' : '⟩';
    toggle.title = v ? 'Развернуть текст песни' : 'Свернуть текст песни';
    toggle.setAttribute('aria-label', toggle.title);
    toggle.setAttribute('aria-expanded', String(!v));
    if (remember) saveClosed(v);
    if (!v) markLive(true);
  }
  toggle.addEventListener('click', () => setClosed(!closed));
  vlabel.addEventListener('click', () => { setClosed(false); toggle.focus(); });
  setClosed(closed, false);

  // ---------------------------------------------------------------- строки

  function goLine(li) {
    const line = lines[li];
    if (!line) return;
    const first = line[0];
    ctx.select([first.id], { reveal: true });
    ctx.seekMs(ctx.msOf(first.start) - 300, true);
  }

  function setVoice(row, v) {
    const line = lines[row.li];
    if (!line) return;
    flush();
    if (voiceOfLine(line) === v) return;
    ctx.apply((s) => M.setVoice(s, line.map((x) => x.id), v), `Строка — ${ctx.voiceLabel(v).to}`);
  }

  function makeRow(key, li, g) {
    const num = h('span', { class: 'n', title: 'Перейти к строке' });
    const inp = h('input', { type: 'text', spellcheck: 'false', autocomplete: 'off' });
    const st = h('div', { class: 'st', 'aria-live': 'polite' });
    const row = { key, li, g, item: null, num, inp, st, vbtns: [] };
    row.vbtns = M.VOICES.map((v) => {
      const { short, to } = ctx.voiceLabel(v);
      const b = h('button', { type: 'button', title: `Отдать строку ${to}`, 'aria-pressed': 'false' }, short);
      b.addEventListener('mousedown', (e) => e.preventDefault()); // фокус не уходит из поля строки
      b.addEventListener('click', () => setVoice(row, v));
      return b;
    });
    const vsw = h('span', { class: 'ne-pv', role: 'group', 'aria-label': 'Певец строки' }, ...row.vbtns);
    row.item = h('li', { class: 'pl' }, num, inp, vsw, st);
    row.item.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      goLine(row.li);
    });
    inp.addEventListener('focus', () => {
      editLi = row.li;
      editBase = null;
      goLine(row.li);
    });
    inp.addEventListener('input', () => {
      // таймлайн перерисовывается не на каждое нажатие, а через паузу в наборе (и сразу на Enter/уходе из поля)
      clearTimeout(typeTimer);
      pending = row;
      typeTimer = setTimeout(flush, TYPE_DELAY);
      paintStatus(row);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        flush();
        (rows[rows.indexOf(row) + 1]?.inp || inp).focus();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        inp.blur();
        els.scroll.focus({ preventScroll: true });
      }
    });
    inp.addEventListener('blur', () => {
      flush();
      editLi = -1;
      editBase = null;
      if (!gone) blurTimer = setTimeout(refresh, 0);
    });
    return row;
  }

  function flush() {
    clearTimeout(typeTimer);
    const row = pending;
    pending = null;
    if (row && !gone) typeLine(row);
  }

  function typeLine(row) {
    const text = row.inp.value;
    const amend = editBase !== null && ctx.state === editBase;
    const ok = ctx.apply((s) => M.setLineText(s, row.li, text), '', { amend });
    if (ok) editBase = ctx.state;
    const line = lines[row.li];
    if (line) typed.set(row.li, { text, sig: sigOf(line) });
    paintStatus(row);
  }

  function addNotes(row, k) {
    clearTimeout(typeTimer); // набранный текст войдёт в тот же шаг, что и новые ноты
    pending = null;
    const text = row.inp.value;
    const ok = ctx.apply((s) => {
      const a = M.addNotesToLine(s, row.li, k);
      return { ...M.setLineText(a, row.li, text), created: a.created };
    }, `Добавлено: ${k} ${plural(k, ['нота', 'ноты', 'нот'])} в конец строки`);
    if (!ok) return;
    editBase = null;
    const line = lines[row.li];
    if (line) typed.set(row.li, { text, sig: sigOf(line) });
    paintStatus(row);
  }

  /** Текст поля: набранный (пока строка та же) или собранный из слогов нот. */
  function lineValue(li) {
    const t = typed.get(li);
    if (t && lines[li] && t.sig === sigOf(lines[li])) return t.text;
    typed.delete(li);
    return M.lineText(lines[li]);
  }

  function paintStatus(row) {
    const line = lines[row.li];
    if (!line) return;
    const { st } = row;
    st.textContent = '';
    // сравнение слогов с нотами — только для строк, набранных в панели: у исходного текста песни
    // деление по гласным может не совпасть с нотами, и это не ошибка
    const own = typed.has(row.li) || editLi === row.li;
    const s = own ? lineStatus(sylCount(row.inp.value), line.length) : lineStatus(line.length, line.length);
    st.className = `st ${s.kind}`;
    st.append(s.text);
    if (s.add && ctx.editable()) {
      const b = h('button', { type: 'button', title: 'Добавить недостающие ноты в конец строки (по 3 бита, высота последней ноты)' }, s.addText);
      b.addEventListener('mousedown', (e) => e.preventDefault()); // фокус остаётся в поле строки
      b.addEventListener('click', () => addNotes(row, s.add));
      st.append(b);
    }
  }

  function markCur() {
    const sel = ctx.selection;
    for (const r of rows) r.item.classList.toggle('cur', !!lines[r.li]?.some((x) => sel.has(x.id)));
  }

  /**
   * Подсветка звучащих строк (у дуэта — по строке каждой партии). repaint — перерисовать и прокрутить
   * к звучащей строке, даже если звучат те же строки (список перестроен, панель развёрнута).
   */
  function markLive(repaint = false) {
    const st = ctx.state;
    const now = st && ctx.playing ? liveLines(st, lines, ctx.beatOf(ctx.posMs)) : new Set();
    if (!repaint && now.size === liveLis.size && [...now].every((li) => liveLis.has(li))) return;
    const fresh = [...now].filter((li) => !liveLis.has(li));
    liveLis = now;
    let scrolled = false;
    for (const r of rows) {
      const on = now.has(r.li);
      r.item.classList.toggle('live', on);
      // прокрутка — к первой новой звучащей строке (у дуэта их может быть две)
      if (on && !scrolled && (repaint || fresh.includes(r.li)) && !closed && editLi < 0) {
        r.item.scrollIntoView({ block: 'nearest' });
        scrolled = true;
      }
    }
  }

  function refreshNames(force = false) {
    const st = ctx.state;
    names.hidden = !st?.duet;
    if (!st?.duet) return;
    const ro = !ctx.editable();
    ['p1', 'p2'].forEach((k, i) => {
      nameInp[i].readOnly = ro;
      if (force || document.activeElement !== nameInp[i]) nameInp[i].value = st.singers?.[k] ?? '';
    });
  }

  function refresh() {
    const st = ctx.state;
    if (!st || gone) return;
    lines = M.lines(st);
    refreshNames();
    // порядок на экране и номера строк внутри партии — panelRows (как в ошибках «Певец 2, строка 3»)
    const want = panelRows(st, lines);
    const keys = new Set(want.map((w) => w.key));
    for (const [k, r] of byKey) {
      if (!keys.has(k)) { r.item.remove(); byKey.delete(k); }
    }
    rows = want.map((w) => {
      let r = byKey.get(w.key);
      if (!r) { r = makeRow(w.key, w.li, w.g); byKey.set(w.key, r); }
      return r;
    });
    // переставлять узлы — только когда порядок изменился (перенос узла снимает фокус с поля)
    const key = `${st.duet ? 1 : 0}|${want.map((w) => w.key).join(',')}`;
    if (key !== orderKey) {
      orderKey = key;
      const nodes = [];
      for (const g of st.duet ? M.parts(st) : [0]) {
        if (g) nodes.push(groupHead[g - 1]);
        nodes.push(...rows.filter((r) => r.g === g).map((r) => r.item));
      }
      list.replaceChildren(...nodes);
    }
    for (const [i, gh] of groupHead.entries()) gh.textContent = ctx.singerLabel(i + 1);
    for (const t of [...typed.keys()]) if (t >= lines.length) typed.delete(t);
    const ro = !ctx.editable();
    for (const [i, r] of rows.entries()) {
      const { num } = want[i];
      r.num.textContent = String(num);
      const v = voiceOfLine(lines[r.li]);
      const label = st.duet ? `${ctx.singerLabel(r.g)}, строка ${num}` : `Строка ${num}`;
      r.inp.setAttribute('aria-label', label);
      r.item.dataset.voice = st.duet ? String(v) : '';
      r.item.classList.toggle('duet', !!st.duet);
      for (const [i, b] of r.vbtns.entries()) {
        const on = M.VOICES[i] === v;
        b.classList.toggle('on', on);
        b.setAttribute('aria-pressed', String(on));
        b.disabled = ro;
      }
      r.inp.readOnly = ro;
      r.inp.title = ro ? 'Только просмотр' : 'Правь строку как текст: слоги разложатся по нотам, | — граница слога';
      if (r.li !== editLi || document.activeElement !== r.inp) r.inp.value = lineValue(r.li);
      paintStatus(r);
    }
    markCur();
    markLive(true); // строки перестроены — подсветку звучащих наложить заново
  }

  ctx.onRender(refresh);
  ctx.onSelect(markCur);
  ctx.onTick(() => markLive());
}
