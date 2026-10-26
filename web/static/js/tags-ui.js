// Свои теги на экране: чип тега, палитра, «Мои теги…» (управление) и «Теги…» песни.

import { api, errorText } from './api.js';
import { h, clear, confirmDialog, toast, songName, plural } from './ui.js';
import {
  TAG_COLORS, DEFAULT_TAG_COLOR, TAG_NAME_MAX, COLOR_LABELS, tagNameError,
} from './tags-logic.js';

const colorOf = (c) => (TAG_COLORS.includes(c) ? c : DEFAULT_TAG_COLOR);

/** Чип своего тега; с onClick — кнопка (клик не доходит до ссылки карточки). */
export function tagChip(tag, { onClick, title } = {}) {
  const cls = `tag user c-${colorOf(tag.color)}`;
  if (!onClick) return h('span', { class: cls }, tag.name);
  return h('button', {
    type: 'button', class: `${cls} tag-btn`, title: title || null,
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); onClick(tag, e); },
  }, tag.name);
}

/** Палитра из 8 цветов (радиокнопки); el.value — выбранный цвет, onChange(color). */
export function colorPicker(value, onChange) {
  let current = colorOf(value);
  const el = h('div', { class: 'palette', role: 'radiogroup', 'aria-label': 'Цвет тега' });
  const swatches = TAG_COLORS.map((c) => {
    const sw = h('button', {
      type: 'button', class: `sw c-${c}`, role: 'radio', title: COLOR_LABELS[c], 'aria-label': COLOR_LABELS[c],
      onclick: () => { select(c); onChange?.(c); },
    });
    sw.style.background = `var(--tag-${c}-fg)`;
    return sw;
  });
  function select(c) {
    current = colorOf(c);
    swatches.forEach((sw, i) => {
      const on = TAG_COLORS[i] === current;
      sw.classList.toggle('sel', on);
      sw.setAttribute('aria-checked', String(on));
    });
  }
  el.append(...swatches);
  select(current);
  Object.defineProperty(el, 'value', { get: () => current, set: select });
  return el;
}

function openDialog(cls, title, ...body) {
  const el = h('dialog', { class: `tags-dlg ${cls}`, 'aria-label': title }, h('h3', {}, title), ...body);
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');
  return el;
}

/** Поле названия + палитра + предпросмотр + ошибка у поля. */
function tagForm({ name = '', color = DEFAULT_TAG_COLOR, label = 'Новый тег', placeholder = 'Название тега' } = {}) {
  const input = h('input', { type: 'text', maxlength: String(TAG_NAME_MAX * 2), placeholder, 'aria-label': label });
  input.value = name;
  const preview = h('span', { class: `tag user c-${colorOf(color)}` }, name || 'тег');
  const err = h('div', { class: 'field-error', hidden: true, role: 'alert' });
  const picker = colorPicker(color, (c) => { preview.className = `tag user c-${c}`; });
  input.addEventListener('input', () => {
    preview.textContent = input.value.trim() || 'тег';
    showError(null);
  });
  function showError(text) {
    err.textContent = text || '';
    err.hidden = !text;
    input.classList.toggle('invalid', !!text);
    if (text) input.focus();
  }
  return {
    input, picker, preview, err, showError,
    el: h('div', { class: 'tag-form' },
      h('label', { class: 'small muted' }, label), input, picker,
      h('div', { class: 'small muted' }, 'Предпросмотр: ', preview), err),
  };
}

const songsCount = (n) => `${n} ${plural(n, 'песня', 'песни', 'песен')}`;

/** «Мои теги…»: переименовать, сменить цвет, удалить; создать новый. onChanged() — после закрытия, если менялось. */
export async function openTagsManager({ onChanged } = {}) {
  let data;
  try {
    data = await api.tags();
  } catch (e) {
    toast(`Не удалось получить теги: ${errorText(e)}`, 'err');
    return;
  }
  let tags = data.tags || [];
  let changed = false;
  const listEl = h('div', { class: 'tag-rows' });
  const create = tagForm();
  const createBtn = h('button', { type: 'button' }, 'Создать');
  const done = h('button', { type: 'button', class: 'primary', onclick: () => el.close() }, 'Готово');

  function row(tag) {
    const input = h('input', { type: 'text', 'aria-label': `Название тега «${tag.name}»` });
    input.value = tag.name;
    const err = h('div', { class: 'field-error', hidden: true, role: 'alert' });
    const chip = tagChip(tag);
    const showError = (text) => {
      err.textContent = text || '';
      err.hidden = !text;
      input.classList.toggle('invalid', !!text);
    };
    const save = async (patch) => {
      try {
        const t = await api.updateTag(tag.id, patch);
        Object.assign(tag, t);
        chip.textContent = t.name;
        chip.className = `tag user c-${colorOf(t.color)}`;
        changed = true;
        showError(null);
        return true;
      } catch (e) {
        if (e.data?.field === 'color') toast(errorText(e), 'err'); else showError(errorText(e));
        return false;
      }
    };
    const rename = async () => {
      if (input.value.trim() === tag.name) { showError(null); return; }
      const bad = tagNameError(input.value, tags, tag.id);
      if (bad) { showError(bad); return; }
      await save({ name: input.value });
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); rename(); } });
    input.addEventListener('change', rename);
    input.addEventListener('input', () => showError(null));
    const picker = colorPicker(tag.color, (c) => save({ color: c }));
    const del = h('button', { type: 'button', class: 'danger' }, 'Удалить');
    del.addEventListener('click', async () => {
      const n = tag.count || 0;
      const text = n ? `Удалить тег «${tag.name}»? Тег снимется со всех песен (${n}).`
        : `Удалить тег «${tag.name}»?`;
      // окно подтверждения — общий <dialog>, поверх этого
      if (!(await confirmDialog(text, 'Удалить', { danger: true }))) return;
      try {
        await api.deleteTag(tag.id);
        tags = tags.filter((t) => t.id !== tag.id);
        changed = true;
        render();
      } catch (e) {
        toast(errorText(e), 'err');
      }
    });
    return h('div', { class: 'tag-row' },
      h('div', { class: 'tag-row-head' }, chip, h('span', { class: 'small muted' }, songsCount(tag.count || 0))),
      input, err, picker, h('div', { class: 'tag-row-actions' }, del));
  }

  function render() {
    clear(listEl);
    if (!tags.length) listEl.append(h('p', { class: 'muted' }, 'Своих тегов пока нет'));
    else listEl.append(...tags.map(row));
  }

  createBtn.addEventListener('click', async () => {
    const bad = tagNameError(create.input.value, tags);
    if (bad) { create.showError(bad); return; }
    createBtn.disabled = true;
    try {
      const t = await api.createTag({ name: create.input.value, color: create.picker.value });
      tags = [...tags, t].sort((a, b) => a.name.localeCompare(b.name, 'ru', { sensitivity: 'base' }));
      changed = true;
      create.input.value = '';
      create.preview.textContent = 'тег';
      render();
    } catch (e) {
      if (e.data?.field === 'name') create.showError(errorText(e)); else toast(errorText(e), 'err');
    } finally {
      createBtn.disabled = false;
    }
  });
  create.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); createBtn.click(); } });

  render();
  const el = openDialog('tags-manager', 'Мои теги', listEl, h('hr'), create.el,
    h('div', { class: 'actions' }, createBtn), h('div', { class: 'actions' }, done));
  el.addEventListener('close', () => { if (changed) onChanged?.(); });
}

/** «Теги…» песни: отметить свои теги, создать новый с цветом; «Сохранить» — набор тегов песни. */
export async function openTagsDialog(song, { onSaved } = {}) {
  let data;
  try {
    data = await api.tags();
  } catch (e) {
    toast(`Не удалось получить теги: ${errorText(e)}`, 'err');
    return;
  }
  const tags = data.tags || [];
  const mine = new Set(song.tags || []);
  const checks = tags.map((t) => {
    const cb = h('input', { type: 'checkbox', value: t.id, checked: mine.has(t.id) });
    return { cb, el: h('label', { class: 'check' }, cb, tagChip(t)) };
  });
  const create = tagForm();
  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const save = h('button', { type: 'button', class: 'primary' }, 'Сохранить');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  let created = null; // создан этим диалогом (если набор песни не сохранился — уйдёт при повторе)
  const el = openDialog('song-tags', `Теги песни «${songName(song.artist, song.title)}»`,
    checks.length ? h('div', { class: 'tag-checks' }, checks.map((c) => c.el))
      : h('p', { class: 'muted' }, 'Своих тегов пока нет — создайте первый'),
    h('hr'), create.el, errEl, h('div', { class: 'actions' }, cancel, save));

  save.addEventListener('click', async () => {
    errEl.hidden = true;
    const ids = checks.filter((c) => c.cb.checked).map((c) => c.cb.value);
    const newName = create.input.value.trim();
    if (newName) {
      const bad = tagNameError(newName, tags);
      if (bad) { create.showError(bad); return; }
    }
    save.disabled = true;
    try {
      if (newName) {
        created = await api.createTag({ name: newName, color: create.picker.value });
        tags.push(created);
        create.input.value = ''; // повторное «Сохранить» не создаст тег ещё раз
      }
      if (created && !ids.includes(created.id)) ids.push(created.id);
      const res = await api.setSongTags(song.song_id, ids);
      el.close();
      toast('Теги сохранены');
      onSaved?.(res.tags);
    } catch (e) {
      if (e.data?.field === 'name') create.showError(errorText(e));
      else { errEl.textContent = errorText(e); errEl.hidden = false; }
    } finally {
      save.disabled = false;
    }
  });
}
