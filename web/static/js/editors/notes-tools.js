// Инструменты редактора нот (таск 04; спека: истории 16, 24–26, 32; решение §10):
// «⇠ текст / текст ⇢», «Разрезать», «Слить», «↵ Строка», склейка строк кликом по ↵,
// режим «Отстукивание» (T, держать J или «Держать») и справка по всем сочетаниям (? и кнопка).

import { h } from '../ui.js';
import { tapTiming, tapQueue } from './notes-panel-logic.js';

const btn = (label, title, attrs = {}) => h('button', { type: 'button', title, 'aria-label': title, ...attrs }, label);

const HELP = [
  [['Пробел'], 'играть / пауза'],
  [['L'], 'проиграть строку с выбранной нотой'],
  [['←', '→'], 'сдвинуть выбранное на 1 бит (Shift — на 4)'],
  [['↑', '↓'], 'выше / ниже на полутон'],
  [['Ctrl+←', 'Ctrl+→'], 'короче / длиннее'],
  [['Alt+←', 'Alt+→'], 'сдвинуть текст строки по нотам'],
  [['Tab', 'Shift+Tab'], 'к следующей / предыдущей ноте'],
  [['F2', 'Enter'], 'править слог выбранной ноты'],
  [['N'], 'новая нота после выбранной'],
  [['S'], 'разрезать ноту пополам'],
  [['Shift+J'], 'слить со следующей нотой'],
  [['G'], 'золотая нота'],
  [['Delete', 'Backspace'], 'удалить выбранное'],
  [['Ctrl+A'], 'выделить всё — затем ←/→ сдвиг всей песни, ↑/↓ тональность'],
  [['Ctrl+Z'], 'отменить'],
  [['Ctrl+Shift+Z', 'Ctrl+Y'], 'повторить'],
  [['Ctrl+S'], 'сохранить'],
  [['+', '−', 'Ctrl+колесо'], 'масштаб таймлайна'],
  [['T'], 'режим отстукивания, затем держи J на каждом слоге'],
  [['Esc'], 'выйти из отстукивания / снять выделение / закрыть'],
  [['?'], 'эта справка'],
];

export function toolsPlugin(ctx) {
  const { M, els } = ctx;

  // ---------------------------------------------------------------- перенос текста, разрезать, слить, строка

  const shiftL = btn('⇠ текст', 'Сдвинуть текст строки влево, начиная с выбранной ноты (Alt+←)');
  const shiftR = btn('текст ⇢', 'Сдвинуть текст строки вправо, начиная с выбранной ноты (Alt+→)');
  const split = btn('Разрезать', 'Разрезать ноту пополам (S)');
  const join = btn('Слить', 'Слить со следующей нотой (Shift+J)');
  const nline = btn('↵ Строка', 'Начать новую строку с выбранной ноты');
  const tools = [shiftL, shiftR, split, join, nline];
  els.slotTools.append(...tools);

  const one = () => {
    const s = ctx.selection;
    return s.size === 1 && ctx.editable() ? [...s][0] : null;
  };
  const run = (fn, okText) => {
    const id = one();
    if (id == null) return false;
    ctx.apply((s) => fn(s, id), okText);
    return true;
  };
  const doShiftL = () => run((s, id) => M.shiftText(s, id, -1), 'Текст сдвинут влево');
  const doShiftR = () => run((s, id) => M.shiftText(s, id, 1), 'Текст сдвинут вправо');
  const doSplit = () => run((s, id) => M.splitNote(s, id), 'Нота разрезана — вторая половина тянет гласную (~)');
  const doJoin = () => run((s, id) => M.joinNext(s, id), 'Ноты слиты');
  const doLine = () => run((s, id) => M.startLine(s, id), 'Новая строка');

  shiftL.addEventListener('click', doShiftL);
  shiftR.addEventListener('click', doShiftR);
  split.addEventListener('click', doSplit);
  join.addEventListener('click', doJoin);
  nline.addEventListener('click', doLine);

  // доступность — по правилам самой модели: пробный вызов операции; отказ модели — причина в подсказке
  const TRIALS = [
    [shiftL, (s, id) => M.shiftText(s, id, -1)],
    [shiftR, (s, id) => M.shiftText(s, id, 1)],
    [split, (s, id) => M.splitNote(s, id)],
    [join, (s, id) => M.joinNext(s, id)],
    [nline, (s, id) => M.startLine(s, id)],
  ];
  function updateTools() {
    const id = one();
    const why = !ctx.editable() ? 'Только просмотр' : 'Выбери одну ноту';
    for (const [b, op] of TRIALS) {
      let reason = id == null ? why : '';
      if (!reason) {
        try { op(ctx.state, id); } catch (e) { reason = e.message; }
      }
      b.disabled = !!reason;
      b.title = reason ? `${b.getAttribute('aria-label')} — ${reason}` : b.getAttribute('aria-label');
    }
  }
  ctx.onRender(updateTools);
  ctx.onSelect(updateTools);

  // склейка строк кликом по ↵ на границе
  els.brkLayer.addEventListener('click', (e) => {
    const b = e.target.closest('.ne-brk b');
    if (!b || !ctx.editable()) return;
    ctx.apply((s) => M.mergeLineAt(s, Number(b.dataset.id)), 'Строки склеены');
  });
  ctx.onRender(() => {
    if (!ctx.editable()) return;
    for (const b of els.brkLayer.querySelectorAll('.ne-brk b')) {
      b.title = 'Граница строки — клик склеивает строки';
      b.classList.add('click');
    }
  });

  // ---------------------------------------------------------------- отстукивание

  const tapBtn = btn('⏺ Отстукивать', 'Отстукивание: включи ▶ и держи J, пока звучит слог (T)', { 'aria-pressed': 'false' });
  els.slotPlay.append(tapBtn);
  const holdBtn = btn('Держать', 'Держи, пока звучит слог (то же, что клавиша J)', { class: 'ne-hold' });
  const tapInfo = h('span', { class: 'ne-tapinfo' });
  const banner = h('div', { class: 'ne-tapbanner', hidden: true, role: 'status' },
    h('span', {}, 'Отстукивание: включи проигрывание и держи ', h('kbd', {}, 'J'),
      ' (или кнопку «Держать»), пока звучит каждый слог — ноты встанут по твоему ритму, начиная с выбранной. Текст и высота сохраняются. ',
      h('kbd', {}, 'Esc'), ' — выйти.'),
    tapInfo, holdBtn, btn('Выйти', 'Выйти из отстукивания (Esc)', { class: 'ne-tapexit' }));
  els.centerTop.append(banner);
  banner.querySelector('.ne-tapexit').addEventListener('click', () => setTap(false));

  let tap = null; // {queue, i, down, base}

  function tapReason() {
    if (!ctx.editable()) return 'Только просмотр';
    return ctx.playReason();
  }

  function updateTap() {
    const reason = tapReason();
    tapBtn.disabled = !!reason && !tap;
    tapBtn.title = reason ? `Отстукивание недоступно: ${reason}` : 'Отстукивание: включи ▶ и держи J, пока звучит слог (T)';
    tapBtn.classList.toggle('on', !!tap);
    tapBtn.setAttribute('aria-pressed', String(!!tap));
    if (tap) {
      const id = tap.queue[tap.i];
      const x = ctx.state.notes.find((n) => n.id === id);
      tapInfo.textContent = x ? `Следующая: «${String(x.text).trim() || '∅'}» (${tap.i + 1} из ${tap.queue.length})` : '';
    }
  }
  ctx.onRender(updateTap);

  function setTap(on) {
    if (on && !tap) {
      const reason = tapReason();
      if (reason) { ctx.toast(`Отстукивание недоступно: ${reason}`, 'err'); return; }
      const st = ctx.state;
      const from = ctx.selection.has(ctx.lastSel) ? ctx.lastSel : null;
      tap = { queue: tapQueue(st.notes, from), i: 0, down: null, base: null };
      banner.hidden = false;
      ctx.select([tap.queue[0]], { reveal: true });
      ctx.toast(ctx.playing ? 'Держи J на каждом слоге' : 'Включи ▶ (Пробел) и держи J на каждом слоге');
    } else if (!on && tap) {
      tap = null;
      banner.hidden = true;
      holdBtn.classList.remove('on');
    }
    updateTap();
  }
  tapBtn.addEventListener('click', () => setTap(!tap));

  function tapDown() {
    if (!tap || tap.down !== null) return;
    if (!ctx.playing) { ctx.toast('Сначала включи ▶ (Пробел) — ноты встают по звуку'); return; }
    tap.down = ctx.posMs;
    holdBtn.classList.add('on');
  }

  function tapUp() {
    if (!tap || tap.down === null) return;
    const down = tap.down;
    tap.down = null;
    holdBtn.classList.remove('on');
    const id = tap.queue[tap.i];
    const st = ctx.state;
    const { start, length } = tapTiming(down, Math.max(ctx.posMs, down), st.gap, st.bpm);
    // вся сессия — один шаг отмены: первое нажатие открывает шаг, следующие дописывают в него
    const amend = tap.base !== null && ctx.state === tap.base;
    const ok = ctx.apply((s) => M.retime(s, id, start, length), '', { amend });
    if (ok) tap.base = ctx.state;
    tap.i += 1;
    if (tap.i >= tap.queue.length) {
      ctx.select([id]);
      setTap(false);
      ctx.toast('Все ноты до конца песни расставлены');
      return;
    }
    ctx.select([tap.queue[tap.i]]);
    updateTap();
  }

  holdBtn.addEventListener('pointerdown', (e) => { e.preventDefault(); holdBtn.setPointerCapture?.(e.pointerId); tapDown(); });
  holdBtn.addEventListener('pointerup', tapUp);
  holdBtn.addEventListener('pointercancel', tapUp);
  holdBtn.addEventListener('keydown', (e) => { if ((e.code === 'Space' || e.code === 'Enter') && !e.repeat) { e.preventDefault(); e.stopPropagation(); tapDown(); } });
  holdBtn.addEventListener('keyup', (e) => { if (e.code === 'Space' || e.code === 'Enter') { e.preventDefault(); tapUp(); } });
  ctx.dlg.addEventListener('keyup', (e) => { if (e.code === 'KeyJ') tapUp(); });

  // конец песни: звук остановился за последней нотой очереди — режим выключается сам
  ctx.onTick((ms, playing) => {
    if (!tap || playing || tap.down !== null) return;
    const lastId = tap.queue[tap.queue.length - 1];
    const x = ctx.state.notes.find((n) => n.id === lastId);
    if (x && ms >= ctx.msOf(x.start + x.length) && ms > 0) { setTap(false); ctx.toast('Песня закончилась — отстукивание выключено'); }
  });
  ctx.dlg.addEventListener('editor-close', () => { tap = null; });

  // ---------------------------------------------------------------- справка

  const helpBtn = btn('?', 'Все сочетания клавиш (?)', { class: 'icon' });
  els.slotEnd.append(helpBtn);
  const table = h('table', { class: 'ne-help-table' });
  for (const [keys, what] of HELP) {
    const k = h('td', {});
    keys.forEach((key, i) => {
      if (i) k.append(' ');
      k.append(h('kbd', {}, key));
    });
    table.append(h('tr', {}, k, h('td', {}, what)));
  }
  const closeHelp = btn('Понятно', 'Закрыть справку');
  const help = h('dialog', { class: 'ne-help', 'aria-label': 'Сочетания клавиш' },
    h('h3', {}, 'Сочетания клавиш'), table,
    h('p', { class: 'small muted' }, 'Клавиши работают и в русской раскладке. Пока курсор в поле ввода, сочетания редактора не срабатывают.'),
    h('p', {}, closeHelp));
  ctx.dlg.append(help);
  // Esc и прочие клавиши справки не доходят до редактора (иначе Esc снял бы выделение вместо закрытия)
  help.addEventListener('keydown', (e) => e.stopPropagation());
  help.addEventListener('keyup', (e) => e.stopPropagation());
  help.addEventListener('click', (e) => { if (e.target === help) help.close(); });
  closeHelp.addEventListener('click', () => help.close());
  // Esc закрывает только справку: если браузер сгруппировал оба окна (открыто без жеста пользователя),
  // отмену окна редактора сразу после справки гасим
  let helpEsc = false; // справку закрывает текущее нажатие Esc
  ctx.dlg.addEventListener('keydown', () => { helpEsc = false; }, { capture: true });
  help.addEventListener('cancel', () => { helpEsc = true; });
  help.addEventListener('close', () => ctx.els.scroll.focus({ preventScroll: true }));
  ctx.dlg.addEventListener('cancel', (e) => {
    if (e.target !== ctx.dlg || (!help.open && !helpEsc)) return;
    helpEsc = false;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, { capture: true });
  const openHelp = () => { if (!help.open) help.showModal(); };
  helpBtn.addEventListener('click', openHelp);
  els.hint.append(h('span', {}, h('kbd', {}, '?'), ' — все сочетания клавиш'));

  // ---------------------------------------------------------------- клавиши

  ctx.addKey({ code: 'Escape', fn: () => { if (!tap) return false; setTap(false); return true; } });
  ctx.addKey({ code: 'KeyJ', ctrl: false, shift: false, fn: (e) => { if (!tap) return false; if (!e.repeat) tapDown(); return true; } });
  ctx.addKey({ code: 'KeyT', ctrl: false, shift: false, fn: () => { if (!tap && tapReason()) { ctx.toast(`Отстукивание недоступно: ${tapReason()}`, 'err'); return true; } setTap(!tap); return true; } });
  // «?» в любой раскладке (в русской это Shift+7) — по символу, а не по коду клавиши
  ctx.dlg.addEventListener('keydown', (e) => {
    if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey || help.open) return;
    if (e.target.closest?.('input, select, textarea, [contenteditable]')) return;
    e.preventDefault();
    openHelp();
  });
  ctx.addKey({ code: 'ArrowLeft', alt: true, ctrl: false, fn: doShiftL });
  ctx.addKey({ code: 'ArrowRight', alt: true, ctrl: false, fn: doShiftR });
  ctx.addKey({ code: 'KeyS', ctrl: false, shift: false, fn: doSplit });
  ctx.addKey({ code: 'KeyJ', ctrl: false, shift: true, fn: doJoin });
}
