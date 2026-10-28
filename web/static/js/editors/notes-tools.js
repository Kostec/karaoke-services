// Инструменты редактора нот (таск 04; спека: истории 16, 24–26, 32; решение §10):
// «⇠ текст / текст ⇢» с областью сдвига и перетаскиванием слога (G03), «Разрезать», «Слить», «↵ Строка»,
// склейка строк кликом по ↵,
// «Строки как в тексте» (строки по исходному тексту песни, сервер сопоставляет слоги),
// режим «Отстукивание» (T, держать J или «Держать») и справка по всем сочетаниям (? и кнопка).

import { h, confirmDialog } from '../ui.js';
import { api, errorText } from '../api.js';
import { tapTiming, tapQueue, plural } from './notes-panel-logic.js';

const SCOPE_KEY = 'notesEditor.shiftScope';
// [область, подпись в списке, «текст …» в подсказках]
const SCOPES = [['word', 'в слове', 'слова'], ['line', 'в строке', 'строки'], ['song', 'до конца песни', 'до конца песни']];
const DRAG_PX = 6; // столько пикселей слог нужно протащить, чтобы клик стал перетаскиванием

function loadScope() {
  try {
    const v = localStorage.getItem(SCOPE_KEY);
    if (SCOPES.some(([k]) => k === v)) return v;
  } catch { /* хранилище недоступно */ }
  return 'line';
}

function saveScope(v) {
  try { localStorage.setItem(SCOPE_KEY, v); } catch { /* хранилище недоступно */ }
}

/** «1 ноту», «2 ноты», «5 нот». */
const notesWord = (n) => `${n} ${plural(n, ['ноту', 'ноты', 'нот'])}`;
const NOTHING_TO_SHIFT = 'Сдвигать нечего — текст не изменится';

const btn = (label, title, attrs = {}) => h('button', { type: 'button', title, 'aria-label': title, ...attrs }, label);

const HELP = [
  [['Пробел', '⏯'], 'играть / пауза (⏯ — медиаклавиша пульта)'],
  [['M'], '«Мелодия нот»: при воспроизведении ноты звучат синтезатором (с учётом скорости)'],
  [['V'], '«Вокал»: выключен — играет минусовка с той же секунды'],
  [['Клик по клавише слева'], '«пианино»: нота этой высоты звучит, пока держишь (до 2 с); провести с зажатой кнопкой — каждая'],
  [['L'], 'проиграть строку с выбранной нотой'],
  [['←', '→'], 'сдвинуть выбранное на 1 бит (Shift — на 4)'],
  [['↑', '↓'], 'выше / ниже на полутон'],
  [['Ctrl+←', 'Ctrl+→'], 'короче / длиннее'],
  [['Alt+←', 'Alt+→'], 'сдвинуть текст по нотам с выбранной ноты; докуда — по списку рядом с «⇠ текст»: в слове, в строке или до конца песни'],
  [['Перетащить слог'], 'по дорожке слогов на другую ноту — текст той же области сдвигается на столько же нот'],
  [['Tab', 'Shift+Tab'], 'к следующей / предыдущей ноте (у дуэта — в партии выбранной ноты)'],
  [['F2', 'Enter'], 'править слог выбранной ноты'],
  [['N'], 'новая нота после выбранной (того же певца)'],
  [['S'], 'разрезать ноту пополам'],
  [['Shift+J'], 'слить со следующей нотой'],
  [['G'], 'золотая нота'],
  [['Delete', 'Backspace'], 'удалить выбранное'],
  [['Ctrl+A'], 'выделить всё — затем ←/→ сдвиг всей песни, ↑/↓ тональность'],
  [['Ctrl+Z'], 'отменить'],
  [['Ctrl+Shift+Z', 'Ctrl+Y'], 'повторить'],
  [['Ctrl+S'], 'сохранить'],
  [['+', '−', 'Ctrl+колесо'], 'масштаб таймлайна'],
  [['T'], 'режим отстукивания, затем держи J на каждом слоге (у дуэта — до конца партии)'],
  [['Esc'], 'выйти из отстукивания / снять выделение / закрыть'],
  [['Строки как в тексте'], 'кнопка: расставить границы строк по исходному тексту песни (только соло); Ctrl+Z отменит'],
  [['P'], 'сыграть выбранную ноту её высотой'],
  [['!'], 'к следующей подозрительной ноте'],
  [['?'], 'эта справка'],
];

// дуэт: что делают кнопки и как работают инструменты внутри партии
// пульт Rii i8: в редакторе стрелки работают по-редакторски, навигация пульта не вмешивается
const REMOTE_HELP = [
  [['Tab', 'Shift+Tab'], 'выбрать следующую / предыдущую ноту'],
  [['←', '→'], 'сдвинуть ноту по времени'],
  [['↑', '↓'], 'выше / ниже на полутон'],
  [['Пробел', '⏯'], 'играть / пауза'],
  [['⏮', '⏭'], 'к началу предыдущей / следующей строки (медиаклавиши)'],
  [['P'], 'сыграть выбранную ноту'],
  [['Esc'], 'снять выделение, ещё раз — закрыть редактор'],
];

const DUET_HELP = [
  ['«Сделать дуэтом»', 'все строки — певцу 1; дальше строки раздаются певцу 2 или обоим'],
  ['«Певцу: 1 / 2 / оба»', 'отдать строки выбранных нот (строка переходит целиком); то же — переключатель у строки в панели «Текст»'],
  ['«Сделать соло»', 'всё — певцу 1, строки «оба» остаются одной копией'],
  // цвета — образцами легенды (токены --accent, --ne-p2, --ne-both), без названий цветов словами
  ['Цвета', () => [
    ...[['p1', 'певец 1'], ['p2', 'певец 2'], ['both', '«оба»']].flatMap(([c, who]) => [
      h('span', { class: `ne-lg ${c}` }, h('i', { 'aria-hidden': 'true' }), who), ' ']),
    '— как в легенде над нотами; слоги певца 1 — на верхней полосе, певца 2 — на нижней']],
  ['Внутри партии', 'Tab, отстукивание, сдвиг текста ⇠/⇢, перетаскивание слога, Разрезать, Слить и ↵ Строка работают в партии выбранной ноты'],
  ['Новая нота', 'получает певца выбранной ноты'],
];

export function toolsPlugin(ctx) {
  const { M, els } = ctx;

  // ---------------------------------------------------------------- перенос текста, разрезать, слить, строка

  let scope = loadScope();
  const scopeName = () => SCOPES.find(([k]) => k === scope)[2];
  const scopeSel = h('select', {
    class: 'ne-scope', 'aria-label': 'Область сдвига текста',
    title: 'Докуда сдвигать текст: кнопки «⇠ текст / текст ⇢», Alt+←/→ и перетаскивание слога',
  }, ...SCOPES.map(([k, label]) => h('option', { value: k }, label)));
  scopeSel.value = scope;
  const shiftL = btn('⇠ текст', '');
  const shiftR = btn('текст ⇢', '');
  const shiftTitles = () => {
    shiftL.setAttribute('aria-label', `Сдвинуть текст ${scopeName()} влево, начиная с выбранной ноты (Alt+←)`);
    shiftR.setAttribute('aria-label', `Сдвинуть текст ${scopeName()} вправо, начиная с выбранной ноты (Alt+→)`);
  };
  shiftTitles();
  const split = btn('Разрезать', 'Разрезать ноту пополам (S)');
  const join = btn('Слить', 'Слить со следующей нотой (Shift+J)');
  const nline = btn('↵ Строка', 'Начать новую строку с выбранной ноты');
  const tools = [shiftL, scopeSel, shiftR, split, join, nline];
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
  // сдвиг, который не меняет текст, выполненным не считается: отказ с причиной
  const shiftOp = (k) => (s, id) => {
    const out = M.shiftTextBy(s, id, k, scope);
    if (out === s) throw new Error(NOTHING_TO_SHIFT);
    return out;
  };
  // кнопка с фокусом после сдвига могла выключиться — фокус на таймлайн, чтобы работали Ctrl+Z и стрелки
  const refocus = () => {
    const a = document.activeElement;
    if (!a || a === document.body || a.disabled || !ctx.dlg.contains(a)) els.scroll.focus({ preventScroll: true });
  };
  const doShift = (k) => {
    const id = one();
    if (id == null) {
      ctx.toast(ctx.editable() ? 'Выбери одну ноту — с неё сдвинется текст' : 'Только просмотр', 'err');
      return true;
    }
    ctx.apply((s) => shiftOp(k)(s, id), `Текст ${scopeName()} сдвинут ${k > 0 ? 'вправо' : 'влево'}`);
    refocus();
    return true;
  };
  const doShiftL = () => doShift(-1);
  const doShiftR = () => doShift(1);
  const doSplit = () => run((s, id) => M.splitNote(s, id), 'Нота разрезана — вторая половина тянет гласную (~)');
  const doJoin = () => run((s, id) => M.joinNext(s, id), 'Ноты слиты');
  const doLine = () => run((s, id) => M.startLine(s, id), 'Новая строка');

  shiftL.addEventListener('click', doShiftL);
  shiftR.addEventListener('click', doShiftR);
  split.addEventListener('click', doSplit);
  join.addEventListener('click', doJoin);
  nline.addEventListener('click', doLine);
  scopeSel.addEventListener('change', () => {
    scope = scopeSel.value;
    saveScope(scope);
    shiftTitles();
    updateTools();
    els.scroll.focus({ preventScroll: true });
  });
  // в списке стрелки выбирают область, а не двигают ноты и текст
  scopeSel.addEventListener('keydown', (e) => e.stopPropagation());
  // Alt+←/→ в окне редактора никогда не уводит браузер «Назад/Вперёд»; в полях ввода и в списке — просто гасится
  ctx.dlg.addEventListener('keydown', (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey || (e.code !== 'ArrowLeft' && e.code !== 'ArrowRight')) return;
    e.preventDefault();
    if (e.target.closest?.('input, select, textarea, [contenteditable]')) e.stopPropagation();
  }, { capture: true });

  // доступность — по правилам самой модели: пробный вызов операции; отказ модели — причина в подсказке
  const TRIALS = [
    [shiftL, (s, id) => shiftOp(-1)(s, id)],
    [shiftR, (s, id) => shiftOp(1)(s, id)],
    [split, (s, id) => M.splitNote(s, id)],
    [join, (s, id) => M.joinNext(s, id)],
    [nline, (s, id) => M.startLine(s, id)],
  ];
  function updateTools() {
    const id = one();
    const why = !ctx.editable() ? 'Только просмотр' : 'Выбери одну ноту';
    scopeSel.disabled = !ctx.editable();
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

  // ---------------------------------------------------------------- строки как в тексте
  // Сервер сопоставляет слоги нот с исходным текстом песни и отдаёт индексы нот — начал строк;
  // правка — обычный шаг отмены, сохраняется общей кнопкой «Сохранить».

  const byText = btn('Строки как в тексте', 'Расставить границы строк как в исходном тексте песни');
  byText.hidden = true;
  els.slotTools.append(byText);
  let aligning = false;
  byText.addEventListener('click', async () => {
    if (aligning || !ctx.editable() || ctx.state.duet) return;
    const before = ctx.state;
    let req;
    try { req = M.lineStartsRequest(before); } catch (e) { ctx.toast(e.message, 'err'); return; }
    aligning = true;
    updateByText();
    let res;
    try {
      res = await api.alignLines(ctx.song.song_id, req.texts, req.starts);
    } catch (e) {
      const text = e?.status === 0 ? 'Нет связи с сервером — строки не расставлены, попробуй ещё раз'
        : errorText(e, 'Не удалось расставить строки по тексту');
      ctx.toast(text, 'err');
      return;
    } finally {
      aligning = false;
      updateByText();
    }
    if (ctx.state !== before) {
      ctx.toast('Ноты изменились, пока шёл запрос — нажми «Строки как в тексте» ещё раз', 'err');
      return;
    }
    const unmatched = Number(res?.unmatched) || 0;
    const total = Number(res?.total) || 0;
    const okText = unmatched > 0
      ? `Строки расставлены по тексту; ${unmatched} из ${total} строк не нашлось в нотах — там оставлены прежние границы`
      : 'Строки расставлены по тексту';
    const ok = ctx.apply((s) => M.setLineStarts(s, res?.starts), okText);
    // apply молчит, если строки и так совпадают с текстом; ошибку модели он показал сам
    if (!ok && ctx.state === before) {
      try { M.setLineStarts(before, res?.starts); ctx.toast(unmatched > 0 ? okText : 'Строки уже как в тексте'); } catch { /* показано */ }
    }
    els.scroll.focus({ preventScroll: true });
  });
  function updateByText() {
    const st = ctx.state;
    byText.hidden = !st || !ctx.editable() || !!st.duet;
    byText.disabled = aligning;
    byText.title = aligning ? 'Сопоставляю ноты с текстом…' : byText.getAttribute('aria-label');
  }
  ctx.onRender(updateByText);

  // ---------------------------------------------------------------- дуэт: сделать дуэтом / соло, отдать певцу

  const duetBtn = btn('Сделать дуэтом', 'Сделать дуэтом: все строки — певцу 1, потом раздай строки певцу 2 или обоим');
  const soloBtn = btn('Сделать соло', 'Сделать соло: всё — певцу 1, строки «оба» — одной копией');
  const voiceBtns = M.VOICES.map((v) => {
    const { short, to: word, at } = ctx.voiceLabel(v);
    const b = btn(short, `Отдать строки выбранных нот ${word}`, { class: 'ne-vbtn' });
    b.addEventListener('click', () => {
      const ids = [...ctx.selection];
      if (!ids.length) return;
      const ok = ctx.apply((s) => M.setVoice(s, ids, v), `Строки выбранных нот — ${word}`);
      if (!ok && ctx.state.duet) ctx.toast(`Строки уже у ${at}`);
    });
    return b;
  });
  const voiceGroup = h('span', { class: 'ne-vgroup', role: 'group', 'aria-label': 'Отдать строки выбранных нот певцу' },
    h('span', { class: 'small muted' }, 'Певцу:'), ...voiceBtns);
  els.slotEnd.append(duetBtn, soloBtn, voiceGroup);

  duetBtn.addEventListener('click', () => {
    if (ctx.apply((s) => M.makeDuet(s), 'Теперь это дуэт: все строки у певца 1 — раздай строки певцу 2 или обоим')) {
      els.scroll.focus({ preventScroll: true });
    }
  });
  soloBtn.addEventListener('click', async () => {
    const ok = await confirmDialog('Сделать песню соло? Все строки перейдут певцу 1, строки «оба» останутся одной копией, '
      + 'имена певцов при сохранении удалятся. Ctrl+Z вернёт дуэт.', 'Сделать соло');
    if (ok) ctx.apply((s) => M.makeSolo(s), 'Песня теперь соло');
    els.scroll.focus({ preventScroll: true });
  });

  function updateDuet() {
    const st = ctx.state;
    const ed = ctx.editable();
    duetBtn.hidden = !st || !ed || !!st.duet;
    soloBtn.hidden = !st || !ed || !st.duet;
    voiceGroup.hidden = !st || !ed || !st.duet;
    const sel = ctx.selection;
    for (const [i, b] of voiceBtns.entries()) {
      b.disabled = !sel.size;
      const v = M.VOICES[i];
      const all = !!st && M.allVoice(st, sel, v);
      b.classList.toggle('on', all);
      b.setAttribute('aria-pressed', String(all));
    }
  }
  ctx.onRender(updateDuet);
  ctx.onSelect(updateDuet);

  // ---------------------------------------------------------------- перетаскивание слога (G03, история 40)
  // Слог тащат по дорожке слогов на другую ноту: текст области сдвигается на K нот (K — разница
  // номеров нот). Пока указатель не ушёл дальше DRAG_PX — это обычный клик или двойной клик.

  const tip = h('div', { class: 'ne-dragtip', hidden: true, role: 'status' });
  ctx.dlg.append(tip);
  let drag = null; // {id, x0, pointerId, started, k, ok, target}
  let suppressClick = false;
  const chipOf = (id) => (id == null ? null : els.lane.querySelector(`.ne-chip[data-id="${id}"]`));

  /** Нота под точкой дорожки среди нот notes (партии слога): та, в которую попали, иначе ближайшая серединой. */
  function noteAtX(clientX, notes) {
    const beat = ctx.xBeat(clientX - els.lane.getBoundingClientRect().left);
    let best = null;
    let bestD = Infinity;
    for (const x of notes) {
      const d = beat >= x.start && beat < x.start + x.length ? -1 : Math.abs(x.start + x.length / 2 - beat);
      if (d < bestD) { best = x; bestD = d; }
      if (d < 0) break;
    }
    return best;
  }

  function dragMove(e) {
    // у дуэта номера нот — в партии перетаскиваемого слога (как считает сдвиг в модели)
    const notes = ctx.partNotes(drag.id);
    const target = noteAtX(e.clientX, notes);
    const from = notes.findIndex((x) => x.id === drag.id);
    const want = target ? notes.indexOf(target) - from : 0;
    // за пределы области текст не уезжает — подсказка называет фактический сдвиг из модели
    let k = want;
    let refusal = '';
    try {
      k = M.shiftAmount(ctx.state, drag.id, want, scope);
      if (k) shiftOp(k)(ctx.state, drag.id);
    } catch (err) { refusal = err.message; }
    if (drag.target !== (target?.id ?? null)) {
      chipOf(drag.target)?.classList.remove('ne-drop');
      drag.target = target?.id ?? null;
    }
    chipOf(drag.target)?.classList.toggle('ne-drop', !!k);
    drag.k = k;
    drag.dest = notes[from + k]?.id ?? null;
    drag.ok = !!k && !refusal;
    let text = 'Отпусти над другой нотой — текст сдвинется';
    if (refusal) text = refusal;
    else if (k) text = `${k > 0 ? 'текст ⇢' : '⇠ текст'} на ${notesWord(Math.abs(k))} (${scopeName()})`;
    tip.textContent = text;
    tip.classList.toggle('err', !!k && !drag.ok);
    tip.style.left = `${e.clientX + 12}px`;
    tip.style.top = `${e.clientY - 36}px`;
    tip.hidden = false;
  }

  function dragEnd(cancel) {
    if (!drag) return;
    const d = drag;
    drag = null;
    tip.hidden = true;
    chipOf(d.target)?.classList.remove('ne-drop');
    chipOf(d.id)?.classList.remove('ne-dragging');
    els.lane.classList.remove('dragging');
    if (!d.started) return;
    // браузер следом пришлёт click — он не должен менять выделение
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
    if (cancel || !d.k) return;
    if (!d.ok) { ctx.toast(tip.textContent, 'err'); return; }
    const ok = ctx.apply((s) => shiftOp(d.k)(s, d.id),
      `Текст ${scopeName()} сдвинут ${d.k > 0 ? 'вправо' : 'влево'} на ${notesWord(Math.abs(d.k))}`);
    if (ok && d.dest != null) ctx.select([d.dest]);
    refocus();
  }

  els.lane.addEventListener('pointerdown', (e) => {
    const c = e.target.closest('.ne-chip');
    if (!c || c.classList.contains('editing') || e.button !== 0 || e.shiftKey || !ctx.editable()) return;
    drag = { id: Number(c.dataset.id), x0: e.clientX, pointerId: e.pointerId, started: false, k: 0, ok: false, target: null, dest: null };
  });
  els.lane.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    // кнопку отпустили где-то вне дорожки — перетаскивание не зависает
    if (e.buttons === 0) { dragEnd(true); return; }
    if (!drag.started) {
      if (Math.abs(e.clientX - drag.x0) < DRAG_PX) return;
      drag.started = true;
      try { els.lane.setPointerCapture(e.pointerId); } catch { /* указатель уже отпущен */ }
      chipOf(drag.id)?.classList.add('ne-dragging');
      els.lane.classList.add('dragging');
    }
    e.preventDefault();
    dragMove(e);
  });
  els.lane.addEventListener('pointerup', () => dragEnd(false));
  els.lane.addEventListener('pointercancel', () => dragEnd(true));
  els.lane.addEventListener('lostpointercapture', () => { if (drag?.started) dragEnd(true); });
  els.lane.addEventListener('click', (e) => {
    if (!suppressClick) return;
    suppressClick = false;
    e.stopPropagation();
  }, { capture: true });
  ctx.addKey({ code: 'Escape', fn: () => { if (!drag?.started) return false; dragEnd(true); return true; } });
  ctx.dlg.addEventListener('editor-close', () => { drag = null; tip.hidden = true; });

  // склейка строк кликом по ↵ на границе
  els.brkLayer.addEventListener('click', (e) => {
    const b = e.target.closest('.ne-brk b');
    if (!b || !ctx.editable()) return;
    // склейка — в партии полосы, на которой стоит ↵ (у строки «оба» значок есть на обеих полосах)
    ctx.apply((s) => M.mergeLineAt(s, Number(b.dataset.id), Number(b.dataset.voice) || null), 'Строки склеены');
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
  const keyTable = (list) => {
    const t = h('table', { class: 'ne-help-table' });
    for (const [keys, what] of list) {
      const k = h('td', {});
      keys.forEach((key, i) => {
        if (i) k.append(' ');
        k.append(h('kbd', {}, key));
      });
      t.append(h('tr', {}, k, h('td', {}, what)));
    }
    return t;
  };
  const table = keyTable(HELP);
  const closeHelp = btn('Понятно', 'Закрыть справку');
  const help = h('dialog', { class: 'ne-help', 'aria-label': 'Сочетания клавиш' },
    h('h3', {}, 'Сочетания клавиш'), table,
    h('h4', {}, 'С пульта Rii i8'), keyTable(REMOTE_HELP),
    h('h4', {}, 'Дуэт'),
    h('table', { class: 'ne-help-table' }, ...DUET_HELP.map(([what, text]) => h('tr', {}, h('td', {}, h('b', {}, what)),
      h('td', {}, ...(typeof text === 'function' ? text() : [text]))))),
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
