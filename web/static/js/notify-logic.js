// Уведомления браузера о заданиях — чистая логика (без document, под node-тесты).
// Тексты и правило «о чём сообщать» — как у воркера (worker/karaoke_worker/notify.py).

export const NOTIFY_KEY = 'notify.browser'; // localStorage: '1' — показывать в этом браузере

export const REASON_INSECURE = 'Браузер разрешает уведомления только на localhost или https — используйте Telegram.';
export const REASON_UNSUPPORTED = 'Этот браузер не умеет показывать уведомления — используйте Telegram.';
export const REASON_DENIED = 'Уведомления для этого сайта запрещены в настройках браузера — разрешите их там или используйте Telegram.';

// «Готово» — только о заданиях песни (служебные copy/publish — нет); «сбой» — о всех.
export const DONE_TYPES = new Set(['generate', 'import', 'instrumental', 'video', 'artwork', 'audio', 'rename']);
export const TYPE_NAMES = {
  generate: 'генерация', import: 'импорт', instrumental: 'минусовка', video: 'видео', artwork: 'обложка',
  audio: 'звук', rename: 'переименование', publish: 'выкладка', copy: 'копирование',
  libcheck: 'проверка библиотеки', mirror: 'зеркало',
};
const FINAL = new Set(['done', 'failed', 'cancelled']);
const ERROR_MAX = 300;

/** Можно ли в этом окне показывать уведомления: {ok, reason, permission?}. */
export function browserNotifyState(win) {
  if (!win || !win.isSecureContext) return { ok: false, reason: REASON_INSECURE };
  const N = win.Notification;
  if (!N) return { ok: false, reason: REASON_UNSUPPORTED };
  if (N.permission === 'denied') return { ok: false, reason: REASON_DENIED };
  return { ok: true, reason: '', permission: N.permission };
}

function songName(job) {
  if (job.artist && job.title) return `${job.artist} — ${job.title}`;
  return job.artist || job.title || `задание #${job.id}`;
}

/** Уведомление о переходе задания в done/failed: {title, body} или null. */
export function jobNotice(prev, job) {
  if (!prev || !job || prev.state === job.state || FINAL.has(prev.state)) return null;
  const what = `${songName(job)} (${TYPE_NAMES[job.type] || job.type})`;
  if (job.state === 'done' && DONE_TYPES.has(job.type)) return { title: '✅ Готово', body: what };
  if (job.state === 'failed') {
    let error = String(job.error || '').split('\n')[0].replace(/\s+/g, ' ').trim() || 'причина в логе задания';
    if (error.length > ERROR_MAX) error = `${error.slice(0, ERROR_MAX - 1)}…`;
    return { title: '❌ Сбой', body: `${what} — ${error}` };
  }
  return null;
}

/** Опрос заданий → уведомления. ``seen`` — результат прошлого вызова (null — первый опрос:
 *  только запомнить). Новое задание (id больше виденных) считается бывшим в очереди — так
 *  сообщается и о том, что успело закончиться между опросами. → {notices:[{id,title,body}], seen}. */
export function collectNotices(seen, jobs) {
  const states = new Map();
  let maxId = seen ? seen.maxId : 0;
  const notices = [];
  for (const job of jobs || []) {
    states.set(job.id, job.state);
    if (seen) {
      const before = seen.states.get(job.id) ?? (job.id > seen.maxId ? 'queued' : null);
      const notice = before ? jobNotice({ state: before }, job) : null;
      if (notice) notices.push({ id: job.id, ...notice });
    }
    maxId = Math.max(maxId, job.id);
  }
  notices.sort((a, b) => a.id - b.id);
  return { notices, seen: { states, maxId } };
}

/** Показать ли уведомление сейчас: включено, разрешено и вкладка не в фокусе. */
export function shouldShow({ enabled, win, focused }) {
  if (!enabled || focused) return false;
  const st = browserNotifyState(win);
  return st.ok && st.permission === 'granted';
}
