// Уведомления браузера о заданиях: пока вкладка открыта, раз в 15 с опрос api.jobs(50);
// задание перешло в «готово»/«сбой» — уведомление, если оно включено в «Настройках», браузер
// разрешил и вкладка не в фокусе. Подключается одной строкой в app.js; переключатель — settings.js.

import { api } from './api.js';
import { NOTIFY_KEY, browserNotifyState, collectNotices, shouldShow } from './notify-logic.js';

const POLL_MS = 15000;
let seen = null;
let timer = null;

function readFlag() {
  try { return localStorage.getItem(NOTIFY_KEY) === '1'; } catch { return false; }
}

function writeFlag(on) {
  try {
    if (on) localStorage.setItem(NOTIFY_KEY, '1');
    else localStorage.removeItem(NOTIFY_KEY);
  } catch { /* приватное окно — переключатель живёт до перезагрузки */ }
}

let enabled = readFlag();

/** Включены ли уведомления в этом браузере (и браузер их разрешил). */
export function notifyEnabled() {
  return enabled && browserNotifyState(window).permission === 'granted';
}

/** Состояние для «Настроек»: {ok, reason, permission?}. */
export function notifyState() {
  return browserNotifyState(window);
}

/** Включить/выключить; включение спрашивает разрешение браузера. → {ok, reason}. */
export async function setNotifyEnabled(on) {
  if (!on) {
    enabled = false;
    writeFlag(false);
    stop();
    return { ok: true, reason: '' };
  }
  let st = browserNotifyState(window);
  if (!st.ok) return st;
  if (st.permission !== 'granted') {
    try { await Notification.requestPermission(); } catch { /* старые браузеры — по колбэку, не поддерживаем */ }
    st = browserNotifyState(window);
    if (!st.ok) return st;
    if (st.permission !== 'granted') return { ok: false, reason: 'Браузер не дал разрешение на уведомления.' };
  }
  enabled = true;
  writeFlag(true);
  start();
  return { ok: true, reason: '' };
}

function focused() {
  return document.visibilityState === 'visible' && document.hasFocus();
}

function show(notice) {
  try {
    const n = new Notification(notice.title, { body: notice.body, tag: `job-${notice.id}` });
    n.onclick = () => {
      window.focus();
      location.hash = '#queue';
      n.close();
    };
  } catch { /* браузер может отказать в конструкторе (Android Chrome) — молча */ }
}

async function poll() {
  if (!notifyEnabled()) { stop(); return; }
  let jobs;
  try {
    jobs = await api.jobs(50);
  } catch {
    return; // нет связи — следующий опрос
  }
  const out = collectNotices(seen, Array.isArray(jobs) ? jobs : jobs?.jobs || []);
  seen = out.seen;
  if (!shouldShow({ enabled: notifyEnabled(), win: window, focused: focused() })) return;
  for (const notice of out.notices) show(notice);
}

function start() {
  if (timer) return;
  seen = null;
  poll();
  timer = setInterval(poll, POLL_MS);
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  seen = null;
}

if (notifyEnabled()) start();
