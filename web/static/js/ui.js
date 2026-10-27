// Мелкие помощники интерфейса: создание элементов, подтверждение, уведомления, форматы.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on')) {
      if (typeof v === 'function') el.addEventListener(k.slice(2), v); // строковые обработчики не ставим
    }
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Поле формы с подписью и необязательной подсказкой в скобках. */
export function field(label, input, hint) {
  return h('label', { class: 'field' },
    h('span', {}, label, hint ? h('span', { class: 'hint' }, ` (${hint})`) : null), input);
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

/** Подсказка у погашенных действий с файлами песни, когда хранилище недоступно. */
export const STORAGE_OFF = 'Хранилище недоступно — действия с файлами отключены';

/** Модальное окно: <dialog attrs>…body</dialog> в body, показано; при закрытии удаляется. */
export function openModal(attrs, ...body) {
  const el = h('dialog', attrs, ...body);
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');
  return el;
}

/** Окно подтверждения; resolve(true) при «Да». */
export function confirmDialog(text, okLabel = 'Да', { danger = false } = {}) {
  const dlg = document.getElementById('confirm');
  document.getElementById('confirm-text').textContent = text;
  const ok = document.getElementById('confirm-ok');
  ok.textContent = okLabel;
  ok.className = danger ? 'danger' : 'primary';
  if (typeof dlg.showModal !== 'function') return Promise.resolve(window.confirm(text));
  return new Promise((resolve) => {
    dlg.returnValue = 'cancel';
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
    dlg.showModal();
  });
}

export function toast(text, kind = '') {
  const box = document.getElementById('toasts');
  const t = h('div', { class: `toast ${kind}`, role: kind === 'err' ? 'alert' : 'status' }, text);
  box.append(t);
  setTimeout(() => t.remove(), kind === 'err' ? 7000 : 3500);
}

/** Выполнить действие кнопки: блокировка до ответа, ошибка — уведомлением с текстом detail. */
export async function runAction(button, fn, okText) {
  if (button) button.disabled = true;
  try {
    const res = await fn();
    if (okText) toast(okText);
    return res;
  } catch (e) {
    toast(e.detail || e.message || 'Ошибка', 'err');
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

export function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function fmtDuration(fromIso, toIso) {
  if (!fromIso) return '';
  const a = new Date(fromIso).getTime();
  const b = toIso ? new Date(toIso).getTime() : Date.now();
  if (Number.isNaN(a) || Number.isNaN(b)) return '';
  let s = Math.max(0, Math.round((b - a) / 1000));
  const hh = Math.floor(s / 3600); s -= hh * 3600;
  const mm = Math.floor(s / 60); s -= mm * 60;
  if (hh) return `${hh} ч ${mm} мин`;
  if (mm) return `${mm} мин ${s} с`;
  return `${s} с`;
}

/** «1 день», «2 дня», «5 дней». */
export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

export function days(n) {
  return `${n} ${plural(n, 'день', 'дня', 'дней')}`;
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function songName(artist, title) {
  return `${artist || '?'} - ${title || '?'}`;
}
