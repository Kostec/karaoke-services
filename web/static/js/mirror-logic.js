// Чистая логика карточки «Зеркала» в «Настройках» (истории 44–48): проверка пары до запроса
// (тексты — как у сервера), подписи итога прогона и состояния зеркала. Без DOM — ради node-тестов.

export const MIRROR_SELF = 'Хранилище не может быть зеркалом самого себя';
export const MIRROR_REVERSE = 'Обратное зеркало уже есть';
export const MIRROR_DUPLICATE = 'Такое зеркало уже есть';
export const MIRROR_TRASH_HINT = 'Песни ниже есть только в цели. Зеркало их не удаляет — уберите сами, если не нужны.';

/** Ошибка выбранной пары «откуда → куда»: {field, text} или null. ownId — правка своего зеркала. */
export function mirrorError(from, to, mirrors = [], ownId = '') {
  if (!from) return { field: 'from_target', text: 'Выберите, откуда копировать' };
  if (!to) return { field: 'to_target', text: 'Выберите, куда копировать' };
  if (from === to) return { field: 'to_target', text: MIRROR_SELF };
  for (const m of mirrors) {
    if (m.id === ownId) continue;
    if (m.from_target === to && m.to_target === from) return { field: 'to_target', text: MIRROR_REVERSE };
    if (m.from_target === from && m.to_target === to) return { field: 'to_target', text: MIRROR_DUPLICATE };
  }
  return null;
}

const pad = (n) => String(n).padStart(2, '0');

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Время прогона по-человечески: «сегодня 14:30», «вчера 23:10», иначе «03.10 09:05». */
export function runLabel(iso, now = new Date()) {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  if (sameDay(at, now)) return `сегодня ${time}`;
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(at, yesterday)) return `вчера ${time}`;
  return `${pad(at.getDate())}.${pad(at.getMonth() + 1)} ${time}`;
}

/** Строка итога прошлого прогона. */
export function mirrorSummary(mirror, now = new Date()) {
  const r = mirror?.last_result;
  if (!mirror?.last_run_at || !r) return 'Ещё не синхронизировалось';
  const head = `Последний прогон: ${runLabel(mirror.last_run_at, now)}`;
  if (r.error) return `${head} — ошибка: ${r.error}`;
  const only = (r.only_in_target || []).length;
  return `${head} — добавлено ${r.added || 0}, обновлено ${r.updated || 0}, только в цели ${only}`;
}

/** Состояние зеркала для подписи под заголовком: {kind: err|warn|run|off, text} или null. */
export function mirrorStatus(mirror) {
  if (mirror?.missing) return { kind: 'err', text: 'Хранилище удалено из настроек — зеркало выключено' };
  if (mirror?.waiting) return { kind: 'warn', text: mirror.waiting };
  const job = mirror?.job;
  if (job) {
    if (job.state === 'queued' && !job.stage) return { kind: 'run', text: 'Синхронизация в очереди' };
    return { kind: 'run', text: job.stage ? `Синхронизация: ${job.stage}` : 'Синхронизация…' };
  }
  if (mirror && !mirror.enabled) return { kind: 'off', text: 'Выключено — само не синхронизируется' };
  return null;
}

/** Песни «только в цели» с подписью; removed — id уже убранных в корзину. */
export function onlyInTarget(mirror, removed = new Set()) {
  return (mirror?.last_result?.only_in_target || [])
    .filter((s) => !removed.has(s.song_id))
    .map((s) => ({ ...s, label: s.artist && s.title ? `${s.artist} — ${s.title}` : (s.artist || s.title || s.rel_dir) }));
}
