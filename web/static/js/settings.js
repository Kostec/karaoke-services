// Раздел «Настройки»: папка результата (SMB-шара или локальная папка ПК) с проверкой; учётка usdb;
// ключ доступа Яндекс Музыки (OAuth-токен аккаунта — сервис не спрашивает логин и пароль Яндекса).

import { api } from './api.js';
import { h, clear, toast, field, confirmDialog } from './ui.js';
import { yandexSaveAction, YM_REMOVE_CONFIRM, YM_KEPT, YM_EMPTY } from './link-logic.js';

let root, hooks, f = {}, current = null, built = false;
let u = {}, usdbCurrent = null; // карточка «usdb»
let y = {}, ymCurrent = null; // карточка «Яндекс Музыка»: {has_token}

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
  try {
    usdbCurrent = await api.usdbAccount();
    fillUsdb(usdbCurrent);
  } catch (e) {
    showUsdbResult('err', `Не удалось загрузить учётку usdb: ${e.detail}`);
  }
  try {
    ymCurrent = await api.yandexAccount();
    fillYandex(ymCurrent);
  } catch (e) {
    showYandexResult('err', `Не удалось загрузить настройки Яндекс Музыки: ${e.detail}`);
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
  clear(root).append(h('div', { class: 'view-head' }, h('h2', {}, 'Настройки')), f.loadErr, form, buildUsdb(), buildYandex());
}

// ---------------------------------------------------------------- usdb

function buildUsdb() {
  u.current = h('div', { class: 'small muted' });
  u.user = h('input', { type: 'text', autocomplete: 'off', name: 'usdb-user' });
  u.pwd = h('input', { type: 'password', autocomplete: 'new-password', name: 'usdb-password' });
  u.passHint = h('div', { class: 'small muted' });
  u.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  u.test = h('button', { type: 'button', onclick: () => submitUsdb(false) }, 'Проверить');
  u.save = h('button', { type: 'submit', class: 'primary' }, 'Сохранить');
  const form = h('form', { class: 'card', novalidate: true },
    h('h3', { style: 'margin-top:0' }, 'usdb'),
    u.current,
    h('p', { class: 'small muted' }, 'Учётка ',
      h('a', { href: 'https://usdb.animux.de/', target: '_blank', rel: 'noopener' }, 'usdb.animux.de'),
      ' — для поиска готовых песен в «Импорте».'),
    h('div', { class: 'row2' }, field('Логин', u.user),
      h('div', {}, field('Пароль', u.pwd), u.passHint)),
    u.result,
    h('div', { class: 'actions' }, u.test, u.save),
    h('p', { class: 'small muted' }, 'Сохраняется только учётка, с которой usdb пустил. Пустой логин — удалить учётку.'));
  form.addEventListener('submit', (e) => { e.preventDefault(); submitUsdb(true); });
  u.user.addEventListener('input', updateUsdbHint);
  return form;
}

function fillUsdb(acc) {
  u.user.value = acc.user || '';
  u.pwd.value = '';
  u.current.textContent = acc.user ? `Сейчас: ${acc.user}` : 'Учётка не задана';
  updateUsdbHint();
}

function updateUsdbHint() {
  const same = usdbCurrent && usdbCurrent.has_password && u.user.value.trim() === usdbCurrent.user;
  u.pwd.placeholder = same ? 'сохранён — оставьте пустым, чтобы не менять' : '';
  u.passHint.textContent = !same && u.user.value.trim() && usdbCurrent?.user ? 'Логин изменился — введите пароль' : '';
}

function usdbBody() {
  const b = { user: u.user.value.trim() };
  if (u.pwd.value) b['password'] = u.pwd.value; // пусто — «не менять»
  return b;
}

async function submitUsdb(save) {
  const btn = save ? u.save : u.test;
  u.test.disabled = u.save.disabled = true;
  const label = btn.textContent;
  btn.textContent = save ? 'Сохранение…' : 'Проверка…';
  u.result.hidden = true;
  try {
    if (save) {
      usdbCurrent = await api.saveUsdbAccount(usdbBody());
      fillUsdb(usdbCurrent);
      showUsdbResult('ok', usdbCurrent.user ? `Сохранено: вход в usdb как ${usdbCurrent.user}` : 'Учётка usdb удалена');
      toast('Учётка usdb сохранена');
    } else {
      await api.testUsdbAccount(usdbBody());
      showUsdbResult('ok', 'Проверка пройдена: usdb пустил');
    }
  } catch (e) {
    showUsdbResult('err', e.detail);
    const el = e.data?.field === 'password' ? u.pwd : e.data?.field === 'user' ? u.user : null;
    if (el) {
      el.classList.add('invalid');
      el.addEventListener('input', () => el.classList.remove('invalid'), { once: true });
      el.focus();
    }
  } finally {
    btn.textContent = label;
    u.test.disabled = u.save.disabled = false;
  }
}

function showUsdbResult(kind, text) {
  u.result.className = `banner ${kind}`;
  u.result.textContent = text;
  u.result.hidden = false;
}

// ---------------------------------------------------------------- Яндекс Музыка

const YM_HELP = 'https://yandex-music.readthedocs.io/en/main/token.html';

function buildYandex() {
  y.current = h('div', { class: 'small muted' });
  y.key = h('input', { type: 'password', autocomplete: 'off', name: 'yandex-music-key', spellcheck: 'false' });
  y.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  y.test = h('button', { type: 'button', onclick: () => submitYandex(false) }, 'Проверить');
  y.save = h('button', { type: 'submit', class: 'primary' }, 'Сохранить');
  const form = h('form', { class: 'card', novalidate: true },
    h('h3', { style: 'margin-top:0' }, 'Яндекс Музыка'),
    y.current,
    h('p', { class: 'small muted' }, 'Для генерации по ссылкам music.yandex.ru (трек, альбом, плейлист) нужен ',
      'OAuth-токен вашего аккаунта с подпиской Плюс. Логин и пароль Яндекса сюда не вводятся: токен получают ',
      'сами, в браузере, ', h('a', { href: YM_HELP, target: '_blank', rel: 'noopener' }, 'по этой инструкции'),
      ' — войти в Яндекс на oauth.yandex.ru и скопировать access_token из адресной строки.'),
    field('Токен', y.key),
    y.result,
    h('div', { class: 'actions' }, y.test, y.save),
    h('p', { class: 'small muted' }, 'Сохраняется только токен, который Яндекс Музыка приняла. Пустое поле и «Сохранить» — удалить токен (с подтверждением). ',
      'Проверка с пустым полем проверяет сохранённый.'));
  form.addEventListener('submit', (e) => { e.preventDefault(); submitYandex(true); });
  return form;
}

function fillYandex(acc) {
  y.key.value = '';
  y.current.textContent = acc?.has_token ? 'Токен сохранён' : 'Токен не задан';
  y.key.placeholder = acc?.has_token ? 'сохранён — впишите новый, чтобы заменить' : '';
}

function yandexBody() {
  const b = {};
  b['token'] = y.key.value.trim();
  return b;
}

async function submitYandex(save) {
  if (save) {
    const action = yandexSaveAction(y.key.value, ymCurrent?.has_token);
    if (action === 'empty') {
      showYandexResult('err', YM_EMPTY);
      y.key.focus();
      return;
    }
    if (action === 'confirm-remove' && !(await confirmDialog(YM_REMOVE_CONFIRM, 'Удалить токен', { danger: true }))) {
      showYandexResult('warn', YM_KEPT);
      y.key.focus();
      return;
    }
  }
  const btn = save ? y.save : y.test;
  y.test.disabled = y.save.disabled = true;
  const label = btn.textContent;
  btn.textContent = save ? 'Сохранение…' : 'Проверка…';
  y.result.hidden = true;
  try {
    if (save) {
      const removing = !y.key.value.trim();
      ymCurrent = await api.saveYandexAccount(yandexBody());
      fillYandex(ymCurrent);
      showYandexResult('ok', removing ? 'Токен Яндекс Музыки удалён' : 'Сохранено: Яндекс Музыка приняла токен');
      toast(removing ? 'Токен Яндекс Музыки удалён' : 'Токен Яндекс Музыки сохранён');
    } else {
      await api.testYandexAccount(yandexBody());
      showYandexResult('ok', 'Проверка пройдена: Яндекс Музыка приняла токен');
    }
  } catch (e) {
    showYandexResult('err', e.detail);
    if (e.data?.field === 'token') {
      y.key.classList.add('invalid');
      y.key.addEventListener('input', () => y.key.classList.remove('invalid'), { once: true });
      y.key.focus();
    }
  } finally {
    btn.textContent = label;
    y.test.disabled = y.save.disabled = false;
  }
}

function showYandexResult(kind, text) {
  y.result.className = `banner ${kind}`;
  y.result.textContent = text;
  y.result.hidden = false;
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
