// Пульт Rii i8 (обычная HID-клавиатура): глобальная навигация стрелками, горячие клавиши,
// подсказка «Клавиши пульта», рамка фокуса (body.kbd) и обработчики Media Session.
//
// Слушатель keydown — на window (всплытие): экран, обработавший клавишу сам, зовёт
// preventDefault, и пульт её пропускает. Не вмешивается в редактор нот (dialog.editor)
// и открытое меню «…» (menu.js).

import { h, openModal, toast } from './ui.js';
import { pickNeighbor, keyCommand, GLOBAL_KEYS, TAB_VIEWS } from './remote-logic.js';

const HINT_KEY = 'remote.hinted';
const HINT_TEXT = 'Пульт: ? — подсказка по клавишам';
const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), '
  + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';
const TEXT_TYPES = new Set(['', 'text', 'search', 'email', 'url', 'tel', 'password', 'number',
  'date', 'time', 'datetime-local', 'month', 'week']);
// Куда «назад», если внутри сервиса ещё не переходили (страницу открыли по ссылке).
const BACK_TO = { song: '#songs', check: '#songs', new: '#queue' };
const MEDIA_ACTIONS = ['play', 'pause', 'previoustrack', 'nexttrack'];

let views = TAB_VIEWS;
let started = false;
const trail = []; // адреса, пройденные внутри сервиса, — есть ли куда history.back()
const screenKeys = new Map();
let helpDlg = null;

function storeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function storeSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* приватное окно — без памяти */ }
}

/** Клавиши экрана для подсказки: [[клавиши], описание]; пусто — только общие. */
export function setScreenKeys(view, list) {
  if (list && list.length) screenKeys.set(view, list);
  else screenKeys.delete(view);
}

/** Обработчики медиаклавиш через Media Session ({play, pause, previoustrack, nexttrack}) или null — снять. */
export function setMediaHandlers(handlers) {
  const ms = typeof navigator !== 'undefined' ? navigator.mediaSession : null;
  if (!ms || typeof ms.setActionHandler !== 'function') return;
  for (const action of MEDIA_ACTIONS) {
    try { ms.setActionHandler(action, handlers?.[action] || null); } catch { /* действие не поддержано */ }
  }
}

function currentView() {
  return document.querySelector('main > section[data-view]:not([hidden])')?.dataset.view || '';
}

function keyRows(list) {
  return list.map(([keys, text]) => h('tr', {},
    h('td', { class: 'remote-keys' }, ...keys.flatMap((k, i) => (i ? [' ', h('kbd', {}, k)] : [h('kbd', {}, k)]))),
    h('td', {}, text)));
}

/** Диалог «Клавиши пульта»: общие + клавиши текущего экрана. */
export function openRemoteHelp() {
  if (helpDlg?.open) { helpDlg.close(); return; }
  const own = screenKeys.get(currentView()) || [];
  const close = h('button', { type: 'button', class: 'primary', autofocus: '' }, 'Закрыть');
  const dlg = openModal({ class: 'remote-help-dlg', 'aria-label': 'Клавиши пульта' },
    h('h3', {}, 'Клавиши пульта'),
    h('h4', {}, 'Общие'),
    h('table', { class: 'remote-table' }, h('tbody', {}, ...keyRows(GLOBAL_KEYS))),
    h('h4', {}, 'Этот экран'),
    own.length
      ? h('table', { class: 'remote-table' }, h('tbody', {}, ...keyRows(own)))
      : h('p', { class: 'muted small' }, 'Своих клавиш у экрана нет.'),
    h('div', { class: 'actions' }, close));
  close.addEventListener('click', () => dlg.close());
  dlg.addEventListener('keydown', (e) => {
    if (e.key === '?' || e.key === 'F1') { e.preventDefault(); dlg.close(); }
  });
  dlg.addEventListener('close', () => { if (helpDlg === dlg) helpDlg = null; });
  helpDlg = dlg;
  close.focus();
}

function visible(el) {
  if (el.tabIndex < 0 || el.getClientRects().length === 0) return false;
  if (el.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  const st = getComputedStyle(el);
  return st.visibility !== 'hidden';
}

function candidatesIn(roots) {
  const out = new Set();
  for (const root of roots) {
    if (!root) continue;
    const list = root.matches?.(FOCUSABLE) ? [root] : [];
    list.push(...root.querySelectorAll(FOCUSABLE));
    for (const el of list) if (visible(el)) out.add(el);
  }
  return [...out];
}

/** Открытый модальный диалог (кроме редактора) — пульт ходит только внутри него. */
function openDialog() {
  const all = [...document.querySelectorAll('dialog[open]')].filter((d) => !d.classList.contains('editor'));
  for (let i = all.length - 1; i >= 0; i--) {
    let modal = true;
    try { modal = all[i].matches(':modal'); } catch { /* старый браузер — считаем модальным */ }
    if (modal) return all[i];
  }
  return null;
}

function fieldState(el) {
  const tag = el?.tagName;
  const editable = !!el?.isContentEditable;
  const isInput = tag === 'INPUT';
  const type = isInput ? (el.getAttribute('type') || '').toLowerCase() : '';
  return {
    inText: isInput && TEXT_TYPES.has(type),
    inMultiline: tag === 'TEXTAREA' || editable,
    // range, как и список, сам меняет значение стрелками
    inSelect: tag === 'SELECT' || (isInput && type === 'range'),
  };
}

function move(dir, dlg) {
  const active = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
  const section = document.querySelector('main > section[data-view]:not([hidden])');
  const screenRoots = [section, document.querySelector('nav.tabs'), document.getElementById('fab-new'),
    ...document.querySelectorAll('header .remote-help')];
  const roots = dlg ? [dlg] : screenRoots;
  const inScope = active && roots.some((r) => r?.contains(active));
  let list;
  let from = null;
  if (inScope) {
    list = candidatesIn(roots).filter((el) => el !== active);
    from = active.getBoundingClientRect();
  } else {
    // без фокуса — первый элемент самого экрана, не шапка
    list = candidatesIn(dlg ? [dlg] : [section]);
    if (!list.length) list = candidatesIn(roots);
  }
  const id = pickNeighbor(from, dir, list.map((el, i) => ({ id: i, rect: el.getBoundingClientRect() })));
  if (id === null) {
    // некуда — докрутить страницу, вдруг ниже/выше ещё есть элементы
    if (!dlg && (dir === 'up' || dir === 'down')) {
      window.scrollBy({ top: (dir === 'down' ? 1 : -1) * window.innerHeight * 0.4, behavior: 'smooth' });
    }
    return;
  }
  const el = list[id];
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  if (!storeGet(HINT_KEY)) {
    storeSet(HINT_KEY, '1');
    toast(HINT_TEXT);
  }
}

function back(view) {
  if (trail.length > 1) { history.back(); return; }
  if (view === 'play') {
    const id = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
    location.hash = id ? `#song?id=${encodeURIComponent(id)}` : '#songs';
    return;
  }
  location.hash = BACK_TO[view] || '#queue';
}

function focusSearch() {
  const go = () => {
    const input = document.querySelector('#view-songs input[type="search"]');
    if (input) { input.focus(); input.select?.(); }
  };
  if (currentView() === 'songs') { go(); return; }
  location.hash = '#songs';
  setTimeout(go, 0); // после route(): секция «Песен» станет видимой
}

function onKeyDown(e) {
  if (e.key !== 'Shift' && e.key !== 'Control' && e.key !== 'Alt' && e.key !== 'Meta') {
    document.body.classList.add('kbd');
  }
  if (e.defaultPrevented || e.ctrlKey || e.altKey || e.metaKey) return;
  if (document.querySelector('dialog.editor[open]')) return; // у редактора нот свои клавиши
  if (document.querySelector('.menu[role="menu"]')) return; // меню «…» ведёт клавиши само
  const view = currentView();
  const cmd = keyCommand(e, { ...fieldState(document.activeElement), view });
  if (!cmd) return;
  const dlg = openDialog();
  if (dlg) {
    // в окне — только переходы и подсказка; Esc закрывает окно, как раньше
    if (cmd.type === 'move') { e.preventDefault(); move(cmd.dir, dlg); }
    return;
  }
  e.preventDefault();
  switch (cmd.type) {
    case 'move': move(cmd.dir, null); break;
    case 'blur': document.activeElement?.blur(); break;
    case 'back': back(view); break;
    case 'tab': if (views[cmd.index]) location.hash = `#${views[cmd.index]}`; break;
    case 'new': location.hash = '#new'; break;
    case 'search': focusSearch(); break;
    case 'help': openRemoteHelp(); break;
    default: break;
  }
}

/** Подключить пульт (один раз, из app.js). */
export function initRemote({ views: list } = {}) {
  if (started) return;
  started = true;
  if (Array.isArray(list) && list.length) views = list;
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('pointerdown', () => document.body.classList.remove('kbd'), true);
  trail.push(location.hash);
  window.addEventListener('hashchange', () => {
    // вернулись на предыдущий адрес — шаг назад, иначе новый шаг
    if (trail.length > 1 && trail[trail.length - 2] === location.hash) trail.pop();
    else trail.push(location.hash);
  });
  // кнопка «⌨» — в шапке и в панелях экранов («Прогон»): по классу, без своих обработчиков
  document.addEventListener('click', (e) => {
    if (e.target.closest?.('button.remote-help')) { e.preventDefault(); openRemoteHelp(); }
  });
}
