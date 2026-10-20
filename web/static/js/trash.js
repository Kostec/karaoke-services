// Раздел «Корзина»: что, откуда, когда удалено, сколько дней осталось; восстановление.

import { api } from './api.js';
import { h, clear, runAction, fmtDate, days, plural } from './ui.js';

let root, listEl, emptyEl, errEl;

export function mount(section) {
  root = section;
  errEl = h('div', { class: 'banner err', hidden: true });
  emptyEl = h('div', { class: 'card empty', hidden: true },
    h('p', {}, 'Корзина пуста'),
    h('p', { class: 'small muted' }, 'Удалённые песни и старые версии файлов хранятся здесь, а потом удаляются окончательно.'));
  listEl = h('div');
  root.append(h('div', { class: 'view-head' }, h('h2', {}, 'Корзина')), errEl, emptyEl, listEl);
}

export async function show() {
  try {
    const items = await api.trash();
    errEl.hidden = true;
    render(items);
  } catch (e) {
    errEl.textContent = `Не удалось получить корзину: ${e.detail}`;
    errEl.hidden = false;
  }
}

function fmtSize(bytes) {
  if (!bytes) return '';
  const mb = bytes / 1048576;
  return mb >= 1 ? `${mb.toFixed(1).replace('.', ',')} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
}

function render(items) {
  emptyEl.hidden = items.length > 0;
  clear(listEl).append(...items.map((it) => {
    const title = it.artist || it.title ? `${it.artist || '?'} - ${it.title || '?'}` : it.name;
    const what = it.kind === 'version'
      ? `Старая версия файла ${it.rel_file || ''}`
      : `Песня, ${Object.keys(it.files || {}).length} ${plural(Object.keys(it.files || {}).length, 'файл', 'файла', 'файлов')}`;
    const left = typeof it.days_left === 'number'
      ? (it.days_left > 0 ? `удалится окончательно через ${days(it.days_left)}` : 'удалится окончательно при ближайшей очистке')
      : '';
    const btn = h('button', { type: 'button', class: 'primary' }, 'Восстановить');
    btn.addEventListener('click', async () => {
      const res = await runAction(btn, () => api.restore(it.id), `«${title}» восстановлена`);
      if (res) show();
    });
    return h('article', { class: 'card' },
      h('div', { class: 'job-title' }, title),
      h('div', { class: 'job-meta' },
        h('span', {}, [what, fmtSize(it.size)].filter(Boolean).join(', ')),
        h('span', {}, `откуда: ${it.target_label || '?'}/${it.rel_dir}`),
        h('span', {}, `удалено ${fmtDate(it.deleted_at)}`),
        it.reason ? h('span', {}, it.reason) : null),
      left ? h('div', { class: 'small', style: 'margin-top:4px' }, left) : null,
      h('div', { class: 'actions' }, btn));
  }));
}
