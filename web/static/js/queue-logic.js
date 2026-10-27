// Чистая логика очереди: ночной старт, подписи времени, порядок ожидающих (без document).

const pad = (n) => String(n).padStart(2, '0');
const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

/** Ближайшие 01:00 местного времени строго после `now`. */
export function nightStart(now = new Date()) {
  const at = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 1, 0, 0, 0);
  if (at <= now) at.setDate(at.getDate() + 1);
  return at;
}

/** Ближайшее `HH:MM` местного времени после `now`; пустое/неверное — null. */
export function timeStart(value, now = new Date()) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(value || '').trim());
  if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) return null;
  const at = new Date(now.getFullYear(), now.getMonth(), now.getDate(), Number(m[1]), Number(m[2]), 0, 0);
  if (at <= now) at.setDate(at.getDate() + 1);
  return at;
}

/** Время для API: всегда с поясом (`…Z`) — сервер не примет сырое значение поля времени. */
export function startIso(date) {
  return date.toISOString();
}

/** «Начнётся сегодня в 01:00» / «завтра в 14:30» / «28.10 в 09:00»; не отложено — ''. */
export function scheduleLabel(job, now = new Date()) {
  if (!job || !job.start_at || job.state !== 'queued') return '';
  const at = new Date(job.start_at);
  if (Number.isNaN(at.getTime())) return '';
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  const days = Math.round((dayStart(at) - dayStart(now)) / 86400000);
  if (days <= 0) return `Начнётся сегодня в ${time}`;
  if (days === 1) return `Начнётся завтра в ${time}`;
  return `Начнётся ${pad(at.getDate())}.${pad(at.getMonth() + 1)} в ${time}`;
}

/** Ожидающие в порядке очереди (как их берёт воркер): position, у старых — id. */
export function queuedOrder(jobs) {
  return jobs.filter((j) => j.state === 'queued')
    .sort((a, b) => ((a.position ?? a.id) - (b.position ?? b.id)) || (a.id - b.id));
}

/** Порядок показа: идущие, ожидающие по очереди, затем остальные как пришли. */
export function displayOrder(jobs) {
  const live = jobs.filter((j) => j.state === 'running' || j.state === 'publishing');
  const rest = jobs.filter((j) => !['running', 'publishing', 'queued'].includes(j.state));
  return [...live, ...queuedOrder(jobs), ...rest];
}

/** id → место среди ожидающих (1…), только у неотложенных; и сколько ожидающих без времени. */
export function queuePlaces(jobs) {
  const places = new Map();
  let n = 0;
  for (const j of queuedOrder(jobs)) {
    if (!j.start_at) places.set(j.id, ++n);
  }
  return places;
}
