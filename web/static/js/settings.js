// Раздел «Настройки»: «Куда выкладывать» — список хранилищ (локальное, SMB, папка ПК, Яндекс Диск,
// WebDAV, Google Диск) с проверкой и основной целью; учётка usdb; ключ доступа Яндекс Музыки
// (OAuth-токен аккаунта — сервис не спрашивает логин и пароль Яндекса); «Уведомления» — Telegram-бот
// (токен назад не отдаётся) и уведомления в этом браузере.

import { api, request } from './api.js';
import { h, clear, toast, field, confirmDialog } from './ui.js';
import { targetBody, savedBody, formKind, fieldTarget, needsLocalHint, sameAccount } from './targets-logic.js';
import { yandexSaveAction, YM_REMOVE_CONFIRM, YM_KEPT, YM_EMPTY } from './link-logic.js';
import { notifyEnabled, notifyState, setNotifyEnabled } from './notify.js';

let root, hooks, built = false;
const T = {}; // карточка «Куда выкладывать»: элементы, список, форма
let u = {}, usdbCurrent = null; // карточка «usdb»
let y = {}, ymCurrent = null; // карточка «Яндекс Музыка»: {has_token}
let n = {}, tgCurrent = null; // карточка «Уведомления»: {has_token, chat_id, on_done, on_failed, on_queue_empty}

export function mount(section, ctx) {
  root = section;
  hooks = ctx;
}

export async function show() {
  if (!built) build();
  await loadTargets();
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
  fillBrowserNotify();
  try {
    tgCurrent = await api.telegram();
    fillTelegram(tgCurrent);
  } catch (e) {
    showNotifyResult('err', `Не удалось загрузить настройки уведомлений: ${e.detail}`);
  }
}

export function hide() {
  stopGooglePoll();
}

function build() {
  built = true;
  clear(root).append(h('div', { class: 'view-head' }, h('h2', {}, 'Настройки')),
    buildTargets(), buildUsdb(), buildYandex(), buildNotify());
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

// ---------------------------------------------------------------- Уведомления (Telegram и браузер)

const TG_HELP = 'https://core.telegram.org/bots/features#botfather';

function buildNotify() {
  n.key = h('input', { type: 'password', autocomplete: 'off', name: 'telegram-bot-key', spellcheck: 'false' });
  n.keyHint = h('div', { class: 'small muted' });
  n.chat = h('input', { type: 'text', autocomplete: 'off', name: 'telegram-chat', spellcheck: 'false',
    placeholder: '248019337' });
  n.find = h('button', { type: 'button', onclick: findTelegramChat }, 'Найти чат');
  n.onDone = h('input', { type: 'checkbox' });
  n.onFailed = h('input', { type: 'checkbox' });
  n.onEmpty = h('input', { type: 'checkbox' });
  n.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  n.test = h('button', { type: 'button', onclick: () => submitTelegram(false) }, 'Проверить');
  n.save = h('button', { type: 'submit', class: 'primary' }, 'Сохранить');
  n.browser = h('input', { type: 'checkbox', onchange: toggleBrowserNotify });
  n.browserLabel = h('label', { class: 'check' }, n.browser, 'Показывать, пока вкладка открыта');
  n.browserNote = h('div', { class: 'banner warn', hidden: true, role: 'status', style: 'margin:4px 0 0' });
  const form = h('form', { class: 'card', novalidate: true },
    h('h3', { style: 'margin-top:0' }, 'Уведомления'),
    h('p', { class: 'small muted', style: 'margin-top:0' },
      'Telegram работает с любого устройства. Сообщение приходит, когда задание готово или упало. ',
      'Бота создают у ', h('a', { href: TG_HELP, target: '_blank', rel: 'noopener' }, '@BotFather'),
      ' — он выдаёт токен.'),
    h('div', { class: 'row2' },
      h('div', {}, field('Токен бота', n.key), n.keyHint),
      h('div', {},
        h('label', { class: 'field' }, h('span', {}, 'Chat id'),
          h('div', { style: 'display:flex;gap:8px' }, n.chat, n.find)),
        h('div', { class: 'small muted' }, 'сначала напишите боту любое сообщение'))),
    h('div', { class: 'radio-row', style: 'margin-top:8px' },
      h('label', {}, n.onDone, 'Готово'), h('label', {}, n.onFailed, 'Сбой'),
      h('label', {}, n.onEmpty, 'Очередь опустела')),
    n.result,
    h('div', { class: 'actions' }, n.test, n.save),
    h('hr', { style: 'border:0;border-top:1px solid var(--border);margin:14px 0' }),
    h('h3', { style: 'font-size:1rem' }, 'Уведомления в этом браузере'),
    n.browserLabel,
    n.browserNote);
  form.addEventListener('submit', (e) => { e.preventDefault(); submitTelegram(true); });
  n.chat.addEventListener('input', () => n.chat.classList.remove('invalid'));
  n.key.addEventListener('input', () => n.key.classList.remove('invalid'));
  return form;
}

function fillTelegram(t) {
  n.key.value = '';
  n.key.placeholder = t?.has_token ? '••••••••••••••••' : '123456:ABC…';
  n.keyHint.textContent = t?.has_token ? 'сохранён — оставьте пустым, чтобы не менять' : 'токен ещё не задан';
  n.chat.value = t?.chat_id || '';
  n.onDone.checked = t?.on_done ?? true;
  n.onFailed.checked = t?.on_failed ?? true;
  n.onEmpty.checked = t?.on_queue_empty ?? false;
}

/** Тело запроса: пустой токен не шлётся — сервер возьмёт сохранённый (назад он его не отдаёт). */
function telegramBody(withEvents = true) {
  const b = { chat_id: n.chat.value.trim() };
  if (withEvents) Object.assign(b, { on_done: n.onDone.checked, on_failed: n.onFailed.checked, on_queue_empty: n.onEmpty.checked });
  const typed = n.key.value.trim();
  if (typed) b['bot_token'] = typed;
  return b;
}

function markNotifyField(e) {
  const el = e.data?.field === 'bot_token' ? n.key : e.data?.field === 'chat_id' ? n.chat : null;
  if (el) {
    el.classList.add('invalid');
    el.focus();
  }
}

async function submitTelegram(save) {
  const btn = save ? n.save : n.test;
  n.test.disabled = n.save.disabled = n.find.disabled = true;
  const label = btn.textContent;
  btn.textContent = save ? 'Сохранение…' : 'Отправка…';
  n.result.hidden = true;
  try {
    if (save) {
      tgCurrent = await api.saveTelegram(telegramBody());
      fillTelegram(tgCurrent);
      showNotifyResult('ok', 'Сохранено');
      toast('Уведомления сохранены');
    } else {
      await api.testTelegram(telegramBody(false));
      showNotifyResult('ok', '✓ Тестовое сообщение отправлено');
    }
  } catch (e) {
    showNotifyResult('err', e.detail);
    markNotifyField(e);
  } finally {
    btn.textContent = label;
    n.test.disabled = n.save.disabled = n.find.disabled = false;
  }
}

async function findTelegramChat() {
  n.find.disabled = true;
  const label = n.find.textContent;
  n.find.textContent = 'Поиск…';
  n.result.hidden = true;
  try {
    const body = telegramBody(false);
    delete body.chat_id;
    const found = await api.findTelegramChat(body);
    n.chat.value = found.chat_id;
    n.chat.classList.remove('invalid');
    showNotifyResult('ok', `Найден чат ${found.chat_id} — нажмите «Сохранить»`);
  } catch (e) {
    showNotifyResult(e.status === 404 ? 'warn' : 'err', e.detail);
    markNotifyField(e);
  } finally {
    n.find.textContent = label;
    n.find.disabled = false;
  }
}

function showNotifyResult(kind, text) {
  n.result.className = `banner ${kind}`;
  n.result.textContent = text;
  n.result.hidden = false;
}

/** Переключатель «в этом браузере»: погашен с причиной, если браузер не даст (http, запрет). */
function fillBrowserNotify(reason = '') {
  const st = notifyState();
  n.browser.checked = st.ok && notifyEnabled();
  n.browser.disabled = !st.ok;
  n.browserLabel.style.opacity = st.ok ? '' : '.55';
  const text = st.ok ? reason : st.reason;
  n.browserNote.textContent = text;
  n.browserNote.hidden = !text;
}

async function toggleBrowserNotify() {
  n.browser.disabled = true;
  const st = await setNotifyEnabled(n.browser.checked);
  fillBrowserNotify(st.ok ? '' : st.reason);
  if (st.ok && n.browser.checked) toast('Уведомления в этом браузере включены');
}

// ---------------------------------------------------------------- Куда выкладывать

const KINDS = {
  smb: 'SMB-шара',
  local: 'Папка ПК',
  yandex: 'Яндекс Диск',
  webdav: 'WebDAV',
  gdrive: 'Google Диск',
};
const KIND_HINTS = {
  smb: 'Сетевая папка (Samba), например на Raspberry Pi.',
  local: 'Любая папка внутри «Папок ПК» или «Локального хранилища».',
  yandex: 'Яндекс Диск по WebDAV с паролем приложения.',
  webdav: 'Nextcloud, NAS или другой сервер WebDAV.',
  gdrive: 'Google Диск через вход в аккаунт Google.',
};
const YANDEX_PASS_HELP = 'https://id.yandex.ru/security/app-passwords';
const GOOGLE_CONSOLE = 'https://console.cloud.google.com/apis/credentials';
const KEEP_HINT = 'сохранён — оставьте пустым, чтобы не менять';
const GOOGLE_POLL_MS = 2000;
const GOOGLE_POLL_MAX_MS = 10 * 60 * 1000;

function buildTargets() {
  T.loadErr = h('div', { class: 'banner err', hidden: true });
  T.list = h('ul', { class: 'target-list' });
  T.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  T.statuses = {};
  T.add = h('button', { type: 'button', onclick: openKindChooser }, '+ Добавить хранилище');
  T.chooser = h('div', { class: 'target-kinds', hidden: true },
    h('div', { class: 'small muted' }, 'Какое хранилище добавить?'),
    h('div', { class: 'target-kind-grid' },
      Object.entries(KINDS).map(([kind, label]) => h('button', {
        type: 'button', class: 'target-kind', onclick: () => openForm({ kind }),
      }, h('b', {}, label), h('span', { class: 'small muted' }, KIND_HINTS[kind])))),
    h('div', { class: 'actions' }, h('button', { type: 'button', onclick: closeForm }, 'Отмена')));
  T.formBox = h('div', { hidden: true });
  return h('section', { class: 'card' },
    h('h3', { style: 'margin-top:0' }, 'Куда выкладывать'),
    h('p', { class: 'small muted' }, 'Новые песни выкладываются в «Локальное хранилище» и в основную цель. ',
      'Переключение основной цели не меняет сами хранилища: их адреса и пароли сохраняются.'),
    T.loadErr, T.list, T.result,
    h('div', { class: 'actions' }, T.add),
    T.chooser, T.formBox);
}

async function loadTargets() {
  try {
    const r = await request('GET', '/api/targets');
    T.targets = r.targets;
    T.defaultId = r.default_id;
    T.roots = r.roots || { host: false, output: true };
    T.loadErr.hidden = true;
    renderTargets();
  } catch (e) {
    T.loadErr.textContent = `Не удалось загрузить хранилища: ${e.detail}`;
    T.loadErr.hidden = false;
  }
}

function renderTargets() {
  clear(T.list);
  for (const t of T.targets || []) {
    const st = T.statuses[t.id];
    const radio = h('input', { type: 'radio', name: 'default-target', value: t.id, checked: t.id === T.defaultId,
      title: 'Основная цель', onchange: () => setDefault(t) });
    const status = st ? h('span', { class: `tag ${st.ok ? 'on' : 'bad'}`, title: st.text },
      st.ok ? 'доступно' : 'ошибка') : null;
    const buttons = [h('button', { type: 'button', onclick: (e) => checkTarget(t, e.currentTarget) }, 'Проверить')];
    if (!t.builtin) {
      buttons.push(h('button', { type: 'button', onclick: () => openForm(t) }, 'Изменить'),
        h('button', { type: 'button', class: 'danger', onclick: () => removeTarget(t) }, 'Удалить'));
    }
    const extra = t.kind === 'gdrive' ? h('span', { class: `tag ${t.connected ? 'on' : ''}` },
      t.connected ? 'подключено' : 'не подключено') : null;
    T.list.append(h('li', { class: `target-item${t.id === T.defaultId ? ' default' : ''}` },
      h('label', { class: 'target-radio', title: 'Основная цель' }, radio, h('span', { class: 'small' }, 'основная')),
      h('div', { class: 'target-main' },
        h('div', { class: 'target-title' }, h('b', {}, t.name || t.label),
          h('span', { class: 'tag' }, t.builtin ? 'встроенное' : (KINDS[formKind(t)] || t.kind)), extra, status),
        h('div', { class: 'small muted target-label' }, t.label),
        st && !st.ok ? h('div', { class: 'small target-error' }, st.text) : null),
      h('div', { class: 'target-buttons' }, buttons)));
  }
}

function showTargetsResult(kind, text) {
  T.result.className = `banner ${kind}`;
  T.result.textContent = text;
  T.result.hidden = false;
}

async function setDefault(t) {
  try {
    const r = await request('PUT', '/api/targets/default', { id: t.id });
    T.targets = r.targets;
    T.defaultId = r.default_id;
    renderTargets();
    showTargetsResult('ok', `Основная цель: «${t.name || t.label}». Список песен пересканируется.`);
    hooks?.refreshStatus?.();
  } catch (e) {
    showTargetsResult('err', e.detail);
    renderTargets();
  }
}

async function checkTarget(t, btn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Проверка…';
  try {
    await request('POST', '/api/targets/test', savedBody(t));
    T.statuses[t.id] = { ok: true, text: 'Проверка пройдена' };
  } catch (e) {
    T.statuses[t.id] = { ok: false, text: e.detail };
  } finally {
    btn.disabled = false;
    btn.textContent = label;
    renderTargets();
  }
}

async function removeTarget(t) {
  if (t.id === T.defaultId) {
    showTargetsResult('err', 'Сначала выберите другую основную цель');
    return;
  }
  const ok = await confirmDialog(`Удалить хранилище «${t.name || t.label}» из настроек? Песни в нём не удаляются, `
    + 'но пропадут из списка «Песен».', 'Удалить', { danger: true });
  if (!ok) return;
  try {
    await request('DELETE', `/api/targets/${encodeURIComponent(t.id)}`);
    delete T.statuses[t.id];
    if (T.form?.target?.id === t.id) closeForm();
    await loadTargets();
    toast('Хранилище удалено');
  } catch (e) {
    showTargetsResult('err', e.detail);
  }
}

// ---- форма добавления / правки

function openKindChooser() {
  closeForm();
  T.result.hidden = true;
  T.chooser.hidden = false;
  T.add.hidden = true;
}

function closeForm() {
  stopGooglePoll();
  T.form = null;
  T.chooser.hidden = true;
  clear(T.formBox).hidden = true;
  T.add.hidden = false;
}

function input(name, attrs = {}) {
  return h('input', { type: 'text', autocomplete: 'off', name, spellcheck: 'false', ...attrs });
}

function openForm(t) {
  closeForm();
  T.add.hidden = true;
  T.result.hidden = true;
  const kind = formKind(t);
  const editing = Boolean(t.id);
  const F = T.form = { kind, target: editing ? t : null, inputs: {} };
  const I = F.inputs;
  I.name = input('name', { placeholder: 'пусто — по адресу' });
  I.name.value = t.name || '';
  const rows = [field('Название', I.name)];

  if (kind === 'smb') {
    I.host = input('host', { placeholder: '192.168.0.129' });
    I.share = input('share');
    I.path = input('path', { placeholder: 'пусто — корень шары' });
    I.user = input('user', { autocomplete: 'username' });
    rows.push(h('div', { class: 'row2' }, field('Сервер (IP)', I.host), field('Имя шары', I.share)),
      h('p', { class: 'small muted' }, 'Имена вроде pi.local внутри контейнера не работают — впишите IP-адрес.'),
      field('Путь', I.path, 'папка внутри шары'),
      h('div', { class: 'row2' }, field('Логин', I.user, 'пусто — гостевой доступ'), passwordField(F, 'Пароль')));
  } else if (kind === 'yandex') {
    I.user = input('user', { autocomplete: 'username', placeholder: 'login@yandex.ru' });
    I.path = input('path', { placeholder: 'Караоке' });
    rows.push(h('div', { class: 'row2' }, field('Логин Яндекса', I.user), passwordField(F, 'Пароль приложения')),
      h('p', { class: 'small muted' }, 'Нужен не основной пароль, а пароль приложения: ',
        h('a', { href: YANDEX_PASS_HELP, target: '_blank', rel: 'noopener' }, 'id.yandex.ru → Безопасность → Пароли приложений'),
        ', тип «Файлы WebDAV».'),
      field('Папка на Диске', I.path, 'пусто — корень Диска'));
  } else if (kind === 'webdav') {
    I.url = input('url', { type: 'url', placeholder: 'https://cloud.example.ru/remote.php/dav/files/me' });
    I.user = input('user', { autocomplete: 'username' });
    I.path = input('path', { placeholder: 'Karaoke' });
    rows.push(field('Адрес WebDAV', I.url),
      h('div', { class: 'row2' }, field('Логин', I.user, 'пусто — без входа'), passwordField(F, 'Пароль')),
      field('Путь', I.path, 'папка на сервере'));
  } else if (kind === 'gdrive') {
    I.client_id = input('client_id', { placeholder: '…apps.googleusercontent.com' });
    I.path = input('path', { placeholder: 'Karaoke' });
    rows.push(h('p', { class: 'small muted' }, 'Нужен свой OAuth-клиент Google: ',
      h('a', { href: GOOGLE_CONSOLE, target: '_blank', rel: 'noopener' }, 'Google Cloud Console'),
      ' → Credentials → OAuth client ID, тип «Desktop app»; в проекте включите Google Drive API.'),
    h('div', { class: 'row2' }, field('Client ID', I.client_id), passwordField(F, 'Client secret')),
    field('Папка на Диске', I.path, 'пусто — корень «Мой диск»'));
    if (needsLocalHint(location.hostname)) {
      rows.push(h('div', { class: 'banner warn' },
        'Подключите Google Диск с компьютера, где запущен сервис (адрес localhost): Google возвращает вход только туда.'));
    }
  } else if (kind === 'local') {
    rows.push(buildBrowser(F, t.path || ''));
  }

  if (kind !== 'local') {
    for (const key of ['host', 'share', 'path', 'user', 'url', 'client_id']) if (I[key]) I[key].value = t[key] || '';
  }

  F.result = h('div', { class: 'banner', hidden: true, role: 'status' });
  F.test = h('button', { type: 'button', onclick: () => submitForm(false) }, 'Проверить');
  F.save = h('button', { type: 'submit', class: 'primary' }, 'Сохранить');
  const actions = [F.test];
  if (kind === 'gdrive') {
    const connected = editing && t.connected;
    F.google = h('button', { type: 'button', class: connected ? '' : 'primary', onclick: googleLogin },
      connected ? 'Войти через Google заново' : 'Войти через Google');
    F.test.hidden = !connected;
    actions.push(F.google);
    if (connected) actions.push(F.save);
  } else {
    actions.push(F.save);
  }
  actions.push(h('button', { type: 'button', onclick: closeForm }, 'Отмена'));

  const form = h('form', { class: 'target-form', novalidate: true },
    h('h4', {}, editing ? `Изменить: ${t.name || t.label}` : `Новое хранилище: ${KINDS[kind]}`),
    rows, F.result, h('div', { class: 'actions' }, actions),
    h('p', { class: 'small muted' }, kind === 'gdrive'
      ? 'Хранилище сохраняется после входа в Google и проверки доступа к папке.'
      : 'Проверка записывает и удаляет пробный файл. Сохраняется только хранилище, прошедшее проверку.'));
  form.addEventListener('submit', (e) => { e.preventDefault(); submitForm(true); });
  for (const key of ['host', 'share', 'user', 'url', 'client_id']) I[key]?.addEventListener('input', () => updatePassHint(F));
  clear(T.formBox).append(form);
  T.formBox.hidden = false;
  updatePassHint(F);
  (I.host || I.user || I.url || I.client_id || I.name).focus();
}

function passwordField(F, label) {
  F.inputs['password'] = h('input', { type: 'password', autocomplete: 'new-password', name: 'password' });
  F.passHint = h('div', { class: 'small muted' });
  return h('div', {}, field(label, F.inputs.password), F.passHint);
}

function updatePassHint(F) {
  if (!F.inputs.password) return;
  const same = sameAccount(F.kind, formValues(F), F.target);
  F.inputs.password.placeholder = same ? KEEP_HINT : '';
  F.passHint.textContent = F.target?.has_password && !same ? 'Адрес или логин изменились — введите пароль заново' : '';
}

/** Значения полей формы (папка «Папки ПК» — выбранный путь). */
function formValues(F) {
  const values = {};
  for (const [key, el] of Object.entries(F.inputs)) if (el) values[key] = el.value;
  if (F.kind === 'local') values.path = F.browser.chosen || '';
  return values;
}

function formBody(F) {
  return targetBody(F.kind, formValues(F), { id: F.target?.id });
}

function showFormResult(F, kind, text) {
  F.result.className = `banner ${kind}`;
  F.result.textContent = text;
  F.result.hidden = false;
}

function setBusy(F, busy) {
  for (const b of [F.test, F.save, F.google]) if (b) b.disabled = busy;
}

async function submitForm(save) {
  const F = T.form;
  if (!F) return;
  if (F.kind === 'local' && !F.browser.chosen) {
    showFormResult(F, 'err', 'Выберите папку: откройте нужную и нажмите «Выбрать эту папку»');
    markField(F, 'path');
    return;
  }
  if (F.kind === 'gdrive' && save && !F.target?.connected) {
    googleLogin();
    return;
  }
  const btn = save ? F.save : F.test;
  const label = btn.textContent;
  setBusy(F, true);
  btn.textContent = save ? 'Сохранение…' : 'Проверка…';
  F.result.hidden = true;
  try {
    const body = formBody(F);
    if (save) {
      const saved = F.target
        ? await request('PUT', `/api/targets/${encodeURIComponent(F.target.id)}`, body)
        : await request('POST', '/api/targets', body);
      T.statuses[saved.id] = { ok: true, text: 'Проверка пройдена' };
      closeForm();
      await loadTargets();
      showTargetsResult('ok', `Сохранено: «${saved.name}» (${saved.label})`);
      toast('Хранилище сохранено');
      hooks?.refreshStatus?.();
    } else {
      const r = await request('POST', '/api/targets/test', body);
      showFormResult(F, 'ok', `Проверка пройдена: ${r.label}`);
    }
  } catch (e) {
    showFormResult(F, 'err', e.detail);
    markField(F, e.data?.field);
  } finally {
    btn.textContent = label;
    setBusy(F, false);
  }
}

/** Подсветить поле формы по `field` из ответа сервера. */
function markField(F, name) {
  const key = fieldTarget(name, F.kind);
  const el = key === 'folder' ? F.browser.box : key ? F.inputs[key] : null;
  if (!el) return;
  el.classList.add('invalid');
  const off = () => el.classList.remove('invalid');
  if (el.tagName === 'INPUT') {
    el.addEventListener('input', off, { once: true });
    el.focus();
  } else {
    el.addEventListener('click', off, { once: true });
  }
}

// ---- «Папка ПК»: обзор каталогов

const ROOT_LABELS = { host: 'Папки ПК', output: 'Локальное хранилище' };

function buildBrowser(F, path) {
  const parts = path.split('/').filter(Boolean);
  const B = F.browser = {
    root: parts[0] in ROOT_LABELS ? parts[0] : (T.roots?.host ? 'host' : 'output'),
    path: parts.slice(1).join('/'),
    chosen: path || '',
  };
  B.chosenEl = h('div', { class: 'small' });
  B.crumbs = h('div', { class: 'browse-crumbs' });
  B.list = h('ul', { class: 'browse-list' });
  B.err = h('div', { class: 'small target-error', hidden: true });
  const radios = Object.entries(ROOT_LABELS).map(([key, label]) => {
    const disabled = key === 'host' && !T.roots?.host;
    const r = h('input', { type: 'radio', name: 'browse-root', value: key, checked: B.root === key, disabled });
    r.addEventListener('change', () => { B.root = key; B.path = ''; browseTo(F); });
    return h('label', { title: disabled ? 'Корень не примонтирован — задайте HOST_FOLDERS_ROOT в .env' : null }, r, label);
  });
  const pick = h('button', { type: 'button', class: 'primary', onclick: () => {
    B.chosen = `/${B.root}${B.path ? `/${B.path}` : ''}`;
    updateChosen(F);
  } }, 'Выбрать эту папку');
  B.box = h('div', { class: 'browse' },
    h('div', { class: 'radio-row' }, radios), B.crumbs, B.list, B.err,
    h('div', { class: 'actions' }, pick), B.chosenEl);
  updateChosen(F);
  browseTo(F);
  return h('div', { class: 'field' }, h('span', {}, 'Папка'), B.box,
    h('p', { class: 'small muted' }, '«Папки ПК» — корень из переменной HOST_FOLDERS_ROOT в файле .env (по умолчанию D:/). ',
      'Нужна папка на другом диске — впишите, например, HOST_FOLDERS_ROOT=E:/ и перезапустите сервис ',
      '(./scripts/compose.ps1 up -d).'));
}

function updateChosen(F) {
  const B = F.browser;
  B.chosenEl.textContent = B.chosen ? `Выбрано: ${B.chosen}` : 'Папка не выбрана';
  B.chosenEl.className = B.chosen ? 'small' : 'small muted';
}

async function browseTo(F) {
  const B = F.browser;
  B.err.hidden = true;
  let r;
  try {
    r = await request('GET', `/api/targets/browse?root=${encodeURIComponent(B.root)}&path=${encodeURIComponent(B.path)}`);
  } catch (e) {
    if (T.form !== F) return;
    if (B.path) { // папку удалили или не открыть — к корню
      B.path = '';
      browseTo(F);
      return;
    }
    B.err.textContent = e.detail;
    B.err.hidden = false;
    clear(B.list);
    clear(B.crumbs);
    return;
  }
  if (T.form !== F) return;
  const go = (path) => () => { B.path = path; browseTo(F); };
  const parts = r.path ? r.path.split('/') : [];
  clear(B.crumbs).append(
    h('button', { type: 'button', class: 'link', onclick: go('') }, ROOT_LABELS[B.root]),
    ...parts.flatMap((p, i) => [' / ', h('button', { type: 'button', class: 'link', onclick: go(parts.slice(0, i + 1).join('/')) }, p)]));
  clear(B.list);
  if (r.parent !== null && r.parent !== undefined) {
    B.list.append(h('li', {}, h('button', { type: 'button', class: 'browse-item up', onclick: go(r.parent) }, '↑ Наверх')));
  }
  for (const d of r.dirs) {
    B.list.append(h('li', {}, h('button', { type: 'button', class: 'browse-item', onclick: go(r.path ? `${r.path}/${d}` : d) },
      `📁 ${d}`)));
  }
  if (!r.dirs.length) B.list.append(h('li', { class: 'small muted browse-empty' }, 'Подпапок нет'));
}

// ---- Google Диск: вход в новой вкладке и опрос черновика

function stopGooglePoll() {
  if (T.googleTimer) clearTimeout(T.googleTimer);
  T.googleTimer = null;
}

async function googleLogin() {
  const F = T.form;
  if (!F) return;
  stopGooglePoll();
  F.result.hidden = true;
  // Вкладку открываем сразу по клику — иначе браузер заблокирует всплывающее окно.
  const tab = window.open('', '_blank');
  setBusy(F, true);
  let draft;
  try {
    ({ draft } = await request('POST', '/api/targets/gdrive/draft', formBody(F)));
  } catch (e) {
    tab?.close();
    setBusy(F, false);
    showFormResult(F, 'err', e.detail);
    markField(F, e.data?.field);
    return;
  }
  const url = `/api/targets/gdrive/auth?draft=${encodeURIComponent(draft)}`;
  if (tab) tab.location.href = url;
  else window.open(url, '_blank');
  setBusy(F, false);
  showFormResult(F, 'warn', 'Войдите в Google в открывшейся вкладке и разрешите доступ к Диску…');
  const started = Date.now();
  const poll = async () => {
    if (T.form !== F) return;
    let st;
    try {
      st = await request('GET', `/api/targets/gdrive/draft/${encodeURIComponent(draft)}`);
    } catch (e) {
      showFormResult(F, 'err', e.detail);
      return;
    }
    if (T.form !== F) return;
    if (st.state === 'connected') {
      const t = st.target;
      if (t) T.statuses[t.id] = { ok: true, text: 'Подключено' };
      closeForm();
      await loadTargets();
      showTargetsResult('ok', `Google Диск подключён: «${t?.name || 'Google Диск'}»`);
      toast('Google Диск подключён');
      return;
    }
    if (st.state === 'error') {
      showFormResult(F, 'err', `${st.error}. Попробуйте ещё раз той же кнопкой.`);
      return;
    }
    if (Date.now() - started > GOOGLE_POLL_MAX_MS) {
      showFormResult(F, 'err', 'Вход в Google не завершён за 10 минут — нажмите «Войти через Google» ещё раз');
      return;
    }
    T.googleTimer = setTimeout(poll, GOOGLE_POLL_MS);
  };
  T.googleTimer = setTimeout(poll, GOOGLE_POLL_MS);
}
