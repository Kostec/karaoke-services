// Раздел «Настройки»: папка результата (SMB-шара или локальная папка ПК) с проверкой.

import { api } from './api.js';
import { h, clear, toast, field } from './ui.js';

let root, hooks, f = {}, current = null, built = false;

export function mount(section, ctx) {
  root = section;
  hooks = ctx;
}

export async function show() {
  if (!built) build();
  try {
    current = await api.output();
    fill(current);
    f.loadErr.hidden = true;
  } catch (e) {
    f.loadErr.textContent = `Не удалось загрузить настройки: ${e.detail}`;
    f.loadErr.hidden = false;
  }
}

function build() {
  built = true;
  f.loadErr = h('div', { class: 'banner err', hidden: true });
  f.current = h('div', { class: 'small muted' });
  f.kindSmb = h('input', { type: 'radio', name: 'kind', value: 'smb' });
  f.kindLocal = h('input', { type: 'radio', name: 'kind', value: 'local' });
  f.host = h('input', { type: 'text', autocomplete: 'off', name: 'host' });
  f.share = h('input', { type: 'text', autocomplete: 'off', name: 'share' });
  f.user = h('input', { type: 'text', autocomplete: 'username', name: 'user' });
  f.pwd = h('input', { type: 'password', autocomplete: 'new-password', name: 'password' });
  f.passHint = h('div', { class: 'small muted' });
  f.path = h('input', { type: 'text', autocomplete: 'off', name: 'path', placeholder: 'пусто — корень' });
  f.winPath = h('div', { class: 'small' });
  f.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  f.test = h('button', { type: 'button', onclick: () => submit(false) }, 'Проверить');
  f.save = h('button', { type: 'submit', class: 'primary' }, 'Сохранить');

  f.smbBox = h('div', {},
    h('div', { class: 'row2' }, field('Адрес сервера', f.host), field('Имя шары', f.share)),
    h('div', { class: 'row2' }, field('Логин', f.user, 'пусто — гостевой доступ'),
      h('div', {}, field('Пароль', f.pwd), f.passHint)));

  const form = h('form', { class: 'card', novalidate: true },
    h('h3', { style: 'margin-top:0' }, 'Папка результата'),
    f.current,
    h('fieldset', { class: 'field', style: 'border:0;padding:0;margin:12px 0' },
      h('legend', {}, 'Куда выкладывать песни'),
      h('div', { class: 'radio-row' },
        h('label', {}, f.kindSmb, 'SMB-шара'),
        h('label', {}, f.kindLocal, 'Локальная папка ПК'))),
    f.smbBox,
    field('Подпапка', f.path, 'внутри шары или корня локальной папки'),
    f.winPath,
    f.result,
    h('div', { class: 'actions' }, f.test, f.save),
    h('p', { class: 'small muted' }, 'Проверка записывает и удаляет пробный файл. Сохраняется только цель, прошедшая проверку.'));
  form.addEventListener('submit', (e) => { e.preventDefault(); submit(true); });
  for (const el of [f.kindSmb, f.kindLocal]) el.addEventListener('change', updateKind);
  for (const el of [f.host, f.share, f.user, f.path]) el.addEventListener('input', updateKind);
  clear(root).append(h('div', { class: 'view-head' }, h('h2', {}, 'Настройки')), f.loadErr, form);
}

function fill(t) {
  f.kindSmb.checked = t.kind !== 'local';
  f.kindLocal.checked = t.kind === 'local';
  f.host.value = t.host || '';
  f.share.value = t.share || '';
  f.user.value = t.user || '';
  f.pwd.value = '';
  f.path.value = t.path || '';
  f.current.textContent = `Сейчас: ${t.label || '—'}`;
  f.result.hidden = true;
  updateKind();
}

function kind() {
  return f.kindLocal.checked ? 'local' : 'smb';
}

function sameAccount() {
  return current && current.kind === 'smb' && kind() === 'smb'
    && f.host.value.trim() === current.host && f.share.value.trim().replace(/^\/+|\/+$/g, '') === current.share
    && f.user.value.trim() === current.user;
}

function windowsPath() {
  const root = (current?.local_root_host || '').replace(/\//g, '\\').replace(/\\+$/, '');
  const sub = f.path.value.trim().replace(/[\\/]+/g, '\\').replace(/^\\+|\\+$/g, '');
  if (!root) return sub ? `…\\${sub}` : '';
  return sub ? `${root}\\${sub}` : (root.endsWith(':') ? `${root}\\` : root);
}

function updateKind() {
  const local = kind() === 'local';
  f.smbBox.hidden = local;
  f.winPath.hidden = !local;
  f.winPath.textContent = local ? `Папка на ПК: ${windowsPath() || 'корень не задан в .env (LOCAL_OUTPUT_ROOT)'}` : '';
  if (sameAccount() && current.has_password) {
    f.pwd.placeholder = 'сохранён — оставьте пустым, чтобы не менять';
    f.passHint.textContent = '';
  } else {
    f.pwd.placeholder = '';
    f.passHint.textContent = f.user.value.trim() && !local ? 'Сервер, шара или логин изменились — введите пароль' : '';
  }
}

function body() {
  const b = { kind: kind(), path: f.path.value.trim() };
  if (b.kind === 'smb') {
    Object.assign(b, { host: f.host.value.trim(), share: f.share.value.trim(), user: f.user.value.trim() });
    if (f.pwd.value) b['password'] = f.pwd.value; // пусто — «не менять»
  }
  return b;
}

async function submit(save) {
  const btn = save ? f.save : f.test;
  f.test.disabled = f.save.disabled = true;
  const label = btn.textContent;
  btn.textContent = save ? 'Сохранение…' : 'Проверка…';
  f.result.hidden = true;
  try {
    if (save) {
      current = await api.saveOutput(body());
      fill(current);
      showResult('ok', `Сохранено: ${current.label}. Список песен пересканируется.`);
      toast('Папка результата сохранена');
      hooks?.refreshStatus();
    } else {
      const r = await api.testOutput(body());
      showResult('ok', `Проверка пройдена: ${r.label}`);
    }
  } catch (e) {
    showResult('err', e.detail);
    markField(e.data.field);
  } finally {
    btn.textContent = label;
    f.test.disabled = f.save.disabled = false;
  }
}

/** Подсветить поле по `field` из ответа сервера. */
function markField(name) {
  const el = name === 'password' ? f.pwd : { host: f.host, share: f.share, user: f.user, path: f.path }[name];
  if (!el) return;
  el.classList.add('invalid');
  el.addEventListener('input', () => el.classList.remove('invalid'), { once: true });
  el.focus();
}

function showResult(kind, text) {
  f.result.className = `banner ${kind}`;
  f.result.textContent = text;
  f.result.hidden = false;
}
