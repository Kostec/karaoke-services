// Выпадающее меню «…»: одно открытое на странице; Esc, клик вне и выбор закрывают; ↑/↓/Home/End/Enter.
//
// items: [{label, onSelect?(event), href?, download?, disabled?: string|false, danger?} | 'sep']
// disabled — строка-причина: пункт серый, причина — в подсказке (title) и тостом по нажатию.

import { h, toast } from './ui.js';

let current = null; // {el, anchor, close}

function place(el, anchor) {
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth;
  const ht = el.offsetHeight;
  const vw = document.documentElement.clientWidth;
  const below = r.bottom + 4;
  const top = below + ht > window.innerHeight - 8 && r.top - ht - 4 >= 8 ? r.top - ht - 4 : below;
  const left = Math.min(Math.max(8, r.right - w), vw - w - 8);
  el.style.top = `${Math.round(top + window.scrollY)}px`;
  el.style.left = `${Math.round(Math.max(8, left) + window.scrollX)}px`;
}

/** Открыть меню у anchor; прежнее открытое закрывается. → {close} */
export function openMenu(anchor, items) {
  current?.close();
  const el = h('div', { class: 'menu', role: 'menu' });
  const entries = [];
  for (const it of items) {
    if (!it) continue;
    if (it === 'sep') {
      if (entries.length && el.lastChild?.className !== 'menu-sep') el.append(h('div', { class: 'menu-sep', role: 'separator' }));
      continue;
    }
    const reason = typeof it.disabled === 'string' ? it.disabled : '';
    const off = !!it.disabled;
    const cls = `menu-item${it.danger ? ' danger' : ''}`;
    const attrs = { class: cls, role: 'menuitem', tabindex: '-1', title: reason || null,
      'aria-disabled': off ? 'true' : null };
    const node = it.href && !off
      ? h('a', { ...attrs, href: it.href, download: it.download ? '' : null }, it.label)
      : h('button', { ...attrs, type: 'button' }, it.label);
    node.addEventListener('click', (e) => {
      if (off) {
        e.preventDefault();
        if (reason) toast(reason);
        return;
      }
      close(false);
      it.onSelect?.(e);
    });
    entries.push(node);
    el.append(node);
  }
  if (el.lastChild?.className === 'menu-sep') el.lastChild.remove();

  const focusAt = (i) => {
    const list = entries.filter((n) => n.getAttribute('aria-disabled') !== 'true');
    if (!list.length) return;
    const idx = list.indexOf(document.activeElement);
    let next;
    if (i === 'first') next = 0;
    else if (i === 'last') next = list.length - 1;
    else if (idx === -1) next = i > 0 ? 0 : list.length - 1;
    else next = (idx + i + list.length) % list.length;
    list[next].focus({ preventScroll: true });
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(true); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(-1); }
    else if (e.key === 'Home') { e.preventDefault(); focusAt('first'); }
    else if (e.key === 'End') { e.preventDefault(); focusAt('last'); }
    else if (e.key === 'Tab') close(false);
  };
  const onDown = (e) => {
    if (!el.contains(e.target) && !anchor.contains(e.target)) close(false);
  };
  const onResize = () => close(false);

  function close(refocus) {
    if (current?.el !== el) return;
    current = null;
    el.remove();
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('pointerdown', onDown, true);
    window.removeEventListener('resize', onResize);
    anchor.setAttribute('aria-expanded', 'false');
    if (refocus && anchor.isConnected) anchor.focus();
  }

  document.body.append(el);
  place(el, anchor);
  anchor.setAttribute('aria-expanded', 'true');
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('pointerdown', onDown, true);
  window.addEventListener('resize', onResize);
  current = { el, anchor, close: () => close(false) };
  focusAt('first');
  return { close: () => close(false) };
}

/** Кнопка «…»: itemsFn() зовётся при каждом открытии; повторное нажатие закрывает меню. */
export function menuButton(itemsFn, { label = '…', title = 'Ещё действия', className = '' } = {}) {
  const btn = h('button', { type: 'button', class: `menu-btn${className ? ` ${className}` : ''}`, title,
    'aria-label': title, 'aria-haspopup': 'menu', 'aria-expanded': 'false' }, label);
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (current?.anchor === btn) { current.close(); return; }
    openMenu(btn, itemsFn());
  });
  return btn;
}

/** Закрыть открытое меню (смена раздела). */
export function closeMenu() {
  current?.close();
}
