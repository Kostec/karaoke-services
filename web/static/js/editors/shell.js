// Общее окно редакторов: модальный <dialog> (на телефоне — во весь экран), сообщения внутри окна,
// предупреждение о несохранённых правках при закрытии и уходе со страницы.

import { h, clear, confirmDialog } from '../ui.js';

let cssAdded = false;

function addCss() {
  if (cssAdded) return;
  cssAdded = true;
  document.head.append(h('link', { rel: 'stylesheet', href: '/css/editors.css' }));
}

/**
 * openShell({title, subtitle, isDirty}) → {dlg, body, footer, message(text, kind), close(force)}.
 * isDirty() → true, если закрытие потеряет правки (спросим подтверждение).
 */
export function openShell({ title, subtitle, isDirty = () => false }) {
  addCss();
  const msg = h('div', { class: 'banner', hidden: true, role: 'status' });
  const body = h('div', { class: 'ed-body' });
  const footer = h('div', { class: 'actions ed-footer' });
  const closeBtn = h('button', { type: 'button', class: 'ed-close', 'aria-label': 'Закрыть' }, '✕');
  const dlg = h('dialog', { class: 'editor' },
    h('div', { class: 'ed-head' },
      h('div', { class: 'ed-titles' }, h('h3', {}, title), subtitle ? h('div', { class: 'small muted' }, subtitle) : null),
      closeBtn),
    msg, body, footer);

  const beforeUnload = (e) => {
    if (isDirty()) { e.preventDefault(); e.returnValue = ''; }
  };
  let closing = false;
  async function close(force = false) {
    if (closing) return false;
    if (!force && isDirty()) {
      closing = true;
      const ok = await confirmDialog('Есть несохранённые правки. Закрыть без сохранения?', 'Закрыть', { danger: true });
      closing = false;
      if (!ok) return false;
    }
    window.removeEventListener('beforeunload', beforeUnload);
    dlg.dispatchEvent(new Event('editor-close'));
    dlg.close();
    dlg.remove();
    return true;
  }
  closeBtn.addEventListener('click', () => close());
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); }); // Esc
  window.addEventListener('beforeunload', beforeUnload);
  document.body.append(dlg);
  dlg.showModal();

  function message(text, kind = 'ok') {
    clear(msg);
    msg.hidden = !text;
    if (!text) return;
    msg.className = `banner ${kind}`;
    msg.setAttribute('role', kind === 'err' ? 'alert' : 'status');
    msg.append(text);
  }
  return { dlg, body, footer, message, close };
}

/** «1:05.3» для мс. */
export function fmtTime(ms) {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
}
